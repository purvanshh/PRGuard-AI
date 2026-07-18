# Submission Checklist

- Repository URL is public or reviewer-accessible.
- README includes exact setup, limitations, and architecture.
- Demo video link is live.
- `evaluation_report_v2.md` and optional JSON output are included.
- Grafana screenshots are captured from a production-like run.
- Helm values are configured without committed secrets.
- GitHub App credentials are rotated after any public demo.
- Known limitations are stated plainly.

## Honest Story

PRGuard AI is a production-shaped multi-agent pull request review system. The strongest parts are the orchestration architecture, policy and feedback loops, deployability assets, and testable agent/tool boundaries. The parts that still need real-world proving are long-running production traffic, human-labeled benchmark quality, and measured comparison against commercial review tools.
