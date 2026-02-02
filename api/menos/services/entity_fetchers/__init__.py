"""Entity fetchers for external academic metadata."""

from .arxiv import ArxivFetcher, PaperMetadata
from .github import GitHubFetcher, RepoMetadata
from .semantic_scholar import SemanticScholarFetcher

__all__ = [
    "ArxivFetcher",
    "PaperMetadata",
    "GitHubFetcher",
    "RepoMetadata",
    "SemanticScholarFetcher",
]
