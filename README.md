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

Code review is a bottleneck in every engineering org: it consumes senior developer hours, slows delivery, and vulnerabilities slip through when reviews are rushed. PRGuard AI addresses this with a multi-agent system that analyzes pull requests across style, logic, and security dimensions using a mix of rule-based detectors, AST analysis, and LLM reasoning. In a real-world evaluation against 50 CVE-fix PRs from python/cpython and nodejs/node, the system achieved a 0.92 F1 score (0.92 precision, 0.92 recall).

The system is built for production: asynchronous task queues with retry logic, PostgreSQL audit logging, circuit breakers on LLM calls, Redis-backed token budgeting, HMAC webhook verification, replay attack protection, rate limiting, sandboxed repository cloning with LRU-evicted caching, and structured JSON logging with OpenTelemetry trace propagation.

---

## Table of Contents

- [Architecture](#architecture)
- [Example Output](#example-output)
- [Agent Breakdown](#agent-breakdown)
- [Confidence Scoring](#confidence-scoring)
- [Setup](#setup)
- [GitHub Webhook Configuration](#github-webhook-configuration)
- [Environment Variables](#environment-variables)
- [API Endpoints](#api-endpoints)
- [Repository Structure](#repository-structure)
- [Security](#security)
- [Evaluation](#evaluation)
- [Project Status](#project-status)
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
        ORCH -->|"parallel run"| SEMGREP["Semgrep Scanner"]
        INIT -->|"store context"| REDIS[("Redis Context Store")]
        SEMGREP -->|"store findings"| REDIS
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
> **Confidence:** Medium (2 rule-based, 3 LLM-reasoned, 2 verified by tool)
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

### Semgrep Scanner (4th Parallel Task)

Runs as a distinct Celery chord task alongside the Style, Logic, and Security agents. Unlike the LLM-based agents, Semgrep is deterministic and requires no refinement rounds.

| Pass | Method | What It Catches |
|------|--------|-----------------|
| AST Pattern Matching | Semgrep OSS engine | `shell=True` in subprocess, unsafe `eval()`/`pickle`, hardcoded secrets, SQL injection patterns |
| Custom Rules | `rules/python/*.yaml` (test-first) | Project-specific anti-patterns (e.g., missing timeout on requests, credential logging) |
| Diff-Aware | `--baseline-ref origin/main` | Only scans changed files in PRs, keeping scan time < 60 seconds |

**Confidence Weight:** `semgrep` findings carry a deterministic `0.9` weight (`verified=True`), the highest in the system. Findings are deduplicated with LLM outputs by the Confidence Arbitrator based on file + line number.

> **Note:** the Semgrep integration is feature-flag gated (`PRGUARD_FLAG_SEMGREP_INTEGRATION`, see [Environment Variables](#environment-variables)) and runs as a parallel chord task, so it does not add sequential latency to the end-to-end review.

---

## Confidence Scoring

Every finding carries a `confidence_source` tag that maps to a numeric weight:

| Source | Weight | Meaning |
|--------|--------|---------|
| `semgrep` | **0.9** | Deterministic AST scan finding: highest certainty, auto-verified |
| `rule_based` | **0.9** | Deterministic pattern match: high certainty |
| `llm_reasoning` | **0.6** | LLM-generated finding: moderate certainty |
| `inferred` | **0.3** | Heuristic or indirect signal: low certainty |

**Per-agent score:** `refined = (base_confidence + avg_issue_weight) / 2`, clamped to `[0.0, 1.0]`.

**Aggregate score:** Agent scores are averaged, with a +0.1 boost (capped at 1.0) applied when any high-severity issue exists across any agent.

**Disagreement detection:** The arbitrator compares severity distributions across agents and flags the review when one agent reports high-severity findings that another does not.

---

## Setup

### Prerequisites

- Python 3.11+
- Docker and Docker Compose
- A GitHub account with a repository to monitor
- A DeepSeek API key

### Docker (Recommended)

```bash
git clone https://github.com/purvanshh/PRGuard-AI.git
cd PRGuard-AI

cp .env.example .env
# Edit .env with your credentials

docker compose up --build
```

This starts five containers:

| Container | Role | Port |
|-----------|------|------|
| `prguard-api` | FastAPI webhook server | 8000 |
| `prguard-worker` | Celery agent worker | — |
| `prguard-redis-data` | Redis data store (context, cache) | 6379 |
| `prguard-redis-broker` | Redis Celery broker and result backend | 6380 |
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

The test suite enforces a minimum coverage threshold of 70%. 288 tests cover diff parsing, agent analysis, confidence scoring, evaluation infrastructure, model routing, scalability controls, distributed tracing, security hardening, human-in-the-loop review, circuit breaker behaviour, token budgeting, health checks, sanitization, repository caching, task registry, Celery task execution, Pydantic schemas, structured logging, tool executor (including all 14 per-agent tools), policy engine, feedback loop, prompt management, batch review scripts, and the end-to-end pipeline. Current coverage is 77%.

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
| `DEEPSEEK_API_KEY` | Yes | — | DeepSeek API key for LLM analysis |
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
| `PRGUARD_FLAG_SEMGREP_INTEGRATION` | No | `false` | Master feature flag for the Semgrep integration |
| `PRGUARD_FLAG_SEMGREP_INTEGRATION_ROLLOUT_PERCENT` | No | `0` | Per-repo gradual rollout (0–100). E.g., `10` means 10% of repos get scanned |
| `SEMGREP_BINARY` | No | `semgrep` | Semgrep binary path/name used by the scanner |
| `SEMGREP_CONFIGS` | No | `p/owasp-top-ten` | Comma-separated Semgrep configs/rulesets |
| `SEMGREP_TIMEOUT_SECONDS` | No | `90` | Max execution time for a Semgrep scan per PR |
| `SEMGREP_MAX_TARGET_BYTES` | No | `2000000` | Skip files larger than this many bytes during a scan |
| `SEMGREP_BASELINE_REF` | No | `origin/main` | Git ref for diff-aware (PR-time) scanning |

*Required unless GitHub App authentication is configured.*

Reference: [`.env.example`](.env.example)

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/webhook` | GitHub webhook receiver: HMAC-verified, replay-protected |
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
├── tests/                   # Unit and integration test suite (288 tests, 77% coverage)
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
- **LLM output sanitization**: HTML escaping, non-printable character stripping, and per-agent issue caps
- **Secrets never logged**: structured logging masks all sensitive configuration values

---

## Evaluation

### Synthetic Benchmark (200 fixtures, CI/regression)

| Metric | Value |
|--------|-------|
| Precision | 0.71 |
| Recall | 0.96 |
| F1 | 0.82 |

### Real-World CVE Evaluation (50 PRs, python/cpython)

50 CVE-fix PRs scraped from `python/cpython` (and `nodejs/node`) via GitHub search. Ground truth derived from CVE descriptions and commit messages. Evaluation run with DeepSeek API (`deepseek-chat`).

| | Batch 1 (10 PRs) | Batch 2 (40 PRs) | Combined (50) |
|---|---|---|---|
| True Positives | 6 | 17 | 23 |
| False Positives | 1 | 1 | 2 |
| False Negatives | 2 | 0 | 2 |
| **Precision** | 0.86 | **0.94** | **0.92** |
| **Recall** | 0.75 | **1.00** | **0.92** |
| **F1** | **0.80** | **0.97** | **0.92** |

**Gap analysis:** Real-world F1 (0.92) exceeds synthetic F1 (0.82), indicating the system generalizes to unseen, real-world patches. Batch 2 achieved 17/17 security PR detection with zero false negatives. The only false positive across both batches (PR 100373) flagged a legitimate DER certificate concern that was not CVE-tagged. The 2 batch 1 false negatives are attributed to silent empty responses from the LLM under rapid-fire evaluation; retry-with-backoff at the LLM call level is a known gap.

### Running Evaluation

```bash
# Synthetic benchmark
python -m prguard_ai.evaluation.evaluator --dataset src/prguard_ai/evaluation/dataset/

# Scrape and review CVE PRs (requires DEEPSEEK_API_KEY + gh CLI)
python scripts/scrape_cve_prs.py --repos python/cpython nodejs/node --total 40 --out dataset/real_cve_prs_batch2
python scripts/batch_review.py --input dataset/real_cve_prs_batch2 --parallel 4 --output dataset/real_cve_prs_batch2/results.json

# Generate labels template and evaluate
python scripts/generate_labels_template.py --results dataset/real_cve_prs_batch2/results.json --manifest dataset/real_cve_prs_batch2/manifest.json --output dataset/real_cve_prs_batch2/labels.jsonl
python scripts/analyze_real_results.py --labels dataset/real_cve_prs_batch2/labels.jsonl --results dataset/real_cve_prs_batch2/results.json

# Batch 1 evaluation
python scripts/analyze_real_results.py
```

---

## Production Incidents

### The Batch Review That Vanished

Running 40 PRs through the pipeline was supposed to be automated. Instead it was 3 AM, two terminals deep, chasing a process that refused to finish.

**What happened:** The batch review script launched 4 parallel workers. 20 minutes later — no output, no errors, no results file. `ps aux` showed nothing. The process had been silently killed. No crash log, no traceback, nothing.

**Root cause chain:**
1. The `ThreadPoolExecutor` context manager exits on any unhandled exception in a worker thread
2. The security agent's `_parse_llm_issues` calls `json.loads()` on the LLM response
3. DeepSeek occasionally truncates its JSON mid-string (one response ended with `"Unlimited chunked trailer` — no closing quote, no closing brace)
4. `json.JSONDecodeError` propagated uncaught out of the worker thread
5. The `with ThreadPoolExecutor() as pool:` block killed the remaining workers on exit
6. No `try/except` around the parse call, no `finally:` block to flush partial results

**The fix that held:**
- Wrapped `json.loads()` in a `try/except` that records the raw response for debugging instead of crashing
- Changed from writing results once at the end to saving after every completed PR (incremental checkpoint)
- Added `--resume` flag that skips already-completed PRs by reading the partial results file

**The detail that still bothers me:** The `TokenBudget.used` property returned 0 for every single one of the 40 PRs. The token counter was wired up — `LLMClient.__init__` accepts a `token_budget` parameter, `generate()` calls `check_and_consume()` before every API call — but the agents construct their own `LLMClient` internally instead of using the one passed in. So the `token_budget` the batch runner creates never gets wired to anything. The evaluation report shows "Total tokens: 0" — a useless number. I left this unfixed because fixing it means refactoring three agent constructors to forward the client, and the token tracking doesn't affect correctness. It just means I can't answer "how many tokens did 40 PRs cost?" without running the billing report instead.

### The "suspicious LLM response for PR None" Warning

Every PR that went through tripped a log line: `Style agent: suspicious LLM response for PR None — possible prompt injection`.

The `pr_id` was `None` because the prompt injection detector reads the PR number from the review context, and the batch runner passes the diff text directly to agents without building a `ReviewContext` first. The injection detector worked exactly as coded — it just got `None` for the PR number and flagged it anyway. No actual injection, just noisy logs that eroded trust in the monitoring.

**Lesson:** When you have 6 monitoring signals all firing at once, you stop believing any of them. Fewer, quieter, meaningful alerts beat a dashboard full of red.

---

## Known Limitations

PRGuard AI is a research-grade system with the following known gaps:

- **Rule-based detectors are shallow**: Pattern-matched detections (`detect_off_by_one`, `detect_none_dereference`, etc.) use simple regex heuristics that produce false positives on complex code. They are a complement to the LLM, not a replacement for static analysis tools like Semgrep or CodeQL.
- **LLM cost and latency**: Each PR review triggers 12+ LLM calls (3 agents x 3 refinement rounds + coordinator + arbitrator + refinement messages). At DeepSeek pricing ($0.50/M input tokens, $2.00/M output tokens), a moderate PR costs ~$0.01-$0.03. The circuit breaker and token budget mitigate runaway costs but can silently skip analysis.
- **Multi-language support is uneven**: AST parsing and rule detectors are Python-heavy. Go, TypeScript, Rust, and other languages rely almost entirely on the LLM pass without strong static checks.
- **No incremental analysis**: Every PR is fully re-analysed; there is no diff-aware caching of file-level analysis results across sequential PRs.
- **Chunked PR analysis is not yet implemented**: For PRs exceeding 50 files or 5000 lines, the system truncates rather than chunking and merging.
- **CVE lookup is a stub**: `cve_lookup` shells out to `pip-audit` when `requirements.txt` is present; it does not query the GitHub Advisory Database or NVD directly.
- **Secret scanning is regex-only**: `secret_scan` uses hand-written regex patterns with no entropy analysis or pre-commit hook integration. It will miss obfuscated or structured secrets like JWT tokens with low entropy.
- **Symbolic execution is path-counting, not constraint solving**: `symbolic_execute` enumerates AST branches but does not solve path constraints; it cannot prove reachability or detect contradictions.
- **Confidence is tiered**: PRGuard reports High/Medium/Low confidence with source and verification counts instead of pretending decimal scores are probabilities.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines, branching conventions, and pull request requirements.

---

## License

[MIT](LICENSE)

---

<div align="center">

Built by [Purvansh Sahu](https://github.com/purvanshh) &nbsp;|&nbsp; 4th Year CS at Scaler School of Technology + BITS Pilani &nbsp;|&nbsp; ML Research Intern at IIT Madras

LLM backend powered by DeepSeek API (deepseek-chat)

</div>
