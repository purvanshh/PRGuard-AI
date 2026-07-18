from fastapi.testclient import TestClient

from prguard_ai.dashboard.app import app
from prguard_ai.human_review import HumanReviewQueue, escalation_message, human_review_queue
from prguard_ai.schemas.agent_output import Issue
from prguard_ai.schemas.pr_report import PullRequestReport


def make_report(confidence: float) -> PullRequestReport:
    return PullRequestReport(
        overall_confidence=confidence,
        issues=[
            Issue(
                line=3,
                severity="medium",
                message="Borderline finding",
                evidence="uncertain evidence",
                confidence_source="llm_reasoning",
            )
        ],
    )


def test_low_confidence_report_requires_human_review():
    queue = HumanReviewQueue(auto_post_threshold=0.72)

    assert queue.should_auto_post(make_report(0.71)) is False
    assert queue.should_auto_post(make_report(0.90)) is True


def test_escalation_marks_pending_review():
    queue = HumanReviewQueue()
    pending = queue.enqueue("owner/repo#1", make_report(0.4))

    message = escalation_message(pending)

    assert pending.escalation_sent is True
    assert "owner/repo#1" in message


def test_dashboard_pending_review_approve_flow():
    human_review_queue._pending.clear()
    pending = human_review_queue.enqueue("owner/repo#2", make_report(0.5))
    client = TestClient(app)

    page = client.get("/dashboard/pending")
    approve = client.get(f"/dashboard/reviews/{pending.review_id}/approve")

    assert page.status_code == 200
    assert "owner/repo#2" in page.text
    assert approve.json()["status"] == "approved"


def test_dashboard_override_modifies_review():
    human_review_queue._pending.clear()
    pending = human_review_queue.enqueue("owner/repo#3", make_report(0.5))
    client = TestClient(app)

    response = client.get(
        f"/dashboard/reviews/{pending.review_id}/override",
        params={"message": "Ship after adding a regression test."},
    )

    assert response.status_code == 200
    assert pending.report.issues[0].confidence_source == "human_feedback"
