# backend/tasks/dailypapers.py
import os
import time
import requests
import json
import re
from html import unescape
from datetime import datetime, timezone, date
from sqlalchemy.orm import Session
from digest_models import DailyDigest
from digest_database import DigestSessionLocal
from functools import lru_cache
from zoneinfo import ZoneInfo
from datetime import timedelta

# 建议：用 RSS（feedparser）或 Crossref API
# pip install feedparser
import feedparser

JOURNAL_FEEDS = {
    # --- Nature family ---
    "Nature": ["https://www.nature.com/nature.rss"],
    "Nature Materials": ["https://www.nature.com/nmat.rss"],
    "Nature Chemistry": ["https://www.nature.com/nchem.rss"],
    "Nature Physics": ["https://www.nature.com/nphys.rss"],
    "npj Computational Materials": ["https://www.nature.com/npjcompumats.rss"],

    # --- ACS (把每个期刊的 RSS 填成官网 showFeed 链接) ---
    "JACS": [
        "https://pubs.acs.org/action/showFeed?type=etoc&feed=rss&jc=jacsat",
    ],
    "ACS Catalysis": [
        "https://pubs.acs.org/action/showFeed?type=etoc&feed=rss&jc=accacs",
    ],
    "Nano Letters": [
        "https://pubs.acs.org/action/showFeed?type=etoc&feed=rss&jc=nalefd",
    ],
    "JPCL": [
        "https://pubs.acs.org/action/showFeed?type=etoc&feed=rss&jc=jpclcd",
    ],
    "ACS Nano": [
        "https://pubs.acs.org/action/showFeed?type=etoc&feed=rss&jc=ancac3",
    ],

    # --- Materials / Low-dim ---
    "Advanced Materials": [
        "https://onlinelibrary.wiley.com/action/showFeed?ui=0&mi=5e9fis5&type=search&feed=rss&query=%2526AllField%253DAdvanced%252BMaterials%2526content%253DarticlesChapters%2526target%253Ddefault"
    ],
    "Advanced Functional Materials": [
        "https://onlinelibrary.wiley.com/action/showFeed?ui=0&mi=5e9fis5&type=search&feed=rss&query=%2526AllField%253DAdvanced%252BFunctional%252BMaterials%2526content%253DarticlesChapters%2526target%253Ddefault"
    ],
    "Small": [
        "https://onlinelibrary.wiley.com/action/showFeed?ui=0&mi=5e9fis5&type=search&feed=rss&query=%2526AllField%253DSmall%2526content%253DarticlesChapters%2526target%253Ddefault"
    ],
    "Chemistry of Materials": [
        "https://pubs.acs.org/action/showFeed?type=etoc&feed=rss&jc=cmatex",
    ],

    # --- AI / interdisciplinary ---
    "Nature Machine Intelligence": [
        "https://www.nature.com/natmachintell.rss"
    ],
    "npj Artificial Intelligence": [
        "https://www.nature.com/npjai.rss"
    ],
}

DEFAULT_HEADERS = {
    "User-Agent": "LMateLabBot/1.0 (+https://matflow.top)",
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8,zh-CN;q=0.6",
    "Cache-Control": "no-cache",
}

_session = requests.Session()

def _safe_get(url: str, timeout=25):
    last_exc = None
    for i in range(4):  # 4 次更稳一点
        try:
            r = _session.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code in (429, 503):
                time.sleep(1.5 * (2 ** i))  # 1.5,3,6,12
                continue
            r.raise_for_status()
        except Exception as e:
            last_exc = e
            time.sleep(1.0 * (i + 1))
    raise last_exc

def build_digest_text(journal: str, entries, target_date: date):
    lines = [f"{target_date.isoformat()}《{journal}》期刊新文献导读", ""]
    count = 0
    for e in entries[:30]:
        title = getattr(e, "title", "").strip()
        link = getattr(e, "link", "").strip()
        if not title:
            continue
        count += 1
        lines.append(f"{count}. {title}")
        if link:
            lines.append(f"   {link}")
        lines.append("")
    return "\n".join(lines).strip()

