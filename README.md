## PRGuard AI

**Author**: purvansh ([`@purvanshh`](https://github.com/purvanshh))

PRGuard AI is an AI-powered multi-agent review system for GitHub pull requests. It automatically analyzes changes for **style consistency**, **logical correctness**, and **security vulnerabilities**, then aggregates findings into a single, actionable review comment.

### Architecture Overview

- **GitHub Webhook**: GitHub sends `pull_request` events to the FastAPI webhook endpoint.
- **FastAPI Server**: Validates the webhook signature, fetches the PR diff, and enqueues Celery tasks.
- **Analysis Agents**:
  - **Style agent**: Flags formatting and consistency issues.
  - **Logic agent**: Highlights potential logical errors.
  - **Security agent**: Detects obviously unsafe patterns.
- **Confidence Engine**: Aggregates per-agent outputs into an overall confidence score.
- **GitHub Client**: Posts a summarized review comment back to the pull request.
- **Celery + Redis**: Handles task execution for each agent.
- **ChromaDB + tree-sitter**: Provide the foundation for semantic and structural code analysis.

#### High-Level Diagram

```text
GitHub PR Event
        |
        v
  FastAPI /webhook
        |
        v
   Celery Tasks  ----> Style Agent
        |             Logic Agent
        |             Security Agent
        v
  Confidence Arbitrator
        |
        v
 GitHub PR Comment
```

### Setup Instructions

#### 1. Clone the repository

```bash
git clone <your-repo-url> prguard-ai-repo
cd prguard-ai-repo/prguard-ai
```

#### 2. Create and configure environment

Copy the example environment file and set your secrets:

```bash
cp .env.example .env
```

Set at minimum:

- `OPENAI_API_KEY`
- `GITHUB_TOKEN`
- `GITHUB_WEBHOOK_SECRET`
- `REDIS_URL` (optional, defaults to `redis://redis:6379/0`)

#### 3. Install dependencies (local development)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### 4. Run tests

```bash
pytest
```

### Running with Docker Compose

From the `prguard-ai` directory:

```bash
docker-compose up --build
```

This will start:

- `api`: FastAPI webhook server exposed on port `8000`.
- `worker`: Celery worker processing analysis tasks.
- `redis`: Redis instance used as both broker and backend.

### Configuring the GitHub Webhook

1. In your GitHub repository, go to **Settings → Webhooks**.
2. Click **Add webhook**.
3. Set:
   - **Payload URL**: `http://<your-public-host>/webhook`
   - **Content type**: `application/json`
   - **Secret**: must match `GITHUB_WEBHOOK_SECRET` in your `.env`.
4. Under **Which events would you like to trigger this webhook?**
   - Select **Let me select individual events**.
   - Enable **Pull requests**.
5. Click **Add webhook**.

Once configured, new and updated pull requests will trigger PRGuard AI to analyze the diff and post a summarized review comment with aggregated confidence.

