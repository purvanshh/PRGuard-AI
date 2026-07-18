# PRGuard AI: Comprehensive Technical Study Guide

This document provides an in-depth architectural and implementation analysis of PRGuard AI, a multi-agent pull request review system. It is designed for engineers who wish to understand, extend, or replicate this system.

---

## 1. Project Overview

### 1.1 What the Project Does (In Practical Terms)

PRGuard AI is an automated code review pipeline that hooks into GitHub repositories via webhooks. On every pull request event (`opened`, `synchronize`, `ready_for_review`), it runs three independent analysis agents in parallel — **Style**, **Logic**, and **Security** — each combining deterministic rule-based checks with LLM-powered reasoning. A fourth component, the **Confidence Arbitrator**, aggregates all findings, detects disagreements between agents, computes a weighted confidence score, and posts the results as a structured PR comment with inline comments on specific lines.

The system is not a passive linter. It actively surfaces issues that require contextual reasoning — such as command injection risks that span multiple lines, or logical edge cases that depend on function control flow. It does so by combining:

1. **Pattern matching** (regex, string detection) for deterministic, high-confidence findings.
2. **AST analysis** using tree-sitter to extract structural summaries of changed code.
3. **LLM reasoning** via NVIDIA NIM API (OpenAI-compatible) for deeper, context-aware analysis.
4. **Multi-round iterative dialogue** between agents to refine findings through structured debate.

### 1.2 Core Problem It Solves

Manual code review does not scale consistently. Different reviewers apply different standards. Critical issues (security vulnerabilities, logic errors) are frequently missed under time pressure. PRGuard AI augments human review by providing a consistent, always-on second opinion with configurable confidence scoring.

The specific problem is **missed issues in PRs** — specifically:

- Security flaws: command injection, SQL injection, hardcoded secrets, unsafe deserialization.
- Logic bugs: unhandled exceptions, bare `except:` clauses, null handling errors, off-by-one boundary conditions.
- Style inconsistencies: naming conventions, formatting drift, unreadable UI styles.

### 1.3 Key Features and Capabilities

| Feature | Implementation |
|---------|---------------|
| Multi-agent parallel execution | Three Celery tasks (`run_style_agent`, `run_logic_agent`, `run_security_agent`) dispatched simultaneously from the webhook handler. |
| Dual-mode analysis per agent | Each agent runs rule-based checks first, then optionally invokes LLM with constructed prompt. |
| Confidence scoring with weighted sources | Issues tagged as `rule_based` (0.9 weight), `llm_reasoning` (0.6), or `inferred` (0.3). Scores blended per-agent, then aggregated. |
| Disagreement detection | Arbitrator compares severity distributions across agents; flags cases where one agent reports high-severity issues and another reports none. |
| Inline commenting | Up to 10 medium/high-severity issues posted as inline PR review comments on specific file:line. |
| HMAC verification | GitHub webhook payloads verified via `X-Hub-Signature-256`. |
| Replay protection | `X-GitHub-Delivery` ID deduplicated in Redis with 5-minute TTL. |
| Rate limiting | Sliding-window rate limits: 10 PRs/hour per repo, 100 PRs/day per GitHub installation. |
| Cost budgeting | Daily $5 USD cap per repository on LLM calls (enforced via Redis sorted set). |
| Repository caching with LRU eviction | Shallow clones cached and evicted via LRU when total exceeds configurable size limit. |
| Async event streaming | WebSocket endpoint (`/stream/{pr_id}`) for live progress events. |
| Audit logging | PostgreSQL persistence of agent executions, latencies, token usage, and costs (via SQLAlchemy + Alembic). |
| Circuit breaker for LLM | Thread-safe state machine prevents cascading failures when LLM API degrades. |
| Prometheus metrics | `/metrics` endpoint with counters, histograms, gauges for PRs, tokens, errors, circuit breaker state. |
| Structured JSON logging | All logs emitted as JSON with OTel trace/span context, injectable `pr_id` and `agent` fields. |
| Comprehensive health checks | Readiness/liveness endpoints checking Redis, PostgreSQL, LLM, GitHub API, Celery workers, disk space. |
| Evaluation framework | Precision, recall, F1 scoring against hand-annotated datasets; CLI entrypoint for batch evaluation. |
| Multi-round iterative dialogue | Coordinator agent orchestrates up to 3 refinement rounds between agents with early stopping. |

---

## 2. High-Level Architecture

### 2.1 Overall System Design

The system is a **layered, event-driven architecture** with an HTTP-triggered async pipeline. It follows a **fan-out / fan-in** pattern: the webhook dispatches three agent tasks simultaneously, optionally runs multi-round iterative refinement, then aggregates via the arbitrator.

```
┌─────────────────────┐
│   GitHub Webhook    │
│  (POST /webhook)   │
└──────────┬──────────┘
           │
           ▼
┌────────────────────────────────────┐
│  FastAPI Server                  │
│  ┌──────────────────────────┐   │
│  │  Security Validation     │   │◄──── HMAC, rate limit, replay check
│  │  Health Endpoints        │   │◄──── /health, /health/ready, /health/live
│  │  Metrics Endpoint        │   │◄──── /metrics (Prometheus)
│  │  Config Endpoint         │   │◄──── /config (Bearer auth, masked)
│  │  WebSocket Stream        │   │◄──── /stream/{pr_id}
│  └──────────────────────────┘   │
└─────────┬───────────────────────┘
          │
          │  Celery chain: prepare → agent group → refine(×N) → arbitrate → post
          ▼
┌────────────────────────────────────────────────────────────┐
│  Celery + Redis (Broker + Result Backend)                  │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  Orchestrator (review_pr task)                       │ │
│  │  1. prepare_repository() → clone/fetch cache        │ │
│  │  2. group(style, logic, security) — parallel        │ │
│  │  3. iterative refinement (up to 3 rounds)           │ │
│  │  4. arbitrator.aggregate()                          │ │
│  │  5. post_review() — summary + inline comments       │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                            │
│  ┌──────────┬──────────┬────────────┬──────────────┐    │
│  │ Style    │ Logic    │ Security   │ Arbitrator   │    │
│  │ Agent    │ Agent    │ Agent     │ Agent        │    │
│  └────┬─────┴────┬─────┴─────┬────┴──────┬───────┘    │
│       │          │           │           │              │
│       └──────────┴───────────┘           │              │
│                │                         │              │
│                ▼                         ▼              │
│       ┌─────────────────┐  ┌────────────────────┐      │
│       │ Coordinator     │  │ Circuit Breaker    │      │
│       │ (debate loop)   │  │ (LLM resilience)   │      │
│       └─────────────────┘  └────────────────────┘      │
└────────────────────────────────────────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────┐
│  PostgreSQL (SQLAlchemy async + Alembic)      │
│  - agent_logs (executions, timing, tokens)    │
│  - llm_usage (token counts, cost per model)  │
│  - Migrations via Alembic                     │
└────────────────────────────────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────┐
│  GitHub API Client                            │
│  - POST review comment                        │
│  - POST inline comments (up to 10)            │
│  - GET diff for analysis                      │
└────────────────────────────────────────────────┘
```

### 2.2 Major Components and Their Interactions

