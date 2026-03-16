"""Main application entrypoint for PRGuard AI."""

from __future__ import annotations

import logging
import sys

import uvicorn

from config.settings import settings
from github.webhook_server import app as webhook_app
from observability.logging import _get_conn as _init_db  # type: ignore
from observability.tracing import configure_tracing


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


def startup() -> None:
    _configure_logging()
    configure_tracing(service_name="prguard-api")
    _init_db()


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

