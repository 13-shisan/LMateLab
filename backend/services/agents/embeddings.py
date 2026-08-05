# backend/services/agents/embeddings.py
import os
from typing import List

from .rag_config import (
    EMBEDDING_MODEL_NAME,
    EMBEDDING_DEVICE,
    EMBEDDING_USE_FP16,
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_MAX_LENGTH,
)

_embedding_model = None
_embedding_runtime_device = None


def _resolve_device() -> str:
    try:
        import torch
    except ImportError as e:
        raise RuntimeError(
            "未安装 torch。请先安装 PyTorch（GPU 环境请安装 CUDA 版本）。"
        ) from e

    requested = (EMBEDDING_DEVICE or "auto").strip().lower()

    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"

    if requested.startswith("cuda"):
        if not torch.cuda.is_available():
            print("[embeddings] cuda requested but torch.cuda.is_available() is False, fallback to cpu", flush=True)
            return "cpu"
        return requested

    return "cpu"


def get_embedding_model():
    global _embedding_model, _embedding_runtime_device

    if _embedding_model is not None:
        return _embedding_model

    model_path = EMBEDDING_MODEL_NAME

    if not os.path.isdir(model_path):
        raise RuntimeError(f"本地 BGE-M3 模型目录不存在：{model_path}")

    try:
        import torch
    except ImportError as e:
        raise RuntimeError(
            "未安装 torch。请先安装 PyTorch（GPU 环境请安装 CUDA 版本）。"
        ) from e

    try:
        from FlagEmbedding import BGEM3FlagModel
    except ImportError as e:
        raise RuntimeError(
            "未安装 FlagEmbedding。请先执行：pip install -U FlagEmbedding"
        ) from e

    device = _resolve_device()
    use_fp16 = EMBEDDING_USE_FP16 and device.startswith("cuda")

    print(
        f"[embeddings] loading BGE-M3 model from={model_path}, "
        f"requested_device={EMBEDDING_DEVICE}, actual_device={device}, "
        f"fp16={use_fp16}, cuda_available={torch.cuda.is_available()}",
        flush=True
    )

    if torch.cuda.is_available():
        try:
            visible = os.getenv("CUDA_VISIBLE_DEVICES", "")
            count = torch.cuda.device_count()
            names = [torch.cuda.get_device_name(i) for i in range(count)]
            print(
                f"[embeddings] CUDA_VISIBLE_DEVICES={visible}, "
                f"gpu_count={count}, gpu_names={names}",
                flush=True
            )
        except Exception as e:
            print(f"[embeddings] failed to inspect cuda devices: {e}", flush=True)

    _embedding_model = BGEM3FlagModel(
        model_path,
        use_fp16=use_fp16,
        device=device,
    )
    _embedding_runtime_device = device
    return _embedding_model


def embed_texts(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []

    model = get_embedding_model()
    cleaned = [(t or "").strip() for t in texts]

    print(
        f"[embeddings] encoding texts count={len(cleaned)}, "
        f"batch_size={EMBEDDING_BATCH_SIZE}, max_length={EMBEDDING_MAX_LENGTH}, "
        f"device={_embedding_runtime_device}",
        flush=True
    )

    result = model.encode(
        cleaned,
        batch_size=EMBEDDING_BATCH_SIZE,
        max_length=EMBEDDING_MAX_LENGTH,
    )

    dense_vecs = result["dense_vecs"]
    return dense_vecs.tolist() if hasattr(dense_vecs, "tolist") else [list(v) for v in dense_vecs]


def embed_query(text: str) -> List[float]:
    model = get_embedding_model()
    cleaned = (text or "").strip()

    result = model.encode(
        [cleaned],
        batch_size=1,
        max_length=EMBEDDING_MAX_LENGTH,
    )

    dense_vec = result["dense_vecs"][0]
    return dense_vec.tolist() if hasattr(dense_vec, "tolist") else list(dense_vec)
