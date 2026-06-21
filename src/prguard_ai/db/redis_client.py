from __future__ import annotations

from typing import Optional, Union
from prguard_ai.task_queue.redis_client import get_redis
from prguard_ai.schemas.context import ReviewContext


def store_review_context(pr_id: Union[str, int], context: ReviewContext, ttl_seconds: int = 600) -> None:
    """Store the current review context in Redis with an optional TTL."""
    client = get_redis()
    client.setex(f"review:ctx:{pr_id}", ttl_seconds, context.model_dump_json())


def get_review_context(pr_id: Union[str, int]) -> Optional[ReviewContext]:
    """Retrieve the review context from Redis for the given PR ID."""
    client = get_redis()
    data = client.get(f"review:ctx:{pr_id}")
    if not data:
        return None
    # Support both bytes/str input
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return ReviewContext.model_validate_json(data)
