from prguard_ai.analysis.diff_parser import chunk_diff_by_file
from prguard_ai.security import rate_limiter


class FakeRedis:
    def __init__(self) -> None:
        self.values = {}

    def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def decr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) - 1
        return self.values[key]

    def expire(self, key: str, seconds: int) -> None:
        return None


def test_repo_concurrency_is_per_repo(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(rate_limiter, "get_redis", lambda: fake)

    assert rate_limiter.check_repo_concurrency("org/a", max_inflight=1) is True
    assert rate_limiter.check_repo_concurrency("org/a", max_inflight=1) is False
    assert rate_limiter.check_repo_concurrency("org/b", max_inflight=1) is True


def test_release_repo_concurrency_decrements_slot(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(rate_limiter, "get_redis", lambda: fake)

    assert rate_limiter.check_repo_concurrency("org/a", max_inflight=1) is True
    rate_limiter.release_repo_concurrency("org/a")
    assert rate_limiter.check_repo_concurrency("org/a", max_inflight=1) is True


def test_chunk_diff_by_file_keeps_file_boundaries():
    diff = "\n".join(
        f"diff --git a/file{i}.py b/file{i}.py\n+++ b/file{i}.py\n@@ -1 +1 @@\n+print({i})"
        for i in range(5)
    )

    chunks = chunk_diff_by_file(diff, max_files_per_chunk=2)

    assert len(chunks) == 3
    assert all(chunk.count("diff --git") <= 2 for chunk in chunks)
