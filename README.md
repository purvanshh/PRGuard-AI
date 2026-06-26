<div align="center">

# PRGuard AI

**A production-grade, multi-agent pull request review system.**

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Celery](https://img.shields.io/badge/Celery-5.x-37814A?logo=celery&logoColor=white)](https://docs.celeryq.dev)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-336791?logo=postgresql&logoColor=white)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://docker.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/purvanshh/PRGuard-AI/actions/workflows/ci.yml/badge.svg)](https://github.com/purvanshh/PRGuard-AI/actions)

</div>

---

PRGuard AI integrates with GitHub via webhooks and orchestrates a multi-agent analysis pipeline over every incoming pull request. Three independent agents — **Style**, **Logic**, and **Security** — run in parallel as Celery tasks. Their initial findings are persisted in a Redis-backed shared context store. The agents then undergo an iterative refinement loop moderated by a **Coordinator Agent** (up to three rounds), cross-examining each other's findings before converging. A **Confidence Arbitrator** aggregates the final outputs, computes weighted confidence scores, detects inter-agent disagreements, and posts a structured review comment with optional inline annotations directly to the pull request.

The system is built for production: asynchronous task queues with retry logic, PostgreSQL audit logging, circuit breakers on LLM calls, Redis-backed token budgeting, HMAC webhook verification, replay attack protection, rate limiting, sandboxed repository cloning with LRU-evicted caching, and structured JSON logging with OpenTelemetry trace propagation.

---

## Table of Contents

- [Architecture](#architecture)
- [Example Output](#example-output)
- [Agent Breakdown](#agent-breakdown)
- [Confidence Scoring](#confidence-scoring)
- [Production Features](#production-features)
- [Setup](#setup)
- [GitHub Webhook Configuration](#github-webhook-configuration)
- [Environment Variables](#environment-variables)
- [API Endpoints](#api-endpoints)
- [Repository Structure](#repository-structure)
- [Security](#security)
- [Evaluation](#evaluation)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## Architecture

```mermaid
flowchart TD
    GH["GitHub (PR opened / updated)"]
    GH -->|"POST /webhook"| FW

    subgraph FW["FastAPI Server"]
        direction LR
        HMAC["HMAC Sig\nVerification"] --> REPLAY["Replay\nProtection"]
        REPLAY --> TS["Timestamp\nValidation"]
        TS --> RL["Rate Limiter\n(repo + inst.)"]
        RL --> CLONE["Repo Cache\n& Sandbox"]
        CLONE --> IDX["ChromaDB\nIndexing"]
    end

    FW -->|"enqueue review_pr"| CQ

    subgraph CQ["Celery + Redis Task Queue"]
        direction TB
        ORCH["Orchestrator Task"] -->|"round 0 parallel run"| INIT["Style / Logic / Security Agents"]
        INIT -->|"store context"| REDIS[("Redis Context Store")]
        REDIS -->|"refinement loop (rounds 1-3)"| REF["Refinement & Dialogue Pass"]
        REF -->|"stopping conditions check"| COORD["Coordinator Agent"]
        COORD -->|"if converged"| ARB["Confidence Arbitrator"]
    end

    ARB --> C1["PR Comment"]
    ARB --> C2["Inline Comments"]
    ARB --> C3["Audit Log (PostgreSQL)"]
```

---

## Example Output

The following is a real review posted by PRGuard AI on a test pull request containing intentionally planted vulnerabilities:

> **PRGuard AI Review**
>
> **Confidence Score:** 0.77
>
> **Style**
> No issues detected.
>
> **Logic**
> - `HIGH` (line 30): User-provided `probe_options` is interpolated directly into a shell command, allowing command injection.
> - `MEDIUM` (line 31): `subprocess.run` is executed with `shell=True` inside an async endpoint, which blocks the event loop.
> - `HIGH` (line 41): `fitz.open` may raise on malformed files; the exception is uncaught and will produce a 500 response.
> - `MEDIUM` (line 44): Cache key derived from client-supplied filename causes cache collisions.
> - `LOW` (line 50): The in-memory cache is unbounded and may cause memory exhaustion under load.
>
> **Security**
> - `HIGH` (line 30): User-controlled `probe_options` concatenated into a `shell=True` subprocess call — command injection risk.
>
> **Disagreement Summary**
> - Logic reports high-severity issues; Style does not.
> - Security reports high-severity issues; Style does not.

Medium and high-severity findings are additionally posted as inline comments on the specific diff lines (up to 10 per review).

---

## Agent Breakdown

Each agent runs as an independent Celery task on a dedicated queue with automatic retry (`autoretry_for=(Exception,)`, `retry_backoff=True`, `max_retries=1`) and a hard 5-minute task timeout.

### Style Agent

Checks for consistency with the repository's existing conventions using a two-pass approach:

| Pass | Method | What It Catches |
|------|--------|-----------------|
| Rule-based | Deterministic string matching | Tab indentation, lines exceeding 120 characters |
| LLM-guided | Prompt + ChromaDB code examples | Naming conventions, docstring consistency, file structure |

The agent retrieves semantically similar code from the repository's ChromaDB index to ground the LLM analysis in project-specific conventions.

### Logic Agent

Detects logical defects using AST analysis, pattern matching, and contextual LLM reasoning:

| Pass | Method | What It Catches |
|------|--------|-----------------|
| Rule-based | Pattern matching on added lines | Bare `except:` clauses, unresolved `TODO` markers |
| AST-informed | tree-sitter parse tree summary | Function structure, variable usage, control flow across Python, Go, TypeScript, and Rust |
| LLM-guided | Prompt + AST summary + context lines | Off-by-one errors, null dereferences, boundary conditions, unhandled exceptions |

The agent builds a per-file AST summary via `analysis/ast_parser.py` and provides it alongside surrounding diff context as structured input to the LLM.

### Security Agent

Detects vulnerabilities using pattern matching and security-focused LLM prompting:

| Pass | Method | What It Catches |
|------|--------|-----------------|
| Rule-based | Regex and string detection | `eval()`/`exec()` usage, SQL injection patterns, hardcoded secrets and API keys |
| LLM-guided | Security-specific prompt | Command injection, unsafe deserialization, privilege escalation, SSRF, path traversal |

Each rule-based detection function (`detect_sql_injection`, `detect_eval_usage`, `detect_hardcoded_secrets`) is independently exported and testable.

---

## Confidence Scoring

Every finding carries a `confidence_source` tag that maps to a numeric weight:

| Source | Weight | Meaning |
|--------|--------|---------|
| `rule_based` | **0.9** | Deterministic pattern match — high certainty |
| `llm_reasoning` | **0.6** | LLM-generated finding — moderate certainty |
| `inferred` | **0.3** | Heuristic or indirect signal — low certainty |

**Per-agent score:** `refined = (base_confidence + avg_issue_weight) / 2`, clamped to `[0.0, 1.0]`.

**Aggregate score:** Agent scores are averaged, with a +0.1 boost (capped at 1.0) applied when any high-severity issue exists across any agent.

**Disagreement detection:** The arbitrator compares severity distributions across agents and flags the review when one agent reports high-severity findings that another does not.

---

## Production Features

PRGuard AI has been systematically hardened across twelve production phases:

| Phase | Feature | Description |
|-------|---------|-------------|
| 1 | Async Webhook Processing | Webhook handler returns `202 Accepted` immediately; full pipeline runs asynchronously via Celery `group` + `chain` |
| 2 | LLM Circuit Breaker | Thread-safe circuit breaker on all LLM calls; agents fall back to rule-only mode when the breaker is open |
| 3 | PostgreSQL Audit Logging | SQLAlchemy async ORM replaces SQLite; Alembic manages schema migrations |
| 4 | Comprehensive Health Checks | `/health`, `/health/ready`, and `/health/live` endpoints covering Redis, PostgreSQL, LLM, GitHub, Celery, ChromaDB, disk space, logging, and repository cache |
| 5 | Centralized Configuration | All environment variables and constants consolidated into a Pydantic `Settings` model with fail-fast validation |
| 6 | Redis Token Budgeting | Atomic per-PR token accounting via Redis `WATCH` pipelines with 1-hour TTL; in-memory fallback on Redis failure |
| 7 | Arbitrator Retry and Degradation | Arbitrator retries up to 2× with exponential backoff; posts degraded review if agents partially fail |
| 8 | LLM Output Sanitization | Pydantic validation, HTML escaping, non-printable character stripping, and 20-issue-per-agent cap on all LLM outputs |
| 9 | Production Redis Enforcement | `REDIS_FALLBACK_TO_MEMORY` defaults to `false`; fails fast on connection failure in production |
| 10 | Test Coverage Enforcement | `pytest-cov` with a 70% minimum threshold; 109 tests at 72%+ coverage |
| 11 | Structured JSON Logging | `JsonLogFormatter` across all API and Celery worker logs; OpenTelemetry trace/span ID injection; exception stack trace serialization |
| 12 | Repository Cache | Persistent shallow clone cache with LRU eviction at 10 GB; hard-link copy into analysis sandboxes for near-instant workspace setup |

---

## Setup

### Prerequisites

- Python 3.11+
- Docker and Docker Compose
- A GitHub account with a repository to monitor
- An NVIDIA NIM API key or OpenAI API key

### Docker (Recommended)

```bash
git clone https://github.com/purvanshh/PRGuard-AI.git
cd PRGuard-AI

cp .env.example .env
# Edit .env with your credentials

docker compose up --build
```

This starts four containers:

| Container | Role | Port |
|-----------|------|------|
| `prguard-api` | FastAPI webhook server | 8000 |
| `prguard-worker` | Celery agent worker | — |
| `prguard-redis` | Redis broker and result backend | 6379 |
| `prguard-db` | PostgreSQL audit database | 5432 |

### Local Development

```bash
git clone https://github.com/purvanshh/PRGuard-AI.git
cd PRGuard-AI

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

cp .env.example .env
# Edit .env with your credentials

# Start Redis and PostgreSQL
docker run -d -p 6379:6379 redis:7
docker run -d -p 5432:5432 \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=prguard \
  postgres:15-alpine

# Start the Celery worker
celery -A prguard_ai.task_queue.celery_app.celery_app worker \
  --loglevel=INFO --concurrency=1 \
  -Q style,logic,security,arbitrator,celery

# In a separate terminal, start the API server
python -m prguard_ai.main
```

The server runs on `http://localhost:8000`.

### Running Tests

```bash
pytest
```

The test suite enforces a minimum coverage threshold of 70%. Tests cover diff parsing, agent analysis, confidence scoring, circuit breaker behavior, token budgeting, health checks, sanitization, repository caching, and the end-to-end pipeline.

---

## GitHub Webhook Configuration

1. Navigate to your repository **Settings** > **Webhooks** > **Add webhook**.

2. Configure the webhook:

   | Field | Value |
   |-------|-------|
   | Payload URL | `https://your-server.com/webhook` |
   | Content type | `application/json` |
   | Secret | Value of `GITHUB_WEBHOOK_SECRET` in your `.env` |
   | Events | Pull requests only |
   | Active | Enabled |

3. PRGuard AI processes these PR actions: `opened`, `synchronize`, `ready_for_review`.

4. For local development, expose your server with a tunnel:
   ```bash
   ngrok http 8000
   ```
   Use the generated HTTPS URL as the Payload URL.

### GitHub App Authentication (Optional)

PRGuard AI supports GitHub App authentication for fine-grained, installation-scoped permissions:

```env
GITHUB_APP_ID=your_app_id
GITHUB_APP_INSTALLATION_ID=your_installation_id
GITHUB_APP_PRIVATE_KEY=/path/to/private-key.pem
```

The client falls back to `GITHUB_TOKEN` if App credentials are not provided.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NVIDIA_API_KEY` | Yes | — | NVIDIA NIM API key for LLM analysis |
| `OPENAI_API_KEY` | No | — | OpenAI API key (fallback if `NVIDIA_API_KEY` is not set) |
| `GITHUB_TOKEN` | Yes* | — | GitHub personal access token (fallback if App auth is not configured) |
| `GITHUB_WEBHOOK_SECRET` | Yes | — | Shared secret for HMAC-SHA256 signature verification |
| `REDIS_URL` | No | `redis://redis:6379/0` | Redis connection URL |
| `DATABASE_URL` | No | `postgresql+asyncpg://postgres:postgres@localhost:5432/prguard` | PostgreSQL connection URL |
| `CHROMA_PERSIST_DIR` | No | `.chroma` | ChromaDB vector index persistence directory |
| `REDIS_FALLBACK_TO_MEMORY` | No | `false` | Allow in-memory Redis fallback (for local development only) |
| `REPO_CACHE_DIR` | No | `.repo_cache` | Directory for persistent shallow repository clones |
| `REPO_CACHE_MAX_SIZE_GB` | No | `10.0` | Maximum repository cache size before LRU eviction |
| `MAX_FILES_PER_PR` | No | `50` | Maximum number of files analyzed per pull request |
| `DAILY_LIMIT_USD` | No | `5.0` | Daily LLM spend limit in USD |
| `MAX_TOKENS_PER_PR` | No | `8000` | Maximum tokens consumed per pull request |
| `LLM_CIRCUIT_FAIL_MAX` | No | `5` | Failure threshold before the LLM circuit breaker opens |
| `LLM_CIRCUIT_RESET_TIMEOUT` | No | `60` | Seconds before the circuit breaker attempts recovery |
| `PRGUARD_OFFLINE_MODE` | No | `false` | Disable external calls for offline testing |
| `GITHUB_APP_ID` | No | — | GitHub App ID |
| `GITHUB_APP_INSTALLATION_ID` | No | — | GitHub App installation ID |
| `GITHUB_APP_PRIVATE_KEY` | No | — | PEM private key string or file path |
| `ADMIN_TOKEN` | No | `admin-secret-token` | Bearer token for the `/config` admin endpoint |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | No | `http://localhost:4317` | OpenTelemetry OTLP collector endpoint |

*Required unless GitHub App authentication is configured.*

Reference: [`.env.example`](.env.example)

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/webhook` | GitHub webhook receiver — HMAC-verified, replay-protected |
| `GET` | `/review/{pr_id}` | Retrieve agent outputs and analysis trace for a given PR |
| `GET` | `/health` | Aggregated dependency health check |
| `GET` | `/health/ready` | Kubernetes readiness probe |
| `GET` | `/health/live` | Kubernetes liveness probe |
| `GET` | `/metrics` | Prometheus metrics endpoint |
| `GET` | `/config` | Admin-only configuration view (bearer token required) |
| `WS` | `/stream/{pr_id}` | WebSocket stream for live agent progress events |

---

## Repository Structure

```
prguard-ai/
├── src/
│   └── prguard_ai/
│       ├── agents/          # Style, Logic, Security, Arbitrator, Coordinator agents
│       ├── analysis/        # Diff parsing, AST analysis, repo cache, sandbox, ChromaDB indexing
│       ├── confidence/      # Weighted confidence scoring engine
│       ├── config/          # Pydantic Settings with environment-driven configuration
│       ├── cost/            # LLM budget manager and token tracking
│       ├── dashboard/       # Optional web dashboard
│       ├── db/              # SQLAlchemy models, async session, Redis client
│       ├── gh_client/       # Webhook server, GitHub API client, App authentication
│       ├── llm/             # LLM client with circuit breaker and token budgeting
│       ├── observability/   # Structured JSON logging, OpenTelemetry tracing, Prometheus metrics, event streaming
│       ├── reliability/     # Circuit breaker implementation
│       ├── schemas/         # Pydantic models (AgentOutput, Issue, PullRequestReport, ReviewContext)
│       ├── security/        # Per-repo and per-installation rate limiting
│       └── task_queue/      # Celery app, orchestrator, task definitions, task registry, Redis client
├── alembic/                 # Database migration environment and revisions
├── deploy/                  # Production Docker Compose and Prometheus configuration
├── docs/                    # Architecture documentation, example reviews, runbook
├── fixtures/                # Test fixtures and sample diff data
├── prompts/                 # Agent prompt templates
├── scripts/                 # Utility and maintenance scripts
├── tests/                   # Unit and integration test suite (109 tests, 72%+ coverage)
├── .github/workflows/       # GitHub Actions CI pipeline
├── Dockerfile               # Python 3.11-slim container image
├── docker-compose.yml       # Multi-service orchestration (API, worker, Redis, PostgreSQL)
├── pyproject.toml           # Project metadata and packaging configuration
├── requirements.txt         # Python runtime dependencies
└── .env.example             # Environment variable reference template
```

---

## Security

- **HMAC-SHA256 verification** on every incoming webhook payload
- **Replay protection** via `X-GitHub-Delivery` deduplication backed by Redis with a 5-minute TTL
- **Timestamp validation** rejecting payloads older than 2 minutes
- **Payload size limit** of 5 MB enforced at the HTTP layer
- **Rate limiting** applied per repository and per GitHub App installation
- **Global concurrency control** preventing worker queue saturation
- **Sandboxed repository clones** with guaranteed cleanup on completion
- **LLM output sanitization** — HTML escaping, non-printable character stripping, and per-agent issue caps
- **Secrets never logged** — structured logging masks all sensitive configuration values

---

## Evaluation

PRGuard AI includes an evaluation framework for benchmarking agent accuracy against labeled datasets:

1. **Dataset**: Hand-annotated PR diffs in `evaluation/dataset/` with expected issues mapped to specific lines.
2. **Pipeline**: Each diff is processed through all three agents and the arbitrator to produce a detected issue set.
3. **Metrics**: Standard information-retrieval metrics:

   | Metric | Formula |
   |--------|---------|
   | Precision | `TP / (TP + FP)` |
   | Recall | `TP / (TP + FN)` |
   | Confidence | Arbitrator's aggregated confidence score |

Run evaluation against a sample:

```bash
python -c "
from prguard_ai.evaluation.evaluator import evaluate_pr
import json, pathlib
result = evaluate_pr(pathlib.Path('evaluation/dataset/example_1.json').read_text())
print(json.dumps(result, indent=2))
"
```

---

## Roadmap

- [x] Multi-language support — Python, Go, TypeScript, and Rust via tree-sitter
- [x] Async webhook processing with Celery group/chain workflows
- [x] LLM circuit breaker with rule-only fallback mode
- [x] PostgreSQL audit logging with Alembic migrations
- [x] Comprehensive health checks with readiness and liveness probes
- [x] Centralized Pydantic settings with fail-fast validation
- [x] Redis-backed token budgeting with atomic per-PR accounting
- [x] Arbitrator retry logic and graceful degradation on partial agent failures
- [x] LLM output validation and HTML sanitization
- [x] Structured JSON logging with OpenTelemetry trace propagation
- [x] Persistent repository cache with LRU eviction
- [ ] Per-repository `.prguard.yml` configuration for custom thresholds
- [ ] GitHub App Marketplace listing for one-click installation
- [ ] PR suggestion API integration for auto-fixable findings
- [ ] Incremental review — re-analyze only changed files on `synchronize` events
- [ ] Domain-specific fine-tuning on labeled PR review datasets
- [ ] Slack and Microsoft Teams notification integration
- [ ] Self-hosted LLM support via Ollama or vLLM backends
- [ ] Dashboard v2 — real-time review progress, historical analytics, cost tracking

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines, branching conventions, and pull request requirements.

---

## License

[MIT](LICENSE)

---

<div align="center">

Built by [Purvansh Sahu](https://github.com/purvanshh) &nbsp;|&nbsp; 3rd Year CS at Scaler School of Technology + BITS Pilani &nbsp;|&nbsp; ML Research Intern at IIT Madras

LLM backend powered by NVIDIA NIM

</div>
