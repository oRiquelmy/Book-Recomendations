from typing import Literal, Optional

from pydantic import BaseModel, Field


class BookResponse(BaseModel):
    id: str
    title: str
    authors: list[str]
    categories: list[str]
    page_count: Optional[int]
    published_year: Optional[int]
    description: str
    thumbnail: Optional[str]
    language: str
    provider: Literal["google_books", "open_library", "unknown"] = "unknown"
    work_id: Optional[str] = None
    edition_id: Optional[str] = None
    isbn_10: list[str] = Field(default_factory=list)
    isbn_13: list[str] = Field(default_factory=list)


class ScoredBook(BookResponse):
    score: float  # 0.0 a 1.0 - afinidade calibrada com a obra de referência
    score_components: dict[str, float] = Field(default_factory=dict)
    score_coverage: float = 0.0


class RecommendationResponse(BaseModel):
    reference: BookResponse
    recommendations: list[ScoredBook]


class AuthorResponse(BaseModel):
    id: str
    name: str
    alternate_names: list[str] = Field(default_factory=list)
    birth_date: Optional[str] = None
    top_work: Optional[str] = None
    work_count: int = 0
    top_subjects: list[str] = Field(default_factory=list)
