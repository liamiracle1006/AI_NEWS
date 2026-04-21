"""Pydantic data models shared across the pipeline."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

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
    action: Optional[str] = Field(None, description="What actually happened (2-3 sentences allowed)")
    numbers: List[str] = Field(default_factory=list, description="Figures, casualties, quantities")
    context: Optional[str] = Field(None, description="Background / why this is happening (one sentence)")
    key_quotes: List[str] = Field(
        default_factory=list,
        description='Most significant direct quotes, format: "[Person]: quote"',
    )
    source_claims_verbatim: List[str] = Field(
        default_factory=list,
        description="Official statements and attributed claims that cannot be independently verified",
    )


class ArticleFacts(BaseModel):
    """Facts bundled with provenance, ready for cross-reference."""
    article_url: str
    source_name: str
    bias_tag: str
    title: str
    published_at: Optional[datetime] = None
    facts: ExtractedFact


class Divergence(BaseModel):
    """One point on which narratives diverge across bias camps."""
    point: str = Field(description="What the camps disagree on (a short phrase)")
    camp_claims: dict[str, str] = Field(
        default_factory=dict,
        description="bias_tag -> that camp's framing/claim on this point",
    )
    observation: Optional[str] = Field(
        None, description="Analyst's one-line note on the pattern"
    )


class SourceRef(BaseModel):
    source_name: str
    bias_tag: str
    url: str
    title: str


class CrossReferenceResult(BaseModel):
    """Output of Prompt #2: consensus + divergences across bias camps."""
    topic: str
    generated_at: datetime
    sources_covered: List[SourceRef] = Field(default_factory=list)
    consensus_facts: List[str] = Field(default_factory=list)
    divergences: List[Divergence] = Field(default_factory=list)
    suspicious_gaps: List[str] = Field(
        default_factory=list,
        description="Facts asserted by only one camp that others would have"
                    " reason to mention if true.",
    )


class EntityEvent(BaseModel):
    """One political figure and their actions/status in a given analysis round."""
    canonical_name: str
    aliases: List[str] = Field(default_factory=list)
    position: Optional[str] = None
    action_or_status: str
    status_change: Optional[str] = None
    per_source_framing: Dict[str, str] = Field(default_factory=dict)
    sources: List[str] = Field(default_factory=list)


class EntityTrackingResult(BaseModel):
    """Output of Prompt #3: deduplicated political figures and their framing."""
    topic: str
    generated_at: datetime
    entities: List[EntityEvent] = Field(default_factory=list)
