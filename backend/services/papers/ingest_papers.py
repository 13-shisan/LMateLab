# backend/services/papers/ingest_papers.py
import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from .classifier import PaperClassifier, extract_metadata_from_pdf_with_llm, utc_now_iso
from .config import (
    LEGACY_PAPERS_LIBRARY_DIR,
    PAPERS_LIBRARY_DIR,
    PAPERS_LIBRARY_INDEX_PATH,
    PAPERS_RAW_DIR,
)
from .extractors import extract_markdown, get_env
from .sync_papers_to_knowledge import sync_papers_to_knowledge
from .utils import (
    build_library_dirname,
    dump_json,
    ensure_dir,
    ensure_papers_index_scaffold,
    extract_abstract_from_markdown,
    extract_doi_from_text,
    extract_header_footer_texts_from_content_list,
    extract_title_from_md,
    extract_year_from_text,
    extract_year_and_journal_from_content_list,
    file_sha1,
    journal_slug,
    load_json,
    load_manifest,
    match_journal_from_content_list,
    normalize_year_for_dir,
    save_manifest,
    safe_text,
    write_text,
    to_relative_papers_path,
    resolve_papers_path,
    is_reusable_paper_bundle,
)


UNKNOWN_CLASSIFICATION = ["未分类"]


def _reconfigure_stdio():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

def walk_raw_pdfs(base_dir: str):
    base = Path(base_dir)
    if not base.is_dir():
        return

    for path in sorted(base.rglob("*.pdf")):
        if path.is_file():
            yield str(path.resolve())


def build_paper_id(pdf_path: str) -> str:
    return file_sha1(pdf_path)[:12]

def _normalize_manifest_pdf_key(pdf_path: str) -> str:
    """
    统一把 raw pdf 路径规范成相对 PAPERS_ROOT_DIR 的形式。
    例如：
    /storage/software/LMateLab/var/papers/raw/a.pdf -> raw/a.pdf
    /app/var/papers/raw/a.pdf -> raw/a.pdf
    """
    rel = to_relative_papers_path(pdf_path)
    if rel:
        return rel
    return os.path.abspath(pdf_path).replace("\\", "/")


def _iter_manifest_candidate_keys(pdf_path: str) -> list[str]:
    abs_path = os.path.abspath(pdf_path).replace("\\", "/")
    rel_path = _normalize_manifest_pdf_key(pdf_path)

    keys = []
    for key in [abs_path, rel_path]:
        if key and key not in keys:
            keys.append(key)
    return keys


def _find_manifest_record(manifest: dict, pdf_path: str, pdf_sha1: str, paper_id: str) -> tuple[str | None, dict]:
    """
    从 manifest 中兼容查找记录：
    1. 先按当前绝对路径 / 相对路径 key 命中
    2. 再按 pdf_sha1 命中
    3. 再按 paper_id 命中
    返回：(matched_key, record)
    """
    if not isinstance(manifest, dict):
        return None, {}

    for key in _iter_manifest_candidate_keys(pdf_path):
        record = manifest.get(key)
        if isinstance(record, dict):
            return key, record

    for key, record in manifest.items():
        if not isinstance(record, dict):
            continue
        if safe_text(record.get("pdf_sha1") or "") == pdf_sha1:
            return key, record

    for key, record in manifest.items():
        if not isinstance(record, dict):
            continue
        if safe_text(record.get("paper_id") or "") == paper_id:
            return key, record

    return None, {}

def _find_existing_paper_dir(paper_id: str, record: dict | None = None) -> str | None:
    candidates = []

    if record:
        for field in ["paper_dir", "metadata_path"]:
            value = record.get(field)
            resolved = resolve_papers_path(value)
            if not resolved:
                continue

            if field == "metadata_path":
                parent = os.path.dirname(resolved)
                if parent:
                    candidates.append(parent)
            else:
                candidates.append(resolved)

    for root in [PAPERS_LIBRARY_DIR, LEGACY_PAPERS_LIBRARY_DIR]:
        if not root:
            continue

        root = resolve_papers_path(root) or root
        candidates.append(os.path.join(root, paper_id))

        root_path = Path(root)
        if root_path.is_dir():
            for matched in root_path.glob(f"*-{paper_id}"):
                candidates.append(str(matched))

    seen = set()
    for candidate in candidates:
        if not candidate:
            continue
        abs_candidate = os.path.abspath(candidate)
        if abs_candidate in seen:
            continue
        seen.add(abs_candidate)
        if os.path.isdir(abs_candidate):
            return abs_candidate

    # 兜底：扫描 library 下所有 metadata.json，按 paper_id 反查
    for root in [PAPERS_LIBRARY_DIR, LEGACY_PAPERS_LIBRARY_DIR]:
        root = resolve_papers_path(root) or root
        if not root or not os.path.isdir(root):
            continue

        for metadata_file in Path(root).rglob("metadata.json"):
            try:
                data = load_json(str(metadata_file), default={})
                if isinstance(data, dict) and safe_text(data.get("paper_id") or "") == paper_id:
                    return str(metadata_file.parent)
            except Exception:
                continue

    return None