| Component | File | Responsibility |
|----------|------|--------------|
| **Webhook Server** | `gh_client/webhook_server.py` | FastAPI app; receives GitHub webhooks; performs security validation; manages repo cache; exposes health, metrics, config, and WebSocket endpoints. |
| **Orchestrator** | `task_queue/orchestrator.py` | Celery task `review_pr` that chains repo preparation → parallel agent group → iterative refinement → arbitration → comment posting. |
| **Style Agent** | `agents/style_agent.py` | Detects style issues via rule-based checks (tab indentation, long lines, frontend design regression) and LLM-guided style analysis. |
| **Logic Agent** | `agents/logic_agent.py` | Detects logical defects via pattern matching, AST summary, and LLM reasoning. |
| **Security Agent** | `agents/security_agent.py` | Detects vulnerabilities via pattern matching (SQL injection, eval/exec, hardcoded secrets) and LLM reasoning. |
| **Arbitrator** | `agents/arbitrator_agent.py` | Aggregates agent outputs; computes overall confidence; detects inter-agent disagreements; supports partial (degraded) aggregation. |
| **Coordinator** | `agents/coordinator.py` | Manages multi-round iterative dialogue/debate between agents; decides when to stop refinement. |
| **Diff Parser** | `analysis/diff_parser.py` | Parses unified Git diffs into structured `DiffHunk` and `DiffLine` objects with precise line numbers. |
| **AST Parser** | `analysis/ast_parser.py` | Produces structural summaries (functions, variables, control structures) from source using tree-sitter. Supports Python, Go, TypeScript, Rust. |
| **Repository Cache** | `analysis/repo_cache.py` | Manages shallow-cloned repository cache with LRU eviction and configurable max size. |
| **Repository Indexer** | `analysis/repo_indexer.py` | Indexes repository code in ChromaDB for style retrieval (currently a no-op; ChromaDB disabled). |
| **Repository Sandbox** | `analysis/repo_sandbox.py` | Clones target repository to temporary directory; manages cleanup. |
| **Circuit Breaker** | `reliability/circuit_breaker.py` | Thread-safe state machine (`CLOSED → OPEN → HALF_OPEN → CLOSED`) for LLM client resilience. |
| **LLM Client** | `llm/client.py` | Wrapper around OpenAI client (NVIDIA NIM API); enforces token budgets; handles retry/backoff; integrates with circuit breaker; returns stub responses in offline mode. |
| **Scoring Engine** | `confidence/scoring_engine.py` | Computes per-issue, per-agent, and aggregate confidence scores with weighted sources. |
| **Rate Limiter** | `security/rate_limiter.py` | Redis-backed sliding-window rate limits per repository and per installation. |
| **Budget Manager** | `cost/budget_manager.py` | Enforces daily $5 USD cost cap per repository on LLM calls. |
| **Task Queue** | `task_queue/celery_app.py` | Celery app definition and task wrappers with autoretry, time limits, and per-queue routing. |
| **Redis Client** | `task_queue/redis_client.py` | Centralized Redis client with support for single-node, sentinel, and in-memory modes. |
| **Health Checks** | `observability/health.py` | Comprehensive health checkers (Redis, PostgreSQL, LLM, GitHub, Celery, ChromaDB, disk, logging) aggregated into critical/non-critical buckets. |
| **Metrics** | `observability/metrics.py` | Prometheus counters, histograms, summaries, and gauges for system observability. |
| **Structured Logging** | `observability/structured_logging.py` | JSON log formatter with timestamp, level, OTel trace/span IDs, service, pr_id, agent, and event_type. |
| **Evaluation** | `evaluation/evaluator.py` | Precision/recall/F1 benchmarking against hand-annotated datasets; CLI entrypoint. |
| **Database Models** | `db/models.py` | SQLAlchemy declarative models (`AgentLog`, `LLMUsage`) with async SQLAlchemy + asyncpg. |
| **Database Session** | `db/session.py` | Async engine with connection pooling; `init_db()` for DDL; `run_async()` helper for nested event loop safety. |
| **Alembic** | `alembic/env.py` | Async migration environment, auto-discovers models, supports offline/online modes. |

### 2.3 Data Flow Across the System

1. **Webhook Reception** (`webhook_server.py:188-491`)
   - GitHub sends `POST /webhook` with JSON payload.
   - Server validates HMAC signature, replay ID (Redis), timestamp (2-minute window).
   - Validates rate limits (`check_repo_limit`, `check_installation_limit`).
   - Acquires global concurrency slot (`acquire_global_slot`).
   - Returns `202 Accepted` immediately, enqueues `review_pr` Celery task.

2. **Orchestrator Execution** (`orchestrator.py`)
   - `prepare_repository()`: fetches PR diff via GitHub API, clones or fetches from repo cache.
   - `run_agents()`: dispatches `group(style.s(), logic.s(), security.s())` in parallel.
   - `refine()`: if iterative dialogue enabled, runs coordinator to conduct up to 3 refinement rounds with early stopping.
   - `arbitrate()`: dispatches arbitrator to aggregate confidence and detect disagreements.
   - `post_review()`: formats Markdown review comment, posts summary + up to 10 inline comments.

3. **Agent Execution** (Inside Celery Worker)
   - Each agent:
     - Parses diff using `parse_diff()`.
     - Runs rule-based checks.
     - If LLM is available, invokes `generate_analysis()` with agent-specific prompt.
     - Respects circuit breaker state; if OPEN, skips LLM and falls back to rule-based.
     - Returns `AgentOutput` (agent name, confidence, list of `Issue` objects).

4. **Arbitration**
   - Aggregates agent outputs; supports partial aggregation if agents fail.
   - Calls `aggregate_confidence()` and `detect_agent_disagreements()`.
   - Returns `PullRequestReport`.

5. **Response Posting**
   - Posts review comment via `post_pr_comment()`.
   - Posts up to 10 inline comments via `post_inline_comment()`.
   - Logs execution to PostgreSQL via SQLAlchemy.
   - Releases concurrency slot.

---

## 3. Why This Architecture?

### 3.1 Why This Architecture Was Chosen Over Alternatives

| Alternative | Reason for Rejection |
|-------------|---------------------|
| **Single monolithic agent** | Different issue types (style, logic, security) require fundamentally different detection strategies and domain knowledge. A single LLM prompt would dilute focus. The multi-agent design allows each agent to specialize. |
| **Synchronous HTTP calls to agents** | LLM calls have variable latency (2-30 seconds). Blocking the webhook response would risk GitHub's timeout (10 seconds). Celery provides async execution with bounded wait (60s timeout). |
| **Event-driven (Kafka, RabbitMQ)** | Redis was already required for Celery. Adding another broker increases operational complexity. Redis supports all needed primitives (rate limiting, replay protection, cost bucketing, pub/sub for WebSocket events). |
| **Synchronous agent calls within webhook** | Would couple the API server to agent execution time. Celery allows horizontal scaling of workers independent of the API server. |
| **Single Celery queue** | Using separate queues (`style`, `logic`, `security`, `arbitrator`) enables per-agent concurrency limits, independent retry policies, and queue-specific monitoring. |

### 3.2 Trade-offs

| Trade-off | Impact |
|---------|--------|
| **Celery chain instead of synchronous wait** | The webhook returns immediately (202 Accepted); the orchestrator handles the full lifecycle asynchronously. This eliminates the 60-second blocking window but means the user doesn't get immediate feedback within the webhook response. |
| **PostgreSQL for audit logs** | Adds operational dependency compared to SQLite, but enables concurrent writes from multiple API instances, connection pooling, and Alembic-managed migrations. |
| **Rule-based + LLM hybrid** | The system runs rule-based checks first (fast, deterministic), then falls back to LLM only if needed. This reduces LLM calls and cost, but sacrifices some recall. The trade-off is cost vs. completeness. |
| **No incremental analysis** | Every `synchronize` event re-analyzes the entire diff. The roadmap includes incremental analysis, but current simplicity favors correctness over optimization. |
| **Circuit breaker for LLM** | Adds resilience but may reject legitimate LLM requests during recovery window. Tuned constants (`fail_max=5`, `reset_timeout=60s`) bound the impact. |

### 3.3 When This Architecture Would Fail or Become Inefficient

