"""Unit tests for EntityKeywordMatcher."""

from menos.models import EntityModel, EntitySource, EntityType
from menos.services.keyword_matcher import EntityKeywordMatcher, MatchedEntity


def _make_entity(
    name: str,
    entity_type: EntityType,
    normalized_name: str | None = None,
    entity_id: str | None = None,
    metadata: dict | None = None,
) -> EntityModel:
    """Helper to build an EntityModel for tests."""
    from menos.services.normalization import normalize_name

    return EntityModel(
        id=entity_id,
        entity_type=entity_type,
        name=name,
        normalized_name=normalized_name or normalize_name(name),
        metadata=metadata or {},
        source=EntitySource.AI_EXTRACTED,
    )


class TestInit:
    """Tests for EntityKeywordMatcher initialization."""

    def test_empty_caches_on_init(self):
        matcher = EntityKeywordMatcher()
        assert matcher.known_repos == {}
        assert matcher.known_papers == {}
        assert matcher.known_tools == {}
        assert matcher.known_topics == {}
        assert matcher.known_persons == {}
        assert matcher.alias_map == {}
        assert matcher.entities_by_id == {}


class TestGetCacheForType:
    """Tests for _get_cache_for_type."""

    def test_returns_correct_cache_for_each_type(self):
        matcher = EntityKeywordMatcher()
        assert matcher._get_cache_for_type(EntityType.REPO) is matcher.known_repos
        assert matcher._get_cache_for_type(EntityType.PAPER) is matcher.known_papers
        assert matcher._get_cache_for_type(EntityType.TOOL) is matcher.known_tools
        assert matcher._get_cache_for_type(EntityType.TOPIC) is matcher.known_topics
        assert matcher._get_cache_for_type(EntityType.PERSON) is matcher.known_persons

    def test_returns_empty_dict_for_unknown_type(self):
        matcher = EntityKeywordMatcher()
        result = matcher._get_cache_for_type("unknown")
        assert result == {}


class TestLoadEntities:
    """Tests for load_entities."""

    def test_loads_entities_into_correct_caches(self):
        matcher = EntityKeywordMatcher()
        entities = [
            _make_entity("PyTorch", EntityType.TOOL, entity_id="tool:1"),
            _make_entity("LangChain", EntityType.REPO, entity_id="repo:1"),
            _make_entity("RAG", EntityType.TOPIC, entity_id="topic:1"),
            _make_entity(
                "Attention Is All You Need",
                EntityType.PAPER,
                entity_id="paper:1",
            ),
            _make_entity("Andrej Karpathy", EntityType.PERSON, entity_id="person:1"),
        ]
        matcher.load_entities(entities)

        assert "pytorch" in matcher.known_tools
        assert "langchain" in matcher.known_repos
        assert "rag" in matcher.known_topics
        assert "attentionisallyouneed" in matcher.known_papers
        assert "andrejkarpathy" in matcher.known_persons

    def test_loads_entity_by_id(self):
        matcher = EntityKeywordMatcher()
        entity = _make_entity("PyTorch", EntityType.TOOL, entity_id="tool:1")
        matcher.load_entities([entity])

        assert matcher.entities_by_id["tool:1"] is entity

    def test_skips_entity_without_id(self):
        matcher = EntityKeywordMatcher()
        entity = _make_entity("PyTorch", EntityType.TOOL, entity_id=None)
        matcher.load_entities([entity])

        assert matcher.entities_by_id == {}
        assert "pytorch" in matcher.known_tools

    def test_indexes_aliases(self):
        matcher = EntityKeywordMatcher()
        entity = _make_entity(
            "PyTorch",
            EntityType.TOOL,
            entity_id="tool:1",
            metadata={"aliases": ["torch", "pytorch-lib"]},
        )
        matcher.load_entities([entity])

        assert "torch" in matcher.alias_map
        assert matcher.alias_map["torch"] == ("pytorch", EntityType.TOOL)
        assert "pytorchlib" in matcher.alias_map

    def test_entity_without_metadata_skips_aliases(self):
        matcher = EntityKeywordMatcher()
        entity = _make_entity("PyTorch", EntityType.TOOL, entity_id="tool:1")
        entity.metadata = None
        matcher.load_entities([entity])

        assert matcher.alias_map == {}

    def test_clears_caches_before_loading(self):
        matcher = EntityKeywordMatcher()
        first = _make_entity("PyTorch", EntityType.TOOL, entity_id="tool:1")
        matcher.load_entities([first])
        assert "pytorch" in matcher.known_tools

        second = _make_entity("TensorFlow", EntityType.TOOL, entity_id="tool:2")
        matcher.load_entities([second])

        assert "pytorch" not in matcher.known_tools
        assert "tensorflow" in matcher.known_tools
        assert "tool:1" not in matcher.entities_by_id


