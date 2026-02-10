"""Content classification endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from menos.auth.dependencies import AuthenticatedKeyId
from menos.services.classification import ClassificationService
from menos.services.di import get_classification_service, get_minio_storage, get_surreal_repo
from menos.services.storage import MinIOStorage, SurrealDBRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/content", tags=["classification"])


class ClassifyResponse(BaseModel):
    """Response after classifying content."""

    content_id: str
    tier: str
    quality_score: int
    labels: list[str]
    model: str
    status: str


@router.post("/{content_id}/classify", response_model=ClassifyResponse)
async def classify_content(
    content_id: str,
    key_id: AuthenticatedKeyId,
    force: bool = Query(default=False, description="Force reclassification"),
    classification_service: ClassificationService = Depends(get_classification_service),
    minio_storage: MinIOStorage = Depends(get_minio_storage),
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
):
    """Manually classify a content item.

    Fetches content from storage, runs classification synchronously,
    and stores the result.
    """
    # Get content metadata
    content = await surreal_repo.get_content(content_id)
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    # Check if already classified (unless force)
    if not force and content.metadata.get("classification"):
        existing = content.metadata["classification"]
        return ClassifyResponse(
            content_id=content_id,
            tier=existing.get("tier", ""),
            quality_score=existing.get("quality_score", 0),
            labels=existing.get("labels", []),
            model=existing.get("model", ""),
            status="already_classified",
        )

    # Download content text from MinIO
    try:
        content_bytes = await minio_storage.download(content.file_path)
        content_text = content_bytes.decode("utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download content: {e}") from e

    # Set status to processing
    await surreal_repo.update_content_classification_status(content_id, "processing")

    # Run classification
    result = await classification_service.classify_content(
        content_id=content_id,
        content_text=content_text,
        content_type=content.content_type,
        title=content.title or "Untitled",
    )

    if not result:
        await surreal_repo.update_content_classification_status(content_id, "failed")
        raise HTTPException(status_code=500, detail="Classification failed")

    # Store result
    await surreal_repo.update_content_classification(
        content_id=content_id,
        classification_dict=result.model_dump(),
    )

    return ClassifyResponse(
        content_id=content_id,
        tier=result.tier,
        quality_score=result.quality_score,
        labels=result.labels,
        model=result.model,
        status="completed",
    )
