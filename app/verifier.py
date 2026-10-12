from __future__ import annotations

import re
from dataclasses import dataclass

from .config import settings
from .schemas import Evidence
from .providers import source_is_explicitly_outdated


@dataclass(frozen=True)
class Scores:
    support: float = 0.0
    contradiction: float = 0.0
    neutral: float = 1.0


def decide_verdict(scores: list[Scores], evidence: list[Evidence]) -> tuple[str, str | None]:
    """Map evidence/claim NLI scores to a cautious user-facing status."""
    evidence = [item for item in evidence if item.trusted]
    if not scores or not evidence:
        return "cannot_confirm", "no_usable_evidence"
    support = max(item.support for item in scores)
    contradiction = max(item.contradiction for item in scores)
    if source_is_explicitly_outdated(evidence) and support >= 0.45:
        return "outdated", "source_explicitly_marks_information_out_of_date"
    if support >= settings.nli_support_threshold and contradiction >= settings.nli_contradiction_threshold:
        if abs(support - contradiction) < 0.15:
            return "cannot_confirm", "conflicting_sources"
    if support >= settings.nli_support_threshold and support > contradiction + 0.1:
        return "verified", None
    if contradiction >= settings.nli_contradiction_threshold and contradiction > support + 0.1:
        return "false", None
    if max(support, contradiction) >= 0.45:
        return "partly_supported", "evidence_support_is_incomplete"
    return "cannot_confirm", "evidence_did_not_settle_the_claim"


def _token_set(text: str) -> set[str]:
    return {word for word in re.findall(r"[\w']+", text.lower()) if len(word) > 2}


def rank_evidence(claim: str, evidence: list[Evidence], limit: int = 5) -> list[Evidence]:
    claim_words = _token_set(claim)
    if not claim_words:
        return []
    evidence = [item for item in evidence if item.trusted]
    ranked = sorted(
        evidence,
        key=lambda item: len(claim_words & _token_set(item.title + " " + item.excerpt)) / len(claim_words),
        reverse=True,
    )
    return [item for item in ranked[:limit] if claim_words & _token_set(item.title + " " + item.excerpt)]


class LocalNLI:
    def __init__(self) -> None:
        self._pipeline = None
        self._error: str | None = None

    def _load(self) -> None:
        if self._pipeline is not None or self._error is not None:
            return
        if not settings.nli_enabled:
            self._error = "disabled"
            return
        try:
            from transformers import pipeline

            self._pipeline = pipeline("text-classification", model=settings.nli_model, top_k=None)
        except Exception as exc:
            self._error = type(exc).__name__

    @property
    def available(self) -> bool:
        self._load()
        return self._pipeline is not None

    def score_pair(self, claim: str, evidence: Evidence) -> Scores | None:
        self._load()
        if self._pipeline is None:
            return None
        premise = evidence.excerpt[:1800]
        try:
            raw = self._pipeline({"text": premise, "text_pair": claim})
            if raw and isinstance(raw[0], list):
                raw = raw[0]
            values = {str(item.get("label", "")).lower(): float(item.get("score", 0)) for item in raw}
            support = next((v for k, v in values.items() if "entail" in k or "support" in k), 0.0)
            contradiction = next((v for k, v in values.items() if "contrad" in k), 0.0)
            neutral = next((v for k, v in values.items() if "neutral" in k), 0.0)
            return Scores(support, contradiction, neutral)
        except Exception:
            return None

    @property
    def error(self) -> str | None:
        self._load()
        return self._error


nli = LocalNLI()

