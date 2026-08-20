# ruleid: forbid-logging-credentials
logger.info("User token: %s", user_token)

# ruleid: forbid-logging-credentials
log.error("Login failed for password %s", password)

# ok: forbid-logging-credentials
logger.info("User %s logged in", user_id)

# ok: forbid-logging-credentials
log.error("request failed: %s", exc)