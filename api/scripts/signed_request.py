#!/usr/bin/env python
"""Make RFC 9421-signed HTTP requests to the menos API."""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

from menos.client.signer import RequestSigner
from menos.config import settings


def main():
    parser = argparse.ArgumentParser(description="Make signed HTTP requests to the menos API")
    parser.add_argument("method", help="HTTP method (GET, POST, DELETE, PATCH, PUT)")
    parser.add_argument("path", help="Request path (e.g. /api/v1/content)")
    parser.add_argument("body", nargs="?", default=None, help="JSON request body")
    parser.add_argument(
        "--key",
        default=str(Path.home() / ".ssh" / "id_ed25519"),
        help="Path to ed25519 private key (default: ~/.ssh/id_ed25519)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Show request details")
    parser.add_argument(
        "--timeout",
        type=float,
        default=30,
        help="Request timeout in seconds (default: 30)",
    )
    args = parser.parse_args()

    base_url = settings.api_base_url
    method = args.method.upper()
    url = f"{base_url}{args.path}"
    parsed = urlparse(base_url)
    host = parsed.hostname
    if parsed.port and parsed.port not in (80, 443):
        host = f"{host}:{parsed.port}"

    body_bytes = None
    if args.body:
        # Validate JSON
        try:
            json.loads(args.body)
        except json.JSONDecodeError as e:
            print(f"Invalid JSON body: {e}", file=sys.stderr)
            sys.exit(1)
        body_bytes = args.body.encode()

    signer = RequestSigner.from_file(args.key)
    sig_headers = signer.sign_request(method, args.path, body=body_bytes, host=host)

    headers = {**sig_headers}
    if body_bytes:
        headers["content-type"] = "application/json"

    if args.verbose:
        print(f"{method} {url}", file=sys.stderr)
        for k, v in headers.items():
            print(f"  {k}: {v}", file=sys.stderr)
        print(file=sys.stderr)

    response = httpx.request(
        method, url, headers=headers, content=body_bytes, timeout=args.timeout
    )

    # Print response
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            data = response.json()
            print(json.dumps(data, indent=2))
        except (json.JSONDecodeError, ValueError):
            print(response.text)
    else:
        print(response.text)

    if args.verbose:
        print(f"\n--- {response.status_code} {response.reason_phrase} ---", file=sys.stderr)

    sys.exit(0 if response.is_success else 1)


if __name__ == "__main__":
    main()
