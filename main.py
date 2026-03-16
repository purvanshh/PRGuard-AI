"""Main application entrypoint for PRGuard AI."""

from __future__ import annotations

import uvicorn

from github.webhook_server import app as webhook_app
from observability.logging import _get_conn as _init_db  # type: ignore
from observability.tracing import configure_tracing
from observability.structured_logging import configure_structured_logging


app = webhook_app


def _configure_logging() -> None:
    configure_structured_logging()


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

