# Contributing to PRGuard AI

Thanks for your interest in contributing! This project is a polished open-source AI-powered PR review tool.

## 1. Getting Started

```bash
git clone https://github.com/your-org/prguard-ai.git
cd prguard-ai
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set required environment variables in `.env`:

| Variable | Required | Description |
|---|---|---|
| `DEEPSEEK_API_KEY` | Yes | DeepSeek API key for LLM analysis |
| `DATABASE_URL` | Yes | PostgreSQL connection string (e.g. `postgresql+asyncpg://user:pass@localhost:5432/prguard`) |
| `REDIS_URL` | Yes | Redis URL for Celery broker (e.g. `redis://localhost:6379/0`) |
| `GITHUB_TOKEN` | No | GitHub token for private repos (rate-limit boost) |
| `SECRET_KEY` | Yes | Webhook signing secret |

## 2. Running the Full Stack (Docker Compose)

```bash
docker compose up --build
```

This starts:
- **API** on `http://localhost:8000` — health check at `/health`
- **Dashboard** at `/dashboard`
- **2 Celery workers** — process analysis tasks
- **PostgreSQL** — persistent storage
- **Redis** — message broker & result backend

### Running locally (no Docker)

```bash
# Start Redis & PostgreSQL manually, then:
uvicorn prguard_ai.main:app --reload --port 8000
celery -A prguard_ai.task_queue.celery_app worker --loglevel=info
```

## 3. Running Tests

```bash
# Full test suite (251 tests, 79% coverage)
pytest

# Lint
ruff check src/ tests/

# Type check
mypy src/
```

## 4. Project Structure

```
src/prguard_ai/
├── agents/             # Analysis agents (3: security, reliability, confidence)
├── analysis/           # Core analysis pipeline + arbitrator
├── config/             # Settings (pydantic-settings)
├── confidence/         # Confidence scoring
├── cost/               # LLM budget management
├── dashboard/          # FastAPI dashboard app
├── db/                 # SQLAlchemy models + migrations (Alembic)
├── gh_client/          # GitHub integration (webhooks, GraphQL client)
├── llm/                # LLM provider abstraction (OpenAI, NVIDIA)
├── schemas/            # Pydantic models
├── security/           # Security analysis agent
├── reliability/        # Reliability analysis agent
├── task_queue/         # Celery tasks + worker configuration
└── main.py             # FastAPI application entry point
```

The system uses **14 analysis tools** across **3 agent personas** (security, reliability, confidence), orchestrated by a **router** that selects the optimal LLM model per task.

## 5. Adding a New Analysis Agent

1. Create a module under `src/prguard_ai/agents/`, e.g. `performance_agent.py`.
2. Implement a function returning `schemas.agent_output.AgentOutput`:

```python
def analyze_performance(diff_text: str, repo_metadata: dict | None = None) -> AgentOutput:
    ...
```

3. Wire it into:
   - `src/prguard_ai/task_queue/tasks.py` — add a Celery task.
   - `src/prguard_ai/gh_client/webhook.py` — enqueue the new task.
4. Add tests in `tests/`.

## 6. Pull Requests

- Keep changes focused.
- Add or update tests.
- Update `README.md` or `docs/` if behavior changes.
- Ensure `pytest` passes and `ruff check .` is clean.

We welcome contributions that improve security, reliability, developer experience, or agent quality.