def _read_existing_metadata(paper_dir: str | None) -> dict:
    if not paper_dir:
        return {}
    metadata_path = os.path.join(paper_dir, "metadata.json")
    data = load_json(metadata_path, default={})
    return data if isinstance(data, dict) else {}


def _guess_title(markdown_text: str, pdf_path: str, existing_metadata: dict) -> str:
    return safe_text(existing_metadata.get("title") or "") or extract_title_from_md(markdown_text, fallback=Path(pdf_path).stem)


def _find_content_list_json(mineru_dir: str) -> str | None:
    candidate = Path(mineru_dir) / "content_list_v2.json"
    return str(candidate) if candidate.is_file() else None


def _collect_header_footer_texts(content_list_path: str | None) -> list[str]:
    if not content_list_path:
        return []
    entries = extract_header_footer_texts_from_content_list(content_list_path)
    return [safe_text(item.get("text") or "") for item in entries if safe_text(item.get("text") or "")]


def _determine_journal_and_year(markdown_text: str, content_list_path: str | None, existing_metadata: dict) -> tuple[dict, int | None]:
    journal_match = {
        "journal": safe_text(existing_metadata.get("journal") or "") or "UnknownJournal",
        "journal_slug": safe_text(existing_metadata.get("journal_slug") or "") or "UnknownJournal",
        "strategy": "existing_metadata" if existing_metadata else "unknown",
        "publisher": (existing_metadata.get("journal_match") or {}).get("publisher"),
        "matched_pattern": (existing_metadata.get("journal_match") or {}).get("matched_pattern"),
        "matched_text": (existing_metadata.get("journal_match") or {}).get("matched_text"),
        "block_type": (existing_metadata.get("journal_match") or {}).get("block_type"),
    }
    year = existing_metadata.get("year") or extract_year_from_text(markdown_text)

    if content_list_path:
        journal_match = match_journal_from_content_list(content_list_path)
        extracted_year, extracted_journal = extract_year_and_journal_from_content_list(content_list_path)
        if extracted_year is not None:
            year = extracted_year
        if extracted_journal and journal_match.get("journal") == "UnknownJournal":
            journal_match["journal"] = extracted_journal
            journal_match["journal_slug"] = journal_slug(extracted_journal)

    return journal_match, year


def _should_reextract_llm_metadata(existing_metadata: dict, force_llm_metadata: bool, llm_signature: str | None = None) -> bool:
    if force_llm_metadata:
        return True
    status = safe_text(existing_metadata.get("llm_metadata_status") or "")
    abstract = safe_text(existing_metadata.get("abstract") or "")
    doi = safe_text(existing_metadata.get("doi") or "")
    existing_signature = safe_text(existing_metadata.get("llm_signature") or "")
    if llm_signature and existing_signature and existing_signature != llm_signature:
        return True
    return status != "success" or not abstract or not doi


def _should_reclassify(existing_metadata: dict, force_llm_classification: bool, llm_signature: str | None = None) -> bool:
    if force_llm_classification:
        return True
    status = safe_text(existing_metadata.get("llm_classification_status") or "")
    taxonomy_path = existing_metadata.get("taxonomy_path") or []
    existing_signature = safe_text(existing_metadata.get("llm_signature") or "")
    if llm_signature and existing_signature and existing_signature != llm_signature:
        return True
    return status != "success" or taxonomy_path == UNKNOWN_CLASSIFICATION or not taxonomy_path


from .utils import merge_directories, cleanup_empty_or_metadata_only_dir

