## Contributing to PRGuard AI

Thanks for your interest in contributing! This project is meant to be a polished open-source developer tool.

### 1. Getting Started

```bash
git clone https://github.com/your-org/prguard-ai.git
cd prguard-ai
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set the required environment variables in `.env` (at least `OPENAI_API_KEY` and `REDIS_URL`).

### 2. Running Tests

Run the unit test suite:

```bash
pytest
```

Optionally run type checks (if you have `mypy` installed):

```bash
mypy .
```

And linting (e.g. with `ruff` or `flake8`, if installed):

```bash
ruff check .
```

### 3. Running the Demo

**CLI demo**:

```bash
python scripts/prguard_demo.py path/to/repo diff.patch --record-demo
```

**Dashboard demo**:

```bash
uvicorn dashboard.app:app --reload
```

Then open:

- `http://localhost:8000/dashboard`
- `http://localhost:8000/demo`
- `http://localhost:8000/dataset`

### 4. Adding a New Analysis Agent

1. Create a new module under `agents/`, e.g. `agents/performance_agent.py`.
2. Implement a function with the signature:

```python
def analyze_performance(diff_text: str, repo_metadata: Dict[str, Any] | None = None) -> AgentOutput:
    ...
```

3. Return a `schemas.agent_output.AgentOutput` with:
   - `agent` set to your agent name.
   - `confidence` set to a float in `[0, 1]`.
   - `issues` as a list of `Issue` objects.
4. Wire the new agent into:
   - `queue/task_queue.py` (add a Celery task).
   - `github/webhook_server.py` (enqueue the new task and pass its results to the arbitrator).
5. Add tests under `tests/` to cover your agent’s behavior.

### 5. Pull Requests

- Keep changes focused and well-scoped.
- Add or update tests where appropriate.
- Update documentation (`README.md` or `docs/`) if behavior or configuration changes.

We’re happy to review contributions that improve security, reliability, developer experience, or agent quality.

