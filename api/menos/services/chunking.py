"""Text chunking service for content splitting."""


class ChunkingService:
    """Service for splitting content into chunks."""

    def __init__(self, chunk_size: int = 1024, overlap: int = 150):
        """Initialize chunking service.

        Args:
            chunk_size: Target size for each chunk in characters
            overlap: Number of overlapping characters between chunks
        """
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_text(self, text: str) -> list[str]:
        """Split text into overlapping chunks.

        Args:
            text: Text to chunk

        Returns:
            List of text chunks
        """
        if not text:
            return []

        if len(text) <= self.chunk_size:
            return [text]

        chunks = []
        start = 0

        while start < len(text):
            # Get chunk end, don't go past text length
            end = min(start + self.chunk_size, len(text))

            # Try to break at word boundary if not at end
            if end < len(text):
                # Look for last space before chunk_size
                last_space = text.rfind(" ", start, end)
                if last_space > start:
                    end = last_space

            chunk = text[start:end].strip()
            if chunk:  # Only add non-empty chunks
                chunks.append(chunk)

            # If we've reached the end, stop
            if end >= len(text):
                break

            # Move start position, accounting for overlap
            new_start = end - self.overlap
            # Ensure we make progress (at least 1 character forward)
            if new_start <= start:
                new_start = start + 1
            start = new_start

        return chunks

    def chunk_lines(self, text: str, lines_per_chunk: int = 20) -> list[str]:
        """Split text into chunks by line count.

        Args:
            text: Text to chunk
            lines_per_chunk: Number of lines per chunk

        Returns:
            List of text chunks
        """
        lines = text.split("\n")
        chunks = []

        for i in range(0, len(lines), lines_per_chunk):
            chunk_lines = lines[i : i + lines_per_chunk]
            chunk = "\n".join(chunk_lines).strip()
            if chunk:
                chunks.append(chunk)

        return chunks
