"""Video CRUD endpoints."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from menos import database as db
from menos.fetchers import fetch_metadata, fetch_transcript
from menos.models import Video, VideoListItem, VideoSummary

router = APIRouter(prefix="/videos", tags=["videos"])


@router.post("/{video_id}", response_model=Video)
async def create_video(video_id: str, background_tasks: BackgroundTasks):
    """Fetch and store a YouTube video's transcript and metadata."""
    existing = await db.get_video(video_id)
    if existing and existing.get("transcript"):
        return existing

    metadata = await fetch_metadata(video_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Video not found or API error")

    transcript = await asyncio.to_thread(fetch_transcript, video_id)

    video = await db.upsert_video(
        video_id,
        transcript=transcript,
        **metadata,
    )
    return video


@router.get("/{video_id}", response_model=Video)
async def get_video(video_id: str):
    """Get a stored video by ID."""
    video = await db.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


@router.get("/{video_id}/transcript")
async def get_transcript(video_id: str):
    """Get just the transcript for a video."""
    video = await db.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return {"video_id": video_id, "transcript": video.get("transcript")}


@router.put("/{video_id}/summary", response_model=Video)
async def update_summary(video_id: str, body: VideoSummary):
    """Store a client-generated summary."""
    existing = await db.get_video(video_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Video not found")

    video = await db.upsert_video(video_id, summary=body.summary)
    return video


@router.delete("/{video_id}")
async def delete_video(video_id: str):
    """Delete a stored video."""
    deleted = await db.delete_video(video_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Video not found")
    return {"deleted": True}


@router.get("", response_model=list[VideoListItem])
async def list_videos(
    channel: Annotated[str | None, Query(description="Filter by channel name")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """List stored videos with optional filters."""
    return await db.list_videos(channel=channel, limit=limit, offset=offset)
