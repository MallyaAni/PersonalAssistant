"""A rejected request must say which field it was rejected on.

A 422 used to be invisible from the server side: uvicorn logged the status and
nothing else, the browser showed "Server responded with 422", and finding the
cause meant testing candidate payloads against the schema by hand. Chat alone
has six fields that can produce one.
"""

import logging

from fastapi.testclient import TestClient

from backend.main import app

# Authentication resolves before the body is validated, so a protected route
# answers 401 and never reaches the validator. The suite-wide fixture in
# conftest pins AUTH_REQUIRED off so the repository's own `.env` cannot decide
# whether these pass.


def test_a_rejected_request_names_the_field_in_the_log(caplog):
    client = TestClient(app)

    with caplog.at_level(logging.WARNING):
        response = client.post(
            "/api/v1/chat",
            json={
                "user_id": "ani.mallya",
                "conversation_id": "not-a-uuid",
                "query": "hello",
                "metadata": {},
            },
        )

    assert response.status_code == 422
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "conversation_id" in logged
    assert "/api/v1/chat" in logged


# The body carries whatever the user typed, so the log must locate the fault
# without reproducing the message itself.
def test_the_submitted_text_is_not_written_to_the_log(caplog):
    client = TestClient(app)
    secret = "my private message about a medical appointment"

    with caplog.at_level(logging.WARNING):
        client.post(
            "/api/v1/chat",
            json={
                "user_id": "ani.mallya",
                "conversation_id": "not-a-uuid",
                "query": secret,
                "metadata": {},
            },
        )

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert secret not in logged


# The bug this handler shipped with. A field validator that raises ValueError
# puts the exception object into the error's `ctx`, and returning that straight
# to JSONResponse cannot be serialized - so the rejection surfaced as the
# original exception propagating rather than as a 422. A type error (a bad
# UUID) carries no such object and hid it.
def test_a_validator_raising_value_error_still_answers_422(caplog):
    client = TestClient(app)

    response = client.post(
        "/api/v1/chat",
        json={
            "user_id": "ani.mallya",
            "conversation_id": "02eb0706-139a-43ff-8ec8-2a28387c0ee8",
            "query": "   ",
            "metadata": {},
        },
    )

    assert response.status_code == 422
    assert "must not be blank" in response.text
