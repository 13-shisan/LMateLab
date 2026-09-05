from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from competition_authz import require_operator, require_viewer_or_operator
from database import get_db
from models import User
from models_competition_agent import AgentRun
from schemas_competition_agent import (
    AgentRunCreate,
    AgentRunView,
    AgentSettingsUpdate,
    CuratedStructureBuildRequest,
    LiteratureIndexRequest,
)
from services.competition_agent.catalog import list_templates
from services.competition_agent.llm_runtime import llm_configured
from services.competition_agent.examples import ExampleBundleError, build_example_bundle, list_examples
from services.competition_agent.literature import (
    LiteratureError,
    index_record,
    list_records,
    search_openalex,
)
from services.qoder_management import (
    QoderManagementError,
    install_qoder,
    management_enabled,
    qoder_status,
    start_login,
    start_service,
    stop_service,
)
from services.competition_agent.settings import read_settings, write_api_key, write_settings
from services.competition_agent.structure_library import StructureLibraryError, search_structures
from services.competition_agent.service import approve_run, create_run, delete_conversation, run_view
from services.competition_agent.structures import (
    StructureBuildError,
    build_structure,
    build_structure_bundle,
    list_structure_catalog,
)
from services.competition_agent.tools import AgentToolError
from services.competition_agent.uploads import (
    AgentUploadError,
    MAX_AGENT_FILE_BYTES,
    calculation_views,
    list_uploads,
    store_upload,
    upload_view,
)


router = APIRouter(prefix="/competition/agent", tags=["competition-agent"])


def require_agent_enabled() -> None:
    if os.environ.get("LMATELAB_COMPETITION_AGENT_ENABLED", "0") != "1":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")


@router.get("/runtime", dependencies=[Depends(require_agent_enabled)])
def runtime_status(_user: User = Depends(require_viewer_or_operator)):
    provider = os.environ.get("LMATELAB_COMPETITION_AGENT_PROVIDER", "mock")
    auth_mode = os.environ.get("LMATELAB_QODER_AUTH_MODE", "pat")
    llm_key_configured = llm_configured()
    managed_qoder = qoder_status() if management_enabled() else None
    qoder_connected = (
        bool(managed_qoder["authenticated"])
        if managed_qoder is not None
        else os.environ.get("LMATELAB_QODER_CONNECTED", "0") == "1"
    )
    return {
        "provider": provider,
        "auth_mode": auth_mode if provider == "qoder" else None,
        "connected": llm_key_configured if provider == "llm" else (
            provider == "qoder" and qoder_connected
        ),
        "qoder_available": qoder_connected,
        "qoder": {
            "interface": "qoder-agent-sdk",
            "enabled": provider == "qoder",
            "connected": qoder_connected,
            "auth_mode": auth_mode,
            "model": os.environ.get("LMATELAB_QODER_MODEL") or None,
            **(managed_qoder or {}),
        },
    }


def _qoder_action(action):
    try:
        return action()
    except QoderManagementError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.post("/qoder/install", dependencies=[Depends(require_agent_enabled)])
def install_qoder_endpoint(_user: User = Depends(require_operator)):
    return _qoder_action(install_qoder)


@router.post("/qoder/login", dependencies=[Depends(require_agent_enabled)])
def login_qoder_endpoint(_user: User = Depends(require_operator)):
    return _qoder_action(start_login)


@router.post("/qoder/service/start", dependencies=[Depends(require_agent_enabled)])
def start_qoder_service_endpoint(_user: User = Depends(require_operator)):
    return _qoder_action(start_service)


@router.post("/qoder/service/stop", dependencies=[Depends(require_agent_enabled)])
def stop_qoder_service_endpoint(_user: User = Depends(require_operator)):
    return _qoder_action(stop_service)


@router.get("/settings", dependencies=[Depends(require_agent_enabled)])
def agent_settings(_user: User = Depends(require_operator)):
    return {**read_settings(), "api_key_configured": llm_configured()}


@router.put("/settings", dependencies=[Depends(require_agent_enabled)])
def update_agent_settings(
    payload: AgentSettingsUpdate,
    request: Request,
    _user: User = Depends(require_operator),
):
    try:
        if payload.api_key:
            client_host = request.client.host if request.client else ""
            if request.url.scheme != "https" and client_host not in {"127.0.0.1", "::1"}:
                raise HTTPException(status_code=400, detail="API key requires HTTPS or loopback access")
        write_settings(payload.api_url, payload.model)
        if payload.api_key:
            write_api_key(payload.api_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return {**read_settings(), "api_key_configured": llm_configured()}


@router.get("/library/structures", dependencies=[Depends(require_agent_enabled)])
def structure_library(
    query: str = Query("", max_length=100),
    limit: int = Query(30, ge=1, le=100),
    _user: User = Depends(require_viewer_or_operator),
):
    return search_structures(query, limit)


@router.get("/files", dependencies=[Depends(require_agent_enabled)])
def agent_files(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator),
):
    rows = list_uploads(db, current_user.id)
    return {
        "items": [upload_view(row) for row in rows],
        "calculations": calculation_views(rows),
    }


@router.get("/examples", dependencies=[Depends(require_agent_enabled)])
def agent_examples(_user: User = Depends(require_viewer_or_operator)):
    return {"items": list_examples()}


