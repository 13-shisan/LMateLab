# backend/services/agents/knowledge_loader.py
import os
import json
import re
from typing import List, Dict, Any
from .rag_config import RAW_DIR, PAPERS_INDEX_JSON

def load_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def load_json_file_as_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return json.dumps(data, ensure_ascii=False, indent=2)

def split_text(text: str, chunk_size: int = 1500, overlap: int = 200) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    if not paragraphs:
        return []

    chunks: List[str] = []
    current = ""

    def push_current():
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    def split_long_paragraph(para: str) -> List[str]:
        pieces = []
        start = 0
        while start < len(para):
            if len(para) - start <= chunk_size:
                pieces.append(para[start:].strip())
                break

            end = start + chunk_size
            window = para[start:end]

            cut = max(
                window.rfind("。"),
                window.rfind("！"),
                window.rfind("？"),
                window.rfind("\n"),
            )

            if cut == -1 or cut < int(chunk_size * 0.6):
                cut = chunk_size

            piece = para[start:start + cut].strip()
            if piece:
                pieces.append(piece)

            next_start = start + cut - overlap
            if next_start <= start:
                next_start = start + cut
            start = next_start

        return pieces

    for para in paragraphs:
        if len(para) <= chunk_size:
            if not current:
                current = para
            elif len(current) + 2 + len(para) <= chunk_size:
                current += "\n\n" + para
            else:
                push_current()
                current = para
        else:
            push_current()
            long_pieces = split_long_paragraph(para)
            chunks.extend(long_pieces)

    push_current()
    return chunks


