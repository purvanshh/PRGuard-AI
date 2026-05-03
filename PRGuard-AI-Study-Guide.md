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
| Repository cloning and sandboxing | Temporary clone of target repository for analysis, cleaned up after completion. |
| Async event streaming | WebSocket endpoint (`/stream/{pr_id}`) for live progress events. |
| Audit logging | SQLite persistence of agent executions, latencies, token usage, and costs. |

---

## 2. High-Level Architecture

### 2.1 Overall System Design

The system is a **layered, event-driven architecture** with an HTTP-triggered async pipeline. It is not a monolith in theDDD sense, but rather a **webhook server** (FastAPI) that enqueues work to a **task queue** (Celery + Redis), where workers execute the agents.

```
┌─────────────────────┐
│   GitHub Webhook    │
│  (POST /webhook)   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────────┐
│  FastAPI Server       │◄──── HMAC Verification
│  (webhook_server)    │◄──── Replay Protection
│                    │◄──── Rate Limiting
│                    │◄──── Repo Clone/Sandbox
│                    │
│  [Syncronous        │
│   Orchestrator]      │
└─────────┬───────────┘
          │
          │  .delay() — async enqueue
          ▼
┌───────────────────────────────────────────┐
│        Celery + Redis Task Queue          │
│  ┌──────────┬──────────┬────────────┐  │
│  │ Style    │ Logic    │ Security   │  │
│  │ Agent    │ Agent    │ Agent     │  │
│  └────┬─────┴────┬─────┴─────┬────┘  │
│       │          │           │        │
│       └──────────┴───────────┘        │
│                │                     │
│                ▼                     │
│       ┌─────────────────┐            │
│       │ Confidence      │            │
│       │ Arbitrator      │            │
│       └────────┬────────┘            │
└────────────────┴────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────┐
│  GitHub API Client                        │
│  - POST review comment                   │
│  - POST inline comments (up to 10)     │
│  - POST diff for analysis              │
└─────────────────────────────────────────────┘
```

The key architectural choice is the **fan-out / fan-in** pattern: the webhook dispatches three agent tasks simultaneously, waits for all to complete (via `.get(timeout=60)`), then dispatches the arbitrator.

### 2.2 Major Components and Their Interactions

| Component | File | Responsibility |
|----------|------|--------------|
| **Webhook Server** | `gh_client/webhook_server.py` | FastAPI app; receives GitHub webhooks; performs security validation; clones repo; dispatches Celery tasks; waits for results; posts review comments. |
| **Style Agent** | `agents/style_agent.py` | Detects style issues via rule-based checks (tab indentation, long lines, frontend design regression) and LLM-guided style analysis. |
| **Logic Agent** | `agents/logic_agent.py` | Detects logical defects via pattern matching, AST summary, and LLM reasoning. |
| **Security Agent** | `agents/security_agent.py` | Detects vulnerabilities via pattern matching (SQL injection, eval/exec, hardcoded secrets) and LLM reasoning. |
| **Arbitrator** | `agents/arbitrator_agent.py` | Aggregates agent outputs; computes overall confidence; detects inter-agent disagreements. |
| **Diff Parser** | `analysis/diff_parser.py` | Parses unified Git diffs into structured `DiffHunk` and `DiffLine` objects with precise line numbers. |
| **AST Parser** | `analysis/ast_parser.py` | Produces structural summaries (functions, variables, control structures) from Python source using tree-sitter orstdlib `ast`. |
| **Repository Indexer** | `analysis/repo_indexer.py` | Indexes repository code in ChromaDB for style retrieval (currently a no-op; ChromaDB disabled). |
| **Repository Sandbox** | `analysis/repo_sandbox.py` | Clones target repository to temporary directory; manages cleanup. |
| **LLM Client** | `llm/client.py` | Wrapper around OpenAI client (NVIDIA NIM API); enforces token budgets; handles retry/backoff; returns stub responses in offline mode. |
| **Scoring Engine** | `confidence/scoring_engine.py` | Computes per-issue, per-agent, and aggregate confidence scores with weighted sources. |
| **Rate Limiter** | `security/rate_limiter.py` | Redis-backed sliding-window rate limits per repository and per installation. |
| **Budget Manager** | `cost/budget_manager.py` | Enforces daily $5 USD cost cap per repository on LLM calls. |
| **Task Queue** | `task_queue/celery_app.py` | Celery app definition and task wrappers with autoretry. |
| **Redis Client** | `task_queue/redis_client.py` | Centralized Redis client with support for single-node, sentinel, and in-memory modes. |
| **Observability** | `observability/` | Structured logging (SQLite), metrics (Prometheus), tracing (OpenTelemetry), and event streaming (WebSocket). |

### 2.3 Data Flow Across the System

1. **Webhook Reception** (`webhook_server.py:188-491`)
   - GitHub sends `POST /webhook` with JSON payload.
   - Server validates HMAC signature, replay ID (Redis), timestamp (2-minute window).
   - Validates rate limits (`check_repo_limit`, `check_installation_limit`).
   - Acquires global concurrency slot (`acquire_global_slot`).

2. **Repository Setup**
   - Calls `get_pr_diff()` via GitHub API (`github_client.py:53-78`).
   - Clones repository to sandbox (`clone_repository` → `repo_sandbox.py`).
   - Initializes index (`initialize_repo_index` → `repo_indexer.py`, no-op).
   - Builds code graph (`build_code_graph` → `code_graph.py`, best-effort).

