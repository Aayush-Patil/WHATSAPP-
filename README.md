# ForwardCheck

ForwardCheck is an isolated prototype for checking claims in forwarded messages, screenshots, voice notes, PDFs, and URLs. It keeps verdicts tied to retrieved evidence. GenAI is optional and only drafts claim lists and explanations; it does not assign verdicts.

## Run locally

```powershell
cd whatsapp-forward-checker
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. The base app works without API keys. For PDFs, install the listed PDF extra. For image OCR, install Tesseract OCR and `pytesseract`. Voice transcription uses the configured server-side OpenAI API key. Web search uses a server-side Brave Search API key. Optional local NLI uses the `nli` extra and downloads the configured model on first use.

## Configuration

Copy `.env.example` to `.env`. GenAI and web search are off by default. Set `GENAI_ENABLED=true` and `OPENAI_API_KEY` to enable structured claim extraction and grounded explanations. Set `WEB_SEARCH_ENABLED=true` and `BRAVE_SEARCH_API_KEY` to enable web search. `NLI_ENABLED=true` enables the local DeBERTa MNLI verifier. Without a verifier, the app returns `cannot_confirm` rather than guessing.

Secrets belong in the server environment only. Do not put API keys in browser code. Uploaded material is processed for the request and is not stored by the app.

## Evidence and verdicts

The API returns each claim, its status, short explanation, evidence source IDs, and source excerpts/URLs. Statuses are `verified`, `false`, `partly_supported`, `outdated`, and `cannot_confirm`. Conflicting evidence is reported as `cannot_confirm` with a conflict reason. The app labels AI-written explanations and validates that their evidence IDs came from retrieved sources. If extraction, search, the model, or structured output fails, deterministic fallbacks stay available.

This prototype is not a substitute for professional medical, legal, or emergency advice. Search results and model outputs need human review, especially for high-impact claims.

## Checks

Run the deterministic checks with:

```powershell
python -m unittest discover -s tests -v
```

They exercise status mapping with fixed evidence-classifier scores. They do not contact external APIs or validate the live NLI/GenAI services.
