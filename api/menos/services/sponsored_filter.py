"""Filter for promotional and affiliate links."""

import re
from urllib.parse import urlparse


class SponsoredFilter:
    """Filters promotional/affiliate links from URLs."""

    SPONSORED_PATTERNS = [
        r"bit\.ly/",
        r"amzn\.to/",
        r"geni\.us/",
        r"tinyurl\.com/",
        r"\?ref=",
        r"\?affiliate",
        r"utm_source=",
        r"sponsored",
        r"#ad\b",
        r"discount code",
    ]

    SPONSORED_DOMAINS = [
        "amazon.com",
        "brilliant.org",
        "squarespace.com",
        "skillshare.com",
        "audible.com",
    ]

    def __init__(
        self,
        sponsored_domains: list[str] | None = None,
        sponsored_patterns: list[str] | None = None,
    ):
        """
        Initialize the sponsored filter.

        Args:
            sponsored_domains: Optional custom list of domains to block
            sponsored_patterns: Optional custom list of regex patterns to block
        """
        self.sponsored_domains = sponsored_domains or self.SPONSORED_DOMAINS
        self.sponsored_patterns = sponsored_patterns or self.SPONSORED_PATTERNS
        self._compiled_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.sponsored_patterns
        ]

    def is_sponsored_link(self, url: str, context: str | None = None) -> bool:
        """
        Check if a URL is a sponsored/affiliate link.

        Args:
            url: The URL to check
            context: Optional surrounding text for context-aware filtering

        Returns:
            True if the URL appears to be sponsored, False otherwise
        """
        url_lower = url.lower()

        # Special case: Check if this is an AWS-related URL
        is_aws_url = any(
            aws_domain in url_lower
            for aws_domain in ["aws.amazon.com", "docs.aws.amazon.com"]
        )

        # If it's an AWS URL and we have AWS context, it's not sponsored
        if is_aws_url and context:
            context_lower = context.lower()
            if any(
                keyword in context_lower
                for keyword in ["aws", "s3", "ec2", "lambda", "cloud"]
            ):
                return False

        # Check patterns
        for pattern in self._compiled_patterns:
            if pattern.search(url_lower):
                return True

        # Check domains
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            # Remove www. prefix
            if domain.startswith("www."):
                domain = domain[4:]

            for blocked_domain in self.sponsored_domains:
                if domain == blocked_domain or domain.endswith(f".{blocked_domain}"):
                    return True
        except Exception:
            # If URL parsing fails, err on the side of not filtering
            pass

        return False

    def filter_urls(self, urls: list[str], context: str | None = None) -> list[str]:
        """
        Filter out sponsored URLs from a list.

        Args:
            urls: List of URLs to filter
            context: Optional surrounding text for context-aware filtering

        Returns:
            List of non-sponsored URLs
        """
        return [url for url in urls if not self.is_sponsored_link(url, context)]
