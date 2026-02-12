"""URL detection service for GitHub repos, arXiv papers, DOIs, PyPI, and npm packages."""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse


@dataclass
class DetectedURL:
    """Represents a URL detected in content."""

    url: str
    url_type: str
    extracted_id: str


class URLDetector:
    """Detects and extracts information from various URL types."""

    # GitHub repository
    GITHUB_REPO_PATTERN = re.compile(
        r"https?://github\.com/([a-zA-Z0-9_-]+)/([a-zA-Z0-9_.-]+?)(?:\.git)?(?:/|\s|\)|\?|#|$)"
    )

    # arXiv
    ARXIV_PATTERN = re.compile(r"https?://arxiv\.org/abs/(\d{4}\.\d{4,5}(?:v\d+)?)")

    # DOI
    DOI_PATTERN = re.compile(r"https?://doi\.org/(10\.\d{4,}/[^\s<>\"]+?)(?:\s|<|>|\"|$)")

    # PyPI
    PYPI_PATTERN = re.compile(r"https?://pypi\.org/project/([a-zA-Z0-9_-]+)/?(?:\s|\)|\?|#|$)")

    # npm
    NPM_PATTERN = re.compile(
        r"https?://(?:www\.)?npmjs\.com/package/([@a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)?)/?(?:\s|\)|\?|#|$)"
    )

    YOUTUBE_WATCH_PATTERN = re.compile(r"(?:youtube\.com|m\.youtube\.com|www\.youtube\.com)")
    YOUTUBE_SHORT_PATTERN = re.compile(r"(?:youtu\.be)/([0-9A-Za-z_-]{11})")

    def detect_urls(self, text: str) -> list[DetectedURL]:
        """
        Detect all supported URLs in text.

        Args:
            text: The text content to scan for URLs

        Returns:
            List of detected URLs with their types and extracted IDs
        """
        detected: list[tuple[int, DetectedURL]] = []

        # Detect GitHub repos
        for match in self.GITHUB_REPO_PATTERN.finditer(text):
            owner = match.group(1)
            repo = match.group(2)
            matched_text = match.group(0).rstrip("/ \t\r\n?#)")
            protocol = "https" if matched_text.startswith("https") else "http"
            full_url = f"{protocol}://github.com/{owner}/{repo}"
            detected.append(
                (
                    match.start(),
                    DetectedURL(
                        url=full_url,
                        url_type="github_repo",
                        extracted_id=f"{owner}/{repo}",
                    ),
                )
            )

        # Detect arXiv papers
        for match in self.ARXIV_PATTERN.finditer(text):
            arxiv_id = match.group(1)
            full_url = match.group(0).rstrip(" \t\r\n)")
            detected.append(
                (
                    match.start(),
                    DetectedURL(
                        url=full_url,
                        url_type="arxiv",
                        extracted_id=arxiv_id,
                    ),
                )
            )

        # Detect DOIs
        for match in self.DOI_PATTERN.finditer(text):
            doi = match.group(1)
            matched_text = match.group(0)
            # Strip trailing whitespace, delimiters, and sentence-ending punctuation
            full_url = matched_text.rstrip(' \t\r\n<>".)')
            detected.append(
                (
                    match.start(),
                    DetectedURL(
                        url=full_url,
                        url_type="doi",
                        extracted_id=doi,
                    ),
                )
            )

        # Detect PyPI packages
        for match in self.PYPI_PATTERN.finditer(text):
            package = match.group(1)
            matched_text = match.group(0)
            protocol = "https" if matched_text.startswith("https") else "http"
            base_url = f"{protocol}://pypi.org/project/{package}"
            detected.append(
                (
                    match.start(),
                    DetectedURL(
                        url=base_url,
                        url_type="pypi",
                        extracted_id=package,
                    ),
                )
            )

        # Detect npm packages
        for match in self.NPM_PATTERN.finditer(text):
            package = match.group(1)
            matched_text = match.group(0)
            has_www = "www." in matched_text
            protocol = "https" if matched_text.startswith("https") else "http"
            www_part = "www." if has_www else ""
            base_url = f"{protocol}://{www_part}npmjs.com/package/{package}"
            detected.append(
                (
                    match.start(),
                    DetectedURL(
                        url=base_url,
                        url_type="npm",
                        extracted_id=package,
                    ),
                )
            )

        # Sort by position and return just the DetectedURL objects
        detected.sort(key=lambda x: x[0])
        return [url for _, url in detected]

    def detect_github_repos(self, text: str) -> list[DetectedURL]:
        """Detect only GitHub repository URLs."""
        all_urls = self.detect_urls(text)
        return [url for url in all_urls if url.url_type == "github_repo"]

    def detect_arxiv(self, text: str) -> list[DetectedURL]:
        """Detect only arXiv paper URLs."""
        all_urls = self.detect_urls(text)
        return [url for url in all_urls if url.url_type == "arxiv"]

    def detect_dois(self, text: str) -> list[DetectedURL]:
        """Detect only DOI URLs."""
        all_urls = self.detect_urls(text)
        return [url for url in all_urls if url.url_type == "doi"]

    def detect_pypi(self, text: str) -> list[DetectedURL]:
        """Detect only PyPI package URLs."""
        all_urls = self.detect_urls(text)
        return [url for url in all_urls if url.url_type == "pypi"]

    def detect_npm(self, text: str) -> list[DetectedURL]:
        """Detect only npm package URLs."""
        all_urls = self.detect_urls(text)
        return [url for url in all_urls if url.url_type == "npm"]

    def classify_url(self, url: str) -> DetectedURL:
        """Classify a single URL for ingest routing."""
        parsed = urlparse(url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return DetectedURL(url=url, url_type="unknown", extracted_id="")

        youtube_id = self._extract_youtube_id(parsed)
        if youtube_id:
            return DetectedURL(url=url, url_type="youtube", extracted_id=youtube_id)

        detected = self.detect_urls(url)
        if detected:
            return detected[0]

        return DetectedURL(url=url, url_type="web", extracted_id="")

    def _extract_youtube_id(self, parsed_url) -> str | None:
        netloc = (parsed_url.netloc or "").lower()
        path = parsed_url.path or ""

        short_match = self.YOUTUBE_SHORT_PATTERN.search(f"{netloc}{path}")
        if short_match:
            return short_match.group(1)

        if not self.YOUTUBE_WATCH_PATTERN.search(netloc):
            return None

        query = parse_qs(parsed_url.query)
        if "v" in query and query["v"]:
            video_id = query["v"][0]
            if re.fullmatch(r"[0-9A-Za-z_-]{11}", video_id):
                return video_id

        path_parts = [part for part in path.split("/") if part]
        if len(path_parts) >= 2 and path_parts[0] in {"shorts", "embed"}:
            video_id = path_parts[1]
            if re.fullmatch(r"[0-9A-Za-z_-]{11}", video_id):
                return video_id

        return None
