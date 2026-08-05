# backend/services/papers/extractors.py
import io
import os
import glob
import time
import zipfile
import shutil
import tempfile
import subprocess
from pathlib import Path
from typing import Any


_DOTENV_LOADED = False


def _load_local_env_if_needed() -> None:
    """
    在容器外直接运行 python -m services.papers.ingest_papers 时，
    自动尝试加载 backend/.env。

    优先级原则：
    1. 已存在的系统环境变量不覆盖
    2. 若 python-dotenv 可用，则使用它
    3. 否则退化为简单的 .env 文本解析
    """
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return

    current_file = Path(__file__).resolve()

    candidate_paths = [
        Path.cwd() / ".env",
        Path.cwd() / "backend" / ".env",
        current_file.parents[3] / ".env",  # backend/.env
        current_file.parents[4] / "backend" / ".env",
    ]

    env_path = None
    for p in candidate_paths:
        if p.exists() and p.is_file():
            env_path = p
            break

    if env_path is None:
        _DOTENV_LOADED = True
        return

    # 先尝试 python-dotenv
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(dotenv_path=env_path, override=False)
        print(f"[extractors] loaded .env from {env_path}", flush=True)
        _DOTENV_LOADED = True
        return
    except Exception:
        pass

    # 标准库 fallback：非常轻量，只处理简单 KEY=VALUE
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()

                if not line or line.startswith("#"):
                    continue

                if "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()

                if not key:
                    continue

                # 去掉未加引号值后面的行内注释
                # 例如: CUDA_VISIBLE_DEVICES=1 # comment
                if value and not (
                    (value.startswith('"') and value.endswith('"')) or
                    (value.startswith("'") and value.endswith("'"))
                ):
                    if " #" in value:
                        value = value.split(" #", 1)[0].rstrip()

                # 去掉简单引号
                if len(value) >= 2 and (
                    (value.startswith('"') and value.endswith('"')) or
                    (value.startswith("'") and value.endswith("'"))
                ):
                    value = value[1:-1]

                os.environ.setdefault(key, value)


        print(f"[extractors] loaded .env (fallback parser) from {env_path}", flush=True)
    finally:
        _DOTENV_LOADED = True


def extract_with_pymupdf4llm(pdf_path: str) -> str:
    import pymupdf4llm
    return pymupdf4llm.to_markdown(pdf_path)


def _find_first_markdown_file(output_dir: str) -> str | None:
    candidates = glob.glob(os.path.join(output_dir, "**", "*.md"), recursive=True)
    if not candidates:
        return None

    candidates = sorted(candidates, key=lambda x: os.path.getsize(x), reverse=True)
    return candidates[0]

def extract_with_mineru(pdf_path: str) -> str:
    """
    通过 MinerU CLI 提取 markdown。
    使用 CPU pipeline 模式，兼容无 GPU 环境。
    """
    if shutil.which("mineru") is None:
        raise RuntimeError("mineru CLI not found in PATH")

    with tempfile.TemporaryDirectory(prefix="mineru_out_") as out_dir:
        cmd = [
            "mineru",
            "-p", pdf_path,
            "-o", out_dir,
            "-b", "pipeline",
        ]

        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if proc.returncode != 0:
            raise RuntimeError(
                f"mineru cli failed: code={proc.returncode}\n"
                f"stdout={proc.stdout}\n"
                f"stderr={proc.stderr}"
            )

        md_file = _find_first_markdown_file(out_dir)
        if not md_file or not os.path.exists(md_file):
            raise RuntimeError(
                f"mineru cli succeeded but no markdown file found under {out_dir}\n"
                f"stdout={proc.stdout}\n"
                f"stderr={proc.stderr}"
            )

        with open(md_file, "r", encoding="utf-8") as f:
            return f.read()


def _env(name: str, default: str | None = None) -> str | None:
    _load_local_env_if_needed()
    value = os.getenv(name, default)
    if value is None:
        return None
    value = value.strip()
    return value or default


