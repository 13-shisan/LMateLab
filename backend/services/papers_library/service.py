# backend/services/papers_library/service.py
from __future__ import annotations

import os
from typing import Optional

from services.papers.config import LEGACY_PAPERS_INDEX_PATH, PAPERS_LIBRARY_INDEX_PATH
from services.papers.utils import (
    load_json,
    load_taxonomy_config,
    read_text,
    safe_text,
    resolve_papers_path,
)



class PapersLibraryService:
    def __init__(self):
        self.index_path = PAPERS_LIBRARY_INDEX_PATH

    def _load_index(self):
        print("[papers_library] self.index_path =", self.index_path, flush=True)
        print("[papers_library] legacy_index_path =", LEGACY_PAPERS_INDEX_PATH, flush=True)

        items = load_json(self.index_path, default=[])
        print("[papers_library] loaded type =", type(items).__name__, flush=True)

        if isinstance(items, list):
            print("[papers_library] loaded len =", len(items), flush=True)
            if items:
                print("[papers_library] first paper_id =", items[0].get("paper_id"), flush=True)
                print("[papers_library] first title =", items[0].get("title"), flush=True)

        if not items and os.path.isfile(LEGACY_PAPERS_INDEX_PATH):
            print("[papers_library] fallback to legacy index", flush=True)
            items = load_json(LEGACY_PAPERS_INDEX_PATH, default=[])

        result = items if isinstance(items, list) else []
        print("[papers_library] final len =", len(result), flush=True)
        return result


    def _load_taxonomy(self):
        return load_taxonomy_config()

    @staticmethod
    def _normalize_taxonomy_path(value: str | list[str] | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [safe_text(x) for x in value if safe_text(x)]
        return [seg for seg in (safe_text(part) for part in str(value).split("/")) if seg]

    def _get_item_taxonomy_path(self, item: dict) -> list[str]:
        path = self._normalize_taxonomy_path(item.get("taxonomy_path"))
        if path:
            return path
        if item.get("topic_label"):
            return [safe_text(item.get("topic_label"))]
        if item.get("topic"):
            return [safe_text(item.get("topic"))]
        return []

    def _match_taxonomy(self, item: dict, taxonomy_path: str | None = None) -> bool:
        selected = self._normalize_taxonomy_path(taxonomy_path)
        if not selected:
            return True
        current = self._get_item_taxonomy_path(item)
        return current[:len(selected)] == selected

    def _match_query(self, item: dict, q: str = "") -> bool:
        q = safe_text(q).lower()
        if not q:
            return True
        fields = [
            item.get("title") or "",
            item.get("journal") or "",
            item.get("abstract") or "",
            item.get("summary") or "",
            " ".join(item.get("taxonomy_path") or []),
            " ".join(item.get("authors") or []),
            " ".join(item.get("keywords") or []),
        ]
        text = "\n".join(fields).lower()
        return q in text

    def _serialize_item(self, item: dict):
        paper_id = item.get("paper_id") or item.get("id")
        taxonomy_path = self._get_item_taxonomy_path(item)

        abstract = item.get("abstract") or item.get("summary") or ""
        return {
            "id": paper_id,
            "title": item.get("title") or "Untitled",
            "journal": item.get("journal") or "UnknownJournal",
            "journal_slug": item.get("journal_slug") or "UnknownJournal",
            "year": item.get("year"),
            "taxonomy_path": taxonomy_path or ["未分类"],
            "main_topic": item.get("main_topic") or (taxonomy_path[0] if taxonomy_path else "未分类"),
            "leaf_topic": item.get("leaf_topic") or (taxonomy_path[-1] if taxonomy_path else "未分类"),
            "abstract": abstract,
            "summary": item.get("summary") or abstract,
            "doi": item.get("doi"),
            "authors": item.get("authors") or [],
            "keywords": item.get("keywords") or [],
            "source_pdf": resolve_papers_path(item.get("source_pdf")),
            "md_path": resolve_papers_path(item.get("md_path") or item.get("source_path")),
        }

    def get_topics(self):
        roots = (self._load_taxonomy().get("roots") or [])
        return [
            {
                "key": safe_text(node.get("label") or node.get("name") or ""),
                "label": safe_text(node.get("label") or node.get("name") or ""),
            }
            for node in roots
            if safe_text(node.get("label") or node.get("name") or "")
        ]

    def get_taxonomy(self):
        index_items = self._load_index()
        count_map = {}
        for item in index_items:
            path = self._get_item_taxonomy_path(item)
            for i in range(1, len(path) + 1):
                key = tuple(path[:i])
                count_map[key] = count_map.get(key, 0) + 1

        def build(nodes, prefix=None):
            prefix = prefix or []
            result = []
            for node in nodes or []:
                label = safe_text(node.get("label") or node.get("name") or "")
                if not label:
                    continue
                path = prefix + [label]
                result.append({
                    "label": label,
                    "path": path,
                    "count": count_map.get(tuple(path), 0),
                    "children": build(node.get("children") or [], path),
                })
            return result

        return build(self._load_taxonomy().get("roots") or [])

    def get_journals(self, taxonomy_path: Optional[str] = None):
        items = [x for x in self._load_index() if self._match_taxonomy(x, taxonomy_path)]
        counter = {}
        slug_map = {}
        for item in items:
            journal = safe_text(item.get("journal") or "") or "UnknownJournal"
            counter[journal] = counter.get(journal, 0) + 1
            slug_map[journal] = item.get("journal_slug") or "UnknownJournal"

        return [
            {"journal": journal, "slug": slug_map.get(journal) or "UnknownJournal", "count": count}
            for journal, count in sorted(counter.items(), key=lambda x: (-x[1], x[0]))
        ]

    def search(
        self,
        q: str = "",
        taxonomy_path: Optional[str] = None,
        journal: Optional[str] = None,
        limit: int = 50,
    ):
        items = self._load_index()
        items = [x for x in items if self._match_taxonomy(x, taxonomy_path)]

        if journal:
            items = [x for x in items if safe_text(x.get("journal") or "") == safe_text(journal)]

        items = [x for x in items if self._match_query(x, q)]
        items.sort(key=lambda x: ((x.get("year") or 0), x.get("title") or ""), reverse=True)
        total = len(items)
        return {
            "items": [self._serialize_item(item) for item in items[:limit]],
            "total": total,
        }

    def get_detail(self, paper_id: str):
        items = self._load_index()
        for item in items:
            current_id = item.get("paper_id") or item.get("id")
            if current_id != paper_id:
                continue

            md_path = resolve_papers_path(item.get("md_path"))
            content = ""
            if md_path:
                try:
                    content = read_text(md_path)
                except Exception as e:
                    print(f"[papers_library] read detail failed: md_path={md_path}, error={e}", flush=True)
                    content = ""


            return {
                "item": self._serialize_item(item),
                "content": content,
            }

        raise ValueError(f"paper not found: {paper_id}")
