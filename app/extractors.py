from __future__ import annotations

import io
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import UploadFile

from .config import settings
from .schemas import Evidence
from .providers import is_trusted_domain


class _PageText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self._in_title = False
        self._skip = 0
        self.published_at: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in {"script", "style", "noscript", "svg", "nav", "footer"}:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key in {"article:published_time", "datepublished", "date", "pubdate"}:
                self.published_at = values.get("content")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "nav", "footer"} and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "br", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        clean = " ".join(data.split())
        if not clean:
            return
        if self._in_title:
            self.title += clean
        elif not self._skip:
            self.parts.append(clean)

    @property
    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())


def _validate_public_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public http and https URLs are supported.")
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError("Private and local URLs are not allowed.")
    try:
        addresses = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if not ip.is_global:
                raise ValueError("Private and local URLs are not allowed.")
    except socket.gaierror as exc:
        raise ValueError("The URL host could not be resolved.") from exc
    return url


async def fetch_page(url: str, *, max_bytes: int = 1_500_000) -> tuple[str, str, str | None]:
    current = _validate_public_url(url)
    async with httpx.AsyncClient(timeout=12, follow_redirects=False, headers={"User-Agent": "ForwardCheck/0.1"}) as client:
        for _ in range(5):
            response = await client.get(current)
            if response.status_code in {301, 302, 303, 307, 308}:
                target = response.headers.get("location")
                if not target:
                    break
                current = _validate_public_url(urljoin(current, target))
                continue
            response.raise_for_status()
            raw = response.content[:max_bytes]
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                raise ValueError("The linked page is not an HTML or text page.")
            parser = _PageText()
            parser.feed(raw.decode(response.encoding or "utf-8", errors="replace"))
            return parser.title[:200] or current, parser.text[:30_000], parser.published_at
    raise ValueError("The URL redirected too many times.")


async def extract_upload(file: UploadFile, data: bytes) -> tuple[str, str]:
    name = file.filename or "uploaded file"
    suffix = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if suffix in {"txt", "md", "csv", "json"}:
        return data.decode("utf-8", errors="replace")[:40_000], f"Text extracted from {name}"
    if suffix == "pdf" or file.content_type == "application/pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("PDF extraction needs the optional pypdf package.") from exc
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join(page.extract_text() or "" for page in reader.pages[:50])
        return text[:40_000], f"Text extracted from {name}"
    if suffix in {"png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"} or (file.content_type or "").startswith("image/"):
        try:
            from PIL import Image
            import pytesseract
        except ImportError as exc:
            raise ValueError("Image OCR needs Pillow, pytesseract, and the Tesseract OCR program.") from exc
        image = Image.open(io.BytesIO(data))
        return pytesseract.image_to_string(image)[:40_000], f"OCR text from {name}"
    if suffix in {"mp3", "wav", "m4a", "ogg", "webm", "mp4"} or (file.content_type or "").startswith("audio/"):
        transcript = await transcribe_audio(name, file.content_type or "application/octet-stream", data)
        return transcript, f"Voice transcript from {name}"
    raise ValueError(f"Unsupported file type for {name}.")


async def transcribe_audio(name: str, content_type: str, data: bytes) -> str:
    if not settings.openai_api_key:
        raise ValueError("Voice transcription needs a server-side OPENAI_API_KEY.")
    async with httpx.AsyncClient(timeout=settings.openai_timeout_seconds) as client:
        response = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            data={"model": "gpt-4o-mini-transcribe"},
            files={"file": (name, data, content_type)},
        )
        response.raise_for_status()
        return str(response.json().get("text", ""))[:40_000]


async def url_evidence(url: str, evidence_id: str) -> Evidence:
    title, text, published_at = await fetch_page(url)
    host = urlparse(url).hostname or "user-provided URL"
    return Evidence(
        id=evidence_id,
        title=title,
        url=url,
        publisher=host,
        excerpt=text[:1800],
        published_at=published_at,
        trusted=is_trusted_domain(host),
    )
