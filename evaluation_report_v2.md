# PRGuard AI Evaluation Report v2

## Scope

This report documents the phase-15 evaluation path for the current repository state. The checked-in dataset contains 525 JSON PR fixtures under `src/prguard_ai/evaluation/dataset/`.

## How to Reproduce

```bash
python -m prguard_ai.evaluation.evaluator \
  --dataset src/prguard_ai/evaluation/dataset \
  --output evaluation_report_v2.json
```

The local Codex environment used for this implementation does not include `pytest`, `PyGithub`, or the async PostgreSQL driver, so the full benchmark was not executed here. The evaluator, dataset fixtures, semantic matcher, confidence intervals, and per-agent summaries are checked in for reproducible execution in the project environment.

## Metrics Produced

The evaluator reports:

- Overall precision, recall, and F1 with confidence intervals
- Per-agent precision, recall, F1, confidence, and issue count
- Semantic true-positive matches using line proximity and token overlap
- Calibration inputs for confidence scoring

## Calibration Curve Plan

Online feedback from GitHub reactions and human approvals is stored in the phase-12 feedback tables. Monthly recalibration fits Platt-style parameters from `(confidence, accepted)` samples and writes snapshots to `calibration_snapshots`.

## Submission Evidence Checklist

- Demo video: record `scripts/run_demo.sh` against `fixtures/sample_pr_payload.json`
- Production-like deploy: use `terraform/` plus `helm/prguard`
- Metrics screenshots: Grafana dashboard at `deploy/grafana/dashboards/prguard.json`
- Architecture proof: ADRs in `docs/adr/`
