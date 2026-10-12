from __future__ import annotations

import asyncio
import re
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .extractors import extract_upload, url_evidence
from .providers import draft_explanation, extract_claims, search_evidence
from .schemas import AuditResponse, ClaimResult, Evidence
from .verifier import decide_verdict, nli, rank_evidence

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="ForwardCheck", description="Evidence-grounded claim checking for forwarded content")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
async def home() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/health")
async def health() -> dict[str, bool | str]:
    return {"status": "ok", "genai_enabled": settings.genai_enabled and bool(settings.openai_api_key), "web_search_enabled": settings.web_search_enabled and bool(settings.brave_search_api_key), "nli_enabled": settings.nli_enabled}


def _urls_from_form(urls: str, extracted_text: str) -> list[str]:
    candidates = [*re.split(r"[\s,]+", urls), *re.findall(r"https?://[^\s<>\"']+", extracted_text)]
    result: list[str] = []
    for candidate in candidates:
        value = candidate.strip().rstrip(".,;:!?)]}")
        if value.startswith(("http://", "https://")) and value not in result:
            result.append(value)
        if len(result) >= 5:
            break
    return result


async def _source_from_text(text: str) -> Evidence:
    return Evidence(id="source_context", title="Source text supplied by the user", url="", publisher="User-provided text", excerpt=text[:1800])


def _fallback_explanation(verdict: str, reason: str | None, evidence: list[Evidence]) -> str:
    if verdict == "verified":
        return "The available evidence supports this claim. Review the linked sources to see what they say."
    if verdict == "false":
        return "The available evidence conflicts with this claim. Review the linked sources for the correction."
    if verdict == "partly_supported":
        return "Some evidence matches this claim, but it does not support the full statement. Check the source details."
    if verdict == "outdated":
        return "A source says this information has expired or been replaced. Check the source for the current status."
    if reason == "conflicting_sources":
        return "The sources disagree, so this check cannot settle the claim. Compare the sources before sharing it."
    if not evidence:
        return "No relevant reliable source was found for this claim, so it cannot be confirmed yet."
    return "The available sources do not establish whether this claim is true. More reliable evidence is needed."


