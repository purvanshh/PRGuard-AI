## PRGuard AI Architecture

### Agent System Design

- **Style agent** (`agents/style_agent.py`): rule-based checks (tabs, long lines) plus LLM-guided style issues.
- **Logic agent** (`agents/logic_agent.py`): AST-based summaries and context snippets fed into an LLM to surface logic bugs.
- **Security agent** (`agents/security_agent.py`): pattern-based checks (eval/exec, SQL injection, secrets) plus LLM guidance.
- **Arbitrator** (`agents/arbitrator_agent.py`): aggregates all agent outputs into a single `PullRequestReport` with overall confidence and disagreement notes.

Each agent receives:

- Unified diff text for the PR.
- `repo_metadata` with `repository`, `pr_number`, `pr_id`.

All agents return a `schemas.agent_output.AgentOutput` object.

### Code Graph Reasoning

`analysis/code_graph.py` builds a lightweight import graph over the repository:

- Scans Python files up to a fixed limit.
- Extracts `import` / `from` statements into an adjacency map.
- Caches results per repository path.

Agents can use this graph to understand module relationships, e.g. to prioritize issues in central modules.

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

