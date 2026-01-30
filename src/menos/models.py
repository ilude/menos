"""Pydantic models for API request/response."""

from datetime import datetime

from pydantic import BaseModel


class VideoBase(BaseModel):
    """Base video fields."""

    video_id: str
    title: str | None = None
    channel_name: str | None = None
    channel_id: str | None = None
    duration_seconds: int | None = None
    published_at: datetime | None = None
    description: str | None = None
    view_count: int | None = None


class VideoCreate(BaseModel):
    """Request to fetch a video."""

    video_id: str


class VideoSummary(BaseModel):
    """Request to store a summary."""

    summary: str


class Video(VideoBase):
    """Full video response."""

    transcript: str | None = None
    summary: str | None = None
    fetched_at: datetime | None = None

    class Config:
        from_attributes = True


class VideoListItem(VideoBase):
    """Video in list response (no transcript)."""

    summary: str | None = None
    fetched_at: datetime | None = None

    class Config:
        from_attributes = True


class SearchResult(BaseModel):
    """Search result with snippet."""

    video_id: str
    title: str | None
    channel_name: str | None
    snippet: str
    rank: float


class SearchResponse(BaseModel):
    """Search response."""

    query: str
    results: list[SearchResult]
    total: int