def extract_markdown_title(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""

    lines = text.splitlines()
    for line in lines[:20]:
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            return s.lstrip("#").strip()

    for line in lines[:20]:
        s = line.strip()
        if s:
            return s

    return ""


def load_documents_from_subdir(subdir: str) -> List[Dict[str, Any]]:
    target_dir = os.path.join(RAW_DIR, subdir)
    docs = []

    print(f"[knowledge_loader] RAW_DIR={RAW_DIR}", flush=True)
    print(f"[knowledge_loader] target_dir={target_dir}", flush=True)

    if not os.path.isdir(target_dir):
        print(f"[knowledge_loader] directory not found: {target_dir}", flush=True)
        return docs

    for root, dirs, files in os.walk(target_dir):
        if subdir == "papers":
            dirs[:] = [d for d in dirs if d != "mineru"]

        for name in files:
            path = os.path.join(root, name)
            rel_path = os.path.relpath(path, RAW_DIR).replace("\\", "/")

            print(f"[knowledge_loader] scanning file: {path}", flush=True)

            try:
                if name.endswith(".md") or name.endswith(".txt"):
                    text = load_text_file(path)
                elif name.endswith(".json"):
                    text = load_json_file_as_text(path)
                else:
                    print(f"[knowledge_loader] skipped unsupported file: {path}", flush=True)
                    continue

                if not text.strip():
                    print(f"[knowledge_loader] skipped empty file: {path}", flush=True)
                    continue

                docs.append({
                    "source": rel_path,
                    "text": text,
                })

                print(f"[knowledge_loader] loaded file: {path}, length={len(text)}", flush=True)

            except Exception as e:
                print(f"[knowledge_loader] failed to load {path}: {e}", flush=True)

    print(f"[knowledge_loader] loaded docs count for {subdir}: {len(docs)}", flush=True)
    return docs


def normalize_library_md_path_to_knowledge_source(md_path: str) -> str:
    """
    papers_index.json 中的 md_path 形如:
    library/2026-J.Am.Chem.Soc.2026,148,1655-1661-b13235b6de98/full.md

    knowledge/raw 中对应的 source 形如:
    papers/2026-J.Am.Chem.Soc.2026,148,1655-1661-b13235b6de98/full.md
    """
    md_path = (md_path or "").strip().replace("\\", "/")
    if not md_path:
        return ""

    if md_path.startswith("library/"):
        return "papers/" + md_path[len("library/"):]

    if md_path.startswith("papers/"):
        return md_path

    return md_path


def load_papers_index() -> List[Dict[str, Any]]:
    path = PAPERS_INDEX_JSON
    print(f"[knowledge_loader] PAPERS_INDEX_JSON={PAPERS_INDEX_JSON}", flush=True)
    if not os.path.isfile(path):
        print(f"[knowledge_loader] papers index not found: {path}", flush=True)
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            print(f"[knowledge_loader] loaded papers index count={len(data)}", flush=True)
            return data

        print(f"[knowledge_loader] papers index format invalid: {path}", flush=True)
        return []
    except Exception as e:
        print(f"[knowledge_loader] failed to load papers index: {path}, error={e}", flush=True)
        return []


def build_paper_metadata_text(item: Dict[str, Any]) -> str:
    """
    把 papers_index.json 的一条记录格式化成一个 metadata chunk 文本。
    """
    paper_id = str(item.get("paper_id") or "").strip()
    title = str(item.get("title") or "").strip()
    journal = str(item.get("journal") or "").strip()
    journal_slug = str(item.get("journal_slug") or "").strip()
    year = item.get("year")
    doi = str(item.get("doi") or "").strip()
    abstract = str(item.get("abstract") or "").strip()
    main_topic = str(item.get("main_topic") or "").strip()
    leaf_topic = str(item.get("leaf_topic") or "").strip()
    classification_reason = str(item.get("classification_reason") or "").strip()
    source_pdf = str(item.get("source_pdf") or "").strip()
    raw_source_pdf = str(item.get("raw_source_pdf") or "").strip()
    md_path = str(item.get("md_path") or "").strip()
    mineru_dir = str(item.get("mineru_dir") or "").strip()

    taxonomy_path = item.get("taxonomy_path") or []
    if not isinstance(taxonomy_path, list):
        taxonomy_path = []

    authors = item.get("authors") or []
    if not isinstance(authors, list):
        authors = []

    keywords = item.get("keywords") or []
    if not isinstance(keywords, list):
        keywords = []

    parts = [
        "Paper metadata",
        f"Paper ID: {paper_id}",
        f"Title: {title}",
    ]

    if journal:
        parts.append(f"Journal: {journal}")
    if journal_slug:
        parts.append(f"Journal Slug: {journal_slug}")
    if year:
        parts.append(f"Year: {year}")
    if doi:
        parts.append(f"DOI: {doi}")
    if taxonomy_path:
        parts.append(f"Taxonomy Path: {' > '.join(str(x) for x in taxonomy_path if x)}")
    if main_topic:
        parts.append(f"Main Topic: {main_topic}")
    if leaf_topic:
        parts.append(f"Leaf Topic: {leaf_topic}")
    if authors:
        parts.append(f"Authors: {', '.join(str(x) for x in authors if x)}")
    if keywords:
        parts.append(f"Keywords: {', '.join(str(x) for x in keywords if x)}")
    if source_pdf:
        parts.append(f"Source PDF: {source_pdf}")
    if raw_source_pdf:
        parts.append(f"Raw Source PDF: {raw_source_pdf}")
    if md_path:
        parts.append(f"Markdown Path: {md_path}")
    if mineru_dir:
        parts.append(f"Mineru Dir: {mineru_dir}")
    if abstract:
        parts.append(f"Abstract: {abstract}")
    if classification_reason:
        parts.append(f"Classification Reason: {classification_reason}")

    return "\n".join(parts)


def build_papers_metadata_chunks() -> List[Dict[str, Any]]:
    """
    每条 papers_index 记录生成一个 metadata chunk。
    """
    index_items = load_papers_index()
    chunks: List[Dict[str, Any]] = []

    for item in index_items:
        paper_id = str(item.get("paper_id") or "").strip()
        title = str(item.get("title") or "").strip()
        md_path = str(item.get("md_path") or "").strip()

        if not paper_id or not md_path:
            continue

        source = normalize_library_md_path_to_knowledge_source(md_path)
        text = build_paper_metadata_text(item)

        chunks.append({
            "id": f"papers_meta:{paper_id}",
            "domain": "papers",
            "source": source,
            "chunk_index": -1,
            "paper_id": paper_id,
            "title": title,
            "chunk_type": "paper_metadata",
            "text": text,
        })

    print(f"[knowledge_loader] built paper metadata chunks: count={len(chunks)}", flush=True)
    return chunks


def extract_paper_id_from_source(source: str) -> str:
    """
    从 source 提取 paper_id，例如：
    papers/2026-J.Am.Chem.Soc.2026,148,1655-1661-b13235b6de98/full.md
    -> b13235b6de98
    """
    source = (source or "").replace("\\", "/")
    parts = source.split("/")
    if len(parts) < 2:
        return ""

    folder_name = parts[1]
    if "-" not in folder_name:
        return ""

    return folder_name.split("-")[-1].strip()


def build_chunks_for_domain(domain: str) -> List[Dict[str, Any]]:
    docs = load_documents_from_subdir(domain)
    all_chunks = []

    # 对 papers 域，先加入 papers_index.json 中每篇论文的一条 metadata chunk
    if domain == "papers":
        all_chunks.extend(build_papers_metadata_chunks())

    for doc in docs:
        source = doc["source"]
        text = doc["text"]
        title = extract_markdown_title(text)
        paper_id = extract_paper_id_from_source(source) if domain == "papers" else ""

        chunks = split_text(text, chunk_size=1500, overlap=200)
        print(f"[knowledge_loader] split source={source}, chunks={len(chunks)}", flush=True)

        for idx, chunk in enumerate(chunks):
            all_chunks.append({
                "id": f"{domain}:{source}:{idx}",
                "domain": domain,
                "source": source,
                "chunk_index": idx,
                "paper_id": paper_id,
                "title": title,
                "chunk_type": "paper_fulltext" if domain == "papers" else "text",
                "text": chunk,
            })

    print(f"[knowledge_loader] total chunks for {domain}: {len(all_chunks)}", flush=True)
    return all_chunks
