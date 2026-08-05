# backend/services/papers_library/loader.py

import json
import os
import re
from typing import Dict, Any, List, Tuple


FRONT_MATTER_RE = re.compile(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n(.*)$", re.S)


def parse_simple_front_matter(text: str) -> Tuple[Dict[str, Any], str]:
    text = text or ""
    m = FRONT_MATTER_RE.match(text)
    if not m:
        return {}, text

    raw_meta = m.group(1)
    content = m.group(2)

    meta = {}
    current_key = None

    for line in raw_meta.splitlines():
        if not line.strip():
            continue

        if re.match(r"^\s+-\s+", line) and current_key:
            meta.setdefault(current_key, [])
            meta[current_key].append(re.sub(r"^\s+-\s+", "", line).strip().strip('"'))
            continue

        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip().strip('"')
            current_key = key

            if value == "":
                meta[key] = []
            else:
                if key == "year":
                    try:
                        meta[key] = int(value)
                    except Exception:
                        meta[key] = None
                else:
                    meta[key] = value

    return meta, content


def load_markdown_paper(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    meta, content = parse_simple_front_matter(text)

    return {
        "id": meta.get("doi") or os.path.splitext(os.path.basename(path))[0],
        "title": meta.get("title") or os.path.basename(path),
        "journal": meta.get("journal") or "Unknown",
        "year": meta.get("year"),
        "topic": meta.get("topic") or "unknown",
        "doi": meta.get("doi"),
        "url": meta.get("url"),
        "authors": meta.get("authors", []) if isinstance(meta.get("authors"), list) else [],
        "keywords": meta.get("keywords", []) if isinstance(meta.get("keywords"), list) else [],
        "summary": meta.get("summary"),
        "source_path": path,
        "content": content.strip(),
    }


def walk_papers(raw_base_dir: str) -> List[Dict[str, Any]]:
    items = []
    if not os.path.isdir(raw_base_dir):
        return items

    for root, _, files in os.walk(raw_base_dir):
        for name in files:
            if not name.endswith(".md"):
                continue
            path = os.path.join(root, name)
            try:
                items.append(load_markdown_paper(path))
            except Exception as e:
                print(f"[papers_library] failed loading {path}: {e}", flush=True)

    return items


def load_index_papers(index_path: str) -> List[Dict[str, Any]]:
    if not index_path or not os.path.isfile(index_path):
        return []

    with open(index_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items: List[Dict[str, Any]] = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue

        md_path = item.get("md_path")
        items.append({
            "id": item.get("paper_id") or item.get("doi") or os.path.splitext(os.path.basename(md_path or ""))[0],
            "title": item.get("title") or os.path.basename(md_path or "") or "Untitled",
            "journal": item.get("journal") or "Unknown",
            "year": item.get("year"),
            "topic": item.get("topic") or "unknown",
            "doi": item.get("doi"),
            "url": item.get("url"),
            "authors": item.get("authors", []) if isinstance(item.get("authors"), list) else [],
            "keywords": item.get("keywords", []) if isinstance(item.get("keywords"), list) else [],
            "summary": item.get("summary"),
            "source_path": md_path or item.get("source_pdf"),
            "md_path": md_path,
            "content": None,
        })

    return items


def load_markdown_content(md_path: str | None) -> str:
    if not md_path or not os.path.isfile(md_path):
        return ""

    with open(md_path, "r", encoding="utf-8") as f:
        text = f.read()

    _, content = parse_simple_front_matter(text)
    return content.strip()
