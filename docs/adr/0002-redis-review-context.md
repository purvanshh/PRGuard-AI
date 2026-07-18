# ADR 0002: Redis Review Context

Store active review context in Redis because refinement rounds need fast shared state across multiple Celery tasks.
