"""Main application entrypoint for PRGuard AI."""

from __future__ import annotations

import logging
import sys

import redis
import uvicorn

from config.settings import settings
from github.webhook_server import app as webhook_app
from observability.logging import _get_conn as _init_db  # type: ignore


app = webhook_app


def _configure_logging() -> None:
    handler = logging.StreamHandler(stream=sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s | agent=%(name)s | event=%(levelname)s | message=%(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)


def _verify_redis() -> None:
    client = redis.Redis.from_url(settings.redis_url)
    try:
        client.ping()
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"Failed to connect to Redis at {settings.redis_url}") from exc


def startup() -> None:
    _configure_logging()
    _init_db()
    _verify_redis()


def run() -> None:
    startup()
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    run()