class TestFindInText:
    """Tests for find_in_text."""

    def test_empty_text_returns_empty(self):
        matcher = EntityKeywordMatcher()
        matcher.load_entities([
            _make_entity("PyTorch", EntityType.TOOL, entity_id="tool:1"),
        ])
        assert matcher.find_in_text("") == []

    def test_finds_entity_by_canonical_name(self):
        matcher = EntityKeywordMatcher()
        entity = _make_entity("PyTorch", EntityType.TOOL, entity_id="tool:1")
        matcher.load_entities([entity])

        results = matcher.find_in_text("I love PyTorch for deep learning")
        assert len(results) == 1
        assert results[0].entity is entity
        assert results[0].confidence == 0.9
        assert results[0].match_type == "keyword"

    def test_canonical_match_is_case_insensitive(self):
        matcher = EntityKeywordMatcher()
        entity = _make_entity("PyTorch", EntityType.TOOL, entity_id="tool:1")
        matcher.load_entities([entity])

        results = matcher.find_in_text("pytorch is great")
        assert len(results) == 1

    def test_no_partial_word_match(self):
        matcher = EntityKeywordMatcher()
        matcher.load_entities([
            _make_entity("graph", EntityType.TOPIC, entity_id="topic:1"),
        ])
        results = matcher.find_in_text("graphql is a query language")
        assert results == []

    def test_finds_entity_by_alias(self):
        matcher = EntityKeywordMatcher()
        entity = _make_entity(
            "PyTorch",
            EntityType.TOOL,
            entity_id="tool:1",
            metadata={"aliases": ["torch"]},
        )
        matcher.load_entities([entity])

        results = matcher.find_in_text("I use torch for tensors")
        assert len(results) == 1
        assert results[0].entity is entity
        assert results[0].confidence == 0.85
        assert results[0].match_type == "alias"

    def test_canonical_match_takes_priority_over_alias(self):
        matcher = EntityKeywordMatcher()
        entity = _make_entity(
            "PyTorch",
            EntityType.TOOL,
            entity_id="tool:1",
            metadata={"aliases": ["torch"]},
        )
        matcher.load_entities([entity])

        results = matcher.find_in_text("PyTorch and torch are the same")
        assert len(results) == 1
        assert results[0].match_type == "keyword"

    def test_deduplicates_by_entity_id(self):
        matcher = EntityKeywordMatcher()
        matcher.load_entities([
            _make_entity("PyTorch", EntityType.TOOL, entity_id="tool:1"),
        ])
        results = matcher.find_in_text("PyTorch PyTorch PyTorch")
        assert len(results) == 1

    def test_filters_by_entity_type(self):
        matcher = EntityKeywordMatcher()
        matcher.load_entities([
            _make_entity("Python", EntityType.TOOL, entity_id="tool:1"),
            _make_entity("Python", EntityType.TOPIC, entity_id="topic:1"),
        ])

        tool_results = matcher.find_in_text(
            "Python is great",
            entity_types=[EntityType.TOOL],
        )
        assert len(tool_results) == 1
        assert tool_results[0].entity.entity_type == EntityType.TOOL

    def test_no_entity_types_filter_checks_all(self):
        matcher = EntityKeywordMatcher()
        matcher.load_entities([
            _make_entity("Python", EntityType.TOOL, entity_id="tool:1"),
            _make_entity("RAG", EntityType.TOPIC, entity_id="topic:1"),
        ])

        results = matcher.find_in_text("Python and RAG are cool")
        assert len(results) == 2

    def test_entity_without_id_uses_normalized_for_dedup(self):
        matcher = EntityKeywordMatcher()
        matcher.load_entities([
            _make_entity("Python", EntityType.TOOL, entity_id=None),
        ])
        results = matcher.find_in_text("Python Python Python")
        assert len(results) == 1

    def test_no_match_returns_empty(self):
        matcher = EntityKeywordMatcher()
        matcher.load_entities([
            _make_entity("PyTorch", EntityType.TOOL, entity_id="tool:1"),
        ])
        assert matcher.find_in_text("I love TensorFlow") == []

    def test_entity_with_none_metadata_skips_alias_check(self):
        matcher = EntityKeywordMatcher()
        entity = _make_entity("PyTorch", EntityType.TOOL, entity_id="tool:1")
        entity.metadata = None
        matcher.load_entities([entity])

        results = matcher.find_in_text("something else entirely")
        assert results == []


