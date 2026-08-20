# ruleid: no-hardcoded-secrets
API_KEY = "sk-1234567890abcdef1234567890"

# ruleid: no-hardcoded-secrets
password = "hunter2-secret-password"

# ruleid: no-hardcoded-secrets
slack_token = "xoxb-12345678901234567890"

# ok: no-hardcoded-secrets
api_key = os.environ["API_KEY"]

# ok: no-hardcoded-secrets
password = getpass.getpass()

# ok: no-hardcoded-secrets
SECRET_KEY = settings.deepseek_api_key