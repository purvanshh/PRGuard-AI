from __future__ import annotations

from typing import Optional, Union
from prguard_ai.task_queue.redis_client import get_redis
from prguard_ai.schemas.context import ReviewContext
from prguard_ai.schemas.agent_output import AgentOutput


def _base_key(pr_id: Union[str, int]) -> str:
    return f"review:ctx:{pr_id}:base"


def _agents_key(pr_id: Union[str, int]) -> str:
    return f"review:ctx:{pr_id}:agents"


def _legacy_key(pr_id: Union[str, int]) -> str:
    return f"review:ctx:{pr_id}"


def store_review_context(pr_id: Union[str, int], context: ReviewContext, ttl_seconds: int = 600) -> None:
    """Store the current review context in Redis with an optional TTL."""
    client = get_redis()
    client.setex(_base_key(pr_id), ttl_seconds, context.model_dump_json())
    agent_payloads = {name: output.model_dump_json() for name, output in context.agent_outputs.items()}
    agents_key = _agents_key(pr_id)
    if agent_payloads:
        client.delete(agents_key)
        client.hset(agents_key, mapping=agent_payloads)
        client.expire(agents_key, ttl_seconds)
    else:
        client.delete(agents_key)


def store_review_agent_output(
    pr_id: Union[str, int],
    agent_name: str,
    output: AgentOutput,
    ttl_seconds: int = 600,
) -> None:
    """Persist a single agent output without overwriting sibling agent updates."""
    client = get_redis()
    client.hset(_agents_key(pr_id), agent_name, output.model_dump_json())
    client.expire(_agents_key(pr_id), ttl_seconds)
    client.expire(_base_key(pr_id), ttl_seconds)


def get_review_context(pr_id: Union[str, int]) -> Optional[ReviewContext]:
    """Retrieve the review context from Redis for the given PR ID."""
    client = get_redis()
    data = client.get(_base_key(pr_id))
    if not data:
        data = client.get(_legacy_key(pr_id))
    if not data:
        return None
    # Support both bytes/str input
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    context = ReviewContext.model_validate_json(data)

    raw_outputs = client.hgetall(_agents_key(pr_id))
    if raw_outputs:
        merged_outputs = dict(context.agent_outputs)
        for agent_name, payload in raw_outputs.items():
            if isinstance(agent_name, bytes):
                agent_name = agent_name.decode("utf-8")
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            merged_outputs[str(agent_name)] = AgentOutput.model_validate_json(payload)
        context.agent_outputs = merged_outputs

    return context
