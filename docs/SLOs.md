# PRGuard AI SLOs

## Targets

- Availability: 99.9% of webhook requests return a non-5xx response.
- Latency: p95 end-to-end review latency stays below 5 minutes.
- Error rate: agent task error rate stays below 1% over 15 minutes.
- Queue health: no production queue remains above 100 pending jobs for 10 minutes.

## Prometheus Queries

- p95 latency: `histogram_quantile(0.95, sum(rate(prguard_review_latency_seconds_bucket[5m])) by (le))`
- agent error rate: `sum(rate(prguard_agent_errors_total[15m])) / clamp_min(sum(rate(prguard_prs_processed_total[15m])), 1)`
- queue depth: `max(prguard_queue_depth)`
- circuit breaker open: `prguard_circuit_breaker_state == 2`