- **Very large diffs**: Parsing and AST analysis are O(n) in diff size. Diffs with >10,000 lines will exceed the 60-second timeout per agent.
- **Rate limit exhaustion**: If a repository exceeds 10 PRs/hour or an installation exceeds 100 PRs/day, the system returns 429. Under heavy load from a single active repo, other repos may be starved.
- **LLM API outage**: Circuit breaker transitions to OPEN after 5 failures; agents fall back to rule-based checks only. High-severity logic issues requiring LLM reasoning will be missed during the recovery window.
- **Disk space exhaustion**: Repository clones are cached on disk. LRU eviction helps but under sustained load from large repos, disk may fill up.
- **GitHub API rate limits**: Fetching PR diffs and posting comments consume GitHub API quota. The system does not implement GitHub API-side rate limiting.

---

## 4. Tech Stack Breakdown

### 4.1 Languages, Frameworks, Libraries, Databases

| Category | Technology | Version/Notes |
|----------|------------|---------------|
| **Language** | Python | 3.11+ (enforced by `pyproject.toml` and Dockerfile) |
| **Web Framework** | FastAPI | 0.100+ (async, uvicorn host) |
| **Task Queue** | Celery | 5.x (broker: Redis; result backend: Redis) |
| **Message Broker** | Redis | 7 (single-node; supports sentinel mode) |
| **Database** | PostgreSQL | async SQLAlchemy + asyncpg driver |
| **ORM** | SQLAlchemy | 2.0+ async style (declarative models) |
| **Migrations** | Alembic | Async environment with auto-discovery |
| **LLM Client** | openai (NVIDIA NIM) | Uses `openai.OpenAI` with custom base_url |
| **AST Parsing** | tree-sitter | Python bindings; supports Python, Go, TypeScript, Rust |
| **Vector Store** | chromadb | Disabled in current implementation (no-op placeholder) |
| **Schema Validation** | pydantic | v2 (BaseModel, Field, validator) |
| **Settings** | pydantic-settings | v2 (`BaseSettings`) |
| **GitHub Client** | PyGithub | Raw `requests` for diff fetch (GitHub API v3 diff accept header) |
| **Observability** | OpenTelemetry | API, SDK, OTLP gRPC exporter (optional) |
| **Metrics** | prometheus-client | Exposed at `/metrics` endpoint |
| **Structured Logging** | json | Custom `JsonLogFormatter` via stdlib logging |
| **Linting** | flake8 | Configured in `.flake8` (max-line-length=120, ignores formatter rules) |
| **Container** | Docker | `python:3.11-slim` base |
| **Orchestration** | docker-compose | v3.9 (five services: api, worker, redis-data, redis-broker, db) |
| **Testing** | pytest | 237 tests across diff parsing, agents, scoring, full pipeline, health, metrics, DB, circuit breaker, evaluator, model routing, scalability, observability, security, human review, etc. |

### 4.2 Why Each Was Likely Chosen

| Component | Rationale |
|-----------|-----------|
| **FastAPI** | Native async support; automatic OpenAPI docs; Pydantic integration for request/response validation. Uvicorn provides production-grade ASGI server. |
| **Celery** | Mature, battle-tested task queue with proper task routing, time limits, retry policies, and Redis integration. Supports separate queues needed for per-agent concurrency control. |
| **Redis** | Serves triple duty: Celery broker, rate limiting backend, cost bucketing, and pub/sub for WebSocket events. Single-node to sentinel modes supported. |
| **PostgreSQL + SQLAlchemy** | Replaced SQLite for multi-instance deployment support. Async SQLAlchemy with asyncpg provides connection pooling and concurrent write capability. Alembic manages schema migrations. |
| **pydantic v2** | Type-safe settings and schemas; `BaseModel` used everywhere from settings (`config/settings.py`) to schemas (`schemas/agent_output.py`). |
| **PyGithub** (raw `requests` for diff) | PyGithub does not natively support the `application/vnd.github.v3.diff` media type, hence raw `requests.get()` is used in `get_pr_diff()`. |
| **tree-sitter** | Provides accurate syntactic analysis beyond what stdlib `ast` offers (e.g., preserves exact indentation and whitespace). Multi-language support via compileable grammars. |
| **Prometheus** | Industry-standard metrics; `/metrics` endpoint auto-scraped by Prometheus. |
| **OpenTelemetry** | Vendor-neutral tracing. Optional dependency (available under `observability` extra). |
| **Flake8** | Lightweight static analysis; configured to catch common Python issues without overlapping with formatters. |

### 4.3 What Alternatives Could Have Been Used and Why They Weren't

| Alternative | Why Not |
|-------------|--------|
| **Flask** | No native async; FastAPI + Pydantic provides better developer experience. |
| **HTTPX + asyncio** | Would require custom task queue implementation. Celery provides ready-made retry, routing, and monitoring. |
| **Kafka** | Operational overhead disproportionate to throughput. Redis is already present. |
| **SQLite (for audit)** | Replaced by PostgreSQL. Single-writer SQLite cannot support multi-instance deployment. |
| **LangChain** | Overkill for simple prompt construction; raw `openai` client suffices. |
| **Ruff (over flake8)** | Flake8 was chosen for compatibility with existing CI patterns; Ruff remains a future consideration. |

---

## 5. Folder & Code Structure Deep Dive

```
src/prguard_ai/
├── __init__.py                      # Package marker (empty)
├── main.py                          # Entry point: uvicorn server startup
│
├── agents/
│   ├── __init__.py                 # Exports all agents
│   ├── style_agent.py               # Style analysis
│   ├── logic_agent.py              # Logic analysis
│   ├── security_agent.py           # Security analysis
│   ├── arbitrator_agent.py          # Confidence aggregation
│   └── coordinator.py              # Multi-round dialogue/debate loop
│
├── analysis/
│   ├── __init__.py                 # Exports parsers and indexer
│   ├── diff_parser.py              # Unified diff → DiffHunk[]
│   ├── ast_parser.py              # Source → AstSummary (multi-language)
│   ├── repo_cache.py              # Shallow clone cache with LRU eviction
│   ├── repo_indexer.py            # ChromaDB index (DISABLED - no-op)
│   ├── repo_sandbox.py           # Git clone → temp dir (legacy)
│   ├── code_graph.py            # Dependency graph (placeholder)
│   └── container_runner.py      # Docker-in-Docker (placeholder)
│
├── confidence/
│   ├── __init__.py               # Exports engine
│   └── scoring_engine.py         # Weighted confidence logic
│
├── config/
│   ├── __init__.py               # Exports settings
│   └── settings.py               # Pydantic BaseSettings (all env vars)
│
├── cost/
│   ├── __init__.py              # Exports budget manager
│   └── budget_manager.py        # $5/day per-repo LLM cap
│
├── dashboard/
│   ├── __init__.py             # Placeholder
│   └── app.py                  # Dashboard (placeholder)
│
├── db/
│   ├── __init__.py            # Exports
│   ├── models.py              # SQLAlchemy AgentLog, LLMUsage
│   ├── redis_client.py       # Alt Redis client (legacy)
│   └── session.py            # Async engine, connection pool, init_db
│
├── evaluation/
│   ├── __init__.py           # Exports evaluator
│   └── evaluator.py          # Precision/recall/F1 benchmarking + CLI
│
├── gh_client/
│   ├── __init__.py           # Exports
│   ├── webhook_server.py     # FastAPI app with all endpoints
│   ├── github_client.py     # PyGithub wrapper + raw requests
│   └── app_auth.py          # GitHub App authentication (placeholder)
│
├── llm/
│   ├── __init__.py          # Exports client
│   └── client.py           # OpenAI/NVIDIA NIM wrapper + circuit breaker
│
├── observability/
│   ├── __init__.py          # Exports
│   ├── health.py            # Comprehensive health checkers
│   ├── logging.py           # Legacy SQLite audit logging
│   ├── metrics.py           # Prometheus counters, histograms, gauges
│   ├── structured_logging.py # JSON log formatter with OTel context
│   ├── tracing.py          # OpenTelemetry tracing
│   └── event_stream.py     # WebSocket pub/sub
│
├── reliability/
│   ├── __init__.py        # Exports
│   └── circuit_breaker.py # Thread-safe state machine
│
├── schemas/
│   ├── __init__.py       # Exports
│   ├── agent_output.py   # Issue, AgentOutput
│   ├── context.py        # ReviewContext for iterative dialogue
│   └── pr_report.py     # PullRequestReport
│
├── security/
│   ├── __init__.py       # Placeholder
│   └── rate_limiter.py   # Redis sliding-window rate limiting
│
└── task_queue/
    ├── __init__.py           # Exports
    ├── celery_app.py         # Celery app + task definitions
    ├── orchestrator.py       # review_pr chain task
    ├── redis_client.py       # Centralized Redis client
    └── task_registry.py      # Concurrency slot management
```

