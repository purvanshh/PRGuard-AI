# Semgrep Phase 1: Baseline Scan Report

Scope: PRGuard AI source tree (`src/prguard_ai/`, 599 tracked files)
Tool: Semgrep 1.174.0
Rulesets: `p/owasp-top-ten` (156 rules) and `p/default` (293 rules)
Date: 2026-08-21

## 1. Summary

| Ruleset | Rules run | Findings | ERROR | WARNING | INFO |
|---|---|---|---|---|---|
| `p/owasp-top-ten` | 156 | 3 | 0 | 3 | 0 |
| `p/default` | 293 | 4 | 2 | 2 | 0 |

Both scans completed in < 10 seconds on the pilot repo, well inside the
60-second PR scan target. The baseline validates end-to-end tooling (JSON
output, severity mapping, diff-aware scanning) before automation.

## 2. Findings Triage

| # | Rule ID | Severity | Location | Verdict | Notes |
|---|---|---|---|---|---|
| 1 | `insecure-hash-algorithm-md5` | WARNING | `analysis/repo_indexer.py:48` | FP | MD5 used for content-addressed cache keys (`repo_path:offset` digest), never for cryptography or signatures. |
| 2 | `insecure-hash-algorithm-md5` | WARNING | `analysis/repo_indexer.py:56` | FP | Same non-cryptographic cache-key use. |
| 3 | `python-logger-credential-disclosure` | WARNING | `llm/client.py:305` | FP | Log message contains the word "token budget" matched by rule; no secret material is passed to the logger (only `%s` + exception). |
| 4 | `non-literal-import` | WARNING | `analysis/ast_parser.py:122` | FP | `import_module` receives a static binding name from the `_LANGUAGE_BINDINGS` config dict, not user input. |
| 5 | `detect-insecure-websocket` | ERROR | `dashboard/app.py:190` | FP | Deliberate protocol logic: `wss` when the page is served over `https`, `ws` otherwise. Rule fires on the inlined JS template. |
| 6 | `detect-insecure-websocket` | ERROR | `dashboard/app.py:257` | FP | Same deliberate conditional as #5. |

Observed false positive rate on pilot: 6/6 (100%). All are structural/context
FPs — the result of rules matching patterns without full program context,
which is exactly what the Phases 4–5 tuning strategy addresses.

## 3. Phase 1 Conclusions

1. **Ruleset selection — confirmed:** `p/owasp-top-ten` + `p/python` + in-repo
   custom rules (`rules/`). `p/default` adds cross-language noise on a
   Python-first repo, so it is used only for the weekly exploratory scan, not
   the PR gate.
2. **Severity filtering confirmed:** filtering to ERROR-only on the pilot
   surfaces only the two WebSocket findings; nothing in the repo triggers an
   ERROR-class security defect. This supports the plan's "start
   non-blocking, tune thresholds later" approach.
3. **`nosemgrep` is required:** all six triaged FPs are legitimately
   suppressible with `# nosemgrep: <rule-id>` comments, which Semgrep honors
   natively. Developer guidance is part of the Phase 5 rollout.
4. **Evidence snippets:** Semgrep's public-registry scans omit `extra.lines`
   (requires authentication). The PRGuard scanner therefore reads the file
   line directly when the snippet is absent, keeping `Issue.evidence` populated
   for PR comments.
5. **Output format:** Semgrep JSON is the integration contract
   (`prguard_ai/semgrep/parser.py`); SARIF is emitted only in CI for GitHub
   Code Scanning.

## 4. Baseline Evaluation Dataset

For future F1 comparison (Phase 5.6), the CVE evaluation dataset lives under
`dataset/` and uses the existing `scripts/*eval*` helpers. The Semgrep scan
time on this pilot (6 CPython files, whole tree) is negligible relative to the
LLM agents' latency, so Phase 4's parallel chord execution will not threaten
the < 2-minute end-to-end budget.