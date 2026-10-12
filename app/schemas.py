from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal["verified", "false", "partly_supported", "outdated", "cannot_confirm"]


class Evidence(BaseModel):
    id: str
    title: str
    url: str
    publisher: str
    excerpt: str
    published_at: str | None = None
    trusted: bool = False


class ClaimResult(BaseModel):
    claim: str
    verdict: Verdict
    explanation: str
    explanation_label: Literal["Evidence-based explanation", "AI-drafted explanation"]
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str | None = None


class AuditResponse(BaseModel):
    claims: list[ClaimResult]
    evidence: list[Evidence]
    warnings: list[str] = Field(default_factory=list)
    engine_metadata: dict[str, str | bool] = Field(default_factory=dict)

