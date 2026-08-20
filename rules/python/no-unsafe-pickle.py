# ruleid: no-unsafe-pickle
data = pickle.loads(payload)

# ruleid: no-unsafe-pickle
obj = pickle.load(untrusted_stream)

# ok: no-unsafe-pickle
data = json.loads(payload)

# ok: no-unsafe-pickle
serialized = pickle.dumps(obj)

# ok: no-unsafe-pickle
data = _trusted_local_cache.load()