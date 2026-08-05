# tools/export_fastapi_routes.py
import json
import inspect
import sys
from pathlib import Path

# 让 Python 能从 backend 根目录 import（例如 main.py、app/、routers/ 等）
BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

def main():
    from main import app  # 现在应该能找到了

    out = []
    for r in app.routes:
        endpoint = getattr(r, "endpoint", None)
        methods = sorted(list(getattr(r, "methods", []) or []))

        if endpoint is None or not methods:
            continue

        if getattr(r, "path", "").startswith(("/openapi", "/docs", "/redoc")):
            continue

        mod = getattr(endpoint, "__module__", None)
        name = getattr(endpoint, "__name__", None)

        src_file = None
        src_line = None
        try:
            src_file = inspect.getsourcefile(endpoint)
            src_line = inspect.getsourcelines(endpoint)[1]
        except Exception:
            pass

        out.append({
            "path": getattr(r, "path", None),
            "name": getattr(r, "name", None),
            "methods": methods,
            "endpoint": f"{mod}.{name}" if mod and name else None,
            "source_file": str(Path(src_file).resolve()) if src_file else None,
            "source_line": src_line,
        })

    (BACKEND_ROOT / "artifacts").mkdir(exist_ok=True)
    with open(BACKEND_ROOT / "var" / "artifacts" / "backend_routes.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(out)} routes to artifacts/backend_routes.json")

if __name__ == "__main__":
    main()
