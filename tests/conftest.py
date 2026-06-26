import os

# Configure environment variables for testing before importing settings
os.environ["REDIS_MODE"] = "memory"
os.environ["REDIS_FALLBACK_TO_MEMORY"] = "true"
