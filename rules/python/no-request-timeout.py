# ruleid: no-request-timeout
resp = requests.get(url)

# ruleid: no-request-timeout
requests.post(endpoint, json=payload)

# ok: no-request-timeout
resp = requests.get(url, timeout=10)

# ok: no-request-timeout
client = httpx.Client(timeout=5)

# ok: no-request-timeout
resp = requests.get(url, timeout=(3.05, 27))