### 5.1 Responsibility of Each Top-Level Module

| Module | Responsibility |
|--------|---------------|
| **agents/** | Implement the three domain-specific analyzers, the arbitrator, and the coordinator for multi-round dialogue. Each agent is a pure function invoked both directly and via Celery. |
| **analysis/** | All parsing, repository caching, and repository management. `diff_parser.py` is the most critical — it transforms raw diff text into line-precise hunks. `repo_cache.py` manages shallow-clone caching with LRU eviction. |
| **confidence/** | Contains the confidence scoring logic. Acts as a utilities module consumed by the arbitrator and agents. |
| **config/** | Single source of truth for environment-driven settings. Used everywhere. |
| **cost/** | Budget management. Enforces the daily $5 cap. Acts as middleware between the LLM client and the API. |
| **db/** | SQLAlchemy async models and session management for PostgreSQL persistence. Alebmic migrations for schema evolution. |
| **evaluation/** | Precision/recall/F1 benchmarking framework with CLI entrypoint for batch evaluation over annotated datasets. |
| **gh_client/** | All GitHub interaction. The webhook server validates and routes; the GitHub client performs API calls. Exposes health, metrics, config, and WebSocket endpoints. |
| **llm/** | Single LLM wrapper with circuit breaker integration. All agent code calls `generate_analysis()` from this module, ensuring centralized token budgeting, retry, and resilience. |
| **observability/** | Health checks, Prometheus metrics, structured JSON logging, OpenTelemetry tracing, and WebSocket event streaming. |
| **reliability/** | Circuit breaker for LLM client resilience. Thread-safe state machine preventing cascading failures. |
| **schemas/** | Pydantic models for all data structures. Enforces validation everywhere. Includes `ReviewContext` for iterative dialogue state. |
| **security/** | Rate limiting. Used in the webhook handler before any processing. |
| **task_queue/** | Celery configuration, orchestrator chain task, and Redis connection. All Celery tasks are defined here. |

### 5.2 How Modules Are Connected

The primary connection is through the **orchestrator** (`task_queue/orchestrator.py`), which chains repository preparation → agent group execution → iterative refinement → arbitration → comment posting:

```python
# orchestrator.py (simplified)
chain(
    prepare_repository.s(repo_full_name, pr_number, github_token, clone_url),
    run_agents.s(diff_text, repo_path),
    refine.s(),
    arbitrate.s(),
    post_review.s(repo_full_name, pr_number)
)
```

Each agent imports the LLM client and scoring engine:

```python
# style_agent.py, logic_agent.py, security_agent.py each have:
from prguard_ai.llm.client import generate_analysis
from prguard_ai.confidence.scoring_engine import estimate_issue_confidence
```

The circuit breaker is integrated into the LLM client:

```python
# llm/client.py:
from prguard_ai.reliability.circuit_breaker import llm_breaker
# generate_analysis() checks llm_breaker.state before calling API
```

All database models are defined in `db/models.py` and migrations managed by `alembic/env.py`:

```python
# db/models.py
class AgentLog(Base):
    __tablename__ = "agent_logs"
    # pr_id, agent, started_at, finished_at, confidence, token_usage, ...

class LLMUsage(Base):
    __tablename__ = "llm_usage"
    # pr_id, agent, model, prompt_tokens, completion_tokens, estimated_cost
```

---

## 6. Core Workflows

### 6.1 Step-by-Step Execution of a Pull Request Review

This is the full lifecycle from webhook reception to comment posting.

#### Step 1: Webhook Reception and Security Validation

- **Location**: `gh_client/webhook_server.py:188-285`
- **Flow**:
  1. Extract `raw_body` via `Depends(get_raw_body)`.
  2. Check payload size < 5MB. If exceeded, return 413.
  3. Extract `X-GitHub-Delivery` (delivery ID). Check Redis `SETNX` at key `prguard:webhook:delivery:{delivery_id}`. If key exists, return 409 (replay).
  4. If `X-GitHub-Timestamp` present, validate age within ±120 seconds. If stale, return 400.
  5. Verify HMAC-SHA256 signature via `verify_github_signature()`.
  6. Parse JSON; ensure `X-GitHub-Event == "pull_request"`. If not, return `{"status": "ignored"}`.
  7. Extract `action`. Only process `opened`, `synchronize`, `ready_for_review`.
  8. Validate repository full name via regex `_REPO_FULL_NAME_PATTERN`.
  9. Validate PR number is positive integer.
  10. Call `check_repo_limit(repo)` and `check_installation_limit(installation_id)`. If either fails, return 429.
  11. Call `is_pr_processing(pr_id)`; if already processing, return `{"status": "ignored"}`.
  12. Call `acquire_global_slot()`; if no slot, return 503 (backpressure).
  13. Return `202 Accepted` immediately and enqueue `review_pr` Celery task.

#### Step 2: Repository Preparation (Inside Celery Worker)

- **Location**: `task_queue/orchestrator.py`
- **Flow**:
  1. Call `get_pr_diff(repo_full_name, pr_number)` → raw unified diff text.
  2. Call `get_cached_repo(clone_url, repo_full_name)` → either use cached shallow clone or create new one.
  3. Call `build_code_graph(repo_path)` → best-effort, exceptions swallowed.

#### Step 3: Parallel Agent Execution

- **Location**: `task_queue/orchestrator.py`
- **Flow**:
  1. Dispatch `group(style.s(), logic.s(), security.s())`.
  2. Each agent:
     - Parses diff using `parse_diff()`.
     - Runs rule-based checks.
     - Checks circuit breaker state. If CLOSED, invokes `generate_analysis()`.
     - Returns `AgentOutput`.

#### Step 4: Iterative Refinement (Optional)

- **Location**: `agents/coordinator.py`
- **Flow**:
  1. Run up to 3 refinement rounds.
  2. Each round: agents review each other's findings and update their own outputs.
  3. `CoordinatorAgent.should_stop()` decides early termination.

#### Step 5: Arbitration

- **Location**: `agents/arbitrator_agent.py:56-73`
- **Flow**:
  1. Call `aggregate_confidence(outputs)` → weighted average of agent scores.
  2. If agents failed and `partial=True`, degrade gracefully instead of raising.
  3. Call `detect_agent_disagreements(outputs)` → list of disagreement notes.
  4. Build `PullRequestReport`.

#### Step 6: Post Review Comments

- **Location**: `task_queue/orchestrator.py`
- **Flow**:
  1. Call `format_pr_review(arb_output)` → Markdown body.
  2. Call `post_pr_comment(repo, pr_number, body)` → GitHub API.
  3. Iterate `arb_output.issues`:
     - Limit to first 10.
     - Skip if severity not in `["medium", "high"]`.
     - Skip if no `file_path`.
     - Call `post_inline_comment(repo, pr_number, path, line, body)`.

#### Step 7: Audit Logging

- **Location**: `db/session.py`, `db/models.py`
- **Flow**:
  1. Log each agent execution to `agent_logs` table (pr_id, agent, timing, confidence, tokens, payload).
  2. Log LLM usage to `llm_usage` table (model, prompt/completion tokens, cost).
  3. Both use async SQLAlchemy with connection pooling via `asyncpg`.

### 6.2 Request → Processing → Response Lifecycle

| Phase | What Happens | Key Functions Called |
|-------|---------------|---------------------|
| **1. Request Reception** | HTTP POST to `/webhook` with signed JSON | `verify_github_signature()`, `check_repo_limit()`, `check_installation_limit()` |
| **2. Diff Fetch** | GitHub API returns unified diff | `get_pr_diff()` (`github_client.py`) |
| **3. Repo Caching** | Shallow clone or fetch existing cache | `get_cached_repo()` (`repo_cache.py`) |
| **4. Agent Dispatch** | 3 Celery tasks in parallel group | `run_X_agent.delay()` via Celery `group()` |
| **5. Agent Execution** | Each agent runs rule-based + LLM checks | `parse_diff()`, `generate_analysis()` (with circuit breaker), `analyze_X()` |
| **6. Refinement** | Multi-round dialogue/debate | `CoordinatorAgent.should_stop()`, agent `refine()` |
| **7. Arbitration** | Aggregate confidence and detect disagreements | `aggregate_confidence()`, `detect_agent_disagreements()` |
| **8. Post Comment** | Markdown review + inline comments | `post_pr_comment()`, `post_inline_comment()` |
| **9. Audit Log** | Log to PostgreSQL via SQLAlchemy | `init_db()`, `AgentLog.create()`, `LLMUsage.create()` |

### 6.3 Real-World Example of How the System Behaves

Consider a PR that adds the following Python code:

```python
# app.py
def run_user_command(cmd: str):
    import subprocess
    result = subprocess.run(f"echo {cmd}", shell=True, capture_output=True)
    return result.stdout
```

**System behavior:**

1. **Webhook handler** receives the PR event, validates HMAC, rate limits, returns 202.
2. **Orchestrator** enqueues `review_pr` chain.
3. **get_pr_diff()** fetches the diff.
4. **get_cached_repo()** clones repository (or reuses cache).
5. **Style agent**:
   - Rule check: line length < 120, no tabs → no issues.
   - LLM: detects `f"echo {cmd}"` is a formatting inconsistency? (subjective) → no issues.
6. **Logic agent**:
   - Rule check: no bare `except:`, no TODOs → no issues.
   - LLM: with AST summary showing function `run_user_command(cmd: str)`, the LLM may reason that `cmd` is user-controlled and `shell=True` is unsafe → generates a MEDIUM or HIGH issue.
7. **Security agent**:
   - Rule check: `shell=True` in `subprocess.run` → flags as potential command injection (via pattern `shell=True` detection).
   - LLM: also detects command injection → HIGH issue.
   - Circuit breaker check: if LLM API is degraded, falls back to rule-based only.
8. **Refinement round**: Agents review each other's findings; logic and security agree on injection risk.
9. **Arbitrator**:
   - Aggregates agent scores: average ≈ 0.75.
   - Disagreement detection: logic reports high, style reports none → flagged.
10. **Post**:
    - Review comment with both logic and security issues.
    - Inline comment on line 4 (the `subprocess.run` line).

---

## 7. Data Layer & State Management

### 7.1 Database Schema / Structure

PostgreSQL is used for audit logging, managed via SQLAlchemy async ORM with Alembic migrations.

#### `agent_logs` Table

```python
# db/models.py
class AgentLog(Base):
    __tablename__ = "agent_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    pr_id: Mapped[str]
    agent: Mapped[str]           # "style", "logic", "security", "arbitrator"
    started_at: Mapped[float]    # Unix timestamp
    finished_at: Mapped[float]   # Unix timestamp
    confidence: Mapped[float]    # Confidence 0.0-1.0
    token_usage: Mapped[int]     # Total tokens used
    execution_duration: Mapped[float]
    agent_order: Mapped[int]
    payload: Mapped[str]         # JSON string of full AgentOutput
```

#### `llm_usage` Table

```python
class LLMUsage(Base):
    __tablename__ = "llm_usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    pr_id: Mapped[str]
    agent: Mapped[str]
    model: Mapped[str]           # e.g., "openai/gpt-oss-120b"
    prompt_tokens: Mapped[int]
    completion_tokens: Mapped[int]
    estimated_cost_usd: Mapped[float]
```

### 7.2 Data Flow and Storage Logic

- **Write path**: After each agent completes, the orchestrator logs execution via `AgentLog.create()` and `LLMUsage.create()` using async SQLAlchemy sessions with connection pooling (pool_size=10, max_overflow=20).
- **Read path**: The `/review/{pr_id}` endpoint fetches PR logs using async queries.
- **Migrations**: Managed via Alembic. Auto-discovers `Base.metadata`. Supports both offline and online migration modes.
- **Initialization**: `init_db()` called on startup to ensure tables exist; `run_async()` helper handles both running and absent event loops.

### 7.3 Caching, Indexing, Optimization Techniques

| Technique | Location | Implementation |
|-----------|----------|----------------|
| **Repository cache** | `analysis/repo_cache.py` | Shallow clones (`--depth 1`) fetched or updated; LRU eviction when total exceeds `repo_cache_max_size_gb`; tracks last access via timestamp files. |
| **Repository style index** | `analysis/repo_indexer.py` | ChromaDB index (currently disabled/no-op). Intended for retrieving similar code snippets to pass to LLM as context. |
| **Code graph cache** | `analysis/code_graph.py` | Builds dependency graph of repository; best-effort caching. |
| **Replay protection cache** | `redis_client.py:webhook_server` | Redis `SETNX` with 5-minute TTL at key `prguard:webhook:delivery:{delivery_id}`. |
| **Rate limiting** | `security/rate_limiter.py` | Redis sorted set (`ZSET`) with sliding window. |
| **Cost bucketing** | `cost/budget_manager.py` | Redis string incremented daily, expired at end of day. |
| **Global concurrency slots** | `task_registry.py` | Redis counter for max concurrent PRs. |
| **Circuit breaker state** | `reliability/circuit_breaker.py` | In-memory thread-safe state machine; state recorded via Prometheus gauge. |

---

## 8. Key Design Patterns Used

### 8.1 Multi-Agent Fan-Out / Fan-In

- **What**: One orchestrator dispatches multiple parallel workers, then aggregates results.
- **Where**: `task_queue/orchestrator.py` uses Celery `group()` for parallel dispatch.
- **Why**: Different issue domains require different detectors. Parallel execution reduces wall-clock time.
- **Trade-off**: Complexity of result aggregation; potential for inconsistent findings across agents.

### 8.2 Celery Chain Pattern

- **What**: A sequential chain of Celery tasks: prepare → run_agents → refine → arbitrate → post_review.
- **Where**: `task_queue/orchestrator.py`.
- **Why**: Each step depends on the previous result. Chain enforces ordering while allowing parallel sub-steps (group within chain).
- **Trade-off**: If one step fails, subsequent steps don't execute. Partial aggregation mitigates agent failures.

### 8.3 Confidence Weighting

- **What**: Each issue has a `confidence_source` tag (`rule_based`, `llm_reasoning`, `inferred`) mapped to a numeric weight. Per-agent confidence blends base score with average issue weight. Aggregate confidence boosts by 0.1 if any high-severity issue exists.
- **Location**: `confidence/scoring_engine.py`.
- **Why**: Rule-based findings are deterministic → higher weight. LLM findings are probabilistic → lower weight. Aggregated score reflects cross-agent validation.
- **Trade-off**: Weights are tuned constants; may not generalize across all issue types.

### 8.4 Disagreement Detection

- **What**: The arbitrator compares severity distributions across agents. If one agent reports high-severity issues and another reports none, a disagreement note is added to the review.
- **Location**: `arbitrator_agent.py:12-46`.
- **Why**: When agents disagree, it's worth surfacing the disagreement to the human reviewer.
- **Trade-off**: Disagreement detection is naive (only compares presence/absence of HIGH severity).

### 8.5 Hybrid Rule-Based + LLM Analysis

- **What**: Each agent runs deterministic checks first (fast, high-confidence), then optionally invokes LLM for deeper analysis. Issues from both passes are merged.
- **Location**: Each agent's `analyze_X()` function.
- **Why**: Rule-based checks catch obvious patterns (SQL injection regex, `eval(` keyword). LLM catches context-dependent issues (command injection across multiple lines, logical edge cases).
- **Trade-off**: LLM calls introduce latency, cost, and non-determinism. Circuit breaker protects against LLM API degradation.

### 8.6 Circuit Breaker for LLM

- **What**: Thread-safe state machine: `CLOSED` → `OPEN` (after `fail_max` failures) → `HALF_OPEN` (after `reset_timeout`) → `CLOSED` (on success) or back to `OPEN`.
- **Location**: `reliability/circuit_breaker.py`.
- **Why**: Prevents cascading failures when LLM API degrades; allows recovery without manual intervention.
- **Trade-off**: Legitimate requests may be rejected during OPEN state; tuned constants bound the impact.

### 8.7 Multi-Round Iterative Dialogue

- **What**: Up to 3 refinement rounds where agents review each other's findings and update their outputs. `CoordinatorAgent.should_stop()` enables early termination.
- **Location**: `agents/coordinator.py`.
- **Why**: Single-pass analysis may miss cross-cutting concerns. Dialogue allows agents to discover issues they'd individually miss.
- **Trade-off**: Each round doubles LLM cost and latency; `max_rounds=3` bounds the overhead.

### 8.8 Partial Aggregation (Degraded Mode)

- **What**: If some agents fail (timeout, exception), the arbitrator aggregates only succeeded agents instead of raising.
- **Location**: `arbitrator_agent.py`.
- **Why**: Agent failures shouldn't block the entire review. Degraded review is better than no review.
- **Trade-off**: Degraded reviews have lower confidence and may miss issues from the failed domain.

### 8.9 Sliding Window Rate Limiting

- **What**: Redis sorted set per key; on each request, remove entries older than window, add new entry with score=timestamp, count entries. If count > limit, reject.
- **Location**: `security/rate_limiter.py:18-36`.
- **Why**: Fixed-window counters allow burst at window boundaries; sliding window smooths traffic.
- **Trade-off**: Requires Redis; graceful fallback to allow-all if Redis unavailable.

### 8.10 Budget Manager with Daily Cap

- **What**: Redis string per repository per day; incremented on each LLM call with estimated cost. If value > $5, reject new calls.
- **Location**: `cost/budget_manager.py`.
- **Why**: Unbounded LLM usage would make the system prohibitively expensive. Daily cap per repo enforces budget discipline.
- **Trade-off**: Legitimate high-volume repos hit cap; no queueing or priority.

### 8.11 Repository Cache with LRU Eviction

- **What**: Shallow clones (`--depth 1`) stored on disk; LRU eviction when total exceeds `repo_cache_max_size_gb`; last access tracked via `.last_accessed` timestamp files.
- **Location**: `analysis/repo_cache.py`.
- **Why**: Cloning large repos on every PR is slow and wasteful. Caching reduces clone overhead to a single fetch-update.
- **Trade-off**: Cache consumes disk space; eviction policy may remove repos that are about to receive new PRs.

---

## 9. Performance & Scalability Considerations

### 9.1 Bottlenecks in the Current System

| Bottleneck | Location | Impact |
|-----------|----------|--------|
| **Repository cloning/caching** | `repo_cache.py` | Initial clone for large repos (100MB+) can take 10-30 seconds. Cache hits are fast, but cache misses block the chain. |
| **LLM API latency** | `llm/client.py` | Each LLM call adds 2-30 seconds. With 3 agents + refinement rounds, worst-case latency accumulates. Circuit breaker mitigates during degradation. |
| **PostgreSQL connection pool** | `db/session.py` | Pool size of 10 may exhaust under high concurrency; `max_overflow=20` provides headroom. |
| **No incremental diff analysis** | All agents call `parse_diff()` on full diff every time. | Large diffs (>10k lines) cause O(n) parsing and O(n) AST summarization per agent, repeated across agents. |
| **GitHub API rate limits** | `github_client.py` | Fetching diffs and posting comments consume GitHub API quota. No GitHub API-side retry or backoff. |

### 9.2 How It Scales (Or Doesn't)

- **Horizontal**: Workers can be scaled by adding more Celery worker processes. PostgreSQL with connection pooling supports concurrent webhook instances. Redis single-node may become bottleneck; sentinel mode for HA.
- **Vertical**: Celery task time limits (45s soft, 60s hard) cap individual task runtime. Large diffs may timeout.
- **Database**: PostgreSQL provides concurrent write support. Alembic migrations enable schema evolution without downtime.
- **Repository cache**: LRU eviction prevents unbounded disk growth but may cause cache churn under high repo turnover.

### 9.3 Suggestions for Improvement

1. **Incremental analysis**: On `synchronize` event, store the previous diff in Redis. Compute diff of diffs. Only analyze changed hunks.

2. **GitHub API caching**: Cache PR diffs with ETag/Last-Modified headers. Avoid refetching unchanged diffs.

3. **Result caching**: Store `PullRequestReport` in Redis keyed by (`repo_full_name`, `pr_number`, `diff_hash`). If PR re-opened without new commits, return cached review.

4. **Cached LLM responses**: Cache LLM responses for identical prompts (same diff + same agent). Reduces cost and latency.

5. **Adaptive refinement**: Adjust `max_rounds` based on diff complexity or agent disagreement magnitude instead of fixed 3 rounds.

6. **Per-repo configuration**: Add a `.prguard.yml` in repository root. Allow per-repo overrides for severity thresholds, ignored files, agent behavior, cache size.

---

## 10. Weaknesses & Limitations

### 10.1 Design Flaws or Risks

| Weakness | Severity | Impact |
|---------|----------|--------|
| **Inline comments limited to 10** | Medium | High-volume PRs with >10 medium/high issues will have issues silently dropped. |
| **No per-file confidence scoring** | Medium | All issues from a 1000-line file are treated with same confidence as issues from a 10-line file. |
| **No support for edited comments** | Low | If user edits a PR comment, the system does not update its audit log. |
| **No idempotency for comments** | Low | If webhook retried (e.g., GitHub didn't receive 200), duplicate comments may be posted. |
| **No encryption at rest** | High | PostgreSQL and Redis contain PR diffs and audit logs. If container is compromised, plain-text code is exposed. |
| **Hardcoded severity thresholds** | Low | Severity thresholds (`len(text) > 120`, font size < 12px) are hardcoded. No per-repo configuration yet. |
| **ChromaDB is still disabled** | Medium | `repo_indexer.py` is entirely no-op. ChromaDB is in requirements.txt but never instantiated. |

### 10.2 Technical Debt Areas

| Area | Evidence |
|------|----------|
| **ChromaDB is disabled** | `repo_indexer.py` is entirely no-op. ChromaDB is in requirements.txt but never instantiated. |
| **Code graph is placeholder** | `code_graph.py` is a stub. No evidence of actual graph building in the codebase. |
| **Fake Redis fallback** | `task_queue/redis_client.py` silently falls back to in-memory `fakeredis` if Redis is unreachable (though disabled by default in production). |
| **Dashboard/app.py is placeholder** | `dashboard/app.py` exists but is not wired to any route or functionality. |
| **App auth is placeholder** | `gh_client/app_auth.py` likely returns a stub. GitHub App integration not fully implemented. |
| **Legacy SQLite logging still present** | `observability/logging.py` still has SQLite-based logging code alongside the new PostgreSQL/SQLAlchemy implementation. |
| **Multiple Redis client implementations** | `task_queue/redis_client.py` and `db/redis_client.py` both exist, suggesting incomplete consolidation. |

### 10.3 What Would Break Under Scale or Edge Cases

| Edge Case | Failure Mode |
|-----------|-------------|
| **PR with 500+ changed files** | `MAX_FILES_PER_PR = 50` truncates analysis; issues in files 51+ are silently ignored. |
| **Binary files in diff** | Diff parser may corrupt binary content; AST summary will fail. No binary detection. |
| **Non-Python files** | Logic and security agents run regex on any language. False positives (e.g., JavaScript `eval()` is different from Python `eval()`). |
| **Very long lines (>10k chars)** | Diff parser line buffer may overflow; rule check `len(text) > 120` becomes meaningless. |
| **GitHub API rate limit** | `get_pr_diff()` and `post_pr_comment()` call GitHub API; if rate limited, entire webhook fails. No GitHub API-side retry. |
| **Circuit breaker thrashing** | If LLM API is intermittently failing, the circuit breaker may oscillate between OPEN and CLOSED states, causing inconsistent behavior. |
| **Multiple PRs to same cached repo** | Concurrent writes to the same cached repo directory could cause corruption. No file-level locking in `repo_cache.py`. |

---

## 11. How to Improve This System

### 11.1 Concrete, Actionable Improvements

| Improvement | Effort | Rationale |
|-------------|--------|----------|
| **Enable ChromaDB indexing** | Medium | Uncomment the ChromaDB client creation in `repo_indexer.py`. This enables style agent to retrieve repository-specific examples, improving LLM quality. |
| **Add file-level confidence** | Medium | Weight confidence by file size and line count. Large files that affect many modules should have higher confidence. |
| **Incremental diff analysis** | Medium | On `synchronize`, compute diff between current and base, only analyze changed hunks. Cache base diff in Redis. |
| **GitHub App fully implemented** | High | Complete `app_auth.py` to support GitHub App authentication (currently a placeholder). This enables fine-grained permission management. |
| **Cached LLM responses** | Medium | Cache LLM responses for identical prompts to reduce cost and latency. Use Redis with diff hash + agent as key. |
| **Per-repo configuration** | Medium | Add a `.prguard.yml` in repository root. Allow per-repo overrides for severity thresholds, ignored files, agent behavior. |
| **File-level locking for repo cache** | Low | Add file-level locking to prevent concurrent corruption when multiple PRs access the same cached repo simultaneously. |

### 11.2 Better Architectural Alternatives

1. **Event-driven architecture**: Instead of Celery chain, use Redis pub/sub to notify downstream components when agents complete. This allows more flexible composition and real-time streaming of results.

2. **Result caching**: Store `PullRequestReport` in Redis keyed by (`repo_full_name`, `pr_number`, `diff_hash`). On `synchronize`, if diff hash unchanged, return cached review.

3. **Adaptive circuit breaker**: Use a failure rate window (e.g., 50% failure in last 100 calls) instead of a simple counter to avoid oscillation during intermittent failures.

4. **GitHub Actions integration**: Instead of webhook server, distribute as a GitHub Action that runs in the Actions runner. Eliminates hosting concerns and NAT/firewall issues.

### 11.3 Refactoring Suggestions

1. **Extract agent interfaces**: `style_agent.py`, `logic_agent.py`, and `security_agent.py` share almost identical structure (parse diff → rule check → LLM → merge). Extract a base `Agent` class with `analyze(diff_text) -> AgentOutput` to reduce duplication.

2. **Unify confidence calculation**: Move all confidence computation into `confidence/scoring_engine.py`. Currently duplicated in agents and arbitrator.

3. **Consolidate Redis clients**: Currently `task_queue/redis_client.py`, `db/redis_client.py`, `rate_limiter.py`, `budget_manager.py`, `task_registry.py` each import their own Redis instance. Consolidate to a single Redis client factory.

4. **Remove dead code**: Remove old SQLite logging code in `observability/logging.py` once PostgreSQL path is fully proven. Remove placeholder directories (`dashboard/`, `db/__init__.py` legacy, `code_graph.py`).

5. **Standardize error handling**: Agent exception handling is inconsistent — some catch broadly, others propagate. Standardize around the partial aggregation pattern used in the arbitrator.

---

## 12. Learning Notes (For a Developer)

### 12.1 Key Concepts to Study From This Project

| Concept | Where It Appears | Study Focus |
|---------|-----------------|------------|
| **Multi-agent orchestration** | `task_queue/orchestrator.py` | Celery chain + group pattern for parallel dispatch and sequential aggregation. |
| **Celery chains and groups** | `task_queue/orchestrator.py` | How `chain()` and `group()` compose to build complex workflows. |
| **Circuit breaker pattern** | `reliability/circuit_breaker.py` | Thread-safe state machine with configurable thresholds and reset timeout. |
| **Confidence scoring with weighted sources** | `confidence/scoring_engine.py` | Blending deterministic and probabilistic signals. |
| **Hybrid rule-based + LLM analysis** | Each agent's `analyze_X()` | Running deterministic checks before expensive LLM calls. |
| **Diff parsing** | `analysis/diff_parser.py` | Understanding unified diff format and line number tracking. |
| **AST summarization** | `analysis/ast_parser.py` | Tree-sitter vs stdlib `ast` fallback; multi-language support. |
| **Repository caching** | `analysis/repo_cache.py` | LRU eviction policy, shallow clone optimization. |
| **Rate limiting (sliding window)** | `security/rate_limiter.py` | Redis sorted set implementation. |
| **Cost budgeting** | `cost/budget_manager.py` | Daily token budget enforcement. |
| **Celery task autoretry** | `task_queue/celery_app.py` | Task retry policies and time limits. |
| **GitHub webhook security** | `webhook_server.py:106-285` | HMAC verification, replay protection, timestamp validation. |
| **Async SQLAlchemy + Alembic** | `db/models.py`, `db/session.py`, `alembic/env.py` | asyncpg driver, connection pooling, migration management. |
| **Prometheus metrics** | `observability/metrics.py` | Counters, histograms, summaries, gauges for observability. |
| **Structured logging** | `observability/structured_logging.py` | JSON formatter with OTel context injection. |
| **Health checks** | `observability/health.py` | Aggregated health status with critical/non-critical buckets. |
| **Evaluation framework** | `evaluation/evaluator.py` | Precision, recall, F1 score computation for benchmarking. |

### 12.2 What Skills This Project Demonstrates

- **Building a multi-agent system**: Designing specialized agents that each focus on a single domain (style, logic, security) and aggregating their results.
- **Hybrid AI pipelines**: Combining deterministic rule-based checks with probabilistic LLM reasoning in a single processing pipeline.
- **Resilience patterns**: Circuit breaker, partial aggregation, retry with backoff, degraded mode operation.
- **API integration**: Building and securing a webhook server that integrates with GitHub's API and external LLM providers.
- **Distributed task queues**: Using Celery to run long-running analysis tasks asynchronously with retry and time limits.
- **Observability**: Structured JSON logging, Prometheus metrics, OpenTelemetry tracing, comprehensive health checks.
- **Data persistence**: Async SQLAlchemy with PostgreSQL, Alembic migrations, Redis caching.
- **DevOps**: Docker, docker-compose, CI pipeline with flake8 linting, 237 tests with 81% coverage.
- **Security**: HMAC verification, rate limiting, budget management, input sanitization, circuit breaker for API resilience.

### 12.3 How to Replicate or Build Something Similar

To build a similar multi-agent code review system:

1. **Start with the diff parser**: Before any agents, build a robust `parse_diff()` that transforms unified diffs into line-precise hunks. This is the foundation.

2. **Design agents as pure functions**: Each agent should be a function `(diff_text, metadata) -> AgentOutput`. This makes them testable, Celery-wrappable, and easy to compose in chains.

3. **Choose your analysis approach**:
   - **Rule-based**: Regex, keyword matching, AST pattern matching.
   - **LLM-based**: Prompt engineering with context.
   - **Hybrid**: Run rule-based first (fast), LLM fallback for uncertain cases.

4. **Add a circuit breaker early**: LLM APIs are the most failure-prone component. A circuit breaker prevents cascading failures and maintains system stability.

5. **Add confidence scoring**: Tag each issue with a source (`rule_based`, `llm_reasoning`, `inferred`). Weight aggregate scores accordingly.

6. **Design the orchestrator**: Use Celery chains and groups to compose prepare → analyze → refine → arbitrate → post workflow.

7. **Integrate with a webhook**: Secure with HMAC, rate limit, replay protection. Return 202 immediately and process async.

8. **Choose a database**: Start with SQLite for simplicity, migrate to PostgreSQL when multi-instance support is needed. Use Alembic for migrations from day one.

9. **Add observability early**: JSON structured logging, Prometheus metrics, health checks. These are invaluable for debugging and monitoring.

10. **Add an evaluation framework early**: Build precision/recall/F1 benchmarking against annotated datasets. This lets you measure improvements objectively.

---

## Appendix A: Confidence Score Calculation (Detailed)

### Per-Issue Confidence

```python
CONFIDENCE_WEIGHTS = {
    "rule_based": 0.9,    # Deterministic match
    "llm_reasoning": 0.6, # LLM-generated
    "inferred": 0.3       # Heuristic
}
SEVERITY_CONFIDENCE_WEIGHTS = {
    "low": 0.45,
    "medium": 0.65,
    "high": 0.85
}
```

For each issue:
```python
source_score = CONFIDENCE_WEIGHTS[issue.confidence_source]
severity_score = SEVERITY_CONFIDENCE_WEIGHTS[issue.severity]
issue_score = (source_score + severity_score) / 2
```

### Per-Agent Confidence

```python
avg_weight = sum(_weight_for_source(issue) for issue in issues) / len(issues)
refined = (base_confidence + avg_weight) / 2  # base_confidence = 0.9 if issues else 0.5
```

### Aggregate Confidence

```python
refined_scores = [calculate_agent_confidence(o) for o in outputs]
base_avg = sum(refined_scores) / len(outputs)
if any(issue.severity == "high" for issue in all_issues):
    base_avg = min(1.0, base_avg + 0.1)
```

---

## Appendix B: Rate Limiting Algorithm (Sliding Window)

Location: `security/rate_limiter.py:18-36`.

```python
def _check_limit(key: str, window_seconds: int, max_events: int) -> bool:
    now = int(time.time())
    r = get_redis()
    pipe = r.pipeline()
    pipe.zremrangebyscore(key, 0, now - window_seconds)  # Drop old entries
    pipe.zadd(key, {str(now): now})                        # Add current
    pipe.zcard(key)                                      # Count
    pipe.expire(key, window_seconds)
    _, _, count, _ = pipe.execute()
    return int(count) <= max_events
```

- Uses Redis sorted set (`ZSET`) where score = timestamp, member = timestamp string.
- `ZREMRANGEBYSCORE` removes entries older than window.
- `ZCARD` counts entries within window.
- `EXPIRE` sets key TTL to prevent unbounded growth.

---

## Appendix C: Circuit Breaker State Machine

Location: `reliability/circuit_breaker.py`.

```
CLOSED ───(fail_max failures)───▶ OPEN ───(reset_timeout expires)───▶ HALF_OPEN
  ▲                                                                        │
  └──────────────────────(success)─────────────────────────────────────────┘
  ▲                                                                        │
  └──────────────────────(failure, back to OPEN)───────────────────────────┘
```

- **CLOSED**: Normal operation. LLM calls proceed. Failure counter increments on each failure.
- **OPEN**: LLM calls rejected immediately. `can_execute()` returns `False`. Resets to HALF_OPEN after `reset_timeout` seconds.
- **HALF_OPEN**: Single probe request allowed. On success → back to CLOSED (reset counter). On failure → back to OPEN.

Prometheus gauge `CIRCUIT_BREAKER_STATE`: 0=CLOSED, 1=HALF_OPEN, 2=OPEN.

---

## Appendix D: Key File Locations Reference

| Component | File Path |
|-----------|----------|
| Webhook server (FastAPI app) | `src/prguard_ai/gh_client/webhook_server.py` |
| Celery app + tasks | `src/prguard_ai/task_queue/celery_app.py` |
| Orchestrator (review_pr chain) | `src/prguard_ai/task_queue/orchestrator.py` |
| Style agent | `src/prguard_ai/agents/style_agent.py` |
| Logic agent | `src/prguard_ai/agents/logic_agent.py` |
| Security agent | `src/prguard_ai/agents/security_agent.py` |
| Arbitrator | `src/prguard_ai/agents/arbitrator_agent.py` |
| Coordinator (dialogue loop) | `src/prguard_ai/agents/coordinator.py` |
| Diff parser | `src/prguard_ai/analysis/diff_parser.py` |
| AST parser | `src/prguard_ai/analysis/ast_parser.py` |
| LLM client | `src/prguard_ai/llm/client.py` |
| Circuit breaker | `src/prguard_ai/reliability/circuit_breaker.py` |
| Scoring engine | `src/prguard_ai/confidence/scoring_engine.py` |
| Settings | `src/prguard_ai/config/settings.py` |
| GitHub client | `src/prguard_ai/gh_client/github_client.py` |
| Rate limiter | `src/prguard_ai/security/rate_limiter.py` |
| Budget manager | `src/prguard_ai/cost/budget_manager.py` |
| DB models (SQLAlchemy) | `src/prguard_ai/db/models.py` |
| DB session (asyncpg) | `src/prguard_ai/db/session.py` |
| Alembic migrations | `alembic/env.py` |
| Repo cache | `src/prguard_ai/analysis/repo_cache.py` |
| Health checks | `src/prguard_ai/observability/health.py` |
| Prometheus metrics | `src/prguard_ai/observability/metrics.py` |
| Structured logging | `src/prguard_ai/observability/structured_logging.py` |
| Evaluation framework | `src/prguard_ai/evaluation/evaluator.py` |
| Schemas | `src/prguard_ai/schemas/agent_output.py`, `pr_report.py`, `context.py` |
| Redis client | `src/prguard_ai/task_queue/redis_client.py` |
| Task registry | `src/prguard_ai/task_queue/task_registry.py` |
| Flake8 config | `.flake8` |
| Docker setup | `docker-compose.yml`, `Dockerfile` |

---

*End of study guide. Last updated: 2026-07-19 — reflects all 10 phases of development (237 tests, 81% coverage, PostgreSQL + Alembic, circuit breaker, Prometheus metrics, structured logging, repo caching, health checks, evaluation framework, flake8 integration, model routing, scalability, observability, security hardening, human-in-the-loop).*