def build_papers(journal: str, entries, target_date: date):
    papers = []
    for e in entries[:50]:
        title = (getattr(e, "title", "") or "").strip()
        link = (getattr(e, "link", "") or "").strip()
        if not title:
            continue

        # 日期（按 _entry_date 的时区逻辑）
        published = None
        ed = _entry_date(e)
        if ed:
            published = ed.isoformat()

        # DOI（先提取，再查 Crossref）
        doi = _extract_doi(e)
        cr = _crossref_lookup_cached(doi) if doi else None
        
        # ✅ 如果 RSS 没给日期，用 Crossref 的发表日期补齐（对 ACS 很关键）
        if not published and cr and cr.get("published_date"):
            published = cr["published_date"]

        # RSS summary（HTML + 纯文本）
        summary_html = (getattr(e, "summary", None) or getattr(e, "description", None) or "")
        summary_html = str(summary_html).strip() if summary_html else ""
        summary_text = html_to_text(summary_html)

        # Crossref abstract（JATS/XML → 纯文本）
        abstract_raw = (cr.get("abstract") if cr else "") or ""
        abstract_text = clean_crossref_abstract(abstract_raw)

        # RSS authors（有些 feed 会给 authors）
        rss_authors = []
        for a in (getattr(e, "authors", None) or []):
            n = (a.get("name") if isinstance(a, dict) else None) or ""
            n = str(n).strip()
            if n:
                rss_authors.append(n)

        # 作者优先 Crossref，否则 RSS
        authors = (cr.get("authors") if (cr and cr.get("authors")) else rss_authors)

        papers.append({
            "title": title,
            "link": link,
            "published": published,

            "doi": (cr.get("doi") if cr else doi),
            "authors": authors,

            # ✅ 建议前端优先展示 *_text
            "summary_html": summary_html,
            "summary_text": summary_text,

            "abstract_raw": abstract_raw,
            "abstract_text": abstract_text,

            "source": "rss+crossref" if cr else "rss",
        })
    return papers

def run_daily_digest(journal: str):
    db: Session = DigestSessionLocal()
    try:
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()

        exists = (
            db.query(DailyDigest)
            .filter(DailyDigest.date == today, DailyDigest.journal == journal)
            .first()
        )
        if exists:
            return

        entries = fetch_entries(journal)[:120]  # ACS 一期可能很多篇，稍微取多一点
        if not entries:
            return

        papers = build_papers(journal, entries, today)
        if not papers:
            return

        # ✅ 先“严格当天”，如果当天没有，再 fallback 到近 N 天
        LOOKBACK_DAYS = 30  # 你想要的回看天数
        today_iso = today.isoformat()

        def _pub_date(p) -> str:
            # 统一取 'YYYY-MM-DD'，没有就返回空字符串
            pub = (p.get("published") or "").strip()
            return pub[:10] if len(pub) >= 10 else ""

        papers_today = [p for p in papers if _pub_date(p) == today_iso]

        if papers_today:
            papers = papers_today
            mode_title = f"{today_iso}《{journal}》期刊新文献导读（仅今日）"
        else:
            cutoff = today - timedelta(days=LOOKBACK_DAYS)
            cutoff_iso = cutoff.isoformat()

            papers_window = [
                p for p in papers
                if (cutoff_iso <= _pub_date(p) <= today_iso)
            ]
            papers = papers_window
            mode_title = f"{today_iso}《{journal}》期刊新文献导读（近{LOOKBACK_DAYS}天）"

        if not papers:
            return

        # ✅ 让纯文本 digest 和 papers 对齐（用 papers 生成）
        content_lines = [mode_title, ""]
        for i, p in enumerate(papers[:30], 1):
            content_lines.append(f"{i}. {p.get('title','').strip()}")
            if p.get("link"):
                content_lines.append(f"   {p['link']}")
            if p.get("published"):
                content_lines.append(f"   published: {p['published']}")
            content_lines.append("")
        content = "\n".join(content_lines).strip()

        row = DailyDigest(
            date=today,
            journal=journal,
            code=journal,
            category="综合",
            title=mode_title,
            content=content or "",
            papers_json=json.dumps(papers, ensure_ascii=False),
            created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )
        db.add(row)
        db.commit()
    finally:
        db.close()


def _entry_date(e) -> date | None:
    """
    解析 entry 的日期：
    1) 优先吃 ACS/Wiley 常见的结构化字段（prism_coverdate / dc_date 等）
    2) 再退回到 RSS 标准的 published_parsed / updated_parsed
    """
    # 1) ACS 常见：prism_coverdate = '2025-12-31'
    if hasattr(e, "get"):
        for k in ("prism_coverdate", "prism:coverDate", "dc_date", "dc:date", "published", "updated"):
            v = e.get(k)
            if v:
                s = str(v).strip()
                # 只取前 10 位，兼容 'YYYY-MM-DD...' 的情况
                try:
                    return datetime.fromisoformat(s[:10]).date()
                except Exception:
                    pass

    # 2) 常规 RSS：struct_time
    tm = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
    if not tm:
        return None

    dt_utc = datetime(*tm[:6], tzinfo=timezone.utc)
    return dt_utc.astimezone(ZoneInfo("Asia/Shanghai")).date()

