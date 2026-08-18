from __future__ import annotations

import asyncio
import importlib
import logging
import os
import threading
import time
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
    coordinator_drain_timeout_seconds,
    coordinator_enabled as runtime_coordinator_enabled,
    coordinator_interval_seconds,
    resolve_frontend_file,
    slurm_probe_script,
    slurm_user,
    vasp_stage_script,
    validate_coordinator_drain_timeout_seconds,
    validate_coordinator_interval_seconds,
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


class CoordinatorWorker:
    def __init__(
        self,
        coordinator: Any,
        interval_seconds: float,
        *,
        wait_for_stop: Callable[[threading.Event, float], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._coordinator = coordinator
        self._interval_seconds = interval_seconds
        self._wait_for_stop = wait_for_stop or (
            lambda stop_event, seconds: stop_event.wait(seconds)
        )
        self._clock = clock
        self._stop = threading.Event()
        self._closed = threading.Event()
        self.thread = threading.Thread(
            target=self._run,
            name="lmatelab-competition-coordinator",
            daemon=True,
        )

    def start(self) -> None:
        self.thread.start()

    def request_stop(self) -> None:
        self._stop.set()

    def is_closed(self) -> bool:
        return self._closed.is_set()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                started = self._clock()
                try:
                    self._coordinator.tick_once()
                except Exception:
                    logger.error("competition coordinator tick failed")
                delay = coordinator_sleep_seconds(
                    interval_seconds=self._interval_seconds,
                    started=started,
                    finished=self._clock(),
                )
                if self._wait_for_stop(self._stop, delay):
                    break
        finally:
            close = getattr(self._coordinator, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.error("competition coordinator close failed")
            self._closed.set()


async def wait_for_coordinator_worker(
    worker: CoordinatorWorker,
    timeout_seconds: float,
) -> tuple[bool, bool]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    cancelled = False
    while not worker.is_closed():
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False, cancelled
        try:
            await asyncio.sleep(min(0.01, remaining))
        except asyncio.CancelledError:
            cancelled = True
    return True, cancelled


def _validated_runtime_value(
    value: float | None,
    *,
    load_default: Callable[[], float],
    validate: Callable[[object], float],
) -> float:
    return load_default() if value is None else validate(value)


def build_app(
    *,
    coordinator_factory: Callable[[], Any] | None = None,
    coordinator_enabled: bool | None = None,
    coordinator_interval: float | None = None,
    coordinator_drain_timeout: float | None = None,
    coordinator_wait: Callable[[threading.Event, float], bool] | None = None,
) -> FastAPI:
    enabled = (
        runtime_coordinator_enabled()
        if coordinator_enabled is None
        else coordinator_enabled
    )
    interval = _validated_runtime_value(
        coordinator_interval,
        load_default=coordinator_interval_seconds,
        validate=validate_coordinator_interval_seconds,
    )
    drain_timeout = _validated_runtime_value(
        coordinator_drain_timeout,
        load_default=coordinator_drain_timeout_seconds,
        validate=validate_coordinator_drain_timeout_seconds,
    )
    factory = coordinator_factory or build_production_coordinator

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not enabled:
            yield
            return

        existing_worker = app.state.coordinator_worker
        if existing_worker is not None:
            if not existing_worker.is_closed():
                logger.error(
                    "competition coordinator startup blocked by active worker"
                )
                raise RuntimeError(
                    "competition coordinator worker is still active"
                )
            if app.state.coordinator_worker is existing_worker:
                app.state.coordinator_worker = None

        worker = CoordinatorWorker(
            factory(),
            interval,
            wait_for_stop=coordinator_wait,
        )
        app.state.coordinator_worker = worker
        worker.start()
        try:
            yield
        finally:
            worker.request_stop()
            closed, cancelled = await wait_for_coordinator_worker(
                worker,
                drain_timeout,
            )
            if not closed:
                logger.error("competition coordinator drain timed out")
            elif app.state.coordinator_worker is worker:
                app.state.coordinator_worker = None
            app.state.coordinator_task = None
            if cancelled:
                raise asyncio.CancelledError

    app = FastAPI(
        title="LMateLab 107 Cup",
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.coordinator_task = None
    app.state.coordinator_worker = None

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
