"""Unit tests for entity resolution service."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from menos.models import (
    EdgeType,
    EntityModel,
    EntitySource,
    EntityType,
    ExtractedEntity,
    ExtractionMetrics,
    ExtractionResult,
    PreDetectedValidation,
)
from menos.services.entity_resolution import (
    EntityResolutionService,
    ResolutionResult,
)
from menos.services.keyword_matcher import MatchedEntity

# --- Fixtures ---


@pytest.fixture
def mock_repo():
    """Mock SurrealDBRepository with entity-related methods."""
    repo = MagicMock()
    repo.list_all_entities = AsyncMock(return_value=[])
    repo.find_or_create_entity = AsyncMock(
        return_value=(
            EntityModel(
                id="resolved1",
                entity_type=EntityType.REPO,
                name="test-repo",
                normalized_name="testrepo",
                source=EntitySource.URL_DETECTED,
            ),
            True,
        )
    )
    repo.create_content_entity_edge = AsyncMock()
    repo.update_content_extraction_status = AsyncMock()
    repo.get_topic_hierarchy = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_extraction_service():
    """Mock EntityExtractionService."""
    service = MagicMock()
    service.extract_entities = AsyncMock(
        return_value=(
            ExtractionResult(
                topics=[],
                pre_detected_validations=[],
                additional_entities=[],
            ),
            ExtractionMetrics(content_id="test", llm_skipped=True),
        )
    )
    return service


@pytest.fixture
def mock_keyword_matcher():
    """Mock EntityKeywordMatcher."""
    matcher = MagicMock()
    matcher.find_in_text = MagicMock(return_value=[])
    matcher.load_entities = MagicMock()
    return matcher


@pytest.fixture
def mock_settings():
    """Mock Settings."""
    settings = MagicMock()
    settings.entity_fetch_external_metadata = True
    return settings


@pytest.fixture
def mock_url_detector():
    """Mock URL detector."""
    detector = MagicMock()
    detector.detect_urls = MagicMock(return_value=[])
    return detector


@pytest.fixture
def mock_sponsored_filter():
    """Mock sponsored link filter."""
    filt = MagicMock()
    filt.is_sponsored_link = MagicMock(return_value=False)
    return filt


@pytest.fixture
def mock_github_fetcher():
    """Mock GitHub metadata fetcher."""
    fetcher = MagicMock()
    fetcher.fetch_repo = AsyncMock(return_value=None)
    return fetcher


@pytest.fixture
def mock_arxiv_fetcher():
    """Mock arXiv metadata fetcher."""
    fetcher = MagicMock()
    fetcher.fetch_paper = AsyncMock(return_value=None)
    return fetcher


@pytest.fixture
def resolution_service(
    mock_repo,
    mock_extraction_service,
    mock_keyword_matcher,
    mock_settings,
):
    """Create EntityResolutionService with mocks."""
    return EntityResolutionService(
        repository=mock_repo,
        extraction_service=mock_extraction_service,
        keyword_matcher=mock_keyword_matcher,
        settings=mock_settings,
    )


@pytest.fixture
def full_resolution_service(
    mock_repo,
    mock_extraction_service,
    mock_keyword_matcher,
    mock_settings,
    mock_url_detector,
    mock_sponsored_filter,
    mock_github_fetcher,
    mock_arxiv_fetcher,
):
    """Create EntityResolutionService with all optional dependencies."""
    return EntityResolutionService(
        repository=mock_repo,
        extraction_service=mock_extraction_service,
        keyword_matcher=mock_keyword_matcher,
        settings=mock_settings,
        url_detector=mock_url_detector,
        sponsored_filter=mock_sponsored_filter,
        github_fetcher=mock_github_fetcher,
        arxiv_fetcher=mock_arxiv_fetcher,
    )


def _make_entity(
    name: str = "test-entity",
    entity_type: EntityType = EntityType.REPO,
    entity_id: str | None = "ent1",
    source: EntitySource = EntitySource.URL_DETECTED,
    **kwargs,
) -> EntityModel:
    """Helper to create an EntityModel for tests."""
    return EntityModel(
        id=entity_id,
        entity_type=entity_type,
        name=name,
        normalized_name=name.lower().replace(" ", ""),
        source=source,
        **kwargs,
    )


def _make_url_info(
    url: str = "https://github.com/owner/repo",
    url_type: str = "github_repo",
    extracted_id: str = "owner/repo",
):
    """Helper to create a mock URL detection result."""
    info = MagicMock()
    info.url = url
    info.url_type = url_type
    info.extracted_id = extracted_id
    return info


# --- Tests for refresh_matcher_cache ---


class TestRefreshMatcherCache:
    """Tests for refresh_matcher_cache method."""

    @pytest.mark.asyncio
    async def test_loads_entities_into_matcher(
        self, resolution_service, mock_repo, mock_keyword_matcher
    ):
        entities = [_make_entity("repo1"), _make_entity("repo2")]
        mock_repo.list_all_entities = AsyncMock(return_value=entities)

        await resolution_service.refresh_matcher_cache()

        mock_repo.list_all_entities.assert_awaited_once()
        mock_keyword_matcher.load_entities.assert_called_once_with(entities)

    @pytest.mark.asyncio
    async def test_loads_empty_entity_list(
        self, resolution_service, mock_repo, mock_keyword_matcher
    ):
        mock_repo.list_all_entities = AsyncMock(return_value=[])

        await resolution_service.refresh_matcher_cache()

        mock_keyword_matcher.load_entities.assert_called_once_with([])


# --- Tests for process_content ---


class TestProcessContent:
    """Tests for the full process_content pipeline."""

    @pytest.mark.asyncio
    async def test_returns_resolution_result(self, resolution_service):
        result = await resolution_service.process_content(
            content_id="c1",
            content_text="Some content text",
            content_type="youtube",
            title="Test Video",
        )

        assert isinstance(result, ResolutionResult)
        assert isinstance(result.edges, list)
        assert isinstance(result.entities_created, int)
        assert isinstance(result.entities_reused, int)

    @pytest.mark.asyncio
    async def test_updates_extraction_status(
        self, resolution_service, mock_repo
    ):
        await resolution_service.process_content(
            content_id="c1",
            content_text="Content",
            content_type="youtube",
            title="Test",
        )

        mock_repo.update_content_extraction_status.assert_awaited_once_with(
            "c1", "completed"
        )

    @pytest.mark.asyncio
    async def test_calls_extraction_service(
        self, resolution_service, mock_extraction_service
    ):
        await resolution_service.process_content(
            content_id="c1",
            content_text="Content about AI",
            content_type="youtube",
            title="AI Video",
        )

        mock_extraction_service.extract_entities.assert_awaited_once()
        call_kwargs = (
            mock_extraction_service.extract_entities.call_args.kwargs
        )
        assert call_kwargs["content_text"] == "Content about AI"
        assert call_kwargs["content_type"] == "youtube"
        assert call_kwargs["title"] == "AI Video"

    @pytest.mark.asyncio
    async def test_pre_detected_entity_creates_edge(
        self, full_resolution_service, mock_repo, mock_url_detector,
        mock_extraction_service,
    ):
        """Pre-detected entity confirmed by LLM creates an edge."""
        url_info = _make_url_info(
            url="https://github.com/langchain-ai/langchain",
            url_type="github_repo",
            extracted_id="langchain-ai/langchain",
        )
        mock_url_detector.detect_urls = MagicMock(return_value=[url_info])

        resolved_entity = _make_entity(
            "langchain", entity_id="resolved_lc"
        )
        mock_repo.find_or_create_entity = AsyncMock(
            return_value=(resolved_entity, True)
        )

        # LLM confirms the pre-detected entity
        mock_extraction_service.extract_entities = AsyncMock(
            return_value=(
                ExtractionResult(
                    topics=[],
                    pre_detected_validations=[
                        PreDetectedValidation(
                            entity_id="entity:langchain",
                            edge_type=EdgeType.USES,
                            confirmed=True,
                        )
                    ],
                    additional_entities=[],
                ),
                ExtractionMetrics(content_id="c1"),
            )
        )

        result = await full_resolution_service.process_content(
            content_id="c1",
            content_text="Using langchain for RAG",
            content_type="youtube",
            title="LangChain Tutorial",
        )

        assert result.entities_created >= 1
        assert mock_repo.create_content_entity_edge.await_count >= 1

    @pytest.mark.asyncio
    async def test_unconfirmed_predetected_entity_skipped(
        self, resolution_service, mock_repo, mock_extraction_service,
    ):
        """Pre-detected entity NOT confirmed by LLM is skipped."""
        # Manually patch _detect_urls to return an entity
        entity = _make_entity("noise-repo", entity_id="noise1")
        resolution_service._detect_urls = AsyncMock(
            return_value=[entity]
        )

        mock_extraction_service.extract_entities = AsyncMock(
            return_value=(
                ExtractionResult(
                    topics=[],
                    pre_detected_validations=[
                        PreDetectedValidation(
                            entity_id="entity:noise1",
                            edge_type=EdgeType.MENTIONS,
                            confirmed=False,
                        )
                    ],
                    additional_entities=[],
                ),
                ExtractionMetrics(content_id="c1"),
            )
        )

        result = await resolution_service.process_content(
            content_id="c1",
            content_text="Some content",
            content_type="youtube",
            title="Test",
        )

        # Entity was not confirmed, so no edge should be created for it
        assert result.entities_created == 0
        assert result.entities_reused == 0
        assert len(result.edges) == 0

    @pytest.mark.asyncio
    async def test_predetected_without_validation_defaults_mentions(
        self, resolution_service, mock_repo, mock_extraction_service,
    ):
        """Pre-detected entity without validation gets MENTIONS edge."""
        entity = _make_entity("my-repo", entity_id="mr1")
        resolution_service._detect_urls = AsyncMock(
            return_value=[entity]
        )

        resolved = _make_entity("my-repo", entity_id="resolved_mr")
        mock_repo.find_or_create_entity = AsyncMock(
            return_value=(resolved, False)
        )

        mock_extraction_service.extract_entities = AsyncMock(
            return_value=(
                ExtractionResult(
                    topics=[],
                    pre_detected_validations=[],
                    additional_entities=[],
                ),
                ExtractionMetrics(content_id="c1"),
            )
        )

        result = await resolution_service.process_content(
            content_id="c1",
            content_text="Content",
            content_type="youtube",
            title="Test",
        )

        assert result.entities_reused == 1
        edge = result.edges[0]
        assert edge.edge_type == EdgeType.MENTIONS

    @pytest.mark.asyncio
    async def test_keyword_matched_entities_added(
        self, resolution_service, mock_keyword_matcher,
        mock_extraction_service, mock_repo,
    ):
        """Keyword-matched entities are included in pre-detected list."""
        entity = _make_entity(
            "Python", entity_type=EntityType.TOPIC, entity_id="py1"
        )
        match = MatchedEntity(
            entity=entity, confidence=0.95, match_type="keyword"
        )
        mock_keyword_matcher.find_in_text = MagicMock(
            return_value=[match]
        )

        resolved = _make_entity("Python", entity_id="py_resolved")
        mock_repo.find_or_create_entity = AsyncMock(
            return_value=(resolved, False)
        )

        mock_extraction_service.extract_entities = AsyncMock(
            return_value=(
                ExtractionResult(
                    topics=[],
                    pre_detected_validations=[],
                    additional_entities=[],
                ),
                ExtractionMetrics(content_id="c1"),
            )
        )

        result = await resolution_service.process_content(
            content_id="c1",
            content_text="Learning Python",
            content_type="markdown",
            title="Python Guide",
        )

        assert result.entities_reused == 1

    @pytest.mark.asyncio
    async def test_topics_create_edges(
        self, resolution_service, mock_extraction_service, mock_repo,
    ):
        """LLM-extracted topics create edges."""
        topic = ExtractedEntity(
            entity_type=EntityType.TOPIC,
            name="RAG",
            confidence="high",
            edge_type=EdgeType.DISCUSSES,
            hierarchy=["AI", "LLMs", "RAG"],
        )
        mock_extraction_service.extract_entities = AsyncMock(
            return_value=(
                ExtractionResult(
                    topics=[topic],
                    pre_detected_validations=[],
                    additional_entities=[],
                ),
                ExtractionMetrics(content_id="c1"),
            )
        )

        resolved = _make_entity(
            "RAG", entity_type=EntityType.TOPIC, entity_id="topic_rag"
        )
        mock_repo.find_or_create_entity = AsyncMock(
            return_value=(resolved, True)
        )

        result = await resolution_service.process_content(
            content_id="c1",
            content_text="RAG tutorial content",
            content_type="youtube",
            title="RAG Tutorial",
        )

        # At least one topic edge created
        topic_edges = [
            e for e in result.edges
            if e.source == EntitySource.AI_EXTRACTED
        ]
        assert len(topic_edges) >= 1
        assert topic_edges[0].confidence == 0.85

    @pytest.mark.asyncio
    async def test_additional_entities_create_edges(
        self, resolution_service, mock_extraction_service, mock_repo,
    ):
        """LLM additional entities create edges."""
        additional = ExtractedEntity(
            entity_type=EntityType.TOOL,
            name="FAISS",
            confidence="medium",
            edge_type=EdgeType.MENTIONS,
        )
        mock_extraction_service.extract_entities = AsyncMock(
            return_value=(
                ExtractionResult(
                    topics=[],
                    pre_detected_validations=[],
                    additional_entities=[additional],
                ),
                ExtractionMetrics(content_id="c1"),
            )
        )

        resolved = _make_entity(
            "FAISS", entity_type=EntityType.TOOL, entity_id="faiss1"
        )
        mock_repo.find_or_create_entity = AsyncMock(
            return_value=(resolved, True)
        )

        result = await resolution_service.process_content(
            content_id="c1",
            content_text="Using FAISS for vector search",
            content_type="youtube",
            title="Vector Search",
        )

        assert result.entities_created >= 1
        extra_edges = [
            e for e in result.edges if e.confidence == 0.7
        ]
        assert len(extra_edges) == 1

    @pytest.mark.asyncio
    async def test_edge_creation_failure_logged_not_raised(
        self, resolution_service, mock_extraction_service, mock_repo,
    ):
        """Failed edge creation logs warning, does not crash."""
        entity = _make_entity("fail-repo", entity_id="fail1")
        resolution_service._detect_urls = AsyncMock(
            return_value=[entity]
        )

        resolved = _make_entity("fail-repo", entity_id="fail_res")
        mock_repo.find_or_create_entity = AsyncMock(
            return_value=(resolved, True)
        )
        mock_repo.create_content_entity_edge = AsyncMock(
            side_effect=Exception("DB error")
        )

        mock_extraction_service.extract_entities = AsyncMock(
            return_value=(
                ExtractionResult(
                    topics=[],
                    pre_detected_validations=[],
                    additional_entities=[],
                ),
                ExtractionMetrics(content_id="c1"),
            )
        )

        result = await resolution_service.process_content(
            content_id="c1",
            content_text="Content",
            content_type="youtube",
            title="Test",
        )

        # Edge creation failed, so no edges in result
        assert len(result.edges) == 0
        assert result.entities_created == 1

    @pytest.mark.asyncio
    async def test_topic_edge_failure_logged_not_raised(
        self, resolution_service, mock_extraction_service, mock_repo,
    ):
        """Failed topic edge creation logs warning, continues."""
        topic = ExtractedEntity(
            entity_type=EntityType.TOPIC,
            name="ML",
            confidence="high",
            edge_type=EdgeType.DISCUSSES,
        )
        mock_extraction_service.extract_entities = AsyncMock(
            return_value=(
                ExtractionResult(
                    topics=[topic],
                    pre_detected_validations=[],
                    additional_entities=[],
                ),
                ExtractionMetrics(content_id="c1"),
            )
        )

        resolved = _make_entity(
            "ML", entity_type=EntityType.TOPIC, entity_id="ml1"
        )
        mock_repo.find_or_create_entity = AsyncMock(
            return_value=(resolved, True)
        )
        mock_repo.create_content_entity_edge = AsyncMock(
            side_effect=Exception("DB error")
        )

        result = await resolution_service.process_content(
            content_id="c1",
            content_text="Content",
            content_type="youtube",
            title="Test",
        )

        assert len(result.edges) == 0

    @pytest.mark.asyncio
    async def test_description_urls_passed_to_detect(
        self, full_resolution_service, mock_url_detector,
        mock_extraction_service,
    ):
        """description_urls are passed through to URL detection."""
        mock_url_detector.detect_urls = MagicMock(return_value=[])

        await full_resolution_service.process_content(
            content_id="c1",
            content_text="Content text",
            content_type="youtube",
            title="Test",
            description_urls=["https://example.com"],
        )

        call_args = mock_url_detector.detect_urls.call_args[0][0]
        assert "https://example.com" in call_args


# --- Tests for _detect_urls ---


class TestDetectUrls:
    """Tests for the URL detection stage."""

    @pytest.mark.asyncio
    async def test_returns_empty_without_detector(
        self, resolution_service
    ):
        result = await resolution_service._detect_urls(
            "some text", []
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_calls_detector_with_combined_text(
        self, full_resolution_service, mock_url_detector
    ):
        mock_url_detector.detect_urls = MagicMock(return_value=[])

        await full_resolution_service._detect_urls(
            "body text",
            ["https://example.com"],
        )

        combined = mock_url_detector.detect_urls.call_args[0][0]
        assert "body text" in combined
        assert "https://example.com" in combined

    @pytest.mark.asyncio
    async def test_filters_sponsored_links(
        self, full_resolution_service, mock_url_detector,
        mock_sponsored_filter,
    ):
        url_info = _make_url_info(
            url="https://sponsor.com/deal",
            url_type="github_repo",
            extracted_id="sponsor/deal",
        )
        mock_url_detector.detect_urls = MagicMock(
            return_value=[url_info]
        )
        mock_sponsored_filter.is_sponsored_link = MagicMock(
            return_value=True
        )

        result = await full_resolution_service._detect_urls(
            "text", []
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_converts_detected_urls_to_entities(
        self, full_resolution_service, mock_url_detector,
    ):
        url_info = _make_url_info(
            url="https://github.com/owner/myrepo",
            url_type="github_repo",
            extracted_id="owner/myrepo",
        )
        mock_url_detector.detect_urls = MagicMock(
            return_value=[url_info]
        )

        result = await full_resolution_service._detect_urls(
            "text", []
        )

        assert len(result) == 1
        assert result[0].entity_type == EntityType.REPO
        assert result[0].name == "myrepo"


# --- Tests for _url_to_entity ---


class TestUrlToEntity:
    """Tests for URL-to-entity conversion."""

    @pytest.mark.asyncio
    async def test_github_repo(self, full_resolution_service):
        url_info = _make_url_info(
            url="https://github.com/langchain-ai/langchain",
            url_type="github_repo",
            extracted_id="langchain-ai/langchain",
        )

        result = await full_resolution_service._url_to_entity(url_info)

        assert result is not None
        assert result.entity_type == EntityType.REPO
        assert result.name == "langchain"
        assert result.metadata["owner"] == "langchain-ai"

    @pytest.mark.asyncio
    async def test_arxiv_paper(self, full_resolution_service):
        url_info = _make_url_info(
            url="https://arxiv.org/abs/2301.01234",
            url_type="arxiv",
            extracted_id="2301.01234",
        )

        result = await full_resolution_service._url_to_entity(url_info)

        assert result is not None
        assert result.entity_type == EntityType.PAPER
        assert "2301.01234" in result.name

    @pytest.mark.asyncio
    async def test_pypi_package(self, full_resolution_service):
        url_info = _make_url_info(
            url="https://pypi.org/project/requests",
            url_type="pypi",
            extracted_id="requests",
        )

        result = await full_resolution_service._url_to_entity(url_info)

        assert result is not None
        assert result.entity_type == EntityType.TOOL
        assert result.name == "requests"
        assert result.metadata["registry"] == "pypi"

    @pytest.mark.asyncio
    async def test_npm_package(self, full_resolution_service):
        url_info = _make_url_info(
            url="https://npmjs.com/package/express",
            url_type="npm",
            extracted_id="express",
        )

        result = await full_resolution_service._url_to_entity(url_info)

        assert result is not None
        assert result.entity_type == EntityType.TOOL
        assert result.name == "express"
        assert result.metadata["registry"] == "npm"

    @pytest.mark.asyncio
    async def test_unknown_url_type_returns_none(
        self, full_resolution_service
    ):
        url_info = _make_url_info(
            url="https://unknown.com",
            url_type="unknown",
            extracted_id="something",
        )

        result = await full_resolution_service._url_to_entity(url_info)
        assert result is None


# --- Tests for _resolve_github_repo ---


class TestResolveGithubRepo:
    """Tests for GitHub repo resolution."""

    @pytest.mark.asyncio
    async def test_basic_resolution_without_fetcher(
        self, resolution_service
    ):
        url_info = _make_url_info(
            extracted_id="owner/my-repo"
        )

        result = await resolution_service._resolve_github_repo(url_info)

        assert result is not None
        assert result.name == "my-repo"
        assert result.metadata["owner"] == "owner"
        assert result.source == EntitySource.URL_DETECTED

    @pytest.mark.asyncio
    async def test_returns_none_for_invalid_id(
        self, resolution_service
    ):
        url_info = _make_url_info(extracted_id="noslash")
        result = await resolution_service._resolve_github_repo(url_info)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_id(
        self, resolution_service
    ):
        url_info = _make_url_info(extracted_id="")
        result = await resolution_service._resolve_github_repo(url_info)
        assert result is None

    @pytest.mark.asyncio
    async def test_enriches_with_github_metadata(
        self, full_resolution_service, mock_github_fetcher
    ):
        repo_meta = MagicMock()
        repo_meta.stars = 1000
        repo_meta.language = "Python"
        repo_meta.topics = ["ai", "ml"]
        repo_meta.fetched_at = None
        repo_meta.description = "A great repo"
        repo_meta.name = "awesome-repo"
        mock_github_fetcher.fetch_repo = AsyncMock(
            return_value=repo_meta
        )

        url_info = _make_url_info(extracted_id="owner/awesome-repo")

        result = await full_resolution_service._resolve_github_repo(
            url_info
        )

        assert result is not None
        assert result.metadata["stars"] == 1000
        assert result.metadata["language"] == "Python"
        assert result.name == "awesome-repo"

    @pytest.mark.asyncio
    async def test_handles_github_fetcher_error(
        self, full_resolution_service, mock_github_fetcher
    ):
        mock_github_fetcher.fetch_repo = AsyncMock(
            side_effect=Exception("API error")
        )

        url_info = _make_url_info(extracted_id="owner/repo")

        result = await full_resolution_service._resolve_github_repo(
            url_info
        )

        # Should still return entity without enrichment
        assert result is not None
        assert result.name == "repo"

    @pytest.mark.asyncio
    async def test_skips_fetch_when_disabled(
        self, full_resolution_service, mock_settings,
        mock_github_fetcher,
    ):
        mock_settings.entity_fetch_external_metadata = False

        url_info = _make_url_info(extracted_id="owner/repo")

        result = await full_resolution_service._resolve_github_repo(
            url_info
        )

        mock_github_fetcher.fetch_repo.assert_not_awaited()
        assert result is not None


# --- Tests for _resolve_arxiv_paper ---


class TestResolveArxivPaper:
    """Tests for arXiv paper resolution."""

    @pytest.mark.asyncio
    async def test_basic_resolution(self, resolution_service):
        url_info = _make_url_info(
            url="https://arxiv.org/abs/2301.01234",
            url_type="arxiv",
            extracted_id="2301.01234",
        )

        result = await resolution_service._resolve_arxiv_paper(url_info)

        assert result is not None
        assert result.entity_type == EntityType.PAPER
        assert result.name == "arXiv:2301.01234"
        assert result.metadata["arxiv_id"] == "2301.01234"

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_id(
        self, resolution_service
    ):
        url_info = _make_url_info(extracted_id="")
        result = await resolution_service._resolve_arxiv_paper(url_info)
        assert result is None

    @pytest.mark.asyncio
    async def test_enriches_with_arxiv_metadata(
        self, full_resolution_service, mock_arxiv_fetcher
    ):
        paper_meta = MagicMock()
        paper_meta.title = "Attention Is All You Need"
        paper_meta.authors = ["Vaswani et al."]
        paper_meta.abstract = "A new architecture..."
        paper_meta.doi = "10.1234/test"
        paper_meta.published_at = None
        paper_meta.fetched_at = None
        mock_arxiv_fetcher.fetch_paper = AsyncMock(
            return_value=paper_meta
        )

        url_info = _make_url_info(
            url="https://arxiv.org/abs/1706.03762",
            url_type="arxiv",
            extracted_id="1706.03762",
        )

        result = await full_resolution_service._resolve_arxiv_paper(
            url_info
        )

        assert result is not None
        assert result.name == "Attention Is All You Need"
        assert result.metadata["authors"] == ["Vaswani et al."]

    @pytest.mark.asyncio
    async def test_handles_arxiv_fetcher_error(
        self, full_resolution_service, mock_arxiv_fetcher
    ):
        mock_arxiv_fetcher.fetch_paper = AsyncMock(
            side_effect=Exception("API error")
        )

        url_info = _make_url_info(
            url="https://arxiv.org/abs/2301.01234",
            url_type="arxiv",
            extracted_id="2301.01234",
        )

        result = await full_resolution_service._resolve_arxiv_paper(
            url_info
        )

        assert result is not None
        assert result.name == "arXiv:2301.01234"

    @pytest.mark.asyncio
    async def test_skips_fetch_when_disabled(
        self, full_resolution_service, mock_settings,
        mock_arxiv_fetcher,
    ):
        mock_settings.entity_fetch_external_metadata = False

        url_info = _make_url_info(
            url="https://arxiv.org/abs/2301.01234",
            url_type="arxiv",
            extracted_id="2301.01234",
        )

        result = await full_resolution_service._resolve_arxiv_paper(
            url_info
        )

        mock_arxiv_fetcher.fetch_paper.assert_not_awaited()
        assert result is not None


# --- Tests for _create_tool_entity ---


class TestCreateToolEntity:
    """Tests for tool entity creation."""

    def test_pypi_tool(self, resolution_service):
        url_info = _make_url_info(
            url="https://pypi.org/project/httpx",
            url_type="pypi",
            extracted_id="httpx",
        )

        result = resolution_service._create_tool_entity(
            url_info, "pypi"
        )

        assert result.entity_type == EntityType.TOOL
        assert result.name == "httpx"
        assert result.metadata["registry"] == "pypi"
        assert result.source == EntitySource.URL_DETECTED

    def test_npm_tool(self, resolution_service):
        url_info = _make_url_info(
            url="https://npmjs.com/package/express",
            url_type="npm",
            extracted_id="express",
        )

        result = resolution_service._create_tool_entity(
            url_info, "npm"
        )

        assert result.entity_type == EntityType.TOOL
        assert result.name == "express"
        assert result.metadata["registry"] == "npm"

    def test_unknown_extracted_id_defaults_to_unknown(
        self, resolution_service
    ):
        url_info = _make_url_info(extracted_id=None)

        result = resolution_service._create_tool_entity(
            url_info, "pypi"
        )

        assert result.name == "unknown"


# --- Tests for _resolve_topic ---


class TestResolveTopic:
    """Tests for topic resolution with hierarchy."""

    @pytest.mark.asyncio
    async def test_simple_topic_no_hierarchy(
        self, resolution_service, mock_repo
    ):
        resolved = _make_entity(
            "Python", entity_type=EntityType.TOPIC, entity_id="t1"
        )
        mock_repo.find_or_create_entity = AsyncMock(
            return_value=(resolved, True)
        )

        entity, created = await resolution_service._resolve_topic(
            "Python", None
        )

        assert entity.name == "Python"
        assert created is True

    @pytest.mark.asyncio
    async def test_hierarchical_topic_creates_parents(
        self, resolution_service, mock_repo
    ):
        parent = _make_entity(
            "AI", entity_type=EntityType.TOPIC, entity_id="ai1"
        )
        child = _make_entity(
            "LLMs", entity_type=EntityType.TOPIC, entity_id="llm1"
        )
        leaf = _make_entity(
            "RAG", entity_type=EntityType.TOPIC, entity_id="rag1"
        )

        mock_repo.find_or_create_entity = AsyncMock(
            side_effect=[
                (parent, True),   # "AI" parent
                (child, False),   # "LLMs" parent
                (leaf, True),     # "RAG" leaf
            ]
        )

        entity, created = await resolution_service._resolve_topic(
            "RAG", ["AI", "LLMs", "RAG"]
        )

        assert entity.name == "RAG"
        assert created is True
        assert mock_repo.find_or_create_entity.await_count == 3

    @pytest.mark.asyncio
    async def test_two_level_hierarchy(
        self, resolution_service, mock_repo
    ):
        parent = _make_entity(
            "AI", entity_type=EntityType.TOPIC, entity_id="ai1"
        )
        leaf = _make_entity(
            "ML", entity_type=EntityType.TOPIC, entity_id="ml1"
        )

        mock_repo.find_or_create_entity = AsyncMock(
            side_effect=[
                (parent, False),  # "AI" parent
                (leaf, True),     # "ML" leaf
            ]
        )

        entity, created = await resolution_service._resolve_topic(
            "ML", ["AI", "ML"]
        )

        assert entity.name == "ML"
        assert created is True
        # Last call should include parent metadata
        last_call = mock_repo.find_or_create_entity.call_args
        assert "parent_topic" in last_call.kwargs.get("metadata", {})


# --- Tests for _get_existing_topics ---


class TestGetExistingTopics:
    """Tests for getting existing topic names."""

    @pytest.mark.asyncio
    async def test_returns_topic_names(
        self, resolution_service, mock_repo
    ):
        topics = [
            _make_entity(
                "AI", entity_type=EntityType.TOPIC, entity_id="t1"
            ),
            _make_entity(
                "ML", entity_type=EntityType.TOPIC, entity_id="t2"
            ),
        ]
        mock_repo.get_topic_hierarchy = AsyncMock(return_value=topics)

        result = await resolution_service._get_existing_topics()

        assert result == ["AI", "ML"]

    @pytest.mark.asyncio
    async def test_limits_to_50(
        self, resolution_service, mock_repo
    ):
        topics = [
            _make_entity(
                f"topic{i}",
                entity_type=EntityType.TOPIC,
                entity_id=f"t{i}",
            )
            for i in range(60)
        ]
        mock_repo.get_topic_hierarchy = AsyncMock(return_value=topics)

        result = await resolution_service._get_existing_topics()

        assert len(result) == 50

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_topics(
        self, resolution_service, mock_repo
    ):
        mock_repo.get_topic_hierarchy = AsyncMock(return_value=[])

        result = await resolution_service._get_existing_topics()

        assert result == []


# --- Tests for ResolutionResult dataclass ---


class TestResolutionResult:
    """Tests for the ResolutionResult dataclass."""

    def test_creation(self):
        result = ResolutionResult(
            edges=[],
            entities_created=5,
            entities_reused=3,
            metrics=None,
        )

        assert result.entities_created == 5
        assert result.entities_reused == 3
        assert result.metrics is None
        assert result.edges == []

    def test_with_metrics(self):
        metrics = ExtractionMetrics(content_id="c1", llm_skipped=True)
        result = ResolutionResult(
            edges=[],
            entities_created=0,
            entities_reused=0,
            metrics=metrics,
        )

        assert result.metrics is not None
        assert result.metrics.llm_skipped is True
