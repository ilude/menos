"""Webhook callback delivery for pipeline job completion."""

import asyncio
import hashlib
import hmac
import json
import logging
import uuid

import httpx

from menos.config import Settings
from menos.models import PipelineJob

logger = logging.getLogger(__name__)

NAMESPACE_MENOS = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


def _callback_event_id(job_id: str) -> str:
    """Generate a deterministic event ID from job ID.

    Uses UUID5 with a fixed namespace for stable, reproducible IDs.

    Args:
        job_id: Pipeline job ID

    Returns:
        Deterministic UUID string
    """
    return str(uuid.uuid5(NAMESPACE_MENOS, job_id))


class CallbackService:
    """Delivers HMAC-signed webhook notifications for completed pipeline jobs."""

    def __init__(self, settings: Settings):
        self.callback_url = settings.callback_url
        self.callback_secret = settings.callback_secret

    async def notify(
        self,
        job: PipelineJob,
        result_dict: dict | None = None,
    ) -> None:
        """Send a webhook notification for a completed job.

        Fire-and-forget: delivery failure is logged but never propagated.

        Args:
            job: Completed pipeline job
            result_dict: Pipeline result data (if completed successfully)
        """
        if not self.callback_url or not self.callback_secret:
            return

        payload = {
            "schema_version": "1",
            "event_id": _callback_event_id(job.id or ""),
            "job_id": job.id,
            "content_id": job.content_id,
            "resource_key": job.resource_key,
            "status": job.status.value if hasattr(job.status, "value") else str(job.status),
            "pipeline_version": job.pipeline_version,
        }

        if result_dict:
            payload["result"] = result_dict

        if job.error_code:
            payload["error_code"] = job.error_code
        if job.error_message:
            payload["error_message"] = job.error_message

        body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        signature = hmac.new(
            self.callback_secret.encode(), body.encode(), hashlib.sha256
        ).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-Menos-Signature": signature,
        }

        # Retry with exponential backoff: 1s, 4s, 16s
        delays = [1, 4, 16]
        for attempt, delay in enumerate(delays, 1):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(self.callback_url, content=body, headers=headers)
                    response.raise_for_status()
                    logger.info(
                        "audit.callback_delivery job_id=%s attempt=%d success=true",
                        job.id,
                        attempt,
                    )
                    return
            except Exception as e:
                logger.warning(
                    "Callback attempt %d/%d failed for job %s: %s",
                    attempt,
                    len(delays),
                    job.id,
                    e,
                )
                if attempt < len(delays):
                    await asyncio.sleep(delay)

        logger.error(
            "audit.callback_delivery job_id=%s attempt=%d success=false",
            job.id,
            len(delays),
        )
