# backend/services/papers/utils.py
import os
import re
import json
import yaml
import shutil
import hashlib
import unicodedata
from pathlib import Path
from typing import Dict, Any, Tuple, Iterable

from .config import (
    MANIFEST_PATH,
    INDEX_PATH,
    MAX_FILENAME_LEN,
    JOURNAL_SLUG_MAP,
    TOPIC_LABELS,
    ENDNOTE_JOURNAL_TXT,
    PAPERS_INDEX_DIR,
    PAPERS_JOURNAL_FEATURES_PATH,
    PAPERS_JOURNAL_FEATURES_TEMPLATE_PATH,
    PAPERS_TAXONOMY_PATH,
    PAPERS_TAXONOMY_TEMPLATE_PATH,
    PAPERS_ROOT_DIR,
    HOST_PAPERS_ROOT_DIR,
)


_ENDNOTE_FULL_TO_ABBR: dict[str, str] | None = None
_ENDNOTE_NORMALIZED_LOOKUP: dict[str, tuple[str, str]] | None = None
_ENDNOTE_SORTED_KEYS: list[tuple[str, str, str]] | None = None
_JOURNAL_FEATURES_CACHE: dict[str, Any] | None = None
_TAXONOMY_CACHE: dict[str, Any] | None = None
# [(normalized_key, full_name, abbr)], 按 normalized_key 长度降序

def is_reusable_paper_bundle(paper_dir: str, pdf_sha1: str | None = None) -> bool:
    """
    判断 paper_dir 是否可直接复用，避免重复解析。
    条件：
    - metadata.json 存在
    - source.pdf 存在
    - full.md 存在
    - mineru 目录存在
    - 若给了 pdf_sha1，则 source.pdf 的 sha1 必须一致
    """
    if not is_library_bundle_complete(paper_dir):
        return False

    if not pdf_sha1:
        return True

    source_pdf = os.path.join(paper_dir, "source.pdf")
    if not os.path.isfile(source_pdf):
        return False

    try:
        return file_sha1(source_pdf) == pdf_sha1
    except Exception:
        return False


def load_endnote_journal_map(txt_path: str) -> tuple[dict[str, str], dict[str, tuple[str, str]], list[tuple[str, str, str]]]:
    """
    读取 EndNote 导出的期刊全称/简称表（两列，tab 分隔）。
    返回：
    - full_to_abbr
    - normalized_lookup
    - sorted_keys: [(normalized_key, full_name, abbr)]，按 key 长度降序
    """
    full_to_abbr: dict[str, str] = {}
    normalized_lookup: dict[str, tuple[str, str]] = {}
    sorted_keys: list[tuple[str, str, str]] = []

    if not txt_path or not os.path.exists(txt_path):
        return full_to_abbr, normalized_lookup, sorted_keys

    with open(txt_path, "r", encoding="utf-8-sig") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue

            parts = line.split("\t")
            if len(parts) < 2:
                continue

            full_name = safe_text(parts[0])
            abbr = safe_text(parts[1])

            if not full_name:
                continue

            full_to_abbr[full_name] = abbr

            for src in {full_name, abbr}:
                nk = normalize_journal_key(src)
                if nk:
                    normalized_lookup[nk] = (full_name, abbr)

    for nk, (full_name, abbr) in normalized_lookup.items():
        sorted_keys.append((nk, full_name, abbr))

    sorted_keys.sort(key=lambda x: len(x[0]), reverse=True)
    return full_to_abbr, normalized_lookup, sorted_keys

def get_endnote_journal_lookup():
    global _ENDNOTE_FULL_TO_ABBR, _ENDNOTE_NORMALIZED_LOOKUP, _ENDNOTE_SORTED_KEYS

    if _ENDNOTE_FULL_TO_ABBR is None or _ENDNOTE_NORMALIZED_LOOKUP is None or _ENDNOTE_SORTED_KEYS is None:
        _ENDNOTE_FULL_TO_ABBR, _ENDNOTE_NORMALIZED_LOOKUP, _ENDNOTE_SORTED_KEYS = load_endnote_journal_map(
            ENDNOTE_JOURNAL_TXT
        )

    return _ENDNOTE_FULL_TO_ABBR, _ENDNOTE_NORMALIZED_LOOKUP, _ENDNOTE_SORTED_KEYS

def normalize_path(path: str | None) -> str | None:
    if path is None:
        return None
    value = str(path).strip()
    return value or None


def to_relative_papers_path(path: str | None) -> str | None:
    """
    把绝对路径转成相对 PAPERS_ROOT_DIR / HOST_PAPERS_ROOT_DIR 的相对路径。
    例如：
    /app/var/papers/library/a/full.md -> library/a/full.md
    /storage/software/LMateLab/var/papers/library/a/full.md -> library/a/full.md
    """
    path = normalize_path(path)
    if not path:
        return None

    abs_path = os.path.abspath(path)

    for root in [PAPERS_ROOT_DIR, HOST_PAPERS_ROOT_DIR]:
        root = normalize_path(root)
        if not root:
            continue
        root_abs = os.path.abspath(root)
        try:
            common = os.path.commonpath([abs_path, root_abs])
        except Exception:
            common = None

        if common == root_abs:
            rel = os.path.relpath(abs_path, root_abs)
            return rel.replace("\\", "/")

    if not os.path.isabs(path):
        return path.replace("\\", "/")

    return path


def resolve_papers_path(path: str | None) -> str | None:
    """
    将 papers 相关路径统一解析为当前运行环境可访问的绝对路径。
    支持：
    1. 相对路径：library/... -> <PAPERS_ROOT_DIR>/library/...
    2. 宿主机路径 <-> 容器路径 双向映射
    3. 当前环境绝对路径：直接返回
    """
    path = normalize_path(path)
    if not path:
        return None

    abs_path = os.path.abspath(path)
    papers_root_abs = os.path.abspath(PAPERS_ROOT_DIR)
    host_root_abs = os.path.abspath(HOST_PAPERS_ROOT_DIR) if HOST_PAPERS_ROOT_DIR else None
    container_root_abs = os.path.abspath("/app/var/papers")

    # 1) 相对路径
    if not os.path.isabs(path):
        return os.path.abspath(os.path.join(PAPERS_ROOT_DIR, path))

    # 2) 已经在当前 root 下
    try:
        if os.path.commonpath([abs_path, papers_root_abs]) == papers_root_abs:
            return abs_path
    except Exception:
        pass

    # 3) 宿主机路径 -> 当前 root
    if host_root_abs:
        try:
            if os.path.commonpath([abs_path, host_root_abs]) == host_root_abs:
                rel = os.path.relpath(abs_path, host_root_abs)
                return os.path.abspath(os.path.join(PAPERS_ROOT_DIR, rel))
        except Exception:
            pass

    # 4) 容器路径 -> 当前 root
    try:
        if os.path.commonpath([abs_path, container_root_abs]) == container_root_abs:
            rel = os.path.relpath(abs_path, container_root_abs)
            return os.path.abspath(os.path.join(PAPERS_ROOT_DIR, rel))
    except Exception:
        pass

    return abs_path

