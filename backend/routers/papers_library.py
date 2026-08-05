# backend/routers/papers_library.py

from fastapi import APIRouter, HTTPException, Query, Depends
from auth import get_current_user
from models import User
from services.papers_library.service import PapersLibraryService
from services.papers_library.schemas import (
    PaperSearchResponse,
    PaperDetailResponse,
    PaperTopicItem,
    PaperJournalItem,
    TaxonomyNode,
)
from typing import List

router = APIRouter(prefix="/papers-library", tags=["papers-library"])

service = PapersLibraryService()


@router.get("/topics", response_model=List[PaperTopicItem])
def get_topics(current_user: User = Depends(get_current_user)):
    return service.get_topics()


@router.get("/journals", response_model=List[PaperJournalItem])
def get_journals(
    taxonomy_path: str | None = Query(None),
    current_user: User = Depends(get_current_user),
):
    return service.get_journals(taxonomy_path=taxonomy_path)


@router.get("/taxonomy", response_model=List[TaxonomyNode])
def get_taxonomy(current_user: User = Depends(get_current_user)):
    return service.get_taxonomy()


@router.get("/search", response_model=PaperSearchResponse)
def search_papers(
    q: str = Query(""),
    taxonomy_path: str | None = Query(None),
    journal: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
):
    return PaperSearchResponse(
        **service.search(q=q, taxonomy_path=taxonomy_path, journal=journal, limit=limit)
    )


@router.get("/item/{paper_id}", response_model=PaperDetailResponse)
def get_paper_detail(paper_id: str, current_user: User = Depends(get_current_user)):
    try:
        return PaperDetailResponse(**service.get_detail(paper_id))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