3. **Agent Execution (Parallel)**
   - Dispatches three Celery tasks:
     ```python
     style_result = run_style_agent.delay(diff_text, repo_metadata)
     logic_result = run_logic_agent.delay(diff_text, repo_metadata)
     security_result = run_security_agent.delay(diff_text, repo_metadata)
     ```
   - Each agent:
     - Parses diff using `parse_diff()`.
     - Runs rule-based checks.
     - If LLM is available, invokes `generate_analysis()` with agent-specific prompt.
     - Returns `AgentOutput` (agent name, confidence, list of `Issue` objects).

4. **Arbitration**
   - After all three agents complete, dispatches `run_arbitrator.delay(agent_outputs)`.
   - Arbitrator calls `aggregate_confidence()` (scoring engine).
   - Detects disagreements via `detect_agent_disagreements()`.
   - Returns `PullRequestReport`.

5. **Response Posting**
   - Calls `format_pr_review()` to render Markdown.
   - Posts review comment via `post_pr_comment()`.
   - Iterates issues; posts up to 10 inline comments via `post_inline_comment()`.
   - Cleans up sandbox (`cleanup_repository`).
   - Releases concurrency slot (`release_global_slot`).

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
| **Synchronous waiting in webhook** (`webhook_server.py:346-351`) | The webhook waits synchronously for all three agents to complete before returning. This is a deliberate choice for simplicity — GitHub expects a response quickly, but the review comment is posted after the webhook returns. In exchange, the system tolerates a 60-second wait per agent. |
| **In-memory Redis fallback** (`redis_client.py:109-115`) | If Redis is unreachable, the system falls back to `fakeredis`. This allows local development without Docker, but is not production-safe. The trade-off is developer ergonomics vs. operational guarantees. |
| **Rule-based + LLM hybrid** | The system runs rule-based checks first (fast, deterministic), then falls back to LLM only if needed. This reduces LLM calls and cost, but sacrifices some recall. The trade-off is cost vs. completeness. |
| **No incremental analysis** | Every `synchronize` event re-analyzes the entire diff. The roadmap includes incremental analysis, but current simplicity favors correctness over optimization. |

### 3.3 When This Architecture Would Fail or Become Inefficient

- **Very large diffs**: Parsing and AST analysis are O(n) in diff size. Diffs with >10,000 lines will exceed the 60-second timeout per agent.
- **Rate limit exhaustion**: If a repository exceeds 10 PRs/hour or an installation exceeds 100 PRs/day, the system returns 429. Under heavy load from a single active repo, other repos may be starved.
- **LLM API outage**: If NVIDIA NIM is unavailable, agents fall back to rule-based checks only. High-severity logic issues requiring LLM reasoning will be missed.
- **Disk space exhaustion**: Repository clones are stored in temporary sandboxes. If cleanup fails (crash during webhook handling), disk space leaks.
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
| **LLM Client** | openai (NVIDIA NIM) | Uses `openai.OpenAI` with custom base_url |
| **AST Parsing** | tree-sitter | Python bindings; requires compiled grammar |
| **Vector Store** | chromadb | Disabled in current implementation (no-op placeholder) |
| **Schema Validation** | pydantic | v2 (BaseModel, Field, validator) |
| **Settings** | pydantic-settings | v2 (`BaseSettings`) |
| **GitHub Client** | PyGithub | Raw `requests` for diff fetch (GitHub API v3 diff accept header) |
| **Observability** | OpenTelemetry | API, SDK, OTLP gRPC exporter (optional) |
| **Metrics** | prometheus-client | Exposed at `/metrics` endpoint |
| **Database** | SQLite | File-based (`prguard_logs.sqlite`); no migrations |
| **Container** | Docker | `python:3.11-slim` base |
| **Orchestration** | docker-compose | v3.9 (three services: api, worker, redis) |
| **Testing** | pytest | Test files cover diff parsing, agents, scoring, full pipeline |

### 4.2 Why Each Was Likely Chosen

| Component | Rationale |
|-----------|-----------|
| **FastAPI** | Native async support; automatic OpenAPI docs; Pydantic integration for request/response validation. Uvicorn provides production-grade ASGI server. |
| **Celery** | Mature, battle-tested task queue with proper task routing, time limits, retry policies, and Redis integration. Supports separate queues needed for per-agent concurrency control. |
| **Redis** | Serves triple duty: Celery broker, rate limiting backend, cost bucketing, and pub/sub for WebSocket events. Single-node to sentinel modes supported. |
| **pydantic v2** | Type-safe settings and schemas; `BaseModel` used everywhere from settings (`config/settings.py`) to agent outputs (`schemas/agent_output.py`). |
| **PyGithub** (raw `requests` for diff) | PyGithub does not natively support the `application/vnd.github.v3.diff` media type, hence raw `requests.get()` is used in `get_pr_diff()`. |
| **tree-sitter** | Provides accurate syntactic analysis beyond what stdlib `ast` offers (e.g., preserves exact indentation and whitespace). Falls back to stdlib `ast` when tree-sitter is unavailable. |
| **SQLite** | Zero-configuration persistence for audit logs. Single-writer model avoids concurrency issues in practice. File-based for easy inspection. |
| **Prometheus** | Industry-standard metrics; `/metrics` endpoint auto-scraped by Prometheus. |
| **OpenTelemetry** | Vendor-neutral tracing. Optional dependency (available under `observability` extra). |