class TestFuzzyFindEntity:
    """Tests for fuzzy_find_entity."""

    def test_exact_match_returns_entity(self):
        matcher = EntityKeywordMatcher()
        entity = _make_entity("PyTorch", EntityType.TOOL, entity_id="tool:1")
        matcher.load_entities([entity])

        result = matcher.fuzzy_find_entity("PyTorch")
        assert result is entity

    def test_fuzzy_match_within_distance(self):
        matcher = EntityKeywordMatcher()
        entity = _make_entity("PyTorch", EntityType.TOOL, entity_id="tool:1")
        matcher.load_entities([entity])

        result = matcher.fuzzy_find_entity("Pytorh", max_distance=2)
        assert result is entity

    def test_fuzzy_match_exceeding_distance_returns_none(self):
        matcher = EntityKeywordMatcher()
        matcher.load_entities([
            _make_entity("PyTorch", EntityType.TOOL, entity_id="tool:1"),
        ])

        result = matcher.fuzzy_find_entity("TensorFlow", max_distance=2)
        assert result is None

    def test_filters_by_entity_type(self):
        matcher = EntityKeywordMatcher()
        tool = _make_entity("Python", EntityType.TOOL, entity_id="tool:1")
        topic = _make_entity("Python", EntityType.TOPIC, entity_id="topic:1")
        matcher.load_entities([tool, topic])

        result = matcher.fuzzy_find_entity("Python", entity_type=EntityType.TOPIC)
        assert result is topic

    def test_no_type_filter_checks_all(self):
        matcher = EntityKeywordMatcher()
        matcher.load_entities([
            _make_entity("PyTorch", EntityType.TOOL, entity_id="tool:1"),
        ])

        result = matcher.fuzzy_find_entity("PyTorch", entity_type=None)
        assert result is not None

    def test_returns_none_when_empty(self):
        matcher = EntityKeywordMatcher()
        assert matcher.fuzzy_find_entity("anything") is None

    def test_exact_match_preferred_over_fuzzy(self):
        matcher = EntityKeywordMatcher()
        exact = _make_entity("langchain", EntityType.TOOL, entity_id="tool:1")
        close = _make_entity("langchains", EntityType.TOOL, entity_id="tool:2")
        matcher.load_entities([exact, close])

        result = matcher.fuzzy_find_entity("langchain")
        assert result is exact


