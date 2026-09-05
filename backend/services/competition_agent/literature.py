from __future__ import annotations

import json
import os
import re
import sqlite3
from html import unescape
from datetime import datetime, timezone
from pathlib import Path

import httpx


class LiteratureError(ValueError):
    pass


def database_path() -> Path:
    configured = os.environ.get("LMATELAB_LITERATURE_DB")
    return Path(configured or "data/competition-agent/literature.sqlite").resolve()


def _connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS literature_records (
            record_id TEXT NOT NULL,
            owner_id INTEGER NOT NULL,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            abstract TEXT NOT NULL,
            authors_json TEXT NOT NULL,
            publication_year INTEGER,
            doi TEXT,
            url TEXT,
            library_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (record_id, owner_id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_literature_owner_library "
        "ON literature_records(owner_id, library_name)"
    )
    return connection


def _abstract_from_index(index: object) -> str:
    if not isinstance(index, dict):
        return ""
    positioned: list[tuple[int, str]] = []
    for word, positions in index.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            continue
        positioned.extend((position, word) for position in positions if isinstance(position, int))
    return " ".join(word for _, word in sorted(positioned))[:30000]


def _openalex_item(raw: dict[str, object]) -> dict[str, object]:
    authorships = raw.get("authorships") if isinstance(raw.get("authorships"), list) else []
    authors = []
    for item in authorships[:100]:
        author = item.get("author") if isinstance(item, dict) else None
        name = author.get("display_name") if isinstance(author, dict) else None
        if isinstance(name, str) and name:
            authors.append(name)
    primary = raw.get("primary_location") if isinstance(raw.get("primary_location"), dict) else {}
    source_id = str(raw.get("id") or "").rsplit("/", 1)[-1]
    if not re.fullmatch(r"W\d+", source_id):
        raise LiteratureError("OpenAlex returned an invalid work identifier")
    doi = str(raw.get("doi") or "").removeprefix("https://doi.org/") or None
    open_access = raw.get("open_access") if isinstance(raw.get("open_access"), dict) else {}
    candidates = [primary.get("landing_page_url"), open_access.get("oa_url")]
    url = next(
        (candidate for candidate in candidates if isinstance(candidate, str) and candidate.startswith("https://")),
        f"https://doi.org/{doi}" if doi else None,
    )
    return {
        "kind": "literature",
        "id": f"openalex:{source_id}",
        "source": "OpenAlex",
        "title": str(raw.get("display_name") or "Untitled")[:1000],
        "abstract": _abstract_from_index(raw.get("abstract_inverted_index")),
        "authors": authors,
        "year": raw.get("publication_year") if isinstance(raw.get("publication_year"), int) else None,
        "doi": doi,
        "url": url,
        "library_name": None,
        "indexed": False,
    }


def _crossref_item(raw: dict[str, object]) -> dict[str, object]:
    doi = str(raw.get("DOI") or "").strip() or None
    titles = raw.get("title") if isinstance(raw.get("title"), list) else []
    title = next((str(item).strip() for item in titles if str(item).strip()), "Untitled")
    authors = []
    for item in raw.get("author", []) if isinstance(raw.get("author"), list) else []:
        if not isinstance(item, dict):
            continue
        name = " ".join(
            str(item.get(key) or "").strip() for key in ("given", "family")
        ).strip()
        if name:
            authors.append(name[:200])
    year = None
    for date_key in ("published-print", "published-online", "issued"):
        date = raw.get(date_key) if isinstance(raw.get(date_key), dict) else {}
        parts = date.get("date-parts") if isinstance(date.get("date-parts"), list) else []
        if parts and isinstance(parts[0], list) and parts[0] and isinstance(parts[0][0], int):
            year = parts[0][0]
            break
    provided_url = raw.get("URL")
    url = (
        provided_url
        if isinstance(provided_url, str) and provided_url.startswith("https://")
        else f"https://doi.org/{doi}" if doi else None
    )
    identity = doi or str(raw.get("URL") or title)
    abstract = unescape(re.sub(r"<[^>]+>", " ", str(raw.get("abstract") or "")))
    abstract = re.sub(r"\s+", " ", abstract).strip()[:30000]
    return {
        "kind": "literature",
        "id": f"crossref:{identity}"[:500],
        "source": "Crossref",
        "title": title[:1000],
        "abstract": abstract,
        "authors": authors[:100],
        "year": year,
        "doi": doi,
        "url": url,
        "library_name": None,
        "indexed": False,
    }


def search_openalex(query: str, limit: int = 10, *, client=None) -> list[dict[str, object]]:
    needle = query.strip()
    if len(needle) < 2:
        raise LiteratureError("literature query is too short")
    own_client = client is None
    selected = client or httpx.Client(timeout=12.0, follow_redirects=True)
    params: dict[str, object] = {"search": needle, "per-page": min(max(limit, 1), 20)}
    mailto = os.environ.get("LMATELAB_OPENALEX_MAILTO", "").strip()
    if mailto:
        params["mailto"] = mailto
    try:
        try:
            response = selected.get("https://api.openalex.org/works", params=params)
            response.raise_for_status()
            body = response.json()
            results = body.get("results") if isinstance(body, dict) else None
            if not isinstance(results, list):
                raise LiteratureError("OpenAlex returned an invalid response")
            items = []
            for raw in results:
                if not isinstance(raw, dict):
                    continue
                try:
                    items.append(_openalex_item(raw))
                except LiteratureError:
                    continue
            return items
        except Exception:
            try:
                response = selected.get(
                    "https://api.crossref.org/works",
                    params={"query": needle, "rows": min(max(limit, 1), 20)},
                )
                response.raise_for_status()
                body = response.json()
                message = body.get("message") if isinstance(body, dict) else None
                results = message.get("items") if isinstance(message, dict) else None
                if not isinstance(results, list):
                    raise LiteratureError("Crossref returned an invalid response")
                return [_crossref_item(raw) for raw in results if isinstance(raw, dict)]
            except Exception as crossref_error:
                raise LiteratureError("public literature search is temporarily unavailable") from crossref_error
    finally:
        if own_client:
            selected.close()


def index_record(owner_id: int, payload: dict[str, object]) -> dict[str, object]:
    record_id = str(payload["source_id"])
    source = "OpenAlex" if record_id.startswith("openalex:") else "用户索引"
    now = datetime.now(timezone.utc).isoformat()
    authors = [str(item)[:200] for item in payload.get("authors", [])]
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO literature_records (
                record_id, owner_id, source, title, abstract, authors_json,
                publication_year, doi, url, library_name, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(record_id, owner_id) DO UPDATE SET
                title=excluded.title, abstract=excluded.abstract,
                authors_json=excluded.authors_json, publication_year=excluded.publication_year,
                doi=excluded.doi, url=excluded.url, library_name=excluded.library_name
            """,
            (
                record_id,
                owner_id,
                source,
                str(payload["title"])[:1000],
                str(payload.get("abstract") or "")[:30000],
                json.dumps(authors, ensure_ascii=False),
                payload.get("year"),
                payload.get("doi"),
                payload.get("url"),
                str(payload.get("library_name") or "我的文献库")[:80],
                now,
            ),
        )
    return get_record(owner_id, record_id)


def _view(row: sqlite3.Row) -> dict[str, object]:
    return {
        "kind": "literature",
        "id": row["record_id"],
        "source": row["source"],
        "title": row["title"],
        "abstract": row["abstract"],
        "authors": json.loads(row["authors_json"]),
        "year": row["publication_year"],
        "doi": row["doi"],
        "url": row["url"],
        "library_name": row["library_name"],
        "indexed": True,
    }


def get_record(owner_id: int, record_id: str) -> dict[str, object]:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM literature_records WHERE owner_id = ? AND record_id = ?",
            (owner_id, record_id),
        ).fetchone()
    if row is None:
        raise LiteratureError("literature record is unavailable")
    return _view(row)


def list_records(owner_id: int, query: str = "", limit: int = 100) -> list[dict[str, object]]:
    needle = query.strip()
    sql = "SELECT * FROM literature_records WHERE owner_id = ?"
    params: list[object] = [owner_id]
    if needle:
        sql += " AND (title LIKE ? OR abstract LIKE ? OR doi LIKE ?)"
        token = f"%{needle}%"
        params.extend([token, token, token])
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(min(max(limit, 1), 200))
    with _connect() as connection:
        rows = connection.execute(sql, params).fetchall()
    return [_view(row) for row in rows]


def selected_records(owner_id: int, record_ids: list[str]) -> list[dict[str, object]]:
    ids = list(dict.fromkeys(record_ids))
    if not ids:
        return []
    records = [get_record(owner_id, record_id) for record_id in ids]
    for record in records:
        record["abstract"] = str(record["abstract"])[:8000]
    return records


def retrieve_for_prompt(owner_id: int, prompt: str, *, include_public: bool) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    local = list_records(owner_id, prompt, 5)
    tools = [{"name": "search_literature_index", "status": "succeeded"}]
    public: list[dict[str, object]] = []
    if include_public:
        try:
            public = search_openalex(prompt, 5)
            tools.append({"name": "search_openalex", "status": "succeeded"})
        except LiteratureError:
            tools.append({"name": "search_openalex", "status": "failed"})
    return (local + public)[:10], tools