@app.post("/api/audits", response_model=AuditResponse)
async def audit(
    message: str = Form(""),
    source_text: str = Form(""),
    urls: str = Form(""),
    language: str = Form("English"),
    consent: bool = Form(False),
    enable_web_search: bool = Form(False),
    files: list[UploadFile] = File(default=[]),
) -> AuditResponse:
    if not consent:
        raise HTTPException(status_code=400, detail="Please confirm that you have permission to submit this content for checking.")
    if len(files) > settings.max_files:
        raise HTTPException(status_code=413, detail=f"Upload no more than {settings.max_files} files at once.")

    chunks = [message.strip()] if message.strip() else []
    warnings: list[str] = []
    total_bytes = 0
    for upload in files:
        data = await upload.read(settings.max_upload_mb * 1024 * 1024 + 1)
        total_bytes += len(data)
        if len(data) > settings.max_upload_mb * 1024 * 1024 or total_bytes > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"Files must total no more than {settings.max_upload_mb} MB.")
        try:
            text, label = await extract_upload(upload, data)
            if text.strip():
                chunks.append(text.strip())
            else:
                warnings.append(f"No readable text was extracted from {upload.filename or 'an uploaded file'}.")
        except Exception as exc:
            warnings.append(str(exc))

    extracted_text = "\n\n".join(chunks)[:40_000]
    if not extracted_text:
        raise HTTPException(status_code=400, detail="Add a message or upload a supported file to check.")

    claim_basis = extracted_text or source_text.strip()
    claims, genai_claim_extraction_used = await extract_claims(claim_basis)
    if not claims:
        raise HTTPException(status_code=422, detail="No clear factual claims could be extracted. Try adding more context.")
    if settings.genai_enabled and settings.openai_api_key and not genai_claim_extraction_used:
        warnings.append("AI claim extraction was unavailable or invalid; sentence-based extraction was used instead.")

    evidence: list[Evidence] = []
    if source_text.strip():
        evidence.append(await _source_from_text(source_text.strip()))
        warnings.append("Pasted source text is shown as user-provided context and is excluded from verdicts until checked against a trusted publisher.")

    submitted_urls = _urls_from_form(urls, extracted_text)
    page_results = await asyncio.gather(
        *(url_evidence(url, f"url_{index + 1}") for index, url in enumerate(submitted_urls)),
        return_exceptions=True,
    )
    for url, result in zip(submitted_urls, page_results):
        if isinstance(result, Exception):
            host = urlparse(url).hostname or "link"
            warnings.append(f"Could not read {host}: {str(result)[:180]}")
        else:
            evidence.append(result)
            if not result.trusted:
                warnings.append(f"{result.publisher} is not in the configured trusted-source list; it is shown for context but excluded from verdicts.")

    do_search = enable_web_search and settings.web_search_enabled and bool(settings.brave_search_api_key)
    if enable_web_search and not do_search:
        warnings.append("Web search was requested but is not configured on this server.")
    if do_search:
        search_results = await asyncio.gather(
            *(search_evidence(claim, f"web_{claim_index}_") for claim_index, claim in enumerate(claims, 1)),
            return_exceptions=True,
        )
        for result in search_results:
            if isinstance(result, Exception):
                warnings.append(f"Web search was unavailable: {type(result).__name__}.")
            else:
                evidence.extend(result)

    # Deduplicate exact URLs and preserve a single stable evidence ID per source.
    unique_evidence: list[Evidence] = []
    seen_urls: set[str] = set()
    for item in evidence:
        key = item.url or f"text:{item.id}"
        if key not in seen_urls:
            seen_urls.add(key)
            unique_evidence.append(item)
    evidence = unique_evidence[:40]

    results: list[ClaimResult] = []
    genai_explanation_failed = False
    for claim in claims:
        relevant = rank_evidence(claim, evidence)
        scored = [nli.score_pair(claim, item) for item in relevant]
        pairs = [score for score in scored if score is not None]
        verdict, reason = decide_verdict(pairs, relevant) if pairs else ("cannot_confirm", "verifier_unavailable" if relevant else "no_usable_evidence")
        explanation = _fallback_explanation(verdict, reason, relevant)
        explanation_label = "Evidence-based explanation"
        evidence_ids = [item.id for item in relevant]
        try:
            ai_text, ai_ids = await draft_explanation(claim, verdict, relevant, language.strip()[:40] or "English")
            explanation = ai_text
            evidence_ids = ai_ids
            explanation_label = "AI-drafted explanation"
        except Exception:
            if settings.genai_enabled and settings.openai_api_key and relevant:
                genai_explanation_failed = True
        results.append(
            ClaimResult(
                claim=claim,
                verdict=verdict,
                explanation=explanation,
                explanation_label=explanation_label,
                evidence_ids=evidence_ids,
                reason=reason,
            )
        )

    if genai_explanation_failed:
        warnings.append("An AI explanation was unavailable or failed evidence validation; the evidence-based fallback is shown.")

    nli_available = nli.available
    if settings.nli_enabled and not nli_available:
        warnings.append("The local evidence verifier could not be loaded; claims without a working verifier are marked cannot confirm.")

    metadata = {
        "claim_extraction": "genai" if genai_claim_extraction_used else "sentence_split_fallback",
        "verifier": settings.nli_model if nli_available else "unavailable",
        "web_search_used": do_search,
        "genai_explanations_enabled": settings.genai_enabled and bool(settings.openai_api_key),
        "uploaded_files_processed": bool(files),
    }
    if language.strip().lower() not in {"english", "en"} and not (settings.genai_enabled and settings.openai_api_key):
        warnings.append("Translated explanations need server-side GenAI configuration; fallback explanations are currently in English.")
    return AuditResponse(claims=results, evidence=evidence, warnings=warnings, engine_metadata=metadata)