def _ensure_final_paper_dir(current_dir: str | None, year, journal_slug_value: str, paper_id: str) -> str:
    desired_dir = os.path.join(PAPERS_LIBRARY_DIR, build_library_dirname(year, journal_slug_value, paper_id))
    ensure_dir(PAPERS_LIBRARY_DIR)

    if current_dir:
        current_dir = os.path.abspath(current_dir)
    desired_dir = os.path.abspath(desired_dir)

    if current_dir and current_dir != desired_dir:
        if os.path.exists(current_dir) and not os.path.exists(desired_dir):
            ensure_dir(os.path.dirname(desired_dir))
            shutil.move(current_dir, desired_dir)
        elif os.path.exists(current_dir) and os.path.exists(desired_dir):
            merge_directories(current_dir, desired_dir)
            cleanup_empty_or_metadata_only_dir(current_dir)
        else:
            ensure_dir(desired_dir)

        current_dir = desired_dir

    if not current_dir:
        current_dir = desired_dir

    ensure_dir(current_dir)
    return current_dir

def _load_markdown_text(root_full_md: str, mineru_full_md: str) -> str:
    if os.path.isfile(root_full_md):
        return Path(root_full_md).read_text(encoding="utf-8")
    if os.path.isfile(mineru_full_md):
        return Path(mineru_full_md).read_text(encoding="utf-8")
    return ""


def _build_metadata_dict(
    pdf_path: str,
    paper_id: str,
    paper_dir: str,
    source_pdf_copy: str,
    md_path: str,
    mineru_dir: str,
    title: str,
    journal_match: dict,
    year,
    abstract: str,
    doi: str | None,
    classification: dict,
    existing_metadata: dict,
    llm_metadata_info: dict,
    llm_classification_info: dict,
    llm_signature: str | None = None,
) -> dict:
    journal_slug_value = journal_match.get("journal_slug") or existing_metadata.get("journal_slug") or "UnknownJournal"
    taxonomy_path = classification.get("taxonomy_path") or UNKNOWN_CLASSIFICATION
    metadata = {
        "paper_id": paper_id,
        "title": title,
        "journal": journal_match.get("journal") or existing_metadata.get("journal") or "UnknownJournal",
        "journal_slug": journal_slug_value,
        "year": year,
        "taxonomy_path": taxonomy_path,
        "main_topic": classification.get("main_topic") or taxonomy_path[0],
        "leaf_topic": classification.get("leaf_topic") or taxonomy_path[-1],
        "classification_reason": classification.get("reason") or "",
        "source_pdf": to_relative_papers_path(source_pdf_copy),
        "raw_source_pdf": os.path.abspath(pdf_path),
        "md_path": to_relative_papers_path(md_path),
        "mineru_dir": to_relative_papers_path(mineru_dir),
        "abstract": abstract,
        "doi": doi,
        "authors": existing_metadata.get("authors") or [],
        "keywords": existing_metadata.get("keywords") or [],
        "journal_match": {
            "strategy": journal_match.get("strategy"),
            "publisher": journal_match.get("publisher"),
            "matched_pattern": journal_match.get("matched_pattern"),
            "matched_text": journal_match.get("matched_text"),
            "block_type": journal_match.get("block_type"),
        },
        "llm_signature": llm_signature or existing_metadata.get("llm_signature") or "",
        "llm_metadata_extracted": llm_metadata_info.get("status") == "success",
        "llm_metadata_model": llm_metadata_info.get("model"),
        "llm_metadata_extracted_at": llm_metadata_info.get("extracted_at"),
        "llm_metadata_status": llm_metadata_info.get("status"),
        "llm_metadata_reason": llm_metadata_info.get("reason") or "",
        "llm_metadata_failure_reason": llm_metadata_info.get("failure_reason") or "",
        "llm_classified": llm_classification_info.get("status") == "success",
        "llm_classification_model": llm_classification_info.get("model"),
        "llm_classified_at": llm_classification_info.get("classified_at"),
        "llm_classification_source": llm_classification_info.get("source") or "",
        "llm_classification_status": llm_classification_info.get("status"),
        "llm_classification_failure_reason": llm_classification_info.get("failure_reason") or "",
        "llm_classification_debug": llm_classification_info.get("debug") or "",
    }
    return metadata


