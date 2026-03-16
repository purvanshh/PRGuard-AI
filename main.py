"""Entry point for running the PRGuard AI FastAPI server."""

import uvicorn

from github.webhook_server import app


def run() -> None:
    """Run the FastAPI application using Uvicorn."""
    uvicorn.run(
        "github.webhook_server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    run()

