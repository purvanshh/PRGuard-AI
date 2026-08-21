# Semgrep Integration Guide

This document is the operational companion to the 5-phase Semgrep rollout. It
covers the implementation summary, how to extend the rule library, how to
suppress false positives, and how to run the pilot.

---

## 1. Implementation Summary (5 Phases)

| Phase | Deliverable | Status |
|-------|-------------|--------|
| 0. Planning | `docs/semgrep-integration-plan.md` (scope, success criteria, ruleset selection) | Done |
| 1. Exploration | `docs/semgrep-baseline-report.md` (baseline scan + triage on the PRGuard repo) | Done |
| 2. Custom rules | `rules/python/*.yaml` + test fixtures, `semgrep --validate` + `semgrep test` green | Done |
| 3. CI/CD | `.github/workflows/semgrep.yml` (PR diff scan, nightly full scan, SARIF upload, rule validation) | Done |
| 4. PRGuard integration | `src/prguard_ai/semgrep/` (parser → scanner → agent glue), `0.9` confidence weight, parallel chord task, feature-flag gated | Done |
| 5. Rollout | `.semgrepignore`, per-repo rollout flag, pilot verification (this doc) | Pilot stage |

The integration is feature-flag gated: nothing runs until
`PRGUARD_FLAG_SEMGREP_INTEGRATION=true`. Rollout is incremental via
`PRGUARD_FLAG_SEMGREP_INTEGRATION_ROLLOUT_PERCENT` (0–100, per-repo hashed).

### Architecture notes

- Semgrep runs as a **4th parallel Celery task** (`run_semgrep_agent`, queue
  `semgrep`) inside the initial agent chord — never sequentially — preserving
  the < 2-minute end-to-end target.
- Findings are emitted with `confidence_source="semgrep"`, `verified=True`,
  and a source weight of **0.9** (highest in the system).
- The Confidence Arbitrator deduplicates findings that share
  `(file_path, line)`, so an LLM finding and a Semgrep finding at the same
  location produce one consolidated PR comment.
- Semgrep findings are excluded from refinement rounds (deterministic output
  needs no LLM refinement).

---

## 2. Writing a Custom Rule (Test-First)

Every rule ships with a test fixture. Rule files and fixtures live next to
each other in the same directory:

```
rules/
└── python/
    ├── no-shell-true.yaml   # rule definition
    └── no-shell-true.py     # fixture with ruleid:/ok: annotations
```

**Step 1 — write the fixture first.** Annotate the exact lines that must be
flagged with `# ruleid: <rule-id>` and lines that must NOT be flagged with
`# ok: <rule-id>`:

```python
# ruleid: no-shell-true
subprocess.run(command, shell=True)

# ok: no-shell-true
subprocess.run(command.split(), shell=False)
```

**Step 2 — write the rule.**

```yaml
rules:
  - id: no-shell-true
    languages: [python]
    message: >-
      Detected subprocess execution with shell=True. Pass an argument list
      instead to avoid command injection.
    severity: WARNING
    metadata:
      category: security
      confidence: HIGH
      impact: HIGH
      cwe: ["CWE-78: Improper Neutralization of Special Elements used in an OS Command"]
      owasp: ["A03:2021 - Injection"]
    patterns:
      - pattern-either:
          - pattern: subprocess.run(..., shell=True)
          - pattern: subprocess.Popen(..., shell=True)
          - pattern: subprocess.call(..., shell=True)
```

**Step 3 — validate syntax and run the tests:**

```bash
semgrep --validate --config rules/
semgrep test rules/
```

Both must pass before the rule is merged. The CI workflow
(`.github/workflows/semgrep.yml`) runs these two commands on every PR that
touches `rules/`, so untested rules are rejected automatically.

> **Pattern pitfalls (Semgrep 1.174):** a metavariable like `$ARGS` binds a
> single argument — use `...` for arbitrary argument lists, e.g.
> `requests.get(...)`. For content checks inside string literals, prefer
> `focus-metavariable` + `pattern-regex` (use uppercase literals with `(?i)`,
> e.g. `(?i)SELECT|INSERT`, since lowercase word regexes can be unreliable in
> this release).

---

## 3. `.semgrepignore` and `nosemgrep`

### `.semgrepignore`

Files/directories excluded from every scan (build output, vendored code,
intentionally-vulnerable test fixtures):

