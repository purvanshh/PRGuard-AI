# ADR 0001: Celery Orchestration

Use Celery workers for agent execution so PR analysis can fan out, retry independently, and survive API process restarts.
