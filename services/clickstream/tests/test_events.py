import uuid
from datetime import datetime, timedelta, timezone

from .conftest import access_token, now_iso, product_view

URL = "/api/v1/clickstream/events"


def test_a_batch_is_queued_one_message_per_event_keyed_by_session(client, publisher):
    search = {
        "event_id": str(uuid.uuid4()),
        "type": "search",
        "occurred_at": now_iso(),
        "session_id": "anon-session-1",
        "query": "running shoes",
        "result_count": 12,
    }
    cart = {
        "event_id": str(uuid.uuid4()),
        "type": "add_to_cart",
        "occurred_at": now_iso(),
        "session_id": "anon-session-2",
        "product_id": str(uuid.uuid4()),
        "variant_id": str(uuid.uuid4()),
        "quantity": 2,
    }
    response = client.post(URL, json={"events": [product_view(), search, cart]})

    assert response.status_code == 202
    assert response.json() == {"accepted": 3}
    assert [key for key, _ in publisher.sent] == ["anon-session-1", "anon-session-1", "anon-session-2"]
    assert publisher.sent[1][1]["query"] == "running shoes"


def test_anonymous_events_are_recorded_with_no_user_and_a_receipt_time(client, publisher):
    client.post(URL, json={"events": [product_view()]})

    _, payload = publisher.sent[0]
    assert payload["user_id"] is None
    assert datetime.fromisoformat(payload["received_at"]).tzinfo is not None


def test_a_signed_in_shopper_is_identified_from_the_token_not_the_body(client, publisher):
    user = uuid.uuid4()
    response = client.post(
        URL,
        json={"events": [product_view()]},
        headers={"Authorization": f"Bearer {access_token(user)}"},
    )

    assert response.status_code == 202
    assert publisher.sent[0][1]["user_id"] == str(user)


def test_a_user_id_in_the_body_is_refused(client, publisher):
    body = {"events": [product_view() | {"user_id": str(uuid.uuid4())}]}

    response = client.post(URL, json=body)

    assert response.status_code == 422
    assert publisher.sent == []


def test_an_expired_or_broken_token_is_recorded_as_anonymous(client, publisher):
    expired = access_token(uuid.uuid4(), expires_in=-60)

    for header in (f"Bearer {expired}", "Bearer not-a-token"):
        response = client.post(URL, json={"events": [product_view()]}, headers={"Authorization": header})
        assert response.status_code == 202

    assert [payload["user_id"] for _, payload in publisher.sent] == [None, None]


def test_a_refresh_token_is_not_treated_as_a_sign_in(client, publisher):
    refresh = access_token(uuid.uuid4(), token_type="refresh")

    client.post(URL, json={"events": [product_view()]}, headers={"Authorization": f"Bearer {refresh}"})

    assert publisher.sent[0][1]["user_id"] is None


def test_an_unknown_event_type_is_refused(client, publisher):
    response = client.post(URL, json={"events": [product_view(type="page_view")]})

    assert response.status_code == 422
    assert publisher.sent == []


def test_an_event_stamped_in_the_future_is_refused(client, publisher):
    later = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    response = client.post(URL, json={"events": [product_view(), product_view(occurred_at=later)]})

    assert response.status_code == 422
    assert "events[1]" in response.json()["detail"]
    assert publisher.sent == []


def test_a_slightly_fast_clock_is_allowed(client, publisher):
    soon = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()

    assert client.post(URL, json={"events": [product_view(occurred_at=soon)]}).status_code == 202


def test_an_empty_or_oversized_batch_is_refused(client, publisher):
    assert client.post(URL, json={"events": []}).status_code == 422
    assert client.post(URL, json={"events": [product_view() for _ in range(101)]}).status_code == 422
    assert publisher.sent == []


def test_a_search_query_over_200_characters_is_refused(client, publisher):
    event = {
        "event_id": str(uuid.uuid4()),
        "type": "search",
        "occurred_at": now_iso(),
        "session_id": "anon-session-1",
        "query": "x" * 201,
        "result_count": 0,
    }

    assert client.post(URL, json={"events": [event]}).status_code == 422


def test_a_product_view_needs_a_known_source(client, publisher):
    assert client.post(URL, json={"events": [product_view(source="email")]}).status_code == 422


def test_a_session_id_with_odd_characters_is_refused(client, publisher):
    assert client.post(URL, json={"events": [product_view(session_id="bad id; drop")]}).status_code == 422


def test_a_full_queue_returns_503_and_says_the_batch_can_be_resent(client, publisher):
    publisher.full = True

    response = client.post(URL, json={"events": [product_view()]})

    assert response.status_code == 503
    assert "same batch" in response.json()["detail"]


def test_health_reports_ok(client):
    assert client.get("/health").json() == {"status": "ok", "service": "clickstream"}