class TestFindEntityByName:
    """Tests for find_entity_by_name."""

    def test_finds_by_normalized_name(self):
        matcher = EntityKeywordMatcher()
        entity = _make_entity("PyTorch", EntityType.TOOL, entity_id="tool:1")
        matcher.load_entities([entity])

        result = matcher.find_entity_by_name("PyTorch")
        assert result is entity

    def test_finds_via_alias(self):
        matcher = EntityKeywordMatcher()
        entity = _make_entity(
            "PyTorch",
            EntityType.TOOL,
            entity_id="tool:1",
            metadata={"aliases": ["torch"]},
        )
        matcher.load_entities([entity])

        result = matcher.find_entity_by_name("torch")
        assert result is entity

    def test_direct_match_preferred_over_alias(self):
        matcher = EntityKeywordMatcher()
        entity = _make_entity(
            "PyTorch",
            EntityType.TOOL,
            entity_id="tool:1",
            metadata={"aliases": ["torch"]},
        )
        matcher.load_entities([entity])

        result = matcher.find_entity_by_name("PyTorch")
        assert result is entity

    def test_filters_by_entity_type_direct(self):
        matcher = EntityKeywordMatcher()
        tool = _make_entity("Python", EntityType.TOOL, entity_id="tool:1")
        topic = _make_entity("Python", EntityType.TOPIC, entity_id="topic:1")
        matcher.load_entities([tool, topic])

        result = matcher.find_entity_by_name(
            "Python", entity_type=EntityType.TOPIC
        )
        assert result is topic

    def test_alias_type_filter_match(self):
        matcher = EntityKeywordMatcher()
        entity = _make_entity(
            "PyTorch",
            EntityType.TOOL,
            entity_id="tool:1",
            metadata={"aliases": ["torch"]},
        )
        matcher.load_entities([entity])

        result = matcher.find_entity_by_name(
            "torch", entity_type=EntityType.TOOL
        )
        assert result is entity

    def test_alias_type_filter_mismatch(self):
        matcher = EntityKeywordMatcher()
        entity = _make_entity(
            "PyTorch",
            EntityType.TOOL,
            entity_id="tool:1",
            metadata={"aliases": ["torch"]},
        )
        matcher.load_entities([entity])

        result = matcher.find_entity_by_name(
            "torch", entity_type=EntityType.TOPIC
        )
        assert result is None

    def test_not_found_returns_none(self):
        matcher = EntityKeywordMatcher()
        matcher.load_entities([
            _make_entity("PyTorch", EntityType.TOOL, entity_id="tool:1"),
        ])
        assert matcher.find_entity_by_name("TensorFlow") is None

    def test_no_type_filter_checks_all(self):
        matcher = EntityKeywordMatcher()
        entity = _make_entity("PyTorch", EntityType.TOOL, entity_id="tool:1")
        matcher.load_entities([entity])

        result = matcher.find_entity_by_name("PyTorch", entity_type=None)
        assert result is entity


class TestGetEntityById:
    """Tests for get_entity_by_id."""

    def test_returns_entity_when_found(self):
        matcher = EntityKeywordMatcher()
        entity = _make_entity("PyTorch", EntityType.TOOL, entity_id="tool:1")
        matcher.load_entities([entity])

        assert matcher.get_entity_by_id("tool:1") is entity

    def test_returns_none_when_not_found(self):
        matcher = EntityKeywordMatcher()
        assert matcher.get_entity_by_id("tool:999") is None


class TestGetCachedCount:
    """Tests for get_cached_count."""

    def test_empty_matcher(self):
        matcher = EntityKeywordMatcher()
        counts = matcher.get_cached_count()
        assert counts == {
            "repo": 0,
            "paper": 0,
            "tool": 0,
            "topic": 0,
            "person": 0,
            "aliases": 0,
        }

    def test_counts_after_loading(self):
        matcher = EntityKeywordMatcher()
        matcher.load_entities([
            _make_entity("PyTorch", EntityType.TOOL, entity_id="tool:1"),
            _make_entity("TensorFlow", EntityType.TOOL, entity_id="tool:2"),
            _make_entity("RAG", EntityType.TOPIC, entity_id="topic:1"),
            _make_entity(
                "LangChain",
                EntityType.REPO,
                entity_id="repo:1",
                metadata={"aliases": ["lc", "langchain-lib"]},
            ),
        ])
        counts = matcher.get_cached_count()
        assert counts["tool"] == 2
        assert counts["topic"] == 1
        assert counts["repo"] == 1
        assert counts["paper"] == 0
        assert counts["person"] == 0
        assert counts["aliases"] == 2


class TestMatchedEntity:
    """Tests for the MatchedEntity dataclass."""

    def test_fields(self):
        entity = _make_entity("PyTorch", EntityType.TOOL, entity_id="tool:1")
        matched = MatchedEntity(
            entity=entity, confidence=0.9, match_type="keyword"
        )
        assert matched.entity is entity
        assert matched.confidence == 0.9
        assert matched.match_type == "keyword"
