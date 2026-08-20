# Semgrep Integration Plan

Status: Approved
Owner: PRGuard AI Maintainers
Last updated: 2026-08-21

## 1. Goal

Integrate [Semgrep](https://semgrep.dev) as a deterministic, AST-based static
analysis layer in PRGuard AI. Semgrep findings are fed into the Confidence
Arbitrator alongside the existing Style, Logic, and Security LLM agents so that
high-confidence, rule-based results can corroborate (or contradict) LLM
reasoning — improving precision and reducing reliance on regex-based detectors
alone.

## 2. Scope and Success Criteria

| Metric | Target |
|---|---|
| PR-time scan duration | < 60 seconds on average |
| Nightly full-scan duration | < 5 minutes on the pilot repo |
| False positive rate | < 15% after tuning |
| PRGuard end-to-end pipeline | < 2 minutes (Semgrep runs in parallel with agents) |
| Coverage | 100% of target repos onboarded incrementally |
| Detection quality | Measurable F1 improvement over LLM-only baseline |

## 3. Language Support (0.1)

Pilot target languages and their Semgrep rule categories:

| Language | Status | Rule category |
|---|---|---|
| Python | Supported | `p/python` |
| Go | Supported | `p/golang` |
| TypeScript / JavaScript | Supported | `p/javascript` + `p/typescript` |
| Rust | Supported | `p/rust` |
| Terraform (config) | Supported | `p/terraform` |

PRGuard AI's primary stack (Python/TypeScript) is fully covered by the Semgrep
community rulesets listed in Section 5.

## 4. Scan Frequency and Schedule (0.2)

| Trigger | Scope | Mode |
|---|---|---|
| `pull_request` (diff-aware) | New findings only, via `--baseline-ref main` | Non-blocking advisory first; quality gate later |
| Nightly `schedule` (2:00 AM UTC) | Full scan of default branch | Non-blocking, SARIF uploaded to GitHub Code Scanning |

## 5. Ruleset Selection (0.4)

Initial rulesets (phased):

1. `p/owasp-top-ten` — security baseline across all languages.
2. `p/default` — broad community coverage (used for the Phase 1 baseline scan).
3. `p/python` — language-specific depth for the primary stack.
4. Custom rules in `rules/` — project-specific anti-patterns (Phase 2), shipped
   in-repo so they are versioned with the application.

Rollout: start with `p/owasp-top-ten` + `rules/` in the CI workflow, expand with
`p/python` and additional language packs as more repos onboard.

## 6. Deployment Phases (0.3)

| Phase | Duration (est.) | Deliverable | Gate |
|---|---|---|---|
| 0. Planning | 1–2 days | This document | Stakeholder sign-off |
| 1. Exploration | 2–3 days | Baseline scan report (`docs/semgrep-baseline-report.md`), ruleset selection | FP rate < 30% |
| 2. Custom rules | 1–2 weeks | `rules/` with test fixtures; `semgrep --validate` + `semgrep --test` green | 0 test failures |
| 3. CI/CD | 3–5 days | `.github/workflows/semgrep.yml` (PR + nightly + SARIF) | PR scan < 60 s |
| 4. PRGuard integration | 1 week | `prguard_ai/semgrep/` scanner + arbitrator wiring + tests | E2E < 2 min |
| 5. Rollout | 2–4 weeks | Pilot repos → all repos; rule tuning; `.semgrepignore` | FP < 15% |

Pilot repos: PRGuard AI itself plus one Python service. Expansion is gated by a
per-repo feature flag and rollout percentage
(`PRGUARD_FLAG_SEMGREP_INTEGRATION` + `_ROLLOUT_PERCENT`).

## 7. Confidence and Arbitration Model (Phase 4)

- Semgrep findings are emitted with `confidence_source="semgrep"` and
  `verified=True` (deterministic tool output).
- Source weight: `semgrep` = **0.9** — the highest weight in the scoring engine,
  above the regex `rule_based` detectors (0.88) and `llm_reasoning` (0.62).
- Severity mapping: Semgrep `ERROR` → `high`, `WARNING` → `medium`,
  `INFO` → `low`.
- Tier computation treats `semgrep` issues as deterministic rule-based findings
  for HIGH-tier decisions.
- Deduplication: findings that share `(file_path, line)` with another agent's
  finding are consolidated into one issue with a corroboration note, preventing
  duplicate PR comments.
- Supression: Semgrep honors `# nosemgrep: <rule-id>` comments natively; no
  re-implementation required on the PRGuard side.

## 8. Gotchas Tracked

1. Do not block PRs immediately — start non-blocking (`fail_on: none`),
   monitor FP rate, then raise thresholds. 
2. Custom rules are test-first (`semgrep --test`); untested rules are rejected
   in CI via `semgrep --validate` on every push to `rules/`.
3. `nosemgrep` documentation is included in the developer-facing report notes.
4. Scan size is bounded with `--max-target-bytes` and `.semgrepignore` to keep
   PR scans under 60 seconds.
5. Semgrep runs as a parallel sibling task in the initial agent chord, not
   sequentially, to preserve the < 2-minute end-to-end target.