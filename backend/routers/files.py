# routers/files.py
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from database import get_db
from models import FileRecord, User
from schemas import FileOut
from auth import get_current_user
from datetime import datetime
import os
import uuid
import shutil
from pathlib import Path

router = APIRouter(prefix="/files", tags=["files"])

DATA_DIR = Path(os.getenv("LMATELAB_DATA_DIR", "/app/var")).resolve()
UPLOAD_DIR = Path(os.getenv("UPLOADS_ROOT", str(DATA_DIR / "uploads"))).resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/upload", response_model=FileOut)
def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    original_name = (file.filename or "").strip()
    if not original_name:
        raise HTTPException(status_code=400, detail="filename is required")

    # 生成唯一文件名
    ext = os.path.splitext(original_name)[1]
    unique_name = f"{uuid.uuid4().hex}{ext}"
    save_path = UPLOAD_DIR / unique_name

    first_chunk = file.file.read(1024 * 1024)
    if not first_chunk:
        raise HTTPException(status_code=400, detail="file content is empty")

    with save_path.open("wb") as f:
        f.write(first_chunk)
        shutil.copyfileobj(file.file, f)

    rec = FileRecord(
        filename=unique_name,
        original_name=original_name,
        uploader_id=current_user.id,
        created_at=datetime.utcnow(),
    )
    try:
        db.add(rec)
        db.commit()
        db.refresh(rec)
    except Exception:
        db.rollback()
        try:
            if save_path.exists():
                save_path.unlink()
        except Exception:
            pass
        raise
    return rec


@router.get("/", response_model=list[FileOut])
def list_files(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    files = (
        db.query(FileRecord)
        .filter(FileRecord.uploader_id == current_user.id)
        .order_by(FileRecord.created_at.desc())
        .all()
    )
    return files


@router.get("/{file_id}/download")
def download_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rec = db.query(FileRecord).filter(FileRecord.id == file_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="file not found")

    if rec.uploader_id != current_user.id and getattr(current_user, "role", None) not in {"root", "admin"}:
        raise HTTPException(status_code=403, detail="forbidden")

    file_path = UPLOAD_DIR / rec.filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="file content not found")

    return FileResponse(
        path=str(file_path),
        filename=rec.original_name,
        media_type="application/octet-stream",
    )
