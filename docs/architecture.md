## PRGuard AI Architecture

### Agent System Design

Each agent extends `BaseAgent` (`agents/base_agent.py`) which implements a ReAct loop: observe diff → select tools → execute → synthesise issues → verify findings → refine. The `AgentToolExecutor` (`agents/tools/executor.py`) provides 14 tools, with each agent selecting a subset relevant to its domain.

- **Style agent** (`agents/style_agent.py`): rule-based checks (tabs, long lines) plus LLM-guided style issues. Tools: `run_linter`, `check_formatting`, `get_repo_style_guide`, `read_file`, `search_codebase`.
- **Logic agent** (`agents/logic_agent.py`): AST-based summaries and context snippets fed into an LLM to surface logic bugs. Tools: `get_type_info`, `run_test`, `symbolic_execute`, `check_dead_code`, `search_codebase`.
- **Security agent** (`agents/security_agent.py`): pattern-based checks (eval/exec, SQL injection, secrets) plus LLM guidance. Tools: `dependency_scan`, `cve_lookup`, `secret_scan`, `check_auth_patterns`, `git_blame`, `search_codebase`.
- **Arbitrator** (`agents/arbitrator_agent.py`): aggregates all agent outputs into a single `PullRequestReport` with overall confidence and disagreement notes.

Each agent receives:

- Unified diff text for the PR.
- `repo_metadata` with `repository`, `pr_number`, `pr_id`, and optional `sandbox_path`.

All agents return a `schemas.agent_output.AgentOutput` object.

### Tool System

The `AgentToolExecutor` (`agents/tools/executor.py`) exposes 14 local analysis tools:

| Tool | Agent | Purpose |
|------|-------|---------|
| `read_file` | All | Read a file range from the sandbox |
| `search_codebase` | All | Grep the repo for a pattern |
| `run_linter` | Style | `compileall` syntax check |
| `check_formatting` | Style | `ruff format --check --diff` |
| `get_repo_style_guide` | Style | Read `.editorconfig`, `ruff.toml`, `pyproject.toml` style config |
| `run_test` | Logic | `pytest` on a target |
| `get_type_info` | Logic | AST-based function signature extraction |
| `symbolic_execute` | Logic | Branch-path enumeration through a function |
| `check_dead_code` | Logic | Detect unreachable statements after return/raise |
| `dependency_scan` | Security | Parse dependency manifests for suspicious tokens (`*`, `http://`, `git+http`) |
| `cve_lookup` | Security | Shell out to `pip-audit` for known CVEs |
| `secret_scan` | Security | Regex-based hardcoded secret detection (API keys, tokens, private keys) |
| `check_auth_patterns` | Security | Detect weak auth patterns (bypassed auth, IP-based auth, etc.) |
| `git_blame` | Security | `git blame` for author attribution on suspicious lines |

Each agent's `analyze_tool_needs()` examines the diff and returns only the relevant tools (capped at 3 per ReAct iteration to bound execution time). The `detect_suspicious_findings()` method acts as a second-line trigger, requesting additional tools when LLM findings warrant verification.

### Repository RAG Retrieval

`analysis/repo_indexer.py` and the style agent support retrieval-augmented hints:

- Similar code snippets from the repository are retrieved based on diff content.
- These snippets are injected into the style prompt to align suggestions with existing project conventions.

The implementation is intentionally lightweight for this repo but can be backed by ChromaDB or other vector stores.

### Confidence Scoring

The arbitrator uses `confidence/scoring_engine.py` to:

- Combine per-agent confidence scores into an overall value.
- Optionally weight agents differently (e.g. security higher than style).
- Identify disagreements where one agent flags high-severity issues and others do not.

The final `PullRequestReport` includes:

- `overall_confidence`
- `agent_outputs`
- Flattened `issues` list
- Human-readable disagreement summary

### Evaluation Framework

`evaluation/evaluator.py` and `evaluation/dataset/*.json` define a simple evaluation loop:

- Each dataset sample contains a synthetic diff and expected issues (line + message).
- `evaluate_pr(diff, expected_issues)`:
  - Runs all three agents and the arbitrator.
  - Normalizes issues.
  - Computes true positives, false positives, and missed issues.
  - Returns precision, recall, and final confidence metrics.

`scripts/run_benchmark.py` ties this together into a repeatable benchmark run suitable for CI.

