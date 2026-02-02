"""Entity keyword matcher for fast code-based entity detection."""

from dataclasses import dataclass

from Levenshtein import distance

from menos.models import EntityModel, EntityType
from menos.services.normalization import is_word_boundary_match, normalize_name


@dataclass
class MatchedEntity:
    """Result of matching an entity in text."""

    entity: EntityModel
    confidence: float  # 0.0-1.0
    match_type: str  # "keyword", "alias", "fuzzy"


class EntityKeywordMatcher:
    """Fast, code-based entity detection using keyword matching.

    This class caches known entities from the database for fast lookup,
    avoiding the need for LLM calls for previously-seen entities.
    """

    def __init__(self):
        """Initialize the matcher with empty caches."""
        # Cache of known entities by type, keyed by normalized_name
        self.known_repos: dict[str, EntityModel] = {}
        self.known_papers: dict[str, EntityModel] = {}
        self.known_tools: dict[str, EntityModel] = {}
        self.known_topics: dict[str, EntityModel] = {}
        self.known_persons: dict[str, EntityModel] = {}

        # Alias map: normalized alias -> entity normalized_name
        self.alias_map: dict[str, tuple[str, EntityType]] = {}

        # All entities by ID for quick lookup
        self.entities_by_id: dict[str, EntityModel] = {}

    def _get_cache_for_type(self, entity_type: EntityType) -> dict[str, EntityModel]:
        """Get the appropriate cache for an entity type."""
        cache_map = {
            EntityType.REPO: self.known_repos,
            EntityType.PAPER: self.known_papers,
            EntityType.TOOL: self.known_tools,
            EntityType.TOPIC: self.known_topics,
            EntityType.PERSON: self.known_persons,
        }
        return cache_map.get(entity_type, {})

    def load_entities(self, entities: list[EntityModel]) -> None:
        """Load entities into cache for fast matching.

        Args:
            entities: List of entities to cache
        """
        # Clear existing caches
        self.known_repos.clear()
        self.known_papers.clear()
        self.known_tools.clear()
        self.known_topics.clear()
        self.known_persons.clear()
        self.alias_map.clear()
        self.entities_by_id.clear()

        for entity in entities:
            cache = self._get_cache_for_type(entity.entity_type)
            cache[entity.normalized_name] = entity

            if entity.id:
                self.entities_by_id[entity.id] = entity

            # Index aliases
            aliases = entity.metadata.get("aliases", []) if entity.metadata else []
            for alias in aliases:
                normalized_alias = normalize_name(alias)
                self.alias_map[normalized_alias] = (
                    entity.normalized_name,
                    entity.entity_type,
                )

    def find_in_text(
        self,
        text: str,
        entity_types: list[EntityType] | None = None,
    ) -> list[MatchedEntity]:
        """Find known entities mentioned in text.

        Uses word boundary matching to avoid partial matches (e.g., "graph"
        should not match "graphql").

        Args:
            text: Text to search
            entity_types: Optional filter by entity types

        Returns:
            List of matched entities with confidence scores
        """
        if not text:
            return []

        text_lower = text.lower()
        matches: list[MatchedEntity] = []
        seen_entities: set[str] = set()  # Avoid duplicate matches

        types_to_check = entity_types or list(EntityType)

        for entity_type in types_to_check:
            cache = self._get_cache_for_type(entity_type)

            for normalized, entity in cache.items():
                if entity.id in seen_entities:
                    continue

                # Check canonical name
                if is_word_boundary_match(entity.name.lower(), text_lower):
                    matches.append(
                        MatchedEntity(
                            entity=entity,
                            confidence=0.9,  # High confidence for exact match
                            match_type="keyword",
                        )
                    )
                    seen_entities.add(entity.id or normalized)
                    continue

                # Check aliases
                aliases = entity.metadata.get("aliases", []) if entity.metadata else []
                for alias in aliases:
                    if is_word_boundary_match(alias.lower(), text_lower):
                        matches.append(
                            MatchedEntity(
                                entity=entity,
                                confidence=0.85,
                                match_type="alias",
                            )
                        )
                        seen_entities.add(entity.id or normalized)
                        break

        return matches

    def fuzzy_find_entity(
        self,
        name: str,
        entity_type: EntityType | None = None,
        max_distance: int = 2,
    ) -> EntityModel | None:
        """Find entity allowing for typos/variations.

        Args:
            name: Name to search for
            entity_type: Optional filter by entity type
            max_distance: Maximum Levenshtein distance

        Returns:
            Best matching entity or None
        """
        normalized = normalize_name(name)

        types_to_check = [entity_type] if entity_type else list(EntityType)

        for etype in types_to_check:
            cache = self._get_cache_for_type(etype)

            # Exact match first
            if normalized in cache:
                return cache[normalized]

            # Fuzzy match
            for known_normalized, entity in cache.items():
                if distance(normalized, known_normalized) <= max_distance:
                    return entity

        return None

    def find_entity_by_name(
        self,
        name: str,
        entity_type: EntityType | None = None,
    ) -> EntityModel | None:
        """Find entity by exact name match.

        Checks both normalized names and aliases.

        Args:
            name: Name to search for
            entity_type: Optional filter by entity type

        Returns:
            Matching entity or None
        """
        normalized = normalize_name(name)

        # Check direct match
        types_to_check = [entity_type] if entity_type else list(EntityType)

        for etype in types_to_check:
            cache = self._get_cache_for_type(etype)
            if normalized in cache:
                return cache[normalized]

        # Check alias map
        if normalized in self.alias_map:
            entity_normalized, etype = self.alias_map[normalized]
            if entity_type is None or entity_type == etype:
                cache = self._get_cache_for_type(etype)
                return cache.get(entity_normalized)

        return None

    def get_entity_by_id(self, entity_id: str) -> EntityModel | None:
        """Get entity by ID from cache.

        Args:
            entity_id: Entity ID

        Returns:
            Entity or None if not in cache
        """
        return self.entities_by_id.get(entity_id)

    def get_cached_count(self) -> dict[str, int]:
        """Get count of cached entities by type.

        Returns:
            Dictionary of type name to count
        """
        return {
            "repo": len(self.known_repos),
            "paper": len(self.known_papers),
            "tool": len(self.known_tools),
            "topic": len(self.known_topics),
            "person": len(self.known_persons),
            "aliases": len(self.alias_map),
        }