### 4.3 What Alternatives Could Have Been Used and Why They Weren't

| Alternative | Why Not |
|-------------|--------|
| **Flask** | No native async; FastAPI + Pydantic provides better developer experience. |
| **HTTPX + asyncio** | Would require custom task queue implementation. Celery provides ready-made retry, routing, and monitoring. |
| **Kafka** | Operational overhead disproportionate to throughput. Redis is already present. |
| **PostgreSQL** | Not needed for audit logs; SQLite is sufficient and portable. |
| **LangChain** | Overkill for simple prompt construction; raw `openai` client suffices. |
| **SQLAlchemy** | No complex queries; raw `sqlite3` suffices for audit logging. |

---

## 5. Folder & Code Structure Deep Dive

```
src/prguard_ai/
├── __init__.py                      # Package marker (empty)
├── main.py                          # Entry point: uvicorn server startup
│
├── agents/
│   ├── __init__.py                 # Exports all agents
│   ├── style_agent.py               # Style analysis (293 lines)
│   ├── logic_agent.py              # Logic analysis (159 lines)
│   ├── security_agent.py           # Security analysis (143 lines)
│   └── arbitrator_agent.py          # Confidence aggregation (77 lines)
│
├── analysis/
│   ├── __init__.py                 # Exports parsers and indexer
│   ├── diff_parser.py              # Unified diff → DiffHunk[] (234 lines)
│   ├── ast_parser.py              # Source → AstSummary (224 lines)
│   ├── repo_indexer.py            # ChromaDB index (DISABLED - no-op)
│   ├── repo_sandbox.py           # Git clone → temp dir
│   ├── code_graph.py            # Dependency graph (placeholder)
│   └── container_runner.py      # Docker-in-Docker (placeholder)
│
├── confidence/
│   ├── __init__.py               # Exports engine
│   └── scoring_engine.py         # Weighted confidence logic (101 lines)
│
├── config/
│   ├── __init__.py               # Exports settings
│   └── settings.py               # Pydantic BaseSettings (28 lines)
│
├── cost/
│   ├── __init__.py              # Exports budget manager
│   └── budget_manager.py        # $5/day per-repo LLM cap (58 lines)
│
├── dashboard/
│   ├── __init__.py             # Placeholder
│   └── app.py                  # Dashboard (placeholder)
│
├── db/
│   └── __init__.py            # Placeholder (no DB layer)
│
├── evaluation/
│   ├── __init__.py           # Exports evaluator
│   ├── evaluator.py          # Precision/recall benchmarking
│   └── dataset/             # 5 hand-annotated examples
│
├── gh_client/
│   ├── __init__.py           # Exports
│   ├── webhook_server.py     # FastAPI app (551 lines)
│   ├── github_client.py     # PyGithub wrapper + raw requests (171 lines)
│   └── app_auth.py          # GitHub App authentication (placeholder)
│
├── llm/
│   ├── __init__.py          # Exports client
│   └── client.py           # OpenAI/NVIDIA NIM wrapper (221 lines)
│
├── observability/
│   ├── __init__.py          # Exports
│   ├── logging.py          # SQLite audit logging (175 lines)
│   ├── metrics.py         # Prometheus metrics (placeholder)
│   ├── tracing.py         # OpenTelemetry tracing (placeholder)
│   ├── event_stream.py    # WebSocket pub/sub (placeholder)
│   └── structured_logging.py # Structured logger (placeholder)
│
├── reliability/
│   └── __init__.py        # Placeholder (circuit breaker)
│
├── schemas/
│   ├── __init__.py       # Exports
│   ├── agent_output.py   # Issue, AgentOutput (39 lines)
│   └── pr_report.py     # PullRequestReport (82 lines)
│
├── security/
│   └── __init__.py     # Placeholder for security middleware
│   └── rate_limiter.py # Redis sliding-window rate limiting (52 lines)
│
└── task_queue/
    ├── __init__.py           # Exports
    ├── celery_app.py         # Celery app + task definitions (103 lines)
    ├── redis_client.py     # Centralized Redis client (128 lines)
    └── task_registry.py   # Concurrency slot management (placeholder)
```

### 5.1 Responsibility of Each Top-Level Module

