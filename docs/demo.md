# Demo Script

## Five-Minute Flow

1. Start the stack with `docker compose up --build`.
2. Open Grafana and the approval dashboard.
3. Trigger `scripts/run_demo.sh` or replay `fixtures/sample_pr_payload.json`.
4. Show the Style, Logic, and Security agents producing independent findings.
5. Show coordinator debate and arbitrator synthesis.
6. Demonstrate a low-confidence review entering the human approval queue.
7. Approve the review and show the final GitHub-ready review body.

## Recording Notes

Keep the demo grounded in what the system actually does: webhook intake, async agents, policy enforcement, human review, observability, and deployability. Avoid claims about live production traffic unless the production-like environment has been running and measured.