_DOI_RE = re.compile(r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.IGNORECASE)

def _extract_doi(e) -> str | None:
    # 1) 先从结构化字段里拿（ACS/Wiley 经常在这里）
    if hasattr(e, "get"):
        for k in ("prism_doi", "prism:doi", "dc_identifier", "dc:identifier", "doi", "DOI"):
            v = e.get(k)
            if v:
                m = _DOI_RE.search(str(v))
                if m:
                    return m.group(1)

    # 2) 再从常见文本字段扫一遍
    hay = " ".join([
        str(getattr(e, "id", "") or ""),
        str(getattr(e, "link", "") or ""),
        str(getattr(e, "summary", "") or ""),
        str(getattr(e, "description", "") or ""),
        str(getattr(e, "title", "") or ""),
    ])
    m = _DOI_RE.search(hay)
    return m.group(1) if m else None

def _crossref_lookup(doi: str) -> dict | None:
    url = f"https://api.crossref.org/works/{doi}"
    try:
        r = _session.get(url, headers={"User-Agent": DEFAULT_HEADERS["User-Agent"]}, timeout=15)
        if r.status_code != 200:
            return None
        msg = r.json().get("message") or {}

        authors = []
        for a in (msg.get("author") or []):
            name = " ".join([a.get("given", "") or "", a.get("family", "") or ""]).strip()
            if name:
                authors.append(name)

        abstract = msg.get("abstract")

        # ✅ 尽量取 online，其次 print
        date_parts = None
        for key in ("published-online", "published-print", "created", "issued"):
            dp = ((msg.get(key) or {}).get("date-parts") or None)
            if dp and isinstance(dp, list) and dp and dp[0]:
                date_parts = dp[0]  # [YYYY, MM, DD?]
                break

        published_date = None
        if date_parts:
            y = int(date_parts[0])
            m = int(date_parts[1]) if len(date_parts) >= 2 else 1
            d = int(date_parts[2]) if len(date_parts) >= 3 else 1
            published_date = date(y, m, d).isoformat()

        return {
            "doi": msg.get("DOI") or doi,
            "authors": authors,
            "abstract": abstract,
            "publisher": msg.get("publisher"),
            "container_title": (msg.get("container-title") or [None])[0],
            "published_date": published_date,   # ✅ 新增
        }
    except Exception:
        return None

def fetch_entries(journal: str):
    feed_urls = JOURNAL_FEEDS.get(journal)
    if not feed_urls:
        return []

    if isinstance(feed_urls, str):
        feed_urls = [feed_urls]

    entries_all = []
    for url in feed_urls:
        r = _safe_get(url, timeout=25)
        d = feedparser.parse(r.text)
        entries_all.extend(list(d.entries or []))
    return dedup_entries(entries_all)

def fetch_today_entries(journal: str, target_date: date):
    entries = fetch_entries(journal)
    if not entries:
        return []

    today_entries = []
    for e in entries:
        ed = _entry_date(e)
        if ed == target_date:
            today_entries.append(e)

    return today_entries[:50]

def _openalex_lookup_by_doi(doi: str) -> dict | None:
    url = f"https://api.openalex.org/works/https://doi.org/{doi}"
    try:
        r = _session.get(url, headers={"User-Agent": DEFAULT_HEADERS["User-Agent"]}, timeout=15)
        if r.status_code != 200:
            return None
        w = r.json() or {}
        authors = []
        for a in (w.get("authorships") or []):
            name = (a.get("author") or {}).get("display_name")
            if name:
                authors.append(name)
        # OpenAlex 的 abstract 常是 inverted_index，需要还原；这里先占位，不强求
        return {
            "authors": authors,
            "openalex_id": w.get("id"),
        }
    except Exception:
        return None
    
_TAG_RE = re.compile(r"<[^>]+>")

def html_to_text(s: str) -> str:
    if not s:
        return ""
    s = unescape(s)
    s = s.replace("<br/>", "\n").replace("<br>", "\n").replace("</p>", "\n")
    s = _TAG_RE.sub("", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s

def clean_crossref_abstract(a: str | None) -> str:
    # Crossref abstract 常是 JATS/XML，本质也是“带标签的字符串”
    return html_to_text(a or "")

def dedup_entries(entries):
    seen = set()
    out = []
    for e in entries:
        doi = _extract_doi(e) or ""
        link = str(getattr(e, "link", "") or "")
        title = str(getattr(e, "title", "") or "")
        key = doi.lower().strip() or link.strip() or title.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out

@lru_cache(maxsize=2000)
def _crossref_lookup_cached(doi: str) -> dict | None:
    return _crossref_lookup(doi)