def ingest_one_pdf(
    pdf_path: str,
    manifest: dict,
    classifier: PaperClassifier,
    engine: str,
    force: bool = False,
    force_llm_metadata: bool = False,
    force_llm_classification: bool = False,
):
    pdf_path = os.path.abspath(pdf_path)
    if not os.path.isfile(pdf_path):
        print(f"[papers_ingest] skip missing pdf: {pdf_path}", flush=True)
        return None

    pdf_sha1 = file_sha1(pdf_path)
    parse_signature = build_parse_signature(engine)
    llm_signature = build_llm_signature()
    paper_id = build_paper_id(pdf_path)

    matched_manifest_key, record = _find_manifest_record(
        manifest=manifest,
        pdf_path=pdf_path,
        pdf_sha1=pdf_sha1,
        paper_id=paper_id,
    )

    current_dir = _find_existing_paper_dir(paper_id, record)
    existing_metadata = _read_existing_metadata(current_dir)
    print(f"[papers_ingest] resolved current_dir(before_tmp)={current_dir}", flush=True)


    if current_dir:
        current_dir = os.path.abspath(current_dir)
    else:
        current_dir = os.path.join(PAPERS_LIBRARY_DIR, f"_tmp_{paper_id}")
        ensure_dir(current_dir)
    print(f"[papers_ingest] current_dir(final)={current_dir}", flush=True)

    source_pdf_copy = os.path.join(current_dir, "source.pdf")
    mineru_dir = os.path.join(current_dir, "mineru")
    mineru_full_md = os.path.join(mineru_dir, "full.md")
    root_full_md = os.path.join(current_dir, "full.md")
    metadata_path = os.path.join(current_dir, "metadata.json")

    ensure_dir(current_dir)
    ensure_dir(mineru_dir)

    existing_bundle_reusable = is_reusable_paper_bundle(current_dir, pdf_sha1=pdf_sha1) if current_dir else False

    record_pdf_sha1 = safe_text(record.get("pdf_sha1") or "")
    record_parse_signature = safe_text(record.get("parse_signature") or record.get("ingest_signature") or "")

    reason_flags = {
        "force": force,
        "record_found": bool(record),
        "bundle_reusable": existing_bundle_reusable,
        "pdf_sha1_changed": bool(record) and record_pdf_sha1 and record_pdf_sha1 != pdf_sha1,
        "parse_signature_changed": bool(record) and record_parse_signature and record_parse_signature != parse_signature,
        "missing_full_md": not os.path.isfile(root_full_md),
        "missing_source_pdf": not os.path.isfile(source_pdf_copy),
    }

    # 关键策略：
    # 1. 如果已有 bundle 完整且 source.pdf sha1 一致，则直接跳过解析
    # 2. signature 改变时，不强制重跑 PDF 解析；只影响后续元数据/分类是否需要重算
    # 3. 只有 force / bundle 不可复用 / 文件缺失 / sha1 变化 时才重新解析
    needs_parse = (
        force
        or not existing_bundle_reusable
        or reason_flags["pdf_sha1_changed"]
        or reason_flags["missing_full_md"]
        or reason_flags["missing_source_pdf"]
        or reason_flags["parse_signature_changed"]
    )

    print(
        f"[papers_ingest] parse_check: pdf={pdf_path}, paper_id={paper_id}, "
        f"manifest_key={matched_manifest_key}, record_found={reason_flags['record_found']}, "
        f"bundle_reusable={reason_flags['bundle_reusable']}, "
        f"pdf_sha1_changed={reason_flags['pdf_sha1_changed']}, "
        f"parse_signature_changed={reason_flags['parse_signature_changed']}, "
        f"missing_full_md={reason_flags['missing_full_md']}, "
        f"missing_source_pdf={reason_flags['missing_source_pdf']}, "
        f"needs_parse={needs_parse}",
        flush=True,
    )


    if needs_parse:
        shutil.copy2(pdf_path, source_pdf_copy)
        markdown_text, actual_engine = extract_markdown(pdf_path, engine=engine, assets_dir=mineru_dir)
        write_text(root_full_md, markdown_text)
        if not os.path.isfile(mineru_full_md):
            write_text(mineru_full_md, markdown_text)
    else:
        actual_engine = record.get("engine") or engine
        markdown_text = _load_markdown_text(root_full_md, mineru_full_md)
        if os.path.isfile(pdf_path) and not os.path.isfile(source_pdf_copy):
            shutil.copy2(pdf_path, source_pdf_copy)

    content_list_path = _find_content_list_json(mineru_dir)
    header_footer_texts = _collect_header_footer_texts(content_list_path)
    title = _guess_title(markdown_text, pdf_path, existing_metadata)
    journal_match, year = _determine_journal_and_year(markdown_text, content_list_path, existing_metadata)

    llm_metadata_info = {
        "status": safe_text(existing_metadata.get("llm_metadata_status") or "") or "pending",
        "model": existing_metadata.get("llm_metadata_model"),
        "extracted_at": existing_metadata.get("llm_metadata_extracted_at"),
        "reason": existing_metadata.get("llm_metadata_reason") or "",
        "failure_reason": existing_metadata.get("llm_metadata_failure_reason") or "",
    }

    if _should_reextract_llm_metadata(existing_metadata, force_llm_metadata, llm_signature=llm_signature):
        llm_metadata_result = extract_metadata_from_pdf_with_llm(
            pdf_path=pdf_path,
            markdown_text=markdown_text,
            header_footer_texts=header_footer_texts,
            title_hint=title,
            journal_hint=journal_match.get("journal") or "",
            year_hint=year,
        )
        llm_metadata_info = {
            "status": llm_metadata_result.get("status") or "failed",
            "model": llm_metadata_result.get("model"),
            "extracted_at": llm_metadata_result.get("extracted_at") or utc_now_iso(),
            "reason": llm_metadata_result.get("reason") or "",
            "failure_reason": llm_metadata_result.get("failure_reason") or "",
        }
        llm_title = safe_text(llm_metadata_result.get("title") or "")
        if llm_title:
            title = llm_title

        abstract = safe_text(llm_metadata_result.get("abstract") or "")
        doi = safe_text(llm_metadata_result.get("doi") or "") or None

    else:
        abstract = safe_text(existing_metadata.get("abstract") or "")
        doi = safe_text(existing_metadata.get("doi") or "") or None

    if not abstract:
        abstract = extract_abstract_from_markdown(markdown_text)
        if abstract and llm_metadata_info.get("status") != "success":
            llm_metadata_info["failure_reason"] = llm_metadata_info.get("failure_reason") or "DeepSeek 未返回有效摘要，已回退到 markdown 抽取"

    if not doi:
        doi = extract_doi_from_text(markdown_text)
        if doi and llm_metadata_info.get("status") != "success":
            llm_metadata_info["failure_reason"] = llm_metadata_info.get("failure_reason") or "DeepSeek 未返回 DOI，已回退到正则抽取"

    final_year = year
    final_journal_slug = safe_text(journal_match.get("journal_slug") or "")

    if final_year and final_journal_slug and final_journal_slug != "UnknownJournal":
        final_dir = _ensure_final_paper_dir(
            current_dir=current_dir,
            year=final_year,
            journal_slug_value=final_journal_slug,
            paper_id=paper_id,
        )
    else:
        final_dir = current_dir

    current_dir = final_dir
    source_pdf_copy = os.path.join(current_dir, "source.pdf")
    mineru_dir = os.path.join(current_dir, "mineru")
    root_full_md = os.path.join(current_dir, "full.md")
    metadata_path = os.path.join(current_dir, "metadata.json")

    llm_classification_info = {
        "status": safe_text(existing_metadata.get("llm_classification_status") or "") or "pending",
        "model": existing_metadata.get("llm_classification_model") or classifier.client.classification_model,
        "classified_at": existing_metadata.get("llm_classified_at"),
        "source": existing_metadata.get("llm_classification_source") or "",
        "failure_reason": existing_metadata.get("llm_classification_failure_reason") or "",
        "debug": existing_metadata.get("llm_classification_debug") or "",
    }

    classification = {
        "taxonomy_path": existing_metadata.get("taxonomy_path") or UNKNOWN_CLASSIFICATION,
        "main_topic": existing_metadata.get("main_topic") or "未分类",
        "leaf_topic": existing_metadata.get("leaf_topic") or "未分类",
        "confidence": existing_metadata.get("classification_confidence") or 0,
        "reason": existing_metadata.get("classification_reason") or "",
    }

    if abstract and _should_reclassify(existing_metadata, force_llm_classification, llm_signature=llm_signature):
        classification = classifier.classify(
            abstract=abstract,
            title=title,
            journal=journal_match.get("journal") or "",
        )
        classification_source = classification.get("_classification_source")
        llm_failure_reason = safe_text(classification.get("_llm_failure_reason") or "")
        llm_classification_info = {
            "status": "success" if classification_source == "llm" and classification.get("taxonomy_path") != UNKNOWN_CLASSIFICATION else "failed",
            "model": classifier.client.classification_model,
            "classified_at": utc_now_iso(),
            "source": classification_source or "",
            "failure_reason": (
                ""
                if classification_source == "llm" and classification.get("taxonomy_path") != UNKNOWN_CLASSIFICATION
                else (
                    f"{llm_failure_reason}; classification source={classification_source or 'unknown'}, "
                    f"taxonomy_path={classification.get('taxonomy_path')}"
                    if llm_failure_reason
                    else f"classification source={classification_source or 'unknown'}, taxonomy_path={classification.get('taxonomy_path')}"
                )
            ),
            "debug": llm_failure_reason,
        }
    elif not abstract:
        llm_classification_info = {
            "status": "failed",
            "model": classifier.client.classification_model,
            "classified_at": utc_now_iso(),
            "source": "skipped",
            "failure_reason": "abstract 缺失，无法调用分类模型",
            "debug": "",
        }

    metadata = _build_metadata_dict(
        pdf_path=pdf_path,
        paper_id=paper_id,
        paper_dir=current_dir,
        source_pdf_copy=source_pdf_copy,
        md_path=root_full_md,
        mineru_dir=mineru_dir,
        title=title,
        journal_match=journal_match,
        year=year,
        abstract=abstract,
        doi=doi,
        classification=classification,
        existing_metadata=existing_metadata,
        llm_metadata_info=llm_metadata_info,
        llm_classification_info=llm_classification_info,
        llm_signature=llm_signature,
    )
    dump_json(metadata_path, metadata)
    metadata["_needs_parse"] = needs_parse

    manifest_record = {
        "paper_id": paper_id,
        "paper_dir": to_relative_papers_path(current_dir),
        "metadata_path": to_relative_papers_path(metadata_path),
        "pdf_path": _normalize_manifest_pdf_key(pdf_path),
        "pdf_sha1": pdf_sha1,
        "pdf_mtime": os.path.getmtime(pdf_path),
        "parse_signature": parse_signature,
        "llm_signature": llm_signature,
        "ingest_signature": parse_signature,
        "engine": actual_engine,
        "title": metadata.get("title"),
        "journal": metadata.get("journal"),
        "journal_slug": metadata.get("journal_slug"),
        "year": metadata.get("year"),
        "taxonomy_path": metadata.get("taxonomy_path"),
        "llm_metadata_status": metadata.get("llm_metadata_status"),
        "llm_classification_status": metadata.get("llm_classification_status"),
        "status": "done",
    }


    # 删除旧 key，避免同一文件出现多份宿主机/容器路径记录
    all_old_keys = set(_iter_manifest_candidate_keys(pdf_path))
    if matched_manifest_key:
        all_old_keys.add(matched_manifest_key)

    for old_key in list(all_old_keys):
        if old_key in manifest:
            manifest.pop(old_key, None)

    # 最终统一用相对路径 key 存
    manifest[_normalize_manifest_pdf_key(pdf_path)] = manifest_record


    print(
        f"[papers_ingest] done: paper_id={paper_id}, dir={current_dir}, journal={metadata.get('journal')}, "
        f"year={metadata.get('year')}, metadata_status={metadata.get('llm_metadata_status')}, "
        f"classification_status={metadata.get('llm_classification_status')}, engine={actual_engine}",
        flush=True,
    )
    return metadata

