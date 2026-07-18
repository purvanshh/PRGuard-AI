## PRGuard AI Operational Runbook

### Deploying the System

- **Local development**
  - Start Redis (`docker run -p 6379:6379 redis:7`).
  - Run API with `uvicorn main:app --reload`.
  - Run worker with `celery -A queue.task_queue.celery_app worker --loglevel=INFO`.

- **Production (docker-compose)**
  - `docker compose -f deploy/docker-compose.prod.yml up -d --build`.
  - Ensure environment variables are configured in `.env` or the compose file.

- **Production (Kubernetes)**
  - Build and push the API image: `docker build -t <registry>/prguard-ai:<tag> .`.
  - Provision infrastructure from `terraform/` or attach to an existing EKS/GKE cluster.
  - Create a values override with real secrets and image coordinates.
  - Install with `helm upgrade --install prguard ./helm/prguard -f values.prod.yaml`.
  - Confirm `/health/ready`, `/health/live`, and `/metrics` are reachable through the ingress.

### Rollback

- Roll back application code with `helm rollback prguard <revision>`.
- Roll back a model or prompt canary by setting the relevant rollout percentage to `0`.
- Keep database migrations backward-compatible for one release. If a migration must be reverted, stop workers first, run `alembic downgrade <revision>`, then redeploy the previous image.

### Debugging Failures

- Check `/health`:
  - `status`, `redis`, `database`, `openai`, and `queue_depth` fields.
- Check logs:
  - All logs are structured JSON on stdout; use `jq` or similar tools to filter by `pr_id` or `agent`.
- Check metrics:
  - Visit Prometheus (`/metrics` from the API, or Prometheus UI) for error counters and queue lengths.
- Check traces:
  - Use Jaeger to inspect spans for `webhook_received`, `agent_*`, `llm_call`, and `arbitrator`.

### Restarting Workers

- **Docker / docker-compose**
  - `docker restart prguard-worker` (or corresponding service name).
- **Systemd or process manager**
  - Use your process manager (e.g. `systemctl restart prguard-worker`).

Workers are stateless. Idempotency keys and global concurrency control prevent duplicate PR processing.

### Scaling Workers

- **Docker compose**
  - Increase the `--concurrency` flag or run multiple worker containers.
- **Kubernetes (recommended)**
  - Use the Helm worker `Deployment` and HPA. CPU scaling is included by default; queue-depth scaling can be added with KEDA.
  - Ensure that Redis and the database are sized appropriately before scaling up.

Always monitor:

- Queue depths (Redis lengths for `style`, `logic`, `security`, `arbitrator`).
- Worker CPU/memory usage.

### Rotating Secrets

- Store secrets in:
  - Environment variables in production (or Kubernetes Secrets / Vault).
  - `.env` for local development.
- To rotate:
  1. Update secret source (e.g. new GitHub App key, OpenAI key).
  2. Restart API and workers so they pick up new environment.
  3. Confirm `/health` reports `openai: configured` and webhook flows still succeed.

Do not commit secrets to the repository. Use `.env.example` as a reference only.
