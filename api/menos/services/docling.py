"""Docling HTTP client for web content extraction."""

from dataclasses import dataclass

import httpx
from fastapi import HTTPException


@dataclass
class DoclingResult:
    """Extracted markdown content from Docling."""

    markdown: str
    title: str | None = None


class DoclingClient:
    """Client for Docling source conversion API."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def extract_markdown(self, url: str) -> DoclingResult:
        """Extract markdown from a source URL via Docling."""
        payload = {
            "sources": [{"kind": "http", "url": url}],
            "options": {"to_formats": ["md"], "image_export_mode": "placeholder"},
        }

        endpoint = f"{self.base_url}/v1/convert/source"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=503, detail="Docling service unavailable") from exc

        markdown = _extract_markdown(data)
        if not markdown:
            raise HTTPException(status_code=503, detail="Docling returned no markdown")

        title = _extract_title(data) or _extract_title_from_markdown(markdown)
        return DoclingResult(markdown=markdown, title=title)


def _extract_markdown(data: object) -> str | None:
    if isinstance(data, str):
        return data

    if isinstance(data, list):
        for item in data:
            markdown = _extract_markdown(item)
            if markdown:
                return markdown
        return None

    if not isinstance(data, dict):
        return None

    markdown = data.get("markdown") or data.get("md") or data.get("md_content")
    if isinstance(markdown, str) and markdown.strip():
        return markdown

    if "result" in data:
        nested = _extract_markdown(data["result"])
        if nested:
            return nested

    for key in ("document", "documents", "output", "outputs", "data"):
        if key in data:
            nested = _extract_markdown(data[key])
            if nested:
                return nested

    return None


def _extract_title(data: object) -> str | None:
    if isinstance(data, list):
        for item in data:
            title = _extract_title(item)
            if title:
                return title
        return None

    if not isinstance(data, dict):
        return None

    title = data.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()

    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        nested_title = metadata.get("title")
        if isinstance(nested_title, str) and nested_title.strip():
            return nested_title.strip()

    for key in ("result", "document", "documents", "output", "outputs", "data"):
        if key in data:
            nested = _extract_title(data[key])
            if nested:
                return nested

    return None


def _extract_title_from_markdown(markdown: str) -> str | None:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or None
    return None
