from __future__ import annotations

import importlib
import os
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse

from competition_authz import require_business_access
from competition_runtime import (
    BUSINESS_ROUTER_IMPORTS,
    CORE_ROUTER_IMPORTS,
    resolve_frontend_file,
)
from route_integrity import assert_unique_routes


def build_app() -> FastAPI:
    app = FastAPI(
        title="LMateLab 107 Cup",
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )

    api_router = APIRouter(prefix="/api")
    for module_name, router_name in CORE_ROUTER_IMPORTS:
        module = importlib.import_module(module_name)
        api_router.include_router(getattr(module, router_name))

    business_router = APIRouter(dependencies=[Depends(require_business_access)])
    for module_name, router_name in BUSINESS_ROUTER_IMPORTS:
        module = importlib.import_module(module_name)
        business_router.include_router(getattr(module, router_name))
    api_router.include_router(business_router)
    app.include_router(api_router)
    assert_unique_routes(app)

    frontend_root = Path(os.environ["LMATELAB_FRONTEND_DIST"]).resolve()
    if not (frontend_root / "index.html").is_file():
        raise RuntimeError(f"frontend release is missing: {frontend_root / 'index.html'}")

    @app.get("/{request_path:path}", include_in_schema=False)
    def frontend(request_path: str):
        try:
            response_path = resolve_frontend_file(frontend_root, request_path)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid path") from exc
        return FileResponse(response_path)

    return app


app = build_app()