@router.get("/examples/{example_id}/bundle", dependencies=[Depends(require_agent_enabled)])
def download_agent_example(
    example_id: str,
    _user: User = Depends(require_viewer_or_operator),
):
    try:
        content = build_example_bundle(example_id)
    except ExampleBundleError as exc:
        raise HTTPException(status_code=404, detail="not found") from exc
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{example_id}.zip"'},
    )


@router.post("/files", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_agent_enabled)])
async def upload_agent_file(
    file: UploadFile = File(...),
    category: str = Form("result"),
    library_name: str = Form("我的文献库"),
    calculation_id: str | None = Form(None),
    group_name: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator),
):
    try:
        content = await file.read(MAX_AGENT_FILE_BYTES + 1)
        return upload_view(store_upload(
            db,
            current_user.id,
            file.filename or "",
            content,
            category=category,
            library_name=library_name,
            calculation_id=calculation_id,
            group_name=group_name,
        ))
    except AgentUploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    finally:
        await file.close()


@router.get("/literature", dependencies=[Depends(require_agent_enabled)])
def literature_library(
    query: str = Query("", max_length=300),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator),
):
    indexed = list_records(current_user.id, query)
    uploaded = [
        upload_view(row)
        for row in list_uploads(db, current_user.id)
        if upload_view(row)["category"] == "literature"
    ]
    return {"items": indexed, "uploads": uploaded}


@router.get("/literature/search", dependencies=[Depends(require_agent_enabled)])
def search_literature(
    query: str = Query(..., min_length=2, max_length=300),
    limit: int = Query(10, ge=1, le=20),
    _user: User = Depends(require_operator),
):
    try:
        return {"items": search_openalex(query, limit), "source": "OpenAlex"}
    except LiteratureError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.post("/literature/index", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_agent_enabled)])
def add_literature_index(
    payload: LiteratureIndexRequest,
    current_user: User = Depends(require_operator),
):
    try:
        return index_record(current_user.id, payload.model_dump())
    except LiteratureError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/templates", dependencies=[Depends(require_agent_enabled)])
def templates(_user: User = Depends(require_viewer_or_operator)):
    return {"items": list_templates()}


@router.get("/structures", dependencies=[Depends(require_agent_enabled)])
def structures(_user: User = Depends(require_viewer_or_operator)):
    return {"items": list_structure_catalog()}


def _structure_parameters(payload: CuratedStructureBuildRequest) -> dict[str, object]:
    return payload.model_dump(mode="python")


@router.post("/structures/build", dependencies=[Depends(require_agent_enabled)])
def build_curated_structure(
    payload: CuratedStructureBuildRequest,
    _user: User = Depends(require_operator),
):
    try:
        return build_structure(**_structure_parameters(payload))
    except StructureBuildError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/structures/bundle", dependencies=[Depends(require_agent_enabled)])
def download_curated_structure_bundle(
    payload: CuratedStructureBuildRequest,
    _user: User = Depends(require_operator),
):
    try:
        content = build_structure_bundle(**_structure_parameters(payload))
    except StructureBuildError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{payload.material_id}-vasp-inputs.zip"'
            )
        },
    )


@router.post(
    "/runs",
    response_model=AgentRunView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_agent_enabled)],
)
def create_agent_run(
    payload: AgentRunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator),
):
    try:
        return run_view(create_run(db, current_user.id, payload))
    except (AgentToolError, AgentUploadError, LiteratureError, StructureLibraryError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found") from exc


def _visible_run(db: Session, run_id: str, user: User) -> AgentRun:
    query = select(AgentRun).where(AgentRun.id == run_id)
    if user.role == "operator":
        query = query.where(AgentRun.owner_id == user.id)
    else:
        query = query.where(AgentRun.approved_at.is_not(None))
    run = db.scalar(query)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return run


@router.get(
    "/runs/{run_id}",
    response_model=AgentRunView,
    dependencies=[Depends(require_agent_enabled)],
)
def get_agent_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer_or_operator),
):
    return run_view(
        _visible_run(db, run_id, current_user),
        include_request=current_user.role == "operator",
    )


@router.get("/runs", dependencies=[Depends(require_agent_enabled)])
def list_agent_runs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer_or_operator),
):
    query = select(AgentRun)
    if current_user.role == "operator":
        query = query.where(AgentRun.owner_id == current_user.id)
    else:
        query = query.where(AgentRun.approved_at.is_not(None))
    rows = list(db.scalars(query.order_by(AgentRun.created_at.desc()).limit(50)))
    return {
        "items": [
            run_view(row, include_request=current_user.role == "operator")
            for row in rows
        ]
    }


@router.delete(
    "/runs/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_agent_enabled)],
)
def remove_agent_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator),
):
    try:
        parsed = str(uuid.UUID(conversation_id))
        deleted = delete_conversation(db, current_user.id, parsed)
    except (AttributeError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="conversation cannot be deleted") from exc
    if deleted == 0:
        raise HTTPException(status_code=404, detail="not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/runs/{run_id}/approve",
    response_model=AgentRunView,
    dependencies=[Depends(require_agent_enabled)],
)
def approve_agent_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator),
):
    run = _visible_run(db, run_id, current_user)
    try:
        return run_view(approve_run(db, run, current_user.id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="run is not complete") from exc
