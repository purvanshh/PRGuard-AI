"""Main application entrypoint for PRGuard AI."""

from __future__ import annotations

import uvicorn

from prguard_ai.gh_client.webhook_server import app as webhook_app
from prguard_ai.db.session import init_db, run_async
from prguard_ai.observability.tracing import configure_tracing
from prguard_ai.observability.structured_logging import configure_structured_logging


app = webhook_app


def _configure_logging() -> None:
    configure_structured_logging()


def startup() -> None:
    _configure_logging()
    configure_tracing(service_name="prguard-api")
    run_async(init_db())


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