def _require_env(name: str) -> str:
    value = _env(name)
    if not value:
        raise RuntimeError(f"{name} is not set")
    return value


def _safe_json(resp) -> dict[str, Any]:
    try:
        return resp.json()
    except Exception as e:
        raise RuntimeError(
            f"response is not valid json: status={resp.status_code}, text={resp.text[:1000]}"
        ) from e


def _check_api_success(payload: dict[str, Any], context: str) -> None:
    code = payload.get("code")
    if code != 0:
        msg = payload.get("msg", "")
        trace_id = payload.get("trace_id", "")
        raise RuntimeError(
            f"{context} failed: code={code}, msg={msg}, trace_id={trace_id}, payload={payload}"
        )


def _download_text(url: str, headers: dict[str, str] | None = None, timeout: int = 120) -> str:
    import requests

    resp = requests.get(url, headers=headers or {}, timeout=timeout)
    resp.raise_for_status()
    text = resp.text
    if not text.strip():
        raise RuntimeError(f"downloaded empty text from {url}")
    return text


def _download_zip_and_extract_markdown(
    zip_url: str,
    headers: dict[str, str] | None = None,
    timeout: int = 120,
) -> str:
    import requests

    resp = requests.get(zip_url, headers=headers or {}, timeout=timeout)
    resp.raise_for_status()

    content = resp.content
    if not content:
        raise RuntimeError(f"downloaded empty zip from {zip_url}")

    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = zf.namelist()

        preferred = [n for n in names if n.lower().endswith("/full.md") or n.lower() == "full.md"]
        if not preferred:
            preferred = [n for n in names if n.lower().endswith(".md")]

        if not preferred:
            raise RuntimeError(f"no markdown file found in zip: names={names}")

        if len(preferred) == 1:
            target = preferred[0]
        else:
            target = max(preferred, key=lambda n: zf.getinfo(n).file_size)

        with zf.open(target) as f:
            data = f.read()
            return data.decode("utf-8", errors="replace")

