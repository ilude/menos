"""SQLite database with FTS5 full-text search."""

import aiosqlite

from menos.config import settings

SCHEMA = """
-- Core video table
CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    title TEXT,
    channel_name TEXT,
    channel_id TEXT,
    duration_seconds INTEGER,
    published_at TEXT,
    description TEXT,
    view_count INTEGER,
    transcript TEXT,
    summary TEXT,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT
);

-- Full-text search index
CREATE VIRTUAL TABLE IF NOT EXISTS videos_fts USING fts5(
    video_id,
    title,
    channel_name,
    transcript,
    summary,
    content='videos',
    content_rowid='rowid'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS videos_ai AFTER INSERT ON videos BEGIN
    INSERT INTO videos_fts(rowid, video_id, title, channel_name, transcript, summary)
    VALUES (
        new.rowid, new.video_id, new.title, new.channel_name,
        new.transcript, new.summary
    );
END;

CREATE TRIGGER IF NOT EXISTS videos_ad AFTER DELETE ON videos BEGIN
    INSERT INTO videos_fts(
        videos_fts, rowid, video_id, title, channel_name, transcript, summary
    )
    VALUES (
        'delete', old.rowid, old.video_id, old.title, old.channel_name,
        old.transcript, old.summary
    );
END;

CREATE TRIGGER IF NOT EXISTS videos_au AFTER UPDATE ON videos BEGIN
    INSERT INTO videos_fts(
        videos_fts, rowid, video_id, title, channel_name, transcript, summary
    )
    VALUES (
        'delete', old.rowid, old.video_id, old.title, old.channel_name,
        old.transcript, old.summary
    );
    INSERT INTO videos_fts(rowid, video_id, title, channel_name, transcript, summary)
    VALUES (
        new.rowid, new.video_id, new.title, new.channel_name,
        new.transcript, new.summary
    );
END;
"""


async def get_db() -> aiosqlite.Connection:
    """Get database connection."""
    db = await aiosqlite.connect(settings.database_path)
    db.row_factory = aiosqlite.Row
    return db


async def init_db():
    """Initialize database schema."""
    db = await get_db()
    try:
        await db.executescript(SCHEMA)
        await db.commit()
    finally:
        await db.close()


async def get_video(video_id: str) -> dict | None:
    """Get video by ID."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM videos WHERE video_id = ?", (video_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def upsert_video(video_id: str, **fields) -> dict:
    """Insert or update video."""
    db = await get_db()
    try:
        # Check if exists
        cursor = await db.execute(
            "SELECT video_id FROM videos WHERE video_id = ?", (video_id,)
        )
        exists = await cursor.fetchone()

        if exists:
            # Update
            set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
            await db.execute(
                f"UPDATE videos SET {set_clause} WHERE video_id = ?",
                (*fields.values(), video_id),
            )
        else:
            # Insert
            fields["video_id"] = video_id
            cols = ", ".join(fields.keys())
            placeholders = ", ".join("?" * len(fields))
            await db.execute(
                f"INSERT INTO videos ({cols}) VALUES ({placeholders})",
                tuple(fields.values()),
            )

        await db.commit()
        return await get_video(video_id)
    finally:
        await db.close()


async def list_videos(
    channel: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """List videos with optional filters."""
    db = await get_db()
    try:
        query = """
            SELECT video_id, title, channel_name, channel_id, duration_seconds,
                   published_at, view_count, summary, fetched_at
            FROM videos
        """
        params = []

        if channel:
            query += " WHERE channel_name LIKE ?"
            params.append(f"%{channel}%")

        query += " ORDER BY fetched_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def search_videos(query: str, limit: int = 20) -> list[dict]:
    """Full-text search across videos."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT
                v.video_id,
                v.title,
                v.channel_name,
                snippet(videos_fts, 3, '<mark>', '</mark>', '...', 32) as snippet,
                bm25(videos_fts) as rank
            FROM videos_fts
            JOIN videos v ON videos_fts.video_id = v.video_id
            WHERE videos_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def delete_video(video_id: str) -> bool:
    """Delete video by ID."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "DELETE FROM videos WHERE video_id = ?", (video_id,)
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()
