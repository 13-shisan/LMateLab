# backend/services/papers/classifier.py
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests

from .config import LABEL_TREE_PATH
from .extractors import get_env
from .utils import (
    dump_json,
    extract_abstract_from_markdown_first_n_paragraphs,
    extract_doi_from_text,
    extract_json_from_text,
    load_label_tree,
    merge_classification_path_into_tree,
    safe_get_doi,
    safe_text,
    save_label_tree,
)


DEFAULT_CLASSIFICATION = {
    "taxonomy_path": ["未分类"],
    "main_topic": "未分类",
    "leaf_topic": "未分类",
    "reason": "分类失败，已回退为未分类",
}


DEFAULT_METADATA_EXTRACTION = {
    "title": "",
    "abstract": "",
    "doi": None,
    "reason": "未调用 LLM 元数据提取",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class DeepSeekClient:
    def __init__(self):
        self.api_key = get_env("DEEPSEEK_API_KEY", "") or ""
        self.api_base_url = (
            get_env("DEEPSEEK_API_BASE_URL", "https://api.deepseek.com/chat/completions") or ""
        ).rstrip("/")
        self.default_model = get_env("DEEPSEEK_MODEL", "") or "deepseek-chat"
        self.metadata_model = get_env("DEEPSEEK_METADATA_MODEL", "") or self.default_model
        self.classification_model = get_env("DEEPSEEK_CLASSIFICATION_MODEL", "") or self.default_model
        self.timeout = int(get_env("DEEPSEEK_TIMEOUT", "120") or "120")

    def is_enabled(self) -> bool:
        return bool(self.api_key and self.default_model and self.api_base_url)

    def chat(self, model: str, system_prompt: str, user_prompt: str, temperature: float = 0.1, max_retries: int = 3) -> str:
        if not self.is_enabled():
            raise RuntimeError("DeepSeek API is not configured")

        url = self.api_base_url
        if not url.endswith("/chat/completions"):
            url = f"{url}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }

        last_error = None
        for attempt in range(max_retries):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
                return (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            except Exception as e:
                last_error = e
                print(f"[papers_classifier] DeepSeek 调用失败，第 {attempt + 1} 次重试: {e}", flush=True)
                time.sleep(2 ** attempt)

        raise last_error


def _build_pdf_context(markdown_text: str, header_footer_texts: list[str] | None = None) -> str:
    header_footer_texts = header_footer_texts or []
    header_footer_block = "\n".join([safe_text(x) for x in header_footer_texts if safe_text(x)])[:4000]
    markdown_preview = (markdown_text or "")[:20000]
    return (
        "页眉页脚候选文本：\n"
        f"{header_footer_block or 'N/A'}\n\n"
        "正文/解析文本预览：\n"
        f"{markdown_preview or 'N/A'}"
    )


def extract_metadata_from_pdf_with_llm(
    pdf_path: str,
    markdown_text: str,
    header_footer_texts: list[str] | None = None,
    title_hint: str = "",
    journal_hint: str = "",
    year_hint: Any = None,
    client: DeepSeekClient | None = None,
) -> dict[str, Any]:
    llm = client or DeepSeekClient()
    if not llm.is_enabled():
        return {
            **DEFAULT_METADATA_EXTRACTION,
            "status": "skipped",
            "model": llm.metadata_model,
            "failure_reason": "DeepSeek API is not configured",
            "extracted_at": utc_now_iso(),
        }

    context = _build_pdf_context(markdown_text, header_footer_texts)

    system_prompt = """
你是一个严谨的学术文献信息抽取助手。
请从输入文献内容中提取以下字段，并以 JSON 格式返回：
{
  "title": "文章题目",
  "abstract": "文章摘要",
  "doi": "DOI号"
}

要求：
1. 必须只输出 JSON，不要输出解释。
2. 如果某个字段无法确定，填空字符串。
3. 不要编造内容。
4. 摘要应优先提取原文摘要，而不是自己总结。
"""

    user_prompt = (
        f"请从以下文献内容中提取题目、摘要和 DOI：\n\n"
        f"标题提示: {title_hint or 'N/A'}\n"
        f"期刊提示: {journal_hint or 'N/A'}\n"
        f"年份提示: {year_hint or 'N/A'}\n"
        f"PDF路径: {pdf_path}\n\n"
        f"{context}"
    )

    try:
        raw = llm.chat(
            model=llm.metadata_model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.0,
        )
        result = extract_json_from_text(raw)
    except Exception as e:
        return {
            **DEFAULT_METADATA_EXTRACTION,
            "status": "failed",
            "model": llm.metadata_model,
            "failure_reason": str(e),
            "extracted_at": utc_now_iso(),
        }

    title = safe_text(result.get("title") or "") or safe_text(title_hint or "")
    abstract = safe_text(result.get("abstract") or "")
    doi = safe_text(result.get("doi") or "") or None

    if not doi:
        doi = safe_get_doi(markdown_text) or extract_doi_from_text(markdown_text)

    if not abstract:
        abstract = safe_text(extract_abstract_from_markdown_first_n_paragraphs(markdown_text, max_paragraphs=8, max_chars=4000))

    return {
        "title": title,
        "abstract": abstract,
        "doi": doi,
        "reason": "基于论文解析文本提取题目、原文摘要和 DOI，DOI 采用正则兜底校验",
        "status": "success" if (title or abstract or doi) else "failed",
        "model": llm.metadata_model,
        "failure_reason": "" if (title or abstract or doi) else "DeepSeek returned empty title/abstract/doi",
        "extracted_at": utc_now_iso(),
    }


def classify_abstract_with_llm(
    abstract: str,
    title: str,
    journal: str,
    label_tree: dict[str, Any],
    client: DeepSeekClient | None = None,
) -> tuple[dict[str, Any] | None, str]:
    llm = client or DeepSeekClient()
    if not llm.is_enabled():
        return None, "DeepSeek API is not configured"

    label_tree_text = json.dumps(label_tree or {}, ensure_ascii=False, indent=2)

    system_prompt = """
你是一个学术文献分类助手。
请根据输入文献的题目和摘要，对文献进行树状层级分类。

你会看到一份“已有标签树”。
要求如下：
1. 优先复用已有标签树中的标签，尽量保持标签命名一致。
2. 如果现有标签树中没有合适标签，可以新增必要的新标签。
3. 分类结果应为一条树状路径，从宽泛领域逐步缩小到具体研究方向。
4. 每一层只能有一个标签，整篇文献只能输出一条主路径。
5. 分类路径通常为 3 到 5 层，如无必要不要强行细分。
6. 标签应尽量简洁、规范、学术化，避免口语化或过长描述。
7. 避免创造与已有标签语义重复但表述不同的新标签。
8. 一级标签应尽量稳定且宽泛，二级标签反映学科方向，三级及以下再逐步细化。
9. 不要输出多个候选分类，不要输出并列分支。
10. 只输出 JSON，不要输出其他解释。

输出格式：
{
  "classification_path": ["一级标签", "二级标签", "三级标签"],
  "reason": "简要说明分类依据"
}
"""

    user_prompt = f"""
已有标签树：
{label_tree_text}

文献题目：
{title}

文献摘要：
{abstract}

期刊：
{journal or 'N/A'}

请参考已有标签树，对该文献进行树状层级分类。
若现有标签足够合适，优先复用；若不够，再新增必要标签。
"""

    try:
        raw = llm.chat(
            model=llm.classification_model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.1,
        )
        result = extract_json_from_text(raw)
        return result, ""
    except Exception as e:
        print(f"[papers_classifier] classify_abstract_with_llm failed: {e}", flush=True)
        return None, str(e)


class PaperClassifier:
    def __init__(self):
        self.client = DeepSeekClient()
        self.label_tree_path = LABEL_TREE_PATH
        self.label_tree = load_label_tree(self.label_tree_path)

    def _reload_label_tree(self):
        self.label_tree = load_label_tree(self.label_tree_path)

    def classify(self, abstract: str, title: str = "", journal: str = "") -> dict[str, Any]:
        abstract = safe_text(abstract)
        title = safe_text(title)

        if not abstract:
            return dict(DEFAULT_CLASSIFICATION)

        self._reload_label_tree()

        result, llm_failure_reason = classify_abstract_with_llm(
            abstract=abstract,
            title=title,
            journal=journal,
            label_tree=self.label_tree,
            client=self.client,
        )

        if not isinstance(result, dict):
            fallback = dict(DEFAULT_CLASSIFICATION)
            fallback["_classification_source"] = "failed"
            fallback["_llm_failure_reason"] = llm_failure_reason or ""
            return fallback

        path = result.get("classification_path", [])
        reason = safe_text(result.get("reason") or "")

        if not isinstance(path, list):
            path = []

        cleaned_path = []
        for item in path:
            item = safe_text(str(item))
            if item:
                cleaned_path.append(item)

        if not cleaned_path:
            fallback = dict(DEFAULT_CLASSIFICATION)
            fallback["_classification_source"] = "failed"
            fallback["_llm_failure_reason"] = llm_failure_reason or "classification_path empty"
            return fallback

        merge_classification_path_into_tree(self.label_tree, cleaned_path)
        save_label_tree(self.label_tree, self.label_tree_path)

        return {
            "taxonomy_path": cleaned_path,
            "main_topic": cleaned_path[0],
            "leaf_topic": cleaned_path[-1],
            "reason": reason,
            "_classification_source": "llm",
            "_llm_failure_reason": llm_failure_reason or "",
        }
