import os

# Configure environment variables for testing before importing settings
os.environ["PRGUARD_TESTING"] = "true"
os.environ["REDIS_MODE"] = "memory"
os.environ["REDIS_FALLBACK_TO_MEMORY"] = "true"

# Fallback dummy credentials to pass settings validation during test collection
os.environ.setdefault("GITHUB_TOKEN", "dummy-github-token")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "dummy-webhook-secret")
os.environ.setdefault("OPENAI_API_KEY", "dummy-openai-key")

