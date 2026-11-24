import pytest
from sqlalchemy import text

from tests.integration.helpers import create_alert, create_investigation

pytestmark = pytest.mark.integration


def _audit_rows(engine, investigation_id):
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT from_status, to_status, outcome FROM investigation_audit "
                "WHERE investigation_id = :investigation_id "
                "ORDER BY changed_at, audit_id"
            ),
            {"investigation_id": investigation_id},
        ).all()


def test_investigation_audit_captures_create_and_status_changes(db) -> None:
    alert_id = create_alert(db)
    investigation_id = create_investigation(db, alert_id=alert_id, status="open")

    rows = _audit_rows(db, investigation_id)
    assert len(rows) == 1
    assert rows[0].from_status is None
    assert rows[0].to_status == "open"

    with db.begin() as connection:
        connection.execute(
            text(
                "UPDATE investigations SET status = 'in_review' "
                "WHERE investigation_id = :investigation_id"
            ),
            {"investigation_id": investigation_id},
        )

    rows = _audit_rows(db, investigation_id)
    assert len(rows) == 2
    assert rows[1].from_status == "open"
    assert rows[1].to_status == "in_review"

    with db.begin() as connection:
        connection.execute(
            text(
                "UPDATE investigations SET notes = 'note only' "
                "WHERE investigation_id = :investigation_id"
            ),
            {"investigation_id": investigation_id},
        )

    assert len(_audit_rows(db, investigation_id)) == 2

    with db.begin() as connection:
        connection.execute(
            text(
                "UPDATE investigations SET status = 'closed', "
                "outcome = 'confirmed_issue', closed_at = NOW() "
                "WHERE investigation_id = :investigation_id"
            ),
            {"investigation_id": investigation_id},
        )

    rows = _audit_rows(db, investigation_id)
    assert len(rows) == 3
    assert rows[2].from_status == "in_review"
    assert rows[2].to_status == "closed"
    assert rows[2].outcome == "confirmed_issue"
