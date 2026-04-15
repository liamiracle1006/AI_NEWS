"""Pydantic data models shared across the pipeline."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Article(BaseModel):
    """A single raw article fetched from a source."""
    source_name: str
    bias_tag: str
    lang: str
    title: str
    url: str
    published_at: Optional[datetime] = None
    summary: Optional[str] = None     # RSS summary (may be HTML)
    body: Optional[str] = None        # Clean extracted body text


class ExtractedFact(BaseModel):
    """Result of Prompt #1: fact extraction / emotion stripping."""
    when: Optional[str] = Field(None, description="Time as stated in article")
    where: Optional[str] = None
    who: List[str] = Field(default_factory=list)
    action: Optional[str] = Field(None, description="What actually happened")
    numbers: List[str] = Field(default_factory=list, description="Figures, casualties, quantities")
    source_claims_verbatim: List[str] = Field(
        default_factory=list,
        description="Claims that look like opinions/attributions, not facts",
    )


class ArticleFacts(BaseModel):
    """Facts bundled with provenance, ready for cross-reference."""
    article_url: str
    source_name: str
    bias_tag: str
    facts: ExtractedFact