def build_parse_signature(engine: str) -> str:
    payload = {
        "engine": engine,
        "mineru_api_base_url": get_env("MINERU_API_BASE_URL", ""),
        "mineru_api_model_version": get_env("MINERU_API_MODEL_VERSION", ""),
        "mineru_api_language": get_env("MINERU_API_LANGUAGE", ""),
        "mineru_api_enable_formula": get_env("MINERU_API_ENABLE_FORMULA", ""),
        "mineru_api_enable_table": get_env("MINERU_API_ENABLE_TABLE", ""),
        "mineru_api_is_ocr": get_env("MINERU_API_IS_OCR", ""),
        "mineru_api_page_ranges": get_env("MINERU_API_PAGE_RANGES", ""),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def build_llm_signature() -> str:
    payload = {
        "deepseek_api_base_url": os.getenv("DEEPSEEK_API_BASE_URL", ""),
        "deepseek_model": os.getenv("DEEPSEEK_MODEL", ""),
        "deepseek_metadata_model": os.getenv("DEEPSEEK_METADATA_MODEL", ""),
        "deepseek_classification_model": os.getenv("DEEPSEEK_CLASSIFICATION_MODEL", ""),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()

def rebuild_index_from_library(base_dir: str = PAPERS_LIBRARY_DIR):
    items = []
    base = Path(base_dir)
    if not base.is_dir():
        dump_json(PAPERS_LIBRARY_INDEX_PATH, [])
        return []

    for metadata_file in sorted(base.rglob("metadata.json")):
        metadata = load_json(str(metadata_file), default=None)
        if not isinstance(metadata, dict):
            continue

        paper_dir = metadata_file.parent
        paper_id = safe_text(metadata.get("paper_id") or "") or paper_dir.name.split("-")[-1]
        journal_value = safe_text(metadata.get("journal") or "")
        journal_slug_value = safe_text(metadata.get("journal_slug") or "")
        if journal_value and journal_slug_value in {"", "UnknownJournal"}:
            journal_slug_value = journal_slug(journal_value)
            metadata["journal_slug"] = journal_slug_value

        final_year = metadata.get("year")
        final_journal_slug = safe_text(journal_slug_value or "")

        if final_year and final_journal_slug and final_journal_slug != "UnknownJournal":
            desired_dir = paper_dir.parent / build_library_dirname(final_year, final_journal_slug, paper_id)
            if paper_dir != desired_dir and not desired_dir.exists():
                shutil.move(str(paper_dir), str(desired_dir))
                paper_dir = desired_dir
                metadata_file = paper_dir / "metadata.json"
                metadata["source_pdf"] = to_relative_papers_path(str(paper_dir / "source.pdf"))
                metadata["md_path"] = to_relative_papers_path(str(paper_dir / "full.md"))
                metadata["mineru_dir"] = to_relative_papers_path(str(paper_dir / "mineru"))
                dump_json(str(metadata_file), metadata)

            paper_dir = desired_dir
            metadata_file = paper_dir / "metadata.json"
            metadata["source_pdf"] = to_relative_papers_path(str(paper_dir / "source.pdf"))
            metadata["md_path"] = to_relative_papers_path(str(paper_dir / "full.md"))
            metadata["mineru_dir"] = to_relative_papers_path(str(paper_dir / "mineru"))

            dump_json(str(metadata_file), metadata)

        items.append(metadata)

    items.sort(
        key=lambda item: (
            item.get("year") or 0,
            item.get("journal") or "",
            item.get("title") or "",
        ),
        reverse=True,
    )
    dump_json(PAPERS_LIBRARY_INDEX_PATH, items)
    print(f"[papers_ingest] index rebuilt: total={len(items)}", flush=True)
    return items


def main():
    _reconfigure_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", default=PAPERS_RAW_DIR)
    parser.add_argument(
        "--engine",
        default="mineru_api",
        choices=[
            "mineru_api",
            "mineru_api_url",
            "mineru_agent",
            "mineru_agent_url",
            "mineru",
            "pymupdf4llm",
        ],
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--force-llm-metadata", action="store_true")
    parser.add_argument("--force-llm-classification", action="store_true")
    parser.add_argument("--no-sync", action="store_true")
    args = parser.parse_args()

    ensure_papers_index_scaffold()
    ensure_dir(args.base_dir)
    ensure_dir(PAPERS_LIBRARY_DIR)

    manifest = load_manifest()
    classifier = PaperClassifier()
    converted = 0

    for pdf_path in walk_raw_pdfs(args.base_dir):
        try:
            result = ingest_one_pdf(
                pdf_path=pdf_path,
                manifest=manifest,
                classifier=classifier,
                engine=args.engine,
                force=args.force,
                force_llm_metadata=args.force_llm_metadata,
                force_llm_classification=args.force_llm_classification,
            )
            if result and result.get("_needs_parse"):
                converted += 1
        except Exception as e:
            print(f"[papers_ingest] failed: pdf={pdf_path}, error={e}", flush=True)

    save_manifest(manifest)
    rebuild_index_from_library(PAPERS_LIBRARY_DIR)

    if args.no_sync:
        print("[papers_ingest] skip sync: disabled by --no-sync", flush=True)
    else:
        try:
            sync_papers_to_knowledge(clean_deleted=True)
        except Exception as e:
            print(f"[papers_ingest] sync to knowledge failed: {e}", flush=True)

    print(f"[papers_ingest] finished, converted={converted}", flush=True)


if __name__ == "__main__":
    main()
