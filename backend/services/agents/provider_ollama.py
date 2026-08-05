# backend/services/agents/provider_ollama.py
import re
import time
import requests
from typing import List, Dict, Any


def clean_answer(text: str) -> str:
    text = text or ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    return text.strip()


class OllamaProvider:
    def __init__(self, base_url: str, model: str, timeout: int = 120, max_retries: int = 1):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    def chat(
        self,
        system_prompt: str,
        user_message: str,
        history: List[Dict[str, Any]] | None = None
    ) -> str:
        history = history or []

        prompt_parts = [f"系统指令：\n{system_prompt}\n"]

        if history:
            prompt_parts.append("以下是历史对话：")
            for item in history:
                role = item.get("role", "user")
                content = str(item.get("content", "")).strip()
                if not content:
                    continue
                prompt_parts.append(f"{role}: {content}")

        prompt_parts.append(f"\n用户问题：{user_message}\n")
        prompt_parts.append("请直接输出最终回答，不要输出思考过程，不要输出<think>标签。")

        prompt = "\n".join(prompt_parts)

        last_error = None

        for attempt in range(self.max_retries + 1):
            start = time.time()
            try:
                print(
                    f"[ollama] request start model={self.model} attempt={attempt + 1} timeout={self.timeout}s",
                    flush=True
                )

                resp = requests.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.2,
                        },
                    },
                    timeout=self.timeout,
                )
                resp.raise_for_status()

                data = resp.json()
                answer = clean_answer(data.get("response", ""))

                elapsed = time.time() - start
                print(
                    f"[ollama] request success model={self.model} attempt={attempt + 1} elapsed={elapsed:.2f}s",
                    flush=True
                )

                return answer

            except requests.Timeout as e:
                elapsed = time.time() - start
                print(
                    f"[ollama] timeout model={self.model} attempt={attempt + 1} elapsed={elapsed:.2f}s error={e}",
                    flush=True
                )
                last_error = RuntimeError("Ollama 请求超时，模型响应较慢或服务繁忙")

            except requests.ConnectionError as e:
                elapsed = time.time() - start
                print(
                    f"[ollama] connection error model={self.model} attempt={attempt + 1} elapsed={elapsed:.2f}s error={e}",
                    flush=True
                )
                last_error = RuntimeError("无法连接 Ollama 服务，请检查 Ollama 是否正常运行")

            except requests.HTTPError as e:
                elapsed = time.time() - start
                body = ""
                try:
                    body = resp.text[:500]
                except Exception:
                    pass

                print(
                    f"[ollama] http error model={self.model} attempt={attempt + 1} elapsed={elapsed:.2f}s status={getattr(resp, 'status_code', 'unknown')} body={body} error={e}",
                    flush=True
                )
                last_error = RuntimeError(f"Ollama 返回 HTTP 错误: {e}")

            except Exception as e:
                elapsed = time.time() - start
                print(
                    f"[ollama] unknown error model={self.model} attempt={attempt + 1} elapsed={elapsed:.2f}s error={e}",
                    flush=True
                )
                last_error = RuntimeError(f"Ollama 调用异常: {e}")

            if attempt < self.max_retries:
                print(
                    f"[ollama] retrying model={self.model} next_attempt={attempt + 2}",
                    flush=True
                )
                time.sleep(1)

        raise last_error or RuntimeError("Ollama 调用失败")
