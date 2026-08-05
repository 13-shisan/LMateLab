# routers/notes.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import Note, User
from schemas import NoteCreate, NoteOut
from auth import get_current_user
from datetime import datetime

router = APIRouter(prefix="/notes", tags=["notes"])


@router.get("/", response_model=list[NoteOut])
def list_notes(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notes = (
        db.query(Note)
        .filter(Note.author_id == current_user.id)
        .order_by(Note.created_at.desc())
        .all()
    )
    return notes


@router.post("/", response_model=NoteOut)
def create_note(
    note_in: NoteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.utcnow()
    note = Note(
        project_id=note_in.project_id,
        title=note_in.title,
        content=note_in.content or "",
        author_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note
