from __future__ import annotations

from pydantic import BaseModel
from typing import List, Optional


class PaperItem(BaseModel):
    id: str
    title: str
    journal: str
    journal_slug: Optional[str] = None
    year: Optional[int] = None
    taxonomy_path: List[str] = []
    main_topic: Optional[str] = None
    leaf_topic: Optional[str] = None
    abstract: Optional[str] = None
    summary: Optional[str] = None
    doi: Optional[str] = None
    authors: List[str] = []
    keywords: List[str] = []
    source_pdf: Optional[str] = None
    md_path: Optional[str] = None


class PaperSearchResponse(BaseModel):
    items: List[PaperItem]
    total: int


class PaperTopicItem(BaseModel):
    key: str
    label: str


class PaperJournalItem(BaseModel):
    journal: str
    slug: str
    count: int


class TaxonomyNode(BaseModel):
    label: str
    path: List[str]
    count: int
    children: List["TaxonomyNode"] = []


class PaperDetailResponse(BaseModel):
    item: PaperItem
    content: str


TaxonomyNode.model_rebuild()