| Module | Responsibility |
|--------|---------------|
| **agents/** | Implement the three domain-specific analyzers and the arbitrator. Each agent is a pure function `diff_text → AgentOutput`, invoked both directly and via Celery. |
| **analysis/** | All parsing and repository indexing. `diff_parser.py` is the most critical — it transforms raw diff text into line-precise hunks. |
| **confidence/** | Contains the confidence scoring logic. Acts as a utilities module consumed by the arbitrator and agents. |
| **config/** | Single source of truth for environment-driven settings. Used everywhere. |
| **cost/** | Budget management. Enforces the daily $5 cap. Acts as middleware between the LLM client and the API. |
| **gh_client/** | All GitHub interaction. The webhook server validates and routes; the GitHub client performs API calls. |
| **llm/** | Single LLM wrapper. All agent code calls `generate_analysis()` from this module, ensuring centralized token budgeting and retry. |
| **observability/** | Logging, metrics, tracing. All agent executions log to SQLite via `observability/logging.py`. |
| **schemas/** | Pydantic models for all data structures. Enforces validation everywhere. |
| **security/** | Rate limiting. Used in the webhook handler before any processing. |
| **task_queue/** | Celery configuration and Redis connection. All Celery tasks are defined here. |

### 5.2 How Modules Are Connected

The primary connection is through the **webhook server** (`gh_client/webhook_server.py`), which imports and orchestrates all other modules:

```python
# webhook_server.py (lines 1-51, partial)
from prguard_ai.analysis.repo_indexer import initialize_repo_index
from prguard_ai.analysis.code_graph import build_code_graph
from prguard_ai.analysis.repo_sandbox import clone_repository
from prguard_ai.gh_client.github_client import get_pr_diff, post_pr_comment, post_inline_comment
from prguard_ai.observability.logging import log_agent_execution
from prguard_ai.task_queue.celery_app import run_style_agent, run_logic_agent, run_security_agent, run_arbitrator
from prguard_ai.security.rate_limiter import check_installation_limit, check_repo_limit
from prguard_ai.schemas.agent_output import AgentOutput
```

Each agent imports the LLM client:

```python
# style_agent.py, logic_agent.py, security_agent.py each have:
from prguard_ai.llm.client import generate_analysis
```

The scoring engine is imported by agents and arbitrator:

```python
# logic_agent.py, security_agent.py:
from prguard_ai.confidence.scoring_engine import estimate_issue_confidence

# arbitrator_agent.py:
from prguard_ai.confidence.scoring_engine import aggregate_confidence, calculate_agent_confidence
```

All schemas are defined in `schemas/` and used everywhere `AgentOutput`, `Issue`, and `PullRequestReport` appear.

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

#### Step 2: Repository Setup and Diff Fetch

- **Location**: `gh_client/webhook_server.py:292-314`
- **Flow**:
  1. Call `get_pr_diff(repo_full_name, pr_number)` → raw unified diff text.
  2. Extract `clone_url` from payload.
  3. Call `clone_repository(repo_url, pr_number, repo_full_name)` → `RepoSandbox` object with `.temp_path`.
  4. Call `initialize_repo_index(repo_path)` → no-op in current implementation.
  5. Call `build_code_graph(repo_path)` → best-effort, exceptions swallowed.

#### Step 3: Agent Task Dispatch

- **Location**: `gh_client/webhook_server.py:326-351`
- **Flow**:
  1. Record `style_started = time.time()`.
  2. Call `run_style_agent.delay(diff_text, repo_metadata)`.
  3. Record timestamps and broadcast events for each agent similarly.
  4. Call `.get(timeout=60)` on each `AsyncResult`.
  5. Deserialize each dict to `AgentOutput`:
     ```python
     style_output = AgentOutput(**style_output_dict)
     ```

#### Step 4: Agent Execution (Inside Celery Worker)

Each agent follows the same pattern. Example: **Style Agent**:

- **Location**: `agents/style_agent.py:231-290`
- **Flow**:
  1. Parse diff: `parsed = parse_diff(diff_text)`.
  2. Extract changed files: `extract_changed_files(parsed)[:50]`.
  3. Rule-based checks over hunks:
     - Detect tab indentation (`"\t" in text`).
     - Detect long lines (`len(text) > 120`).
     - Detect frontend design issues (`_detect_frontend_design_issues()`).
  4. Retrieve repository style examples: `retrieve_similar_code(snippet)`.
  5. Build LLM prompt: `_build_llm_input(diff_text, repo_examples)`.
  6. Call `generate_analysis(prompt, max_tokens=1500, pr_id)`.
  7. Parse JSON response: `_parse_llm_issues(text)`.
  8. Attach file paths to issues: `_attach_file_paths_to_llm_issues()`.
  9. Compute confidence: `0.9 if issues else 0.5`.
  10. Return `AgentOutput(agent="style", confidence, issues)`.

**Logic Agent** (`agents/logic_agent.py:90-156`):

- Same pattern, but:
  - Builds AST summary: `_build_ast_summary_for_hunks()` → `summarize_source()`.
  - Retrieves context lines around changes: `extract_context_lines()`.
  - LLM prompt includes AST summary and surrounding code.
  - Confidence: `estimate_issue_confidence(issues, empty_confidence=0.45)`.

**Security Agent** (`agents/security_agent.py:72-135`):

- Same pattern, but:
  - Pattern detectors defined at module level (`detect_sql_injection`, `detect_eval_usage`, `detect_hardcoded_secrets`).
  - Detects `eval(`/`exec(`, SQL injection patterns, hardcoded secrets via regex/keyword matching.
  - Confidence: `estimate_issue_confidence(issues, empty_confidence=0.55)`.

#### Step 5: Arbitrator Execution

- **Location**: `agents/arbitrator_agent.py:56-73`
- **Flow**:
  1. Call `aggregate_confidence(outputs)` → weighted average of agent scores.
  2. Flatten all issues from all agents.
  3. Call `detect_agent_disagreements(outputs)` → list of disagreement notes.
  4. Build `PullRequestReport` with `overall_confidence`, `agent_outputs`, `issues`.
  5. Attach `disagreements` as dynamic attribute via `setattr()`.

#### Step 6: Post Review Comments

- **Location**: `gh_client/webhook_server.py:456-483`
- **Flow**:
  1. Call `format_pr_review(arb_output)` → Markdown body.
  2. Call `post_pr_comment(repo, pr_number, body)` → GitHub API.
  3. Iterate `arb_output.issues`:
     - Limit to first 10.
     - Skip if severity not in `["medium", "high"]`.
     - Skip if no `file_path`.
     - Call `post_inline_comment(repo, pr_number, path, line, body)`.

#### Step 7: Cleanup

- **Location**: `gh_client/webhook_server.py:486-491`
- **Flow**:
  1. If `sandbox_path` exists, call `cleanup_repository(sandbox_path)`.
  2. If `registered`, call `complete_pr_processing(pr_id)`.
  3. Call `release_global_slot()`.

### 6.2 Request → Processing → Response Lifecycle

| Phase | What Happens | Key Functions Called |
|-------|---------------|---------------------|
| **1. Request Reception** | HTTP POST to `/webhook` with signed JSON | `verify_github_signature()`, `check_repo_limit()`, `check_installation_limit()` |
| **2. Diff Fetch** | GitHub API returns unified diff | `get_pr_diff()` (`github_client.py`) |
| **3. Sandbox Setup** | Clone repo to temp dir | `clone_repository()` (`repo_sandbox.py`) |
| **4. Agent Dispatch** | 3 Celery tasks enqueued | `run_X_agent.delay()` (`celery_app.py`) |
| **5. Agent Execution** | Each agent runs rule-based + LLM checks | `parse_diff()`, `generate_analysis()`, `analyze_X()` |
| **6. Arbitration** | Aggregate confidence and detect disagreements | `aggregate_confidence()`, `detect_agent_disagreements()` |
| **7. Post Comment** | Markdown review + inline comments | `post_pr_comment()`, `post_inline_comment()` |
| **8. Cleanup** | Delete sandbox, release slot | `cleanup_repository()`, `release_global_slot()` |

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

1. **Webhook handler** receives the PR event, validates HMAC, rate limits.
2. **get_pr_diff()** fetches the diff containing the above.
3. **Style agent**:
   - Rule check: line length < 120, no tabs → no issues.
   - LLM: detects `f"echo {cmd}"` is a formatting inconsistency? (subjective) → no issues.
4. **Logic agent**:
   - Rule check: no bare `except:`, no TODOs → no issues.
   - LLM: with AST summary showing function `run_user_command(cmd: str)`, the LLM may reason that `cmd` is user-controlled and `shell=True` is unsafe → generates a MEDIUM or HIGH issue.
5. **Security agent**:
   - Rule check: `shell=True` in `subprocess.run` → flags as potential command injection (via pattern `shell=True` detection in rule-based pass if present).
   - LLM: also detects command injection → HIGH issue.
6. **Arbitrator**:
   - Aggregates agent scores: average ≈ 0.75.
   - Disagreement detection: logic reports high, style reports none → flagged.
7. **Post**:
   - Review comment with both logic and security issues.
   - Inline comment on line 4 (the `subprocess.run` line).

---

## 7. Data Layer & State Management

### 7.1 Database Schema / Structure

SQLite is used for audit logging. Database file: `prguard_logs.sqlite` (at `observability/logging.py:11`).

#### `agent_logs` Table

```sql
CREATE TABLE agent_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_id TEXT NOT NULL,
    agent TEXT NOT NULL,          -- "style", "logic", "security", "arbitrator"
    started_at REAL NOT NULL,    -- Unix timestamp
    finished_at REAL NOT NULL,   -- Unix timestamp
    confidence REAL,             -- Confidence 0.0-1.0
    token_usage INTEGER,           -- Total tokens used
    execution_duration REAL,    -- finished_at - started_at
    agent_order INTEGER,          -- 1=style, 2=logic, 3=security, 4=arbitrator
    payload TEXT NOT NULL          -- JSON string of full AgentOutput
)
```

#### `llm_usage` Table

```sql
CREATE TABLE llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_id TEXT NOT NULL,
    agent TEXT NOT NULL,
    model TEXT,                  -- e.g., "openai/gpt-oss-120b"
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    estimated_cost_usd REAL NOT NULL
)
```

### 7.2 Data Flow and Storage Logic

- **Write path**: After each agent completes (lines 358-422 in `webhook_server.py`), `log_agent_execution()` is called, which opens a new sqlite3 connection, executes an INSERT, and closes. No connection pooling.
- **Read path**: The `/review/{pr_id}` endpoint calls `fetch_pr_logs(pr_id)`, which selects from `agent_logs` ordered by `started_at`.
- **No migrations**: The `_get_conn()` function in `observability/logging.py` creates tables on every call if they don't exist (`CREATE TABLE IF NOT EXISTS`). This is safe for single-writer use but would cause race conditions under concurrent writes from multiple API instances.

### 7.3 Caching, Indexing, Optimization Techniques

| Technique | Location | Implementation |
|-----------|----------|----------------|
| **Repository style index** | `analysis/repo_indexer.py` | ChromaDB index (currently disabled/no-op). Intended for retrieving similar code snippets to pass to LLM as context. |
| **Code graph cache** | `analysis/code_graph.py` | Builds dependency graph of repository; best-effort caching. |
| **Replay protection cache** | `redis_client.py:webhook_server` | Redis `SETNX` with 5-minute TTL at key `prguard:webhook:delivery:{delivery_id}`. |
| **Rate limiting** | `security/rate_limiter.py` | Redis sorted set (`ZSET`) with sliding window. |
| **Cost bucketing** | `cost/budget_manager.py` | Redis string incremented daily, expired at end of day. |
| **Global concurrency slots** | `task_registry.py` | Redis counter for max concurrent PRs. |

---

## 8. Key Design Patterns Used

### 8.1 Multi-Agent Fan-Out / Fan-In

- **What**: One orchestrator dispatches multiple parallel workers, then aggregates results.
- **Where**: `webhook_server.py:326-433`.
- **Why**: Different issue domains require different detectors. Parallel execution reduces wall-clock time.
- **Trade-off**: Complexity of result aggregation; potential for inconsistent findings across agents.

### 8.2 Confidence Weighting

- **What**: Each issue has a `confidence_source` tag (`rule_based`, `llm_reasoning`, `inferred`) mapped to a numeric weight. Per-agent confidence blends base score with average issue weight. Aggregate confidence boosts by 0.1 if any high-severity issue exists.
- **Location**: `confidence/scoring_engine.py`.
- **Why**: Rule-based findings are deterministic → higher weight. LLM findings are probabilistic → lower weight. Aggregated score reflects cross-agent validation.
- **Trade-off**: Weights are tuned constants; may not generalize across all issue types.

### 8.3 Disagreement Detection

- **What**: The arbitrator compares severity distributions across agents. If one agent reports high-severity issues and another reports none, a disagreement note is added to the review.
- **Location**: `arbitrator_agent.py:12-46`.
- **Why**: When agents disagree, it's worth surfacing the disagreement to the human reviewer.
- **Trade-off**: Disagreement detection is naive (only compares presence/absence of HIGH severity).

### 8.4 Hybrid Rule-Based + LLM Analysis

- **What**: Each agent runs deterministic checks first (fast, high-confidence), then invokes LLM for deeper analysis. Issues from both passes are merged.
- **Location**: Each agent's `analyze_X()` function.
- **Why**: Rule-based checks catch obvious patterns (SQL injection regex, `eval(` keyword). LLM catches context-dependent issues (command injection across multiple lines, logical edge cases).
- **Trade-off**: LLM calls introduce latency, cost, and non-determinism. Offline mode returns empty results.

### 8.5 Celery Task with Autoretry

- **What**: Each agent task has `autoretry_for=(Exception,)`, `retry_backoff=True`, `retry_kwargs={"max_retries": 1}`.
- **Location**: `task_queue/celery_app.py:49-79`.
- **Why**: Transient failures (Redis blip, LLM API timeout) should not cause PR review to fail silently.
- **Trade-off**: One retry may double execution time; max_retries=1 keeps it bounded.

### 8.6 Sliding Window Rate Limiting

- **What**: Redis sorted set per key; on each request, remove entries older than window, add new entry with score=timestamp, count entries. If count > limit, reject.
- **Location**: `security/rate_limiter.py:18-36`.
- **Why**: Fixed-window counters allow burst at window boundaries; sliding window smooths traffic.
- **Trade-off**: Requires Redis; graceful fallback to allow-all if Redis unavailable.

### 8.7 Budget Manager with Daily Cap

- **What**: Redis string per repository per day; incremented on each LLM call with estimated cost. If value > $5, reject new calls.
- **Location**: `cost/budget_manager.py`.
- **Why**: Unbounded LLM usage would make the system prohibitively expensive. Daily cap per repo enforces budget discipline.
- **Trade-off**: Legitimate high-volume repos hit cap; no queueing or priority.

---

## 9. Performance & Scalability Considerations

### 9.1 Bottlenecks in the Current System

| Bottleneck | Location | Impact |
|-----------|----------|--------|
| **Synchronous wait in webhook** | `webhook_server.py:346-351` | Each agent call `.get(timeout=60)` blocks the webhook thread. With 3 agents + 1 arbitrator, worst-case blocking time ≈ 4×60s = 240s. GitHub webhook timeout is ~10s, so the webhook may return 504 before agents complete if Celery is backlogged. |
| **No incremental diff analysis** | All agents call `parse_diff()` on full diff every time. | Large diffs (>10k lines) cause O(n) parsing and O(n) AST summarization per agent, repeated 3x. |
| **SQLite single-writer** | `observability/logging.py` | Every `log_agent_execution()` opens and closes a connection. Under concurrent requests from 3+ webhooks, writer lock contention. |
| **LLM API latency** | `llm/client.py:141-209` | Each retry attempt adds `RETRY_BACKOFF_SECONDS * attempt`. With MAX_RETRIES=3 and backoff=2s, worst-case LLM call = 6s extra. |
| **Repository cloning** | `repo_sandbox.py` | Small clones (<10MB) are fast; larger repos (100MB+) can take 10-30 seconds, blocking the webhook while cloning. |

### 9.2 How It Scales (Or Doesn't)

- **Horizontal**: Workers can be scaled by adding more Celery worker processes. However, the webhook server itself is single-threaded (uvicorn default). Under load, the webhook becomes the bottleneck.
- **Vertical**: The `task_time_limit=60` and `task_soft_time_limit=45` in Celery config cap individual task runtime. This prevents runaway tasks but also means large diffs may timeout.
- **Database**: SQLite is single-writer. Under concurrent webhook invocations, writes would serialize at the SQLite layer. Not suitable for multi-instance deployment.

### 9.3 Suggestions for Improvement

1. **Make webhook async**: Replace `.get(timeout=60)` with `await` on Celery result using aasync Celery (celery[gevent] or celery[eventlet], or switch to a proper async task queue like `temporal`). Post comments via separate async task after webhook returns.

2. **Incremental analysis**: On `synchronize` event, store the previous diff in Redis. Compute diff of diffs. Only analyze changed hunks.

3. **Connection pooling for SQLite**: Replace per-call `sqlite3.connect()` with a persistent connection or switch to PostgreSQL.

4. **Code graph caching**: Cache repository dependency graph in Redis with per-repo TTL. Reuse across PRs to same repo.

5. **GitHub API caching**: Cache PR diffs with ETag/Last-Modified headers. Avoid refetching unchanged diffs.

6. **Result caching**: If PR is reopened without new commits, return cached review instead of re-running agents.

---

## 10. Weaknesses & Limitations

### 10.1 Design Flaws or Risks

| Weakness | Severity | Impact |
|---------|----------|--------|
| **Inline comments limited to 10** | Medium | High-volume PRs with >10 medium/high issues will have issues silently dropped. |
| **No per-file confidence scoring** | Medium | All issues from a 1000-line file are treated with same confidence as issues from a 10-line file. |
| **No support for edited comments** | Low | If user edits a PR comment, the system does not update its audit log. |
| **No idempotency for comments** | Low | If webhook retried (e.g., GitHub didn't receive 200), duplicate comments may be posted. |
| **No encryption at rest** | High | SQLite and Redis contain PR diffs and audit logs. If container is compromised, plain-text code is exposed. |
| **Hardcoded severity thresholds** | Low | Severity thresholds (`len(text) > 120`, font size < 12px) are hardcoded. No per-repo configuration yet. |
| **No multi-language AST** | High | `ast_parser.py` only supports Python. If repo contains Go, Rust, TypeScript, the tree-sitter fallback is a no-op. |

### 10.2 Technical Debt Areas

| Area | Evidence |
|------|----------|
| **ChromaDB is disabled** | `repo_indexer.py` is entirely no-op. ChromaDB is in requirements.txt but never instantiated. |
| **Code graph is placeholder** | `code_graph.py` exists but likely `build_code_graph()` is a stub. No evidence of actual graph building in the codebase. |
| **Fake Redis fallback** | `redis_client.py:109-115` silently falls back to in-memory `fakeredis` in production if Redis is unreachable. This can mask infrastructure failures. |
| **Offline mode as test stub** | `llm/client.py` returns empty `[]` if API key missing or offline mode enabled. This means tests pass but production silently under-performs. |
| **No test fixtures for large diffs** | `fixtures/sample_diff.txt` is tiny. No stress test of parser with 10k+ lines. |
| **App auth is placeholder** | `gh_client/app_auth.py` likely returns a stub. GitHub App integration not fully implemented. |

### 10.3 What Would Break Under Scale or Edge Cases

| Edge Case | Failure Mode |
|-----------|-------------|
| **PR with 500+ changed files** | `MAX_FILES_PER_PR = 50` truncates analysis; issues in files 51+ are silently ignored. |
| **Binary files in diff** | Diff parser may corrupt binary content; AST summary will fail. No binary detection. |
| **Non-Python files** | Logic and security agents run regex on any language. False positives (e.g., JavaScript `eval()` is different from Python `eval()`). |
| **Very long lines (>10k chars)** | Diff parser line buffer may overflow; rule check `len(text) > 120` becomes meaningless. |
| **GitHub API rate limit** | `get_pr_diff()` and `post_pr_comment()` call GitHub API; if rate limited, entire webhook fails. No GitHub API-side retry. |
| **Concurrent webhooks from same repo** | `is_pr_processing()` and `register_pr_processing()` provide basic idempotency, but SQLite logging under concurrent writes would fail. |

---

## 11. How to Improve This System

### 11.1 Concrete, Actionable Improvements

| Improvement | Effort | Rationale |
|-------------|--------|----------|
| **Enable ChromaDB indexing** | Medium | Uncomment the ChromaDB client creation in `repo_indexer.py`. This enables style agent to retrieve repository-specific examples, improving LLM quality. |
| **Add file-level confidence** | Medium | Weight confidence by file size and line count. Large files that affect many modules should have higher confidence. |
| **Incremental diff analysis** | Medium | On `synchronize`, compute diff between current and base, only analyze changed hunks. Cache base diff in Redis. |
| **GitHub App fully implemented** | High | Complete `app_auth.py` to support GitHub App authentication (currently a placeholder). This enables fine-grained permission management. |
| **Multi-language AST parser** | High | Add tree-sitter grammars for Go, TypeScript, Rust, JavaScript. Currently Python-only. |
| **Replace SQLite with PostgreSQL** | Medium | Single-writer SQLite cannot support multi-instance deployment. PostgreSQL provides connection pooling and ACID compliance. |
| **Per-repo configuration** | Medium | Add a `.prguard.yml` in repository root. Allow per-repo overrides for severity thresholds, ignored files, agent behavior. |

### 11.2 Better Architectural Alternatives

1. **Event-driven architecture**: Instead of synchronous waiting in webhook, use a message queue (Redis pub/sub) to notify the API server when agents complete. The webhook returns immediately; the review comment is posted asynchronously. This removes the 60-second blocking window.

2. **Result caching**: Store `AgentOutput` in Redis keyed by (`repo_full_name`, `pr_number`, `diff_hash`). On `synchronize`, if diff hash unchanged, return cached review.

3. **Circuit breaker for LLM**: Wrap LLM client in circuit breaker pattern (e.g., `pybreaker`). If LLM error rate > threshold, stop invoking LLM in agents, fall back to rule-based only.

4. **Multi-instance deployment**: Add a load balancer in front of multiple FastAPI replicas. Replace SQLite with shared PostgreSQL. Redis already supports sentinel.

### 11.3 Refactoring Suggestions

1. **Extract agent interfaces**: `style_agent.py`, `logic_agent.py`, and `security_agent.py` share almost identical structure (parse diff → rule check → LLM → merge). Extract a base `Agent` class with `analyze(diff_text) -> AgentOutput` to reduce duplication.

2. **Unify confidence calculation**: Move all confidence computation into `confidence/scoring_engine.py`. Currently duplicated in agents and arbitrator.

3. **Remove dead code**: Remove `code_graph.py`, `container_runner.py`, `dashboard/`, `reliability/`, `db/` if they are placeholders.

4. **Consolidate Redis clients**: Currently `redis_client.py`, `rate_limiter.py`, `budget_manager.py`, `task_registry.py` each import their own Redis instance. Consolidate to a single Redis client factory.

---

## 12. Learning Notes (For a Developer)

### 12.1 Key Concepts to Study From This Project

| Concept | Where It Appears | Study Focus |
|---------|-----------------|------------|
| **Multi-agent orchestration** | `webhook_server.py:326-433` | Fan-out/fan-in pattern with parallel Celery tasks. |
| **Confidence scoring with weighted sources** | `confidence/scoring_engine.py` | Blending deterministic and probabilistic signals. |
| **Hybrid rule-based + LLM analysis** | Each agent's `analyze_X()` | Running deterministic checks before expensive LLM calls. |
| **Diff parsing** | `analysis/diff_parser.py` | Understanding unified diff format and line number tracking. |
| **AST summarization** | `analysis/ast_parser.py` | Tree-sitter vs stdlib `ast` fallback. |
| **Rate limiting (sliding window)** | `security/rate_limiter.py` | Redis sorted set implementation. |
| **Cost budgeting** | `cost/budget_manager.py` | Daily token budget enforcement. |
| **Celery task autoretry** | `task_queue/celery_app.py` | Task retry policies and time limits. |
| **GitHub webhook security** | `webhook_server.py:106-285` | HMAC verification, replay protection, timestamp validation. |
| **Audit logging** | `observability/logging.py` | SQLite persistence in code review. |

### 12.2 What Skills This Project Demonstrates

- **Building a multi-agent system**: Designing specialized agents that each focus on a single domain (style, logic, security) and aggregating their results.
- **Hybrid AI pipelines**: Combining deterministic rule-based checks with probabilistic LLM reasoning in a single processing pipeline.
- **API integration**: Building and securing a webhook server that integrates with GitHub's API and accepts external LLM providers.
- **Distributed task queues**: Using Celery to run long-running analysis tasks asynchronously with retry and time limits.
- **Observability**: Structured logging, Prometheus metrics, OpenTelemetry tracing — all integrated into a single pipeline.
- **Security**: HMAC verification, rate limiting, budget management, and sandboxed code execution.

### 12.3 How to Replicate or Build Something Similar

To build a similar multi-agent code review system:

1. **Start with the diff parser**: Before any agents, build a robust `parse_diff()` that transforms unified diffs into line-precise hunks. This is the foundation.

2. **Design agents as pure functions**: Each agent should be a function `(diff_text, metadata) -> AgentOutput`. This makes them testable and Celery-wrappable.

3. **Choose your analysis approach**:
   - **Rule-based**: Regex, keyword matching, AST pattern matching.
   - **LLM-based**: Prompt engineering with context.
   - **Hybrid**: Run rule-based first (fast), LLM fallback for uncertain cases.

4. **Add confidence scoring**: Tag each issue with a source (`rule_based`, `llm_reasoning`, `inferred`). Weight aggregate scores accordingly.

5. **Add disagreement detection**: Aggregate scores across agents and surface disagreements.

6. **Integrate with a webhook**: Secure with HMAC, rate limit, replay protection.

7. **Choose a task queue**: Celery is a good choice for Python. Use separate queues for each agent.

8. **Add observability early**: Log agent executions, latencies, token usage. Add Prometheus metrics for queue depths and latency histograms.

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

## Appendix C: Key File Locations Reference

| Component | File Path |
|-----------|----------|
| Webhook server (FastAPI app) | `src/prguard_ai/gh_client/webhook_server.py` |
| Celery tasks | `src/prguard_ai/task_queue/celery_app.py` |
| Style agent | `src/prguard_ai/agents/style_agent.py` |
| Logic agent | `src/prguard_ai/agents/logic_agent.py` |
| Security agent | `src/prguard_ai/agents/security_agent.py` |
| Arbitrator | `src/prguard_ai/agents/arbitrator_agent.py` |
| Diff parser | `src/prguard_ai/analysis/diff_parser.py` |
| AST parser | `src/prguard_ai/analysis/ast_parser.py` |
| LLM client | `src/prguard_ai/llm/client.py` |
| Scoring engine | `src/prguard_ai/confidence/scoring_engine.py` |
| Settings | `src/prguard_ai/config/settings.py` |
| GitHub client | `src/prguard_ai/gh_client/github_client.py` |
| Rate limiter | `src/prguard_ai/security/rate_limiter.py` |
| Budget manager | `src/prguard_ai/cost/budget_manager.py` |
| Audit logging | `src/prguard_ai/observability/logging.py` |
| Schemas | `src/prguard_ai/schemas/agent_output.py`, `pr_report.py` |

---

*End of study guide.*