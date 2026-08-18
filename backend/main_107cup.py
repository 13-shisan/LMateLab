from __future__ import annotations

import asyncio
import importlib
import logging
import os
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse

from competition_authz import require_business_access
from competition_runtime import (
    BUSINESS_ROUTER_IMPORTS,
    CORE_ROUTER_IMPORTS,
    coordinator_batch_limit,
    coordinator_enabled as runtime_coordinator_enabled,
    coordinator_interval_seconds,
    resolve_frontend_file,
    slurm_probe_script,
    slurm_user,
    vasp_stage_script,
    workflow_root,
)
from database import SessionLocal
from route_integrity import assert_unique_routes
from services.competition_coordinator import CompetitionCoordinator
from services.competition_reconcile import CompetitionReconciler
from services.competition_slurm import SlurmClient


logger = logging.getLogger(__name__)


def coordinator_sleep_seconds(
    *,
    interval_seconds: float,
    started: float,
    finished: float,
) -> float:
    return max(0.0, interval_seconds - (finished - started))


def build_production_coordinator(
    environ: Mapping[str, str] | None = None,
) -> CompetitionCoordinator:
    root = workflow_root(environ)
    probe_script = slurm_probe_script(environ)
    stage_script = vasp_stage_script(environ)
    slurm = SlurmClient(
        workflow_root=root,
        allowed_scripts=(probe_script, stage_script),
    )
    reconciler = CompetitionReconciler(
        slurm=slurm,
        probe_script=probe_script,
        vasp_script=stage_script,
        slurm_user=slurm_user(environ),
    )
    return CompetitionCoordinator(
        session_factory=SessionLocal,
        reconciler=reconciler,
        workflow_root=root,
        vasp_script=stage_script,
        batch_limit=coordinator_batch_limit(environ),
    )


async def coordinator_loop(coordinator: Any, interval_seconds: float) -> None:
    try:
        while True:
            loop = asyncio.get_running_loop()
            started = loop.time()
            tick_task = asyncio.create_task(
                asyncio.to_thread(coordinator.tick_once),
                name="lmatelab-competition-coordinator-tick",
            )
            try:
                await asyncio.shield(tick_task)
            except asyncio.CancelledError:
                while not tick_task.done():
                    try:
                        await asyncio.shield(tick_task)
                    except asyncio.CancelledError:
                        continue
                try:
                    tick_task.result()
                except Exception:
                    logger.error("competition coordinator tick failed")
                raise
            except Exception:
                logger.error("competition coordinator tick failed")
            await asyncio.sleep(
                coordinator_sleep_seconds(
                    interval_seconds=interval_seconds,
                    started=started,
                    finished=loop.time(),
                )
            )
    except asyncio.CancelledError:
        raise
    finally:
        close = getattr(coordinator, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                logger.error("competition coordinator close failed")


def build_app(
    *,
    coordinator_factory: Callable[[], Any] | None = None,
    coordinator_enabled: bool | None = None,
    coordinator_interval: float | None = None,
) -> FastAPI:
    enabled = (
        runtime_coordinator_enabled()
        if coordinator_enabled is None
        else coordinator_enabled
    )
    interval = (
        coordinator_interval_seconds()
        if coordinator_interval is None
        else float(coordinator_interval)
    )
    factory = coordinator_factory or build_production_coordinator

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not enabled:
            yield
            return

        coordinator = factory()
        task = asyncio.create_task(
            coordinator_loop(coordinator, interval),
            name="lmatelab-competition-coordinator",
        )
        app.state.coordinator_task = task
        await asyncio.sleep(0)
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            app.state.coordinator_task = None

    app = FastAPI(
        title="LMateLab 107 Cup",
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.coordinator_task = None

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
