"""Canonical resource key generation and URL normalization."""

import base64
import hashlib
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "_ga",
    "_gid",
}


def normalize_url(url: str) -> str:
    """Normalize a URL for consistent hashing.

    - Lowercase scheme + host
    - Upgrade http to https
    - Remove default ports (80 for http, 443 for https)
    - Strip fragment
    - Remove trailing slash (except root "/")
    - Remove tracking params, sort remaining params
    """
    parsed = urlparse(url)

    # Lowercase scheme and host
    scheme = parsed.scheme.lower()
    host = parsed.hostname or ""
    port = parsed.port

    # Upgrade http to https
    if scheme == "http":
        scheme = "https"

    # Remove default ports
    if port in (80, 443):
        port = None

    # Reconstruct netloc
    netloc = host
    if port:
        netloc = f"{host}:{port}"

    # Strip fragment
    path = parsed.path

    # Remove trailing slash except for root
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    # Parse query params, remove tracking, sort remaining
    query_params = parse_qs(parsed.query, keep_blank_values=True)
    filtered_params = {k: v for k, v in query_params.items() if k not in TRACKING_PARAMS}
    # Sort and rebuild query string
    sorted_pairs = []
    for key in sorted(filtered_params.keys()):
        for val in filtered_params[key]:
            sorted_pairs.append((key, val))
    query = urlencode(sorted_pairs)

    return urlunparse((scheme, netloc, path, "", query, ""))


def generate_resource_key(content_type: str, identifier: str) -> str:
    """Generate a canonical resource key for deduplication.

    Args:
        content_type: Type of content (youtube, url, document, etc.)
        identifier: Video ID, URL, or content ID

    Returns:
        Canonical resource key string
    """
    if content_type == "youtube":
        return f"yt:{identifier}"
    elif content_type == "url":
        normalized = normalize_url(identifier)
        digest = hashlib.sha256(normalized.encode()).digest()
        hash16 = base64.urlsafe_b64encode(digest[:12]).decode().rstrip("=")
        return f"url:{hash16}"
    else:
        return f"cid:{identifier}"