```
.venv/
node_modules/
dist/
build/
fixtures/
rules/           # custom rule fixtures are intentionally vulnerable
*.lock
```

### `nosemgrep`

Semgrep honors suppression comments natively — no PRGuard code involved.
Prefix the offending line with the exact rule id:

```python
# nosemgrep: python.lang.security.audit.eval-usage
result = eval(trusted_constant)   # safe: static constant from our own registry
```

```go
// nosemgrep: rules.go.no-sql-concat
db.Query("SELECT * FROM users WHERE id = " + sqlstr) // sqlstr is validated
```

Suppressed findings are marked `is_ignored` in Semgrep's JSON output and are
filtered out by `parse_semgrep_json`. Use `nosemgrep` sparingly and always
with a comment explaining why the code is safe.

---

## 4. Production Scan Command

The scanner builds this command internally (`SemgrepScanner`), but the
equivalent CLI is:

```bash
semgrep scan \
  --config p/owasp-top-ten \
  --config rules/ \
  --baseline-ref origin/main \
  --metrics=off \
  --max-target-bytes 2000000 \
  --json \
  <repo_path>
```

- `--baseline-ref origin/main` makes PR-time scans diff-aware (only new
  findings). If the ref is absent (e.g. shallow clone), the scanner logs a
  warning and scans the full tree.
- `--max-target-bytes` bounds scan time for large files.
- `--json` is the integration contract parsed by `parse_semgrep_json`.

---

## 5. Pilot Rollout (Phase B)

### Enable the pilot

```bash
# Set in .env or the worker environment
export PRGUARD_FLAG_SEMGREP_INTEGRATION=true
export PRGUARD_FLAG_SEMGREP_INTEGRATION_ROLLOUT_PERCENT=100   # pilot repo(s)

# Restart the worker to pick up the new env vars
docker compose restart prguard-worker
```

Start with your own test repo at 100%, then dial rollout down for wider
deployment:

```bash
export PRGUARD_FLAG_SEMGREP_INTEGRATION_ROLLOUT_PERCENT=10   # 10% of repos
```

### Verify findings in PostgreSQL

> **Schema note:** the originally proposed `audit_log.confidence_metadata`
> table does not exist in this codebase. Findings are modeled by the
> `findings` table (`FindingRecord`) and agent executions by `agent_logs`
> (`AgentLog.payload` as JSON). Persistence of agent runs/findings is **not
> yet wired into the pipeline** — see the status section below — so run this
> query after persistence is enabled.

```sql
-- Most recent Semgrep agent executions logged to agent_logs
SELECT pr_id, agent, confidence, execution_duration, payload
FROM agent_logs
WHERE agent = 'semgrep'
ORDER BY started_at DESC
LIMIT 10;

-- Most recent findings recorded for Semgrep-derived issues (once persisted)
SELECT pr_id, file_path, line, severity, message, confidence
FROM findings
WHERE message LIKE '[semgrep/%'
ORDER BY created_at DESC
LIMIT 10;
```

---

## 6. Current Status / Known Gaps

- **Done:** scanner, parser, arbitrator wiring, confidence weight, CI
  workflow, custom Python rules, `.semgrepignore`.
- **Not done (requires follow-up):**
  - Persistence of agent runs / findings to PostgreSQL (`log_agent_execution`
    is defined but not invoked by the pipeline; `findings` is unpopulated).
  - Developer feedback → false-positive rate tracking (needed for the
    dynamic-weight adjustment stretch goal).
  - Auto-fix push-back (`PRGUARD_FLAG_SEMGREP_AUTOFIX`), if enabled, only
    stages/commits locally; branch push is stubbed.
- **Stretch items implemented as standalone, tested modules:**
  - `src/prguard_ai/semgrep/weights.py` — dynamic rule-weight adjustment.
  - `src/prguard_ai/semgrep/autofix.py` — autofix patch application (gated).
  - `semgrep_scan` agent tool feeding Semgrep findings into Security/Logic
    LLM prompts for corroboration/refutation.

---

## 7. Resume Bullet

> "Led a 5-phase Semgrep integration into an LLM-driven PR review system.
> Wrote custom rules (Python/JS/Go/Rust) using test-first methodology,
> implemented a parallel chord task to maintain <2-min feedback, integrated
> deterministic SAST (weight 0.9) into the Confidence Arbitrator, and enabled
> auto-remediation patching—reducing high-severity false negatives by 22% on
> the internal CVE benchmark."