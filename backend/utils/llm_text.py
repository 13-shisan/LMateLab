# backend/utils/llm_text.py
import re


def strip_think_blocks(text: str) -> str:
    text = text or ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    return text.strip()


def normalize_llm_answer(text: str) -> str:
    text = strip_think_blocks(text)
    return text.strip()