def read_json_debug(path: str, default):
    """
    调试辅助，可按需替换 load_json 使用。
    """
    resolved = resolve_papers_path(path) or path
    if not os.path.exists(resolved):
        print(f"[papers.utils] json not found: original={path}, resolved={resolved}", flush=True)
        return default
    try:
        with open(resolved, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(
            f"[papers.utils] json loaded: original={path}, resolved={resolved}, type={type(data).__name__}",
            flush=True,
        )
        return data
    except Exception as e:
        print(
            f"[papers.utils] json load failed: original={path}, resolved={resolved}, error={e}",
            flush=True,
        )
        return default

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def load_json(path: str, default):
    resolved = resolve_papers_path(path) or path
    if not os.path.exists(resolved):
        return default
    try:
        with open(resolved, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def dump_json(path: str, data):
    resolved = resolve_papers_path(path) or path
    ensure_dir(os.path.dirname(resolved))
    with open(resolved, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def copy_file_if_missing(src: str, dst: str):
    if not src or not os.path.isfile(src) or os.path.exists(dst):
        return
    ensure_dir(os.path.dirname(dst))
    shutil.copy2(src, dst)


def ensure_papers_index_scaffold():
    try:
        ensure_dir(PAPERS_INDEX_DIR)
        copy_file_if_missing(PAPERS_TAXONOMY_TEMPLATE_PATH, PAPERS_TAXONOMY_PATH)
        copy_file_if_missing(PAPERS_JOURNAL_FEATURES_TEMPLATE_PATH, PAPERS_JOURNAL_FEATURES_PATH)
        if not os.path.exists(INDEX_PATH):
            dump_json(INDEX_PATH, [])
        if not os.path.exists(MANIFEST_PATH):
            dump_json(MANIFEST_PATH, {})
    except PermissionError:
        return


def load_manifest():
    return load_json(MANIFEST_PATH, default={})


def save_manifest(data):
    dump_json(MANIFEST_PATH, data)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())

def remove_spaces(text: str) -> str:
    return re.sub(r"\s+", "", safe_text(text or ""))

def _extract_year_candidates_from_text(text: str) -> list[int]:
    years = re.findall(r"\b(19\d{2}|20\d{2})\b", text or "")
    out: list[int] = []
    for y in years:
        yi = int(y)
        if 1900 <= yi <= 2100:
            out.append(yi)
    return out


def _collect_content_list_entries(obj, parent_type: str | None = None) -> list[dict[str, str]]:
    """
    递归提取 content_list_v2.json 中的文本，并尽量保留外层块类型：
    - page_footer
    - page_header
    - paragraph
    等

    返回:
    [
        {"block_type": "page_footer", "text": "..."},
        {"block_type": "paragraph", "text": "..."},
    ]
    """
    entries: list[dict[str, str]] = []

    def walk(x, current_block_type: str | None):
        if isinstance(x, dict):
            node_type = x.get("type")
            next_block_type = current_block_type

            # 只把外层结构类型作为 block type 传下去
            if node_type in {"page_footer", "page_header", "paragraph", "title", "section_header"}:
                next_block_type = node_type

            if node_type == "text" and isinstance(x.get("content"), str):
                t = normalize_whitespace(x.get("content", ""))
                if t:
                    entries.append({
                        "block_type": next_block_type or "",
                        "text": t,
                    })

            for v in x.values():
                walk(v, next_block_type)

        elif isinstance(x, list):
            for item in x:
                walk(item, current_block_type)

    walk(obj, parent_type)
    return entries


def load_content_list_entries(content_list_json_path: str) -> list[dict[str, str]]:
    data = load_json(content_list_json_path, default=None)
    if data is None:
        return []
    return _collect_content_list_entries(data)


def _clean_extracted_journal(text: str) -> str:
    text = safe_text(text or "")

    # 去掉前缀：Cite This / Cite This:
    text = re.sub(r"^\s*Cite\s+This\s*:?\s*", "", text, flags=re.IGNORECASE)

    # 如果后面跟了竖线说明后面大概率不是期刊名
    text = re.split(r"\s*\|\s*", text, maxsplit=1)[0]

    # 去掉从年份开始的尾巴
    text = re.split(r"\s+\((?:19\d{2}|20\d{2})\)", text, maxsplit=1)[0]
    text = re.split(r"\s+(?:19\d{2}|20\d{2})\b", text, maxsplit=1)[0]

    # 去掉首尾空白和明显分隔符，但保留正常缩写里的句点
    text = text.strip(" |,:;")

    return text


def _extract_journal_candidate_from_header_footer_text(text: str) -> str | None:
    """
    从 page_footer / page_header 的文本中，通用兜底提取期刊名。
    仅在特定格式都未匹配时使用。
    """
    s = safe_text(text or "")
    if not s:
        return None

    s = re.sub(r"^\s*Cite\s+This\s*:?\s*", "", s, flags=re.IGNORECASE).strip()

    # 优先按 | 截断
    if "|" in s:
        left = s.split("|", 1)[0].strip()
        left = _clean_extracted_journal(left)
        if left:
            return left

    # 再按年份 / Volume 截断
    patterns = [
        r"\s+\((?:19\d{2}|20\d{2})\)",
        r"\s+(?:19\d{2}|20\d{2})\b",
        r"\s+Volume\b",
        r"\s+Vol\.",
        r"\s+No\.",
        r"\s+pp?\.",
    ]

    cut_pos = None
    for p in patterns:
        m = re.search(p, s, flags=re.IGNORECASE)
        if m:
            pos = m.start()
            if cut_pos is None or pos < cut_pos:
                cut_pos = pos

    candidate = s[:cut_pos].strip() if cut_pos is not None else s.strip()
    candidate = _clean_extracted_journal(candidate)
    return candidate or None



def _extract_year_from_header_footer_text(text: str) -> int | None:
    """
    从 page_footer / page_header 文本中提取年份。
    """
    s = safe_text(text or "")
    if not s:
        return None

    # 优先匹配括号年份，如 (2024)
    m = re.search(r"\((19\d{2}|20\d{2})\)", s)
    if m:
        return int(m.group(1))

    # 再匹配普通年份
    years = _extract_year_candidates_from_text(s)
    return years[0] if years else None


def _parse_published_or_received_year(text: str) -> int | None:
    """
    支持：
    - Published: February 8, 2019
    - Received: December 1, 2018
    """
    if not re.search(r"^\s*(Published|Received)\s*:", text, flags=re.IGNORECASE):
        return None

    years = _extract_year_candidates_from_text(text)
    return years[0] if years else None


def _parse_cite_this_line(text: str) -> tuple[int | None, str | None]:
    """
    支持：
    - Cite This: ACS Nano 2024, 18, 8511-8516
    - Cite This: J. Am. Chem. Soc. 2018, 140, 17895-17900
    """
    m = re.search(
        r"^\s*Cite\s+This\s*:?\s*(?P<journal>.+?)\s+(?P<year>19\d{2}|20\d{2})\b",
        text,
        flags=re.IGNORECASE,
    )
    if not m:
        return None, None

    journal = _clean_extracted_journal(m.group("journal"))
    year = int(m.group("year"))
    return year, journal

def _is_valid_journal_candidate(journal: str | None) -> bool:
    j = safe_text(journal or "")
    if not j:
        return False
    if len(j) <= 1:
        return False
    if re.fullmatch(r"[\W_#]+", j):
        return False
    if re.match(r"^(Published|Received)\s*:", j, flags=re.IGNORECASE):
        return False
    return True

def _parse_aps_journal_line(text: str) -> tuple[int | None, str | None]:
    """
    处理 APS 常见页眉格式，例如：
    - PHYSICAL REVIEW B 106, 115423 (2022)
    - PHYSICAL REVIEW LETTERS 125, 177701 (2020)
    - PHYSICAL REVIEW MATERIALS 2, 114010 (2018)
    - PHYSICAL REVIEW APPLIED 21, 054017 (2024)

    也尽量兼容 OCR 导致的空格/逗号轻微损坏：
    - PHYSICAL REVIEW B109,115427(2024)
    - PHYSICAL REVIEW B 109 115427 (2024)
    """
    s = safe_text(text or "")
    if not s:
        return None, None

    aps_journal_pattern = (
        r"PHYSICAL\s+REVIEW(?:"
        r"\s+LETTERS"
        r"|\s+MATERIALS"
        r"|\s+APPLIED"
        r"|\s+[A-Z]"
        r")"
    )

    patterns = [
        # 标准格式
        rf"^(?P<journal>{aps_journal_pattern})\s+\d+\s*,\s*[\dA-Za-z\-]+(?:\s*\((?P<year>19\d{{2}}|20\d{{2}})\))?\s*$",

        # OCR 紧贴：B109,115427(2024)
        rf"^(?P<journal>{aps_journal_pattern})\s*\d+\s*,\s*[\dA-Za-z\-]+(?:\s*\((?P<year>19\d{{2}}|20\d{{2}})\))?\s*$",

        # OCR 丢逗号：B 109 115427 (2024)
        rf"^(?P<journal>{aps_journal_pattern})\s+\d+\s+[\dA-Za-z\-]+(?:\s*\((?P<year>19\d{{2}}|20\d{{2}})\))?\s*$",
    ]

    for p in patterns:
        m = re.search(p, s, flags=re.IGNORECASE)
        if m:
            journal = safe_text(m.group("journal"))
            year = m.groupdict().get("year")
            return (int(year) if year else None), journal

    return None, None

def _post_clean_journal_name(text: str) -> str:
    """
    对已提取 journal 再做一次后处理，修掉少数规则漏掉的尾巴。
    """
    s = safe_text(text or "")
    if not s:
        return s

    aps_journal_pattern = (
        r"PHYSICAL\s+REVIEW(?:"
        r"\s+LETTERS"
        r"|\s+MATERIALS"
        r"|\s+APPLIED"
        r"|\s+[A-Z]"
        r")"
    )

    # APS: PHYSICAL REVIEW B 109, 115427 -> PHYSICAL REVIEW B
    s = re.sub(
        rf"^({aps_journal_pattern})\s+\d+\s*,\s*[\dA-Za-z\-]+$",
        r"\1",
        s,
        flags=re.IGNORECASE,
    )

    # APS OCR 紧贴: PHYSICAL REVIEW B109,115427 -> PHYSICAL REVIEW B
    s = re.sub(
        rf"^({aps_journal_pattern})\s*\d+\s*,\s*[\dA-Za-z\-]+$",
        r"\1",
        s,
        flags=re.IGNORECASE,
    )

    # APS OCR 丢逗号: PHYSICAL REVIEW B 109 115427 -> PHYSICAL REVIEW B
    s = re.sub(
        rf"^({aps_journal_pattern})\s+\d+\s+[\dA-Za-z\-]+$",
        r"\1",
        s,
        flags=re.IGNORECASE,
    )

    return safe_text(s)


def _parse_footer_or_header_journal_line(text: str) -> tuple[int | None, str | None]:
    s = safe_text(text or "")
    if not s:
        return None, None
    # case 0: 先用 EndNote 期刊词典做整行最长匹配
    y, j = _match_journal_from_text_by_dictionary(s)
    if _is_valid_journal_candidate(j):
        return y, j

    # case 1: Cite This: J. Am. Chem. Soc. 2018, 140, 17895-17900
    m = re.search(
        r"^\s*Cite\s+This\s*:?\s*(?P<journal>.+?)\s+(?P<year>19\d{2}|20\d{2})\b",
        s,
        flags=re.IGNORECASE,
    )
    if m:
        j = _post_clean_journal_name(_clean_extracted_journal(m.group("journal")))
        if _is_valid_journal_candidate(j):
            return int(m.group("year")), j

    # case 2: npj Computational Materials | (2024) 10:229
    m = re.search(
        r"^(?P<journal>[^|]+?)\s*\|\s*\((?P<year>19\d{2}|20\d{2})\)",
        s,
        flags=re.IGNORECASE,
    )
    if m:
        j = _post_clean_journal_name(_clean_extracted_journal(m.group("journal")))
        if _is_valid_journal_candidate(j):
            return int(m.group("year")), j

    # case 3: Nature Reviews Physics | Volume 7 | February 2025 | 73–90
    m = re.search(
        r"^(?P<journal>[^|]+?)\s*\|\s*Volume\b.*?\b(?P<year>19\d{2}|20\d{2})\b",
        s,
        flags=re.IGNORECASE,
    )
    if m:
        j = _post_clean_journal_name(_clean_extracted_journal(m.group("journal")))
        if _is_valid_journal_candidate(j):
            return int(m.group("year")), j

    # case 4: APS header
    y, j = _parse_aps_journal_line(s)
    j = _post_clean_journal_name(j)
    if _is_valid_journal_candidate(j):
        return y, j

    # case 5/6
    # Adv. Funct. Mater. 2025, 2423252
    # ACS Nano 2024, 18, 8511-8516
    m = re.search(
        r"^(?P<journal>.+?)\s+(?P<year>19\d{2}|20\d{2})\s*,\s*[\dA-Za-z\-–:]+(?:\s*,\s*[\dA-Za-z\-–:]+)*\s*$",
        s,
        flags=re.IGNORECASE,
    )
    if m:
        j = _post_clean_journal_name(_clean_extracted_journal(m.group("journal")))
        if _is_valid_journal_candidate(j):
            return int(m.group("year")), j

    # 最后兜底
    journal = _post_clean_journal_name(_extract_journal_candidate_from_header_footer_text(s))
    year = _extract_year_from_header_footer_text(s)
    if _is_valid_journal_candidate(journal):
        return year, journal

    return None, None

def canonicalize_journal_with_dictionary(journal: str) -> str:
    j = safe_text(journal or "")
    if not j:
        return j

    _, normalized_lookup, _ = get_endnote_journal_lookup()

    nk = normalize_journal_key(j)
    hit = normalized_lookup.get(nk)
    if hit:
        full_name, _abbr = hit
        return full_name

    return j

def _is_title_like_header_text(text: str) -> bool:
    """
    判断一个 header/footer 原文是否更像“论文标题页眉”，而不是期刊名。
    重点打击：
    - FIRST-PRINCIPLES METHOD FOR ELECTRON-PHONON . . .
    - 全大写长标题
    - 含连字符学术标题词
    - 有省略号截断
    """
    s = safe_text(text or "")
    if not s:
        return False

    # 有年份 / 卷页结构的，一般更像期刊行，不按标题处理
    if re.search(r"\((19\d{2}|20\d{2})\)", s):
        return False
    if re.search(r"\b\d{1,4}\s*,\s*[\dA-Za-z\-]+\b", s):
        return False

    words = re.findall(r"[A-Za-z][A-Za-z\-]+", s)
    if len(words) < 4:
        return False

    # 典型标题信号
    has_ellipsis = ". . ." in s or "..." in s
    has_hyphen_word = bool(re.search(r"\b[A-Za-z]+-[A-Za-z]+\b", s))
    is_all_upperish = (s.upper() == s)

    title_keywords = {
        "method", "methods", "first-principles", "electron-phonon",
        "calculation", "calculations", "study", "analysis", "approach",
        "transport", "structure", "properties", "simulation", "model",
    }
    lower_s = s.lower()
    keyword_hits = sum(1 for kw in title_keywords if kw in lower_s)

    # 满足这些条件之一，就很像标题页眉
    if has_ellipsis and len(words) >= 5:
        return True
    if has_hyphen_word and keyword_hits >= 1 and len(words) >= 5:
        return True
    if is_all_upperish and keyword_hits >= 2 and len(words) >= 6:
        return True

    return False


def _is_author_like_header_text(text: str) -> bool:
    """
    判断是否像作者姓氏页眉：
    - GUNST, MARKUSSEN, STOKBRO, AND BRANDBYGE
    """
    s = safe_text(text or "")
    if not s:
        return False

    # 没数字、多个逗号、含 AND，且整体大写，很像作者列表
    if re.search(r"\d", s):
        return False

    upper_tokens = re.findall(r"\b[A-Z][A-Z\-]+\b", s)
    if len(upper_tokens) >= 3 and s.count(",") >= 1 and re.search(r"\bAND\b", s):
        return True

    return False

def _score_journal_candidate(
    journal: str | None,
    raw_text: str = "",
    block_type: str = "",
    parsed_year: int | None = None,
) -> int:
    """
    给提取到的期刊候选打分，分数越高越可信。
    用于从多个 page_header/page_footer 候选中选最优者。
    """
    j = safe_text(journal or "")
    raw = safe_text(raw_text or "")

    if not j:
        return -10

    score = 0

    # 太短的一般是垃圾碎片：J / npj / #
    if len(j) == 1:
        score -= 100
    elif len(j) <= 3:
        score -= 40
    elif len(j) <= 6:
        score -= 10
    else:
        score += min(len(j), 30)

    # 单个词通常不靠谱，多个词更像期刊名
    word_count = len(j.split())
    if word_count >= 2:
        score += 20
    elif word_count == 1:
        score -= 10

    # 含有典型期刊缩写特征，略加分
    if "." in j:
        score += 10

    # 原文里如果有这些结构，可信度更高
    if re.search(r"^\s*Cite\s+This\s*:?", raw, flags=re.IGNORECASE):
        score += 40

    if "|" in raw:
        score += 20

    if re.search(r"\((19\d{2}|20\d{2})\)", raw):
        score += 20
    elif re.search(r"\b(19\d{2}|20\d{2})\b", raw):
        score += 10

    if re.search(r"\bVolume\b", raw, flags=re.IGNORECASE):
        score += 10

    # APS 标准期刊头强力加分：
    # PHYSICAL REVIEW B 93, 035414 (2016)
    if re.search(
        r"\bPHYSICAL\s+REVIEW(?:\s+LETTERS|\s+MATERIALS|\s+APPLIED|\s+[A-Z])\s+\d+\s*,\s*[\dA-Za-z\-]+\s*\((19\d{2}|20\d{2})\)",
        raw,
        flags=re.IGNORECASE,
    ):
        score += 35

    # 解析出年份，也说明更像正规期刊行
    if parsed_year is not None:
        score += 8

    # page_footer 一般可信度略低；page_header 中既可能是期刊，也可能是标题/作者页眉
    if block_type == "page_footer":
        score -= 5
    elif block_type == "page_header":
        score += 2

    # 明显不像期刊名的内容降分
    if re.match(r"^(Published|Received)\s*:", j, flags=re.IGNORECASE):
        score -= 100

    if re.fullmatch(r"[\W_#]+", j):
        score -= 100

    # DOI / URL / 域名通常不是期刊名
    if re.search(r"\bdoi\b", raw, flags=re.IGNORECASE):
        score -= 40
    if re.search(r"https?://", raw, flags=re.IGNORECASE):
        score -= 40
    if re.search(r"\bwww\.", raw, flags=re.IGNORECASE):
        score -= 25
    if re.search(r"\bdoi\.org\b", raw, flags=re.IGNORECASE):
        score -= 40

    if re.search(r"\b\d+\s*\(\d+\s+of\s+\d+\)", raw, flags=re.IGNORECASE):
        score -= 35
    if re.search(r"\bpage\s+\d+\s+of\s+\d+\b", raw, flags=re.IGNORECASE):
        score -= 35

    letters_only = re.sub(r"[^A-Za-z]+", "", j)
    if letters_only and j.upper() == j and len(j.split()) >= 2:
        score -= 5

    if re.search(
        r"©|\bcopyright\b|american physical society|wiley-vch|american chemical society",
        raw,
        flags=re.IGNORECASE,
    ):
        score -= 50

    # ===== 关键新增：标题页眉强惩罚 =====
    if block_type == "page_header" and _is_title_like_header_text(raw):
        score -= 45

    # ===== 关键新增：作者页眉强惩罚 =====
    if block_type == "page_header" and _is_author_like_header_text(raw):
        score -= 35

    return score


def extract_year_and_journal_from_content_list(content_list_json_path: str) -> tuple[int | None, str | None]:
    """
    从 content_list_v2.json 提取 year 和 journal。

    优先级策略：
    - journal:
      在所有 page_footer/page_header 候选中选“最可信”的一个；
      若没有，再退到 Cite This
    - year:
      Published > Received > 与 journal 同行 > 全文兜底
    """
    entries = load_content_list_entries(content_list_json_path)
    if not entries:
        return None, None

    published_year = None
    received_year = None
    cite_match: tuple[int | None, str | None] | None = None
    fallback_year = None

    footer_header_candidates: list[tuple[int, int | None, str, str, str]] = []
    # (score, year, journal, raw_text, block_type)

    for item in entries:
        block_type = item.get("block_type", "")
        text = safe_text(item.get("text", ""))

        if not text:
            continue

        # year 优先来源 1: Published
        if re.search(r"^\s*Published\s*:", text, flags=re.IGNORECASE):
            py = _parse_published_or_received_year(text)
            if py is not None and published_year is None:
                published_year = py

        # year 优先来源 2: Received
        if re.search(r"^\s*Received\s*:", text, flags=re.IGNORECASE):
            ry = _parse_published_or_received_year(text)
            if ry is not None and received_year is None:
                received_year = ry

        # 收集所有 page_footer / page_header 候选，不要首次命中就停
        if block_type in {"page_footer", "page_header"}:
            y, j = _parse_footer_or_header_journal_line(text)
            score = _score_journal_candidate(
                j,
                raw_text=text,
                block_type=block_type,
                parsed_year=y,
            )
            print(
                f"[debug][candidate] block_type={block_type}, text={text!r}, parsed_year={y}, parsed_journal={j!r}, score={score}",
                flush=True,
            )
            if j:
                footer_header_candidates.append((score, y, j, text, block_type))


        # journal 备选来源 2: Cite This
        if cite_match is None:
            y, j = _parse_cite_this_line(text)
            if j:
                cite_match = (y, j)

        # fallback year
        if fallback_year is None:
            ys = _extract_year_candidates_from_text(text)
            if ys:
                fallback_year = ys[0]

    footer_header_match: tuple[int | None, str | None] | None = None
    if footer_header_candidates:
        footer_header_candidates.sort(key=lambda x: x[0], reverse=True)
        best = footer_header_candidates[0]
        _, y, j, raw_text, block_type = best
        footer_header_match = (y, j)
        print(
            f"[debug][candidate-best] block_type={block_type}, text={raw_text!r}, year={y}, journal={j!r}",
            flush=True,
        )

    final_journal = None
    year_from_journal_line = None

    if footer_header_match and footer_header_match[1]:
        year_from_journal_line, final_journal = footer_header_match
    elif cite_match and cite_match[1]:
        year_from_journal_line, final_journal = cite_match

    final_year = (
        published_year
        if published_year is not None
        else received_year
        if received_year is not None
        else year_from_journal_line
        if year_from_journal_line is not None
        else fallback_year
    )
    final_journal = canonicalize_journal_with_dictionary(final_journal)
    return final_year, final_journal


def extract_image_refs_from_md(md_text: str) -> set[str]:
    """
    从 markdown 中提取所有 images/xxx.png|jpg|jpeg|gif|webp|svg 引用的文件名。
    兼容：
    ![](images/a.jpg)
    ![](./images/a.jpg)
    <img src="images/a.jpg">
    """
    refs: set[str] = set()

    # markdown image/link
    patterns = [
        r'!\[[^\]]*\]\((?:\./)?images/([^)\/\s]+)\)',
        r'<img[^>]+src=["\'](?:\./)?images/([^"\'>\/\s]+)["\']',
    ]

    for p in patterns:
        for m in re.findall(p, md_text or "", flags=re.IGNORECASE):
            refs.add(os.path.basename(m.strip()))

    return refs


def prune_images_by_full_md(images_dir: str, full_md_path: str) -> dict[str, int]:
    """
    只保留 full.md 中实际引用到的 images 文件。
    返回统计：
    {
        "kept": x,
        "removed": y
    }
    """
    if not os.path.isdir(images_dir):
        return {"kept": 0, "removed": 0}

    if not os.path.isfile(full_md_path):
        return {"kept": 0, "removed": 0}

    md_text = read_text(full_md_path)
    keep_files = extract_image_refs_from_md(md_text)

    kept = 0
    removed = 0

    for name in os.listdir(images_dir):
        fp = os.path.join(images_dir, name)
        if not os.path.isfile(fp):
            continue

        if name in keep_files:
            kept += 1
        else:
            os.remove(fp)
            removed += 1

    return {"kept": kept, "removed": removed}


def safe_text(text: str) -> str:
    return normalize_whitespace(text).strip()


def file_sha1(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ascii_slug(text: str) -> str:
    text = safe_text(text)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "", text)
    return text


def mixed_slug(text: str) -> str:
    text = safe_text(text)
    text = re.sub(r"[\\/:*?\"<>|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace(" ", "_")
    return text

def safe_dirname(name: str) -> str:
    """
    目录名清洗：
    - 去掉文件系统非法字符
    - 去掉所有空格
    """
    name = safe_text(name or "")
    name = re.sub(r'[\\/:*?"<>|]+', "", name)
    name = re.sub(r"\s+", "", name)
    return name or "UnknownJournal"


def normalize_year_for_dir(year: Any) -> str:
    try:
        year_int = int(year)
        if 1900 <= year_int <= 2100:
            return str(year_int)
    except Exception:
        pass
    return "unknown"


def build_library_dirname(year: Any, journal_slug_value: str | None, paper_id: str) -> str:
    year_part = normalize_year_for_dir(year)
    journal_part = safe_dirname(journal_slug_value or "UnknownJournal") or "UnknownJournal"
    paper_part = safe_dirname(paper_id or "unknown") or "unknown"
    return f"{year_part}-{journal_part}-{paper_part}"

def is_library_bundle_complete(paper_dir: str) -> bool:
    """
    判断一个文献目录是否基本完整。
    至少应包含：
    - metadata.json
    - source.pdf
    - full.md
    - mineru 目录
    """
    if not paper_dir or not os.path.isdir(paper_dir):
        return False

    metadata_path = os.path.join(paper_dir, "metadata.json")
    source_pdf = os.path.join(paper_dir, "source.pdf")
    full_md = os.path.join(paper_dir, "full.md")
    mineru_dir = os.path.join(paper_dir, "mineru")

    return (
        os.path.isfile(metadata_path)
        and os.path.isfile(source_pdf)
        and os.path.isfile(full_md)
        and os.path.isdir(mineru_dir)
    )


def merge_directories(src_dir: str, dst_dir: str) -> None:
    """
    把 src_dir 内容合并到 dst_dir。
    规则：
    - dst 不存在则创建
    - 文件若 dst 不存在则移动
    - 子目录递归合并
    - 同名文件若 dst 已存在，则保留 dst，不覆盖
    """
    if not src_dir or not os.path.isdir(src_dir):
        return

    ensure_dir(dst_dir)

    for name in os.listdir(src_dir):
        src_path = os.path.join(src_dir, name)
        dst_path = os.path.join(dst_dir, name)

        if os.path.isdir(src_path):
            if not os.path.exists(dst_path):
                shutil.move(src_path, dst_path)
            else:
                merge_directories(src_path, dst_path)
                try:
                    os.rmdir(src_path)
                except OSError:
                    pass
        else:
            if not os.path.exists(dst_path):
                shutil.move(src_path, dst_path)
            else:
                # 不覆盖已有目标文件
                pass

    try:
        os.rmdir(src_dir)
    except OSError:
        pass


def cleanup_empty_or_metadata_only_dir(paper_dir: str) -> bool:
    """
    清理空目录，或仅包含 metadata.json 的残留目录。
    返回是否已删除。
    """
    if not paper_dir or not os.path.isdir(paper_dir):
        return False

    entries = [x for x in os.listdir(paper_dir) if x not in {".DS_Store"}]
    if not entries:
        os.rmdir(paper_dir)
        return True

    if entries == ["metadata.json"]:
        os.remove(os.path.join(paper_dir, "metadata.json"))
        os.rmdir(paper_dir)
        return True

    return False


def move_paper_bundle_to_journal_dir(
    pdf_path: str,
    md_path: str,
    journal: str,
    assets_dir: str | None = None,
) -> tuple[str, str, str | None]:
    """
    把论文的 pdf/md/assets 移动到以 journal 命名的目录下。

    例如：
    /root/papers/2025-ACSNano-xxx.pdf
    -> /root/papers/ACS Nano/2025-ACSNano-xxx.pdf

    返回：
    (new_pdf_path, new_md_path, new_assets_dir)
    """
    pdf_path = os.path.abspath(pdf_path)
    md_path = os.path.abspath(md_path)

    base_dir = os.path.dirname(pdf_path)
    journal_dirname = journal_slug(journal)
    journal_dir = os.path.join(base_dir, journal_dirname)
    ensure_dir(journal_dir)

    new_pdf = os.path.join(journal_dir, os.path.basename(pdf_path))
    new_md = os.path.join(journal_dir, os.path.basename(md_path))

    new_assets_dir = None
    if assets_dir:
        assets_dir = os.path.abspath(assets_dir)
        new_assets_dir = os.path.join(journal_dir, os.path.basename(assets_dir))

    if not samefile_safe(pdf_path, new_pdf):
        shutil.move(pdf_path, new_pdf)

    if os.path.exists(md_path) and not samefile_safe(md_path, new_md):
        shutil.move(md_path, new_md)

    if assets_dir and os.path.exists(assets_dir):
        if new_assets_dir and not samefile_safe(assets_dir, new_assets_dir):
            if os.path.exists(new_assets_dir):
                shutil.rmtree(new_assets_dir)
            shutil.move(assets_dir, new_assets_dir)

    return new_pdf, new_md, new_assets_dir

def shorten_slug(text: str, max_len: int) -> str:
    text = text[:max_len].strip(" _-")
    return text or "Untitled"

def normalize_journal_key(journal: str) -> str:
    """
    用于期刊名匹配的归一化 key：
    - 小写
    - 去掉空格
    - 去掉常见标点
    - 去掉 Cite This 前缀
    """
    s = safe_text(journal or "")
    s = re.sub(r"^\s*Cite\s+This\s*:?\s*", "", s, flags=re.IGNORECASE)
    s = s.lower()
    s = re.sub(r"[.\-,:;()&|/=]+", "", s)
    s = re.sub(r"\s+", "", s)
    return s

def _match_journal_from_text_by_dictionary(text: str) -> tuple[int | None, str | None]:
    """
    直接拿 header/footer 整行文本去和 EndNote 期刊词典做最长匹配。
    例如：
    - PHYSICAL REVIEW APPLIED 21, 054017 (2024)
      -> PHYSICAL REVIEW APPLIED
    - ACS Nano 2024, 18, 8511-8516
      -> ACS Nano
    """
    s = safe_text(text or "")
    if not s:
        return None, None

    year = _extract_year_from_header_footer_text(s)

    # 先做基础清洗，但保留足够多原始信息
    candidate_texts = [
        s,
        _clean_extracted_journal(s),
        _post_clean_journal_name(s),
        _post_clean_journal_name(_clean_extracted_journal(s)),
    ]

    _, _, sorted_keys = get_endnote_journal_lookup()

    seen = set()
    for candidate in candidate_texts:
        nk_text = normalize_journal_key(candidate)
        if not nk_text or nk_text in seen:
            continue
        seen.add(nk_text)

        for nk_journal, full_name, abbr in sorted_keys:
            if nk_journal and nk_journal in nk_text:
                return year, full_name

    return None, None


def journal_slug(journal: str) -> str:
    journal = safe_text(journal)

    # 容错：去掉可能残留的 Cite This 前缀
    journal = re.sub(r"^\s*Cite\s+This\s*:?\s*", "", journal, flags=re.IGNORECASE)

    if not journal:
        return "UnknownJournal"

    if journal in JOURNAL_SLUG_MAP:
        return JOURNAL_SLUG_MAP[journal]

    normalized_input = normalize_journal_key(journal)
    for k, v in JOURNAL_SLUG_MAP.items():
        if normalize_journal_key(k) == normalized_input:
            return v

    s = remove_spaces(journal)
    s = re.sub(r"[\\/:*?\"<>|]+", "", s)
    return s[:40] if s else "UnknownJournal"



def title_slug(title: str, max_len: int = 36) -> str:
    title = safe_text(title)
    s = ascii_slug(title)
    if not s:
        s = mixed_slug(title)
    return shorten_slug(s, max_len)


def infer_topic_and_journal_from_pdf_path(pdf_path: str) -> Tuple[str, str]:
    path = Path(pdf_path)
    parts = path.parts

    # 期望结构：.../papers/raw/<topic>/<journal>/<file>.pdf
    topic = ""
    journal = ""
    try:
        raw_idx = parts.index("raw")
        if len(parts) > raw_idx + 2:
            topic = parts[raw_idx + 1]
        if len(parts) > raw_idx + 3:
            journal = parts[raw_idx + 2]
    except ValueError:
        pass

    return topic, journal


def build_paper_id(topic: str, journal: str, year, title: str) -> str:
    base = f"{topic}|{journal}|{year}|{title}"
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]
    return digest


def build_front_matter(
    title: str,
    topic: str,
    journal: str,
    source_pdf: str,
    year=None,
    doi=None,
    authors=None,
    url=None,
    keywords=None,
    summary="",
    paper_id=None,
):
    return {
        "paper_id": paper_id or build_paper_id(topic, journal, year, title),
        "title": safe_text(title),
        "journal": safe_text(journal) or "Unknown",
        "year": year,
        "topic": topic or "unknown",
        "topic_label": TOPIC_LABELS.get(topic, topic),
        "doi": doi,
        "authors": authors or [],
        "url": url,
        "keywords": keywords or [],
        "summary": summary or "",
        "source_pdf": source_pdf,
    }


def front_matter_to_text(meta: Dict[str, Any]) -> str:
    return "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n\n"


def parse_front_matter(md_text: str) -> Tuple[Dict[str, Any], str]:
    if not md_text.startswith("---"):
        return {}, md_text

    parts = md_text.split("---", 2)
    if len(parts) < 3:
        return {}, md_text

    raw_yaml = parts[1]
    body = parts[2].lstrip("\n")

    try:
        meta = yaml.safe_load(raw_yaml) or {}
    except Exception:
        meta = {}

    return meta, body


def read_text(path: str) -> str:
    resolved = resolve_papers_path(path) or path
    with open(resolved, "r", encoding="utf-8") as f:
        return f.read()

def write_text(path: str, text: str):
    resolved = resolve_papers_path(path) or path
    ensure_dir(os.path.dirname(resolved))
    with open(resolved, "w", encoding="utf-8") as f:
        f.write(text)

def _is_bad_title_candidate(text: str) -> bool:
    t = safe_text(text or "")
    if not t:
        return True

    # 太短一般不是论文标题
    if len(t) < 8:
        return True

    # URL / DOI / 域名
    if re.search(r"https?://", t, flags=re.IGNORECASE):
        return True
    if re.search(r"\bwww\.", t, flags=re.IGNORECASE):
        return True
    if re.search(r"\bdoi\b", t, flags=re.IGNORECASE):
        return True
    if re.search(r"\bdoi\.org\b", t, flags=re.IGNORECASE):
        return True

    # Cite This 不是标题
    if re.match(r"^\s*Cite\s+This\s*:?", t, flags=re.IGNORECASE):
        return True

    normalized = re.sub(r"[\s\-_–—:]+", " ", t).strip().lower()

    # 常见非标题噪音 / 栏目标签
    bad_phrases = {
        "read online",
        "access",
        "article",
        "article open",
        "open",
        "review",
        "technical review",
        "review article",
        "research article",
        "check for updates",
        "letter",
        "perspective",
        "news and views",
        "news & views",
        "comment",
        "brief communication",
        "editorial",
    }
    if normalized in bad_phrases:
        return True

    # 像 "? Check for updates" 这种前缀噪音
    if re.search(r"check\s+for\s+updates", normalized, flags=re.IGNORECASE):
        return True

    # 全大写短标签往往是栏目，而不是标题
    letters_only = re.sub(r"[^A-Za-z]+", "", t)
    if letters_only and t.upper() == t and len(t.split()) <= 4 and len(letters_only) <= 24:
        upper_bad_tokens = {
            "ARTICLEOPEN",
            "OPEN",
            "ARTICLE",
            "REVIEW",
            "LETTER",
            "PERSPECTIVE",
            "EDITORIAL",
            "COMMENT",
            "ACCESS",
        }
        if letters_only in upper_bad_tokens:
            return True

    return False



def extract_title_from_md(md_text: str, fallback: str) -> str:
    """
    标题提取优先级：
    1. 第一个 Markdown 一级标题 '# '
    2. 前 40 行中最像标题的普通文本行
    3. fallback
    """
    lines = [x.rstrip() for x in (md_text or "").splitlines()]
    nonempty_lines = [x.strip() for x in lines if x.strip()]

    if not nonempty_lines:
        return fallback

    # 1) 优先找第一个一级标题：# Title
    for line in nonempty_lines[:80]:
        if re.match(r"^#\s+.+", line):
            t = re.sub(r"^#\s+", "", line).strip()
            if not _is_bad_title_candidate(t):
                return t[:300]

    # 2) 再找前 40 行里最像标题的普通文本
    for line in nonempty_lines[:40]:
        t = line.strip()
        if t.startswith("#"):
            t = re.sub(r"^#+\s*", "", t).strip()

        if _is_bad_title_candidate(t):
            continue

        return t[:300]

    return fallback

def extract_year_from_text(md_text: str):
    # 简单 heuristic：优先找 19xx / 20xx
    years = re.findall(r"\b(19\d{2}|20\d{2})\b", md_text or "")
    if not years:
        return None

    years = [int(y) for y in years if 1900 <= int(y) <= 2100]
    if not years:
        return None

    # 取最靠前几年里较合理的一个
    return years[0]


def build_standard_stem(year, journal: str, title: str) -> str:
    year_part = str(year) if year else "unknown"
    journal_part = journal_slug(journal)
    title_part = title_slug(title, max_len=36)

    stem = f"{year_part}-{journal_part}-{title_part}"
    if len(stem) > MAX_FILENAME_LEN:
        over = len(stem) - MAX_FILENAME_LEN
        title_part = shorten_slug(title_part, max(12, len(title_part) - over))
        stem = f"{year_part}-{journal_part}-{title_part}"

    return stem


def samefile_safe(a: str, b: str) -> bool:
    try:
        return os.path.abspath(a) == os.path.abspath(b)
    except Exception:
        return False


def rename_pair(old_pdf: str, old_md: str, new_stem: str):
    pdf_dir = os.path.dirname(old_pdf)
    new_pdf = os.path.join(pdf_dir, new_stem + ".pdf")
    new_md = os.path.join(pdf_dir, new_stem + ".md")

    if not samefile_safe(old_pdf, new_pdf):
        os.rename(old_pdf, new_pdf)

    if os.path.exists(old_md) and not samefile_safe(old_md, new_md):
        os.rename(old_md, new_md)

    return new_pdf, new_md


def collect_md_index_item(md_path: str) -> Dict[str, Any]:
    text = read_text(md_path)
    meta, body = parse_front_matter(text)

    return {
        "paper_id": meta.get("paper_id"),
        "title": meta.get("title"),
        "journal": meta.get("journal"),
        "year": meta.get("year"),
        "topic": meta.get("topic"),
        "topic_label": meta.get("topic_label"),
        "doi": meta.get("doi"),
        "authors": meta.get("authors") or [],
        "url": meta.get("url"),
        "keywords": meta.get("keywords") or [],
        "summary": meta.get("summary") or "",
        "source_pdf": meta.get("source_pdf"),
        "md_path": md_path,
        "content_length": len(body or ""),
    }


def save_index(items):
    dump_json(INDEX_PATH, items)


def load_yaml(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or default
    except Exception:
        return default


def dump_yaml(path: str, data):
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def load_journal_features(path: str = PAPERS_JOURNAL_FEATURES_PATH) -> dict[str, Any]:
    global _JOURNAL_FEATURES_CACHE
    if _JOURNAL_FEATURES_CACHE is None:
        ensure_papers_index_scaffold()
        runtime_data = load_yaml(path, default={})
        _JOURNAL_FEATURES_CACHE = runtime_data or load_yaml(PAPERS_JOURNAL_FEATURES_TEMPLATE_PATH, default={})
    return _JOURNAL_FEATURES_CACHE


def load_taxonomy_config(path: str = PAPERS_TAXONOMY_PATH) -> dict[str, Any]:
    global _TAXONOMY_CACHE
    if _TAXONOMY_CACHE is None:
        ensure_papers_index_scaffold()
        runtime_data = load_json(path, default={"version": 1, "roots": []})
        if runtime_data == {"version": 1, "roots": []}:
            runtime_data = load_json(PAPERS_TAXONOMY_TEMPLATE_PATH, default={"version": 1, "roots": []})
        _TAXONOMY_CACHE = runtime_data
    return _TAXONOMY_CACHE


def normalize_feature_match_text(text: str, normalize_cfg: dict[str, Any] | None = None) -> str:
    cfg = normalize_cfg or {}
    value = str(text or "")
    if cfg.get("unicode_nfkc", True):
        value = unicodedata.normalize("NFKC", value)
    if cfg.get("ignore_case", True):
        value = value.lower()
    if cfg.get("ignore_punctuation", True):
        value = re.sub(r"[\W_]+", "", value, flags=re.UNICODE)
    if cfg.get("ignore_whitespace", True):
        value = re.sub(r"\s+", "", value, flags=re.UNICODE)
    return value


def _extract_text_fragments(node: Any) -> list[str]:
    fragments: list[str] = []
    if isinstance(node, dict):
        node_type = node.get("type")
        if node_type == "text" and isinstance(node.get("content"), str):
            text = safe_text(node.get("content", ""))
            if text:
                fragments.append(text)
        for value in node.values():
            fragments.extend(_extract_text_fragments(value))
    elif isinstance(node, list):
        for item in node:
            fragments.extend(_extract_text_fragments(item))
    return fragments


def extract_header_footer_texts_from_content_list(
    content_list_json_path: str,
    journal_features: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    data = load_json(content_list_json_path, default=None)
    if data is None:
        return []

    features = journal_features or load_journal_features()
    scope = (features.get("match_scope") or {})
    enabled_types = set(scope.get("enabled_block_types") or ["page_header", "page_footer"])
    max_scan = int(scope.get("max_scan_blocks_per_type") or 20)
    counts = {block_type: 0 for block_type in enabled_types}
    results: list[dict[str, str]] = []

    def walk(node: Any):
        if isinstance(node, dict):
            block_type = node.get("type")
            if block_type in enabled_types and counts.get(block_type, 0) < max_scan:
                texts = _extract_text_fragments(node.get("content"))
                for text in texts:
                    results.append({
                        "block_type": block_type,
                        "text": text,
                    })
                counts[block_type] = counts.get(block_type, 0) + 1

            for value in node.values():
                walk(value)

        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return results


def match_journal_from_content_list(content_list_json_path: str) -> dict[str, Any]:
    journal_features = load_journal_features()
    normalize_cfg = journal_features.get("normalize") or {}
    strategy_cfg = journal_features.get("match_strategy") or {}
    use_priority_first = bool(strategy_cfg.get("use_priority_first", True))
    use_longest_match = bool(strategy_cfg.get("use_longest_match_as_tiebreaker", True))
    allow_substring_match = bool(strategy_cfg.get("allow_substring_match", True))

    entries = extract_header_footer_texts_from_content_list(
        content_list_json_path,
        journal_features=journal_features,
    )

    best_match: dict[str, Any] | None = None
    for entry in entries:
        normalized_text = normalize_feature_match_text(entry.get("text", ""), normalize_cfg)
        if not normalized_text:
            continue

        for journal in journal_features.get("journals") or []:
            patterns = journal.get("match_any") or journal.get("aliases") or []
            priority = int(journal.get("priority") or 0)

            for raw_pattern in patterns:
                normalized_pattern = normalize_feature_match_text(raw_pattern, normalize_cfg)
                if not normalized_pattern:
                    continue

                matched = (
                    normalized_pattern in normalized_text
                    if allow_substring_match
                    else normalized_pattern == normalized_text
                )
                if not matched:
                    continue

                candidate = {
                    "journal": journal.get("canonical_name") or "UnknownJournal",
                    "journal_slug": journal.get("slug") or "UnknownJournal",
                    "publisher": journal.get("publisher"),
                    "priority": priority,
                    "matched_pattern": raw_pattern,
                    "matched_text": entry.get("text", ""),
                    "block_type": entry.get("block_type", ""),
                    "match_length": len(normalized_pattern),
                    "strategy": "journal_features",
                }

                if best_match is None:
                    best_match = candidate
                    continue

                if use_priority_first:
                    candidate_key = (candidate["priority"], candidate["match_length"] if use_longest_match else 0)
                    best_key = (best_match["priority"], best_match["match_length"] if use_longest_match else 0)
                else:
                    candidate_key = (candidate["match_length"], candidate["priority"])
                    best_key = (best_match["match_length"], best_match["priority"])

                if candidate_key > best_key:
                    best_match = candidate

    if best_match:
        return best_match

    extracted_year, extracted_journal = extract_year_and_journal_from_content_list(content_list_json_path)
    fallback_journal = safe_text(extracted_journal or "") or "UnknownJournal"
    return {
        "journal": fallback_journal,
        "journal_slug": journal_slug(fallback_journal),
        "publisher": None,
        "priority": -1,
        "matched_pattern": None,
        "matched_text": None,
        "block_type": None,
        "match_length": 0,
        "strategy": "fallback_dictionary" if extracted_journal else "unknown",
        "year": extracted_year,
    }


def extract_abstract_from_markdown(md_text: str) -> str:
    _meta, body = parse_front_matter(md_text)
    text = body or md_text or ""

    abstract_heading = re.search(r"(?im)^(#{0,6}\s*)?abstract\s*$", text)
    if abstract_heading:
        start = abstract_heading.end()
        remaining = text[start:].lstrip()
        lines = remaining.splitlines()
        abstract_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if abstract_lines:
                    abstract_lines.append("")
                continue
            if re.match(r"^#{1,6}\s+", stripped):
                break
            if re.match(r"^(keywords?|introduction|background|results?|discussion|references)\s*:?\s*$", stripped, flags=re.I):
                break
            abstract_lines.append(stripped)
            if len(" ".join(abstract_lines)) >= 2400:
                break

        abstract = normalize_whitespace("\n".join(abstract_lines))
        if abstract:
            return abstract

    paragraphs = [
        normalize_whitespace(p)
        for p in re.split(r"\n\s*\n", text)
        if normalize_whitespace(p)
    ]
    for para in paragraphs:
        if len(para) < 120:
            continue
        if re.match(r"^(keywords?|introduction|background|results?|discussion|references)\b", para, flags=re.I):
            continue
        return para[:2400]

    return ""

def split_markdown_paragraphs(md_text: str) -> list[str]:
    """
    将 markdown 正文切成段落。
    - 自动去掉 front matter
    - 过滤过短/纯标题/纯图片引用段
    """
    _meta, body = parse_front_matter(md_text)
    text = body or md_text or ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    raw_paragraphs = re.split(r"\n\s*\n+", text)
    paragraphs: list[str] = []

    for p in raw_paragraphs:
        para = normalize_whitespace(p)
        if not para:
            continue

        # 跳过纯 markdown 标题
        if re.match(r"^#{1,6}\s+", para):
            continue

        # 跳过图片/表格链接占位
        if re.match(r"^!\[.*\]\(.*\)$", para):
            continue

        # 跳过过短碎片
        if len(para) < 20:
            continue

        paragraphs.append(para)

    return paragraphs

def extract_abstract_from_markdown_first_n_paragraphs(md_text: str, max_paragraphs: int = 20, max_chars: int = 12000) -> str:
    """
    直接取 full.md 的前 N 个有效段落作为 abstract/classification 输入。
    这是一个“长摘要/内容前览”，不是严格学术 abstract。
    """
    paragraphs = split_markdown_paragraphs(md_text)
    if not paragraphs:
        return ""

    selected: list[str] = []
    total_chars = 0

    for para in paragraphs[:max_paragraphs]:
        if not para:
            continue
        if total_chars + len(para) > max_chars:
            remain = max_chars - total_chars
            if remain > 200:
                selected.append(para[:remain])
            break
        selected.append(para)
        total_chars += len(para)

    return "\n\n".join(selected).strip()


def extract_doi_from_text(text: str) -> str | None:
    value = text or ""
    match = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b", value, flags=re.I)
    if not match:
        return None
    return safe_text(match.group(0).rstrip(".,;:"))


def iter_taxonomy_paths(nodes: Iterable[dict[str, Any]], prefix: list[str] | None = None):
    prefix = prefix or []
    for node in nodes:
        label = safe_text(node.get("label") or node.get("name") or "")
        if not label:
            continue
        path = prefix + [label]
        yield path
        children = node.get("children") or []
        if isinstance(children, list):
            yield from iter_taxonomy_paths(children, path)


def load_taxonomy_paths(path: str = PAPERS_TAXONOMY_PATH) -> list[list[str]]:
    config = load_taxonomy_config(path)
    roots = config.get("roots") or []
    return [candidate for candidate in iter_taxonomy_paths(roots) if candidate]

def extract_json_from_text(text: str) -> Dict[str, Any]:
    text = safe_text(text)

    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.S)
    if match:
        return json.loads(match.group(1))

    match = re.search(r"(\{.*\})", text, re.S)
    if match:
        return json.loads(match.group(1))

    raise ValueError(f"无法从模型输出中解析 JSON: {text[:1000]}")


def safe_get_doi(text: str) -> str | None:
    doi_pattern = r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b"
    match = re.search(doi_pattern, text or "", re.I)
    if match:
        return safe_text(match.group(0).rstrip(".,;:"))
    return None


def load_label_tree(file_path: str) -> Dict[str, Any]:
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_label_tree(label_tree: Dict[str, Any], file_path: str):
    ensure_dir(os.path.dirname(file_path))
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(label_tree, f, ensure_ascii=False, indent=2)


def merge_classification_path_into_tree(label_tree: Dict[str, Any], classification_path: list[str]):
    current = label_tree
    for label in classification_path:
        label = safe_text(str(label))
        if not label:
            continue
        if label not in current:
            current[label] = {}
        current = current[label]