def _download_zip_and_extract_bundle(
    zip_url: str,
    out_dir: str,
    headers: dict[str, str] | None = None,
    timeout: int = 120,
) -> str:
    """
    下载 full_zip_url 并把整个 zip 解压到 out_dir（含 figures/equations/tables 等）。
    返回解压后找到的 markdown 文本（优先 full.md）。
    """
    import requests

    resp = requests.get(zip_url, headers=headers or {}, timeout=timeout)
    resp.raise_for_status()

    content = resp.content
    if not content:
        raise RuntimeError(f"downloaded empty zip from {zip_url}")

    os.makedirs(out_dir, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        zf.extractall(out_dir)

    md_file = _find_first_markdown_file(out_dir)
    if not md_file:
        raise RuntimeError(f"no markdown file found after extracting zip to {out_dir}")

    with open(md_file, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _build_data_id_from_path(pdf_path: str) -> str:
    base = os.path.basename(pdf_path)
    name = os.path.splitext(base)[0]
    cleaned = []
    for ch in name:
        if ch.isalnum() or ch in ("_", "-", "."):
            cleaned.append(ch)
        else:
            cleaned.append("_")
    result = "".join(cleaned).strip("._-") or "paper"
    return result[:128]


def _guess_model_version_by_ext(file_path: str, default: str = "vlm") -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".html":
        return "MinerU-HTML"
    return default


def _get_standard_api_common_options(file_path: str) -> dict[str, Any]:
    model_version = _env("MINERU_API_MODEL_VERSION", "vlm")
    model_version = _guess_model_version_by_ext(file_path, default=model_version)

    opts: dict[str, Any] = {
        "model_version": model_version,
    }

    is_ocr = _env("MINERU_API_IS_OCR")
    if is_ocr is not None and model_version != "MinerU-HTML":
        opts["is_ocr"] = is_ocr.lower() in ("1", "true", "yes", "on")

    enable_formula = _env("MINERU_API_ENABLE_FORMULA")
    if enable_formula is not None and model_version != "MinerU-HTML":
        opts["enable_formula"] = enable_formula.lower() in ("1", "true", "yes", "on")

    enable_table = _env("MINERU_API_ENABLE_TABLE")
    if enable_table is not None and model_version != "MinerU-HTML":
        opts["enable_table"] = enable_table.lower() in ("1", "true", "yes", "on")

    language = _env("MINERU_API_LANGUAGE")
    if language and model_version != "MinerU-HTML":
        opts["language"] = language

    page_ranges = _env("MINERU_API_PAGE_RANGES")
    if page_ranges:
        opts["page_ranges"] = page_ranges

    no_cache = _env("MINERU_API_NO_CACHE")
    if no_cache is not None:
        opts["no_cache"] = no_cache.lower() in ("1", "true", "yes", "on")

    cache_tolerance = _env("MINERU_API_CACHE_TOLERANCE")
    if cache_tolerance:
        try:
            opts["cache_tolerance"] = int(cache_tolerance)
        except ValueError:
            pass

    extra_formats = _env("MINERU_API_EXTRA_FORMATS")
    if extra_formats and model_version != "MinerU-HTML":
        formats = [x.strip() for x in extra_formats.split(",") if x.strip()]
        if formats:
            opts["extra_formats"] = formats

    data_id = _env("MINERU_API_DATA_ID") or _build_data_id_from_path(file_path)
    if data_id:
        opts["data_id"] = data_id

    return opts


def _standard_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _poll_standard_batch_result(batch_id: str, token: str, timeout: int, interval: int, target_file_name: str) -> str:
    import requests

    base_url = _env("MINERU_API_BASE_URL", "https://mineru.net").rstrip("/")
    url = f"{base_url}/api/v4/extract-results/batch/{batch_id}"
    headers = _standard_headers(token)

    started = time.time()
    last_payload: dict[str, Any] | None = None

    while time.time() - started < timeout:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        payload = _safe_json(resp)
        _check_api_success(payload, "mineru standard batch result")
        last_payload = payload

        data = payload.get("data", {})
        results = data.get("extract_result", []) or []

        target = None
        for item in results:
            if item.get("file_name") == target_file_name:
                target = item
                break

        if target is None and len(results) == 1:
            target = results[0]

        if target:
            state = str(target.get("state", "")).lower()

            if state == "done":
                full_zip_url = target.get("full_zip_url")
                if not full_zip_url:
                    raise RuntimeError(f"task done but full_zip_url missing: {target}")
                return _download_zip_and_extract_markdown(full_zip_url, timeout=timeout)

            if state == "failed":
                err_msg = target.get("err_msg", "")
                raise RuntimeError(f"mineru standard api task failed: {err_msg} | payload={target}")

            print(f"[extractors] mineru_api batch state={state}, file={target.get('file_name')}", flush=True)

        time.sleep(interval)

    raise RuntimeError(
        f"mineru standard batch polling timeout, batch_id={batch_id}, last_payload={last_payload}"
    )

def _poll_standard_batch_full_zip_url(
    batch_id: str, token: str, timeout: int, interval: int, target_file_name: str
) -> str:
    import requests

    base_url = _env("MINERU_API_BASE_URL", "https://mineru.net").rstrip("/")
    url = f"{base_url}/api/v4/extract-results/batch/{batch_id}"
    headers = _standard_headers(token)

    started = time.time()
    last_payload: dict[str, Any] | None = None

    while time.time() - started < timeout:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        payload = _safe_json(resp)
        _check_api_success(payload, "mineru standard batch result")
        last_payload = payload

        data = payload.get("data", {})
        results = data.get("extract_result", []) or []

        target = None
        for item in results:
            if item.get("file_name") == target_file_name:
                target = item
                break
        if target is None and len(results) == 1:
            target = results[0]

        if target:
            state = str(target.get("state", "")).lower()

            if state == "done":
                full_zip_url = target.get("full_zip_url")
                if not full_zip_url:
                    raise RuntimeError(f"task done but full_zip_url missing: {target}")
                return full_zip_url

            if state == "failed":
                err_msg = target.get("err_msg", "")
                raise RuntimeError(f"mineru standard api task failed: {err_msg} | payload={target}")

            print(f"[extractors] mineru_api batch state={state}, file={target.get('file_name')}", flush=True)

        time.sleep(interval)

    raise RuntimeError(
        f"mineru standard batch polling timeout, batch_id={batch_id}, last_payload={last_payload}"
    )


def extract_with_mineru_api(pdf_path: str) -> str:
    """
    精准解析 API：本地文件上传模式
    1) POST /api/v4/file-urls/batch
    2) PUT 上传文件
    3) GET /api/v4/extract-results/batch/{batch_id}
    4) 下载 full_zip_url 并提取 full.md
    """
    import requests

    token = _require_env("MINERU_API_TOKEN")
    base_url = _env("MINERU_API_BASE_URL", "https://mineru.net").rstrip("/")
    timeout = int(_env("MINERU_API_TIMEOUT", "300") or "300")
    interval = int(_env("MINERU_API_POLL_INTERVAL", "3") or "3")

    url = f"{base_url}/api/v4/file-urls/batch"
    headers = _standard_headers(token)

    file_name = os.path.basename(pdf_path)
    options = _get_standard_api_common_options(pdf_path)

    file_payload = {
        "name": file_name,
        "data_id": options.pop("data_id", _build_data_id_from_path(pdf_path)),
    }

    file_is_ocr = _env("MINERU_API_IS_OCR")
    if file_is_ocr is not None and options.get("model_version") != "MinerU-HTML":
        file_payload["is_ocr"] = file_is_ocr.lower() in ("1", "true", "yes", "on")

    page_ranges = _env("MINERU_API_PAGE_RANGES")
    if page_ranges:
        file_payload["page_ranges"] = page_ranges

    payload = {
        "files": [file_payload],
        **options,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    result = _safe_json(resp)
    _check_api_success(result, "mineru standard apply upload url")

    data = result.get("data", {})
    batch_id = data.get("batch_id")
    file_urls = data.get("file_urls") or []

    if not batch_id:
        raise RuntimeError(f"batch_id missing in response: {result}")
    if not file_urls:
        raise RuntimeError(f"file_urls missing in response: {result}")

    upload_url = file_urls[0]
    with open(pdf_path, "rb") as f:
        put_resp = requests.put(upload_url, data=f, timeout=timeout)

    if put_resp.status_code not in (200, 201):
        raise RuntimeError(
            f"file upload failed: status={put_resp.status_code}, text={put_resp.text[:1000]}"
        )

    return _poll_standard_batch_result(
        batch_id=batch_id,
        token=token,
        timeout=timeout,
        interval=interval,
        target_file_name=file_name,
    )

def extract_with_mineru_api_doc_bundle(pdf_path: str, assets_dir: str) -> str:
    """
    MinerU 标准 API：下载 full_zip_url 并解压整个 bundle 到 assets_dir（含 figures/ 等）。
    返回 markdown 文本（从解压后的 full.md/最大 md 读取）。
    """
    import requests

    token = _require_env("MINERU_API_TOKEN")
    base_url = _env("MINERU_API_BASE_URL", "https://mineru.net").rstrip("/")
    timeout = int(_env("MINERU_API_TIMEOUT", "300") or "300")
    interval = int(_env("MINERU_API_POLL_INTERVAL", "3") or "3")

    url = f"{base_url}/api/v4/file-urls/batch"
    headers = _standard_headers(token)

    file_name = os.path.basename(pdf_path)
    options = _get_standard_api_common_options(pdf_path)

    file_payload = {
        "name": file_name,
        "data_id": options.pop("data_id", _build_data_id_from_path(pdf_path)),
    }

    file_is_ocr = _env("MINERU_API_IS_OCR")
    if file_is_ocr is not None and options.get("model_version") != "MinerU-HTML":
        file_payload["is_ocr"] = file_is_ocr.lower() in ("1", "true", "yes", "on")

    page_ranges = _env("MINERU_API_PAGE_RANGES")
    if page_ranges:
        file_payload["page_ranges"] = page_ranges

    payload = {
        "files": [file_payload],
        **options,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    result = _safe_json(resp)
    _check_api_success(result, "mineru standard apply upload url")

    data = result.get("data", {})
    batch_id = data.get("batch_id")
    file_urls = data.get("file_urls") or []
    if not batch_id:
        raise RuntimeError(f"batch_id missing in response: {result}")
    if not file_urls:
        raise RuntimeError(f"file_urls missing in response: {result}")

    upload_url = file_urls[0]
    with open(pdf_path, "rb") as f:
        put_resp = requests.put(upload_url, data=f, timeout=timeout)
    if put_resp.status_code not in (200, 201):
        raise RuntimeError(
            f"file upload failed: status={put_resp.status_code}, text={put_resp.text[:1000]}"
        )

    full_zip_url = _poll_standard_batch_full_zip_url(
        batch_id=batch_id,
        token=token,
        timeout=timeout,
        interval=interval,
        target_file_name=file_name,
    )

    # 解压完整 bundle 到 assets_dir（按文献名区分目录）
    return _download_zip_and_extract_bundle(full_zip_url, out_dir=assets_dir, timeout=timeout)


def extract_with_mineru_api_url(file_url: str, source_name: str | None = None) -> str:
    """
    精准解析 API：公网 URL 模式
    1) POST /api/v4/extract/task
    2) GET /api/v4/extract/task/{task_id}
    3) 下载 full_zip_url 并提取 full.md
    """
    import requests

    token = _require_env("MINERU_API_TOKEN")
    base_url = _env("MINERU_API_BASE_URL", "https://mineru.net").rstrip("/")
    timeout = int(_env("MINERU_API_TIMEOUT", "300") or "300")
    interval = int(_env("MINERU_API_POLL_INTERVAL", "3") or "3")

    headers = _standard_headers(token)
    submit_url = f"{base_url}/api/v4/extract/task"

    fake_name = source_name or os.path.basename(file_url.split("?")[0]) or "remote.pdf"
    options = _get_standard_api_common_options(fake_name)
    payload = {
        "url": file_url,
        **options,
    }

    resp = requests.post(submit_url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    result = _safe_json(resp)
    _check_api_success(result, "mineru standard submit url task")

    task_id = (result.get("data") or {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"task_id missing in response: {result}")

    task_url = f"{base_url}/api/v4/extract/task/{task_id}"
    last_payload: dict[str, Any] | None = None
    started = time.time()

    while time.time() - started < timeout:
        poll_resp = requests.get(task_url, headers=headers, timeout=timeout)
        poll_resp.raise_for_status()
        poll_payload = _safe_json(poll_resp)
        _check_api_success(poll_payload, "mineru standard poll task")
        last_payload = poll_payload

        data = poll_payload.get("data", {})
        state = str(data.get("state", "")).lower()

        if state == "done":
            full_zip_url = data.get("full_zip_url")
            if not full_zip_url:
                raise RuntimeError(f"task done but full_zip_url missing: {poll_payload}")
            return _download_zip_and_extract_markdown(full_zip_url, timeout=timeout)

        if state == "failed":
            err_msg = data.get("err_msg", "")
            raise RuntimeError(f"mineru standard url task failed: {err_msg} | payload={poll_payload}")

        print(f"[extractors] mineru_api_url task state={state}, task_id={task_id}", flush=True)
        time.sleep(interval)

    raise RuntimeError(
        f"mineru standard url polling timeout, task_id={task_id}, last_payload={last_payload}"
    )


def _agent_base_url() -> str:
    return _env("MINERU_AGENT_BASE_URL", "https://mineru.net/api/v1/agent").rstrip("/")


def _agent_timeout() -> int:
    return int(_env("MINERU_AGENT_TIMEOUT", "180") or "180")


def _agent_interval() -> int:
    return int(_env("MINERU_AGENT_POLL_INTERVAL", "3") or "3")


def _agent_language() -> str | None:
    return _env("MINERU_AGENT_LANGUAGE", "ch")


def _agent_page_range() -> str | None:
    return _env("MINERU_AGENT_PAGE_RANGE")


def _poll_agent_task(task_id: str) -> str:
    import requests

    base_url = _agent_base_url()
    timeout = _agent_timeout()
    interval = _agent_interval()

    url = f"{base_url}/parse/{task_id}"
    started = time.time()
    last_payload: dict[str, Any] | None = None

    while time.time() - started < timeout:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        payload = _safe_json(resp)
        _check_api_success(payload, "mineru agent poll")
        last_payload = payload

        data = payload.get("data", {})
        state = str(data.get("state", "")).lower()

        if state == "done":
            markdown_url = data.get("markdown_url")
            if not markdown_url:
                raise RuntimeError(f"agent task done but markdown_url missing: {payload}")
            return _download_text(markdown_url, timeout=timeout)

        if state == "failed":
            err_code = data.get("err_code")
            err_msg = data.get("err_msg", "")
            raise RuntimeError(f"mineru agent task failed: err_code={err_code}, err_msg={err_msg}")

        print(f"[extractors] mineru_agent state={state}, task_id={task_id}", flush=True)
        time.sleep(interval)

    raise RuntimeError(f"mineru agent polling timeout, task_id={task_id}, last_payload={last_payload}")


def extract_with_mineru_agent(pdf_path: str) -> str:
    """
    Agent 轻量 API：本地文件签名上传模式
    """
    import requests

    base_url = _agent_base_url()
    timeout = _agent_timeout()

    file_name = os.path.basename(pdf_path)
    payload: dict[str, Any] = {
        "file_name": file_name,
    }

    language = _agent_language()
    if language:
        payload["language"] = language

    page_range = _agent_page_range()
    if page_range:
        payload["page_range"] = page_range

    resp = requests.post(f"{base_url}/parse/file", json=payload, timeout=timeout)
    resp.raise_for_status()
    result = _safe_json(resp)
    _check_api_success(result, "mineru agent apply upload url")

    data = result.get("data", {})
    task_id = data.get("task_id")
    file_url = data.get("file_url")
    if not task_id or not file_url:
        raise RuntimeError(f"agent file upload init response invalid: {result}")

    with open(pdf_path, "rb") as f:
        put_resp = requests.put(file_url, data=f, timeout=timeout)
    if put_resp.status_code not in (200, 201):
        raise RuntimeError(
            f"agent file upload failed: status={put_resp.status_code}, text={put_resp.text[:1000]}"
        )

    return _poll_agent_task(task_id)


def extract_with_mineru_agent_url(file_url: str, source_name: str | None = None) -> str:
    """
    Agent 轻量 API：公网 URL 模式
    """
    import requests

    base_url = _agent_base_url()
    timeout = _agent_timeout()

    payload: dict[str, Any] = {
        "url": file_url,
    }

    language = _agent_language()
    if language:
        payload["language"] = language

    page_range = _agent_page_range()
    if page_range:
        payload["page_range"] = page_range

    if source_name:
        payload["file_name"] = source_name

    resp = requests.post(f"{base_url}/parse/url", json=payload, timeout=timeout)
    resp.raise_for_status()
    result = _safe_json(resp)
    _check_api_success(result, "mineru agent submit url task")

    task_id = (result.get("data") or {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"agent url response missing task_id: {result}")

    return _poll_agent_task(task_id)

def _allow_fallback() -> bool:
    value = str(_env("PAPERS_EXTRACT_ALLOW_FALLBACK", "1") or "").strip().lower()
    return value in ("1", "true", "yes", "on")

def get_env(name: str, default: str | None = None) -> str | None:
    return _env(name, default)

def extract_markdown(pdf_path: str, engine: str = "mineru", assets_dir: str | None = None) -> tuple[str, str]:
    """
    return: (markdown_text, actual_engine)
    """
    engine = (engine or "mineru").lower()

    if engine == "pymupdf4llm":
        print(f"[extractors] using pymupdf4llm: {pdf_path}", flush=True)
        return extract_with_pymupdf4llm(pdf_path), "pymupdf4llm"

    if engine == "mineru_api":
        try:
            print(f"[extractors] using mineru_api (standard file upload): {pdf_path}", flush=True)
            if assets_dir:
                print(f"[extractors] using mineru_api doc bundle (save assets): {pdf_path} -> {assets_dir}", flush=True)
                md = extract_with_mineru_api_doc_bundle(pdf_path, assets_dir=assets_dir)

                # 让 md 引用指向 “按文献名分目录”的 assets
                assets_name = os.path.basename(assets_dir.rstrip("/"))
                for sub in ("figures/", "equations/", "tables/"):
                    md = md.replace(f"]({sub}", f"]({assets_name}/{sub}")
                    md = md.replace(f"({sub}", f"({assets_name}/{sub}")

                return md, "mineru_api_doc"
            else:
                print(f"[extractors] using mineru_api (standard file upload): {pdf_path}", flush=True)
                return extract_with_mineru_api(pdf_path), "mineru_api"
        except Exception as e:
            if _allow_fallback():
                print(f"[extractors] MinerU standard API failed, fallback to pymupdf4llm: {e}", flush=True)
                return extract_with_pymupdf4llm(pdf_path), "pymupdf4llm"

            print(f"[extractors] MinerU standard API failed and fallback is disabled: {e}", flush=True)
            raise

    if engine == "mineru_api_url":
        try:
            print(f"[extractors] using mineru_api_url: {pdf_path}", flush=True)
            return extract_with_mineru_api_url(pdf_path, source_name=os.path.basename(pdf_path)), "mineru_api_url"
        except Exception as e:
            if _allow_fallback():
                print(f"[extractors] MinerU standard API failed, fallback to pymupdf4llm: {e}", flush=True)
                return extract_with_pymupdf4llm(pdf_path), "pymupdf4llm"

            print(f"[extractors] MinerU standard API failed and fallback is disabled: {e}", flush=True)
            raise

    if engine == "mineru_agent":
        try:
            print(f"[extractors] using mineru_agent (light file upload): {pdf_path}", flush=True)
            return extract_with_mineru_agent(pdf_path), "mineru_agent"
        except Exception as e:
            if _allow_fallback():
                print(f"[extractors] MinerU standard API failed, fallback to pymupdf4llm: {e}", flush=True)
                return extract_with_pymupdf4llm(pdf_path), "pymupdf4llm"

            print(f"[extractors] MinerU standard API failed and fallback is disabled: {e}", flush=True)
            raise

    if engine == "mineru_agent_url":
        try:
            print(f"[extractors] using mineru_agent_url: {pdf_path}", flush=True)
            return extract_with_mineru_agent_url(pdf_path, source_name=os.path.basename(pdf_path)), "mineru_agent_url"
        except Exception as e:
            if _allow_fallback():
                print(f"[extractors] MinerU standard API failed, fallback to pymupdf4llm: {e}", flush=True)
                return extract_with_pymupdf4llm(pdf_path), "pymupdf4llm"

            print(f"[extractors] MinerU standard API failed and fallback is disabled: {e}", flush=True)
            raise

    if engine == "mineru":
        try:
            print(f"[extractors] using mineru cli: {pdf_path}", flush=True)
            return extract_with_mineru(pdf_path), "mineru"
        except Exception as e:
            if _allow_fallback():
                print(f"[extractors] MinerU standard API failed, fallback to pymupdf4llm: {e}", flush=True)
                return extract_with_pymupdf4llm(pdf_path), "pymupdf4llm"

            print(f"[extractors] MinerU standard API failed and fallback is disabled: {e}", flush=True)
            raise

    raise ValueError(f"unsupported engine: {engine}")