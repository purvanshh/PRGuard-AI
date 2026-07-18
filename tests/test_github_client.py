from __future__ import annotations

from types import SimpleNamespace


def test_post_pr_comment_skips_duplicate(monkeypatch):
    from prguard_ai.gh_client import github_client as ghc

    created = []
    edited = []

    class Comment:
        def __init__(self, body: str):
            self.body = body

        def edit(self, body: str) -> None:
            edited.append(body)
            self.body = body

    existing = Comment(ghc._review_body_with_marker("same body"))
    pr = SimpleNamespace(
        get_issue_comments=lambda: [existing],
        create_issue_comment=lambda body: created.append(body),
    )
    repo = SimpleNamespace(get_pull=lambda pr_number: pr)
    gh = SimpleNamespace(get_repo=lambda repo_full_name: repo)

    monkeypatch.setattr(ghc, "_get_github_client", lambda token=None: gh)

    ghc.post_pr_comment("owner/repo", 1, "same body")

    assert created == []
    assert edited == []


def test_post_pr_comment_updates_existing_review(monkeypatch):
    from prguard_ai.gh_client import github_client as ghc

    created = []
    edited = []

    class Comment:
        def __init__(self, body: str):
            self.body = body

        def edit(self, body: str) -> None:
            edited.append(body)
            self.body = body

    existing = Comment(ghc._review_body_with_marker("old body"))
    pr = SimpleNamespace(
        get_issue_comments=lambda: [existing],
        create_issue_comment=lambda body: created.append(body),
    )
    repo = SimpleNamespace(get_pull=lambda pr_number: pr)
    gh = SimpleNamespace(get_repo=lambda repo_full_name: repo)

    monkeypatch.setattr(ghc, "_get_github_client", lambda token=None: gh)

    ghc.post_pr_comment("owner/repo", 1, "new body")

    assert created == []
    assert edited == [ghc._review_body_with_marker("new body")]


def test_post_inline_comment_skips_duplicate(monkeypatch):
    from prguard_ai.gh_client import github_client as ghc

    created = []
    existing = SimpleNamespace(path="foo.py", line=10, body="duplicate")
    pr = SimpleNamespace(
        head=SimpleNamespace(sha="abc123"),
        get_review_comments=lambda: [existing],
        create_review_comment=lambda body, commit_id, path, line: created.append((body, commit_id, path, line)),
    )
    repo = SimpleNamespace(get_pull=lambda pr_number: pr)
    gh = SimpleNamespace(get_repo=lambda repo_full_name: repo)

    monkeypatch.setattr(ghc, "_get_github_client", lambda token=None: gh)

    ghc.post_inline_comment("owner/repo", 1, "foo.py", 10, "duplicate")

    assert created == []
