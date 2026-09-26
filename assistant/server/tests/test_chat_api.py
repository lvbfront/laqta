"""The HTTP layer, over a scripted model. No API calls anywhere here.

Every test drives the real `run_turn` through the real endpoints. What is
faked is the model and nothing else: the tools run, the database is written,
and the confirmation rule is enforced by the same code the CLI uses.
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agent.loop import API_ERROR_MESSAGE
from app.models import Booking, Confirmation, Interaction
from server.app import create_app
from server.config import ServerSettings, WrongDatabase
from tests.conftest import TEST_DATABASE_URL
from tests.factories import make_when
from tests.fakes import FakeClient, calls_tool, says, transient_api_error

FAR_DAY = date(2026, 10, 15)
WHEN_ID = "w0000001"
DETAILS = {
    # Not the seed's «ملتقى الريّان»: that booking exists already, and a
    # shared name would make every count here ambiguous.
    "event_name": "لقاء تجريبي للويب",
    "city": "jeddah",
    "venue": "فندق هيلتون جدة",
    "expected_guests": 400,
    "photographers": 2,
    "match_mode": "face",
    "strict_mode": False,
    "package": "premium",
    "addons": [],
    "onsite_support": False,
}
# The server refuses assistant_test, which is the database the suite has. So
# the tests build the app against that URL through the one door that skips the
# guard — and one test checks the guard itself, with the real entry point.
LIVE_URL = TEST_DATABASE_URL.replace("assistant_test", "assistant_under_test")


@pytest.fixture(autouse=True)
def stub_embeddings(monkeypatch):
    from app.config import EMBEDDING_DIM

    monkeypatch.setattr(
        "app.kb.search.embed_query", lambda text: [1.0] + [0.0] * (EMBEDDING_DIM - 1)
    )


@pytest.fixture(autouse=True)
def allow_the_test_database(monkeypatch):
    """The suite's database is `assistant_test`, which the server exists to
    refuse. Narrow the denylist for the tests that are not about the guard;
    `test_the_server_refuses_a_database_that_gets_wiped` restores it.
    """
    monkeypatch.setattr("server.config.REFUSED_DATABASES", frozenset({"never_used_name"}))


def build(model_client=None, *, dev=True, **overrides):
    config = ServerSettings(dev=dev, **overrides)
    return create_app(
        server_settings=config, database_url=TEST_DATABASE_URL, model_client=model_client
    )


@pytest.fixture()
def client(seeded):
    """`seeded` gives the app a database with the seed contacts committed in
    it, and takes them away again afterwards."""
    app = build(lambda: FakeClient(says("أهلاً")))
    with TestClient(app) as test_client:
        yield test_client


def new_session(client, **body):
    response = client.post("/chat/sessions", json=body)
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def send(client, session_id, text, client_message_id="m1"):
    return client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"client_message_id": client_message_id, "text": text},
    )


# --- Idempotency


def test_a_replayed_client_message_id_does_not_run_the_loop_again(seeded):
    """The rule the whole store exists for. Re-entering the loop would
    advance user_turn with no new customer message behind it, and that is
    exactly what confirm_action reads as the customer having replied."""
    fake = FakeClient(says("أهلاً"), says("مرة ثانية"))
    app = build(fake)
    with TestClient(app) as client:
        session_id = new_session(client)
        first = send(client, session_id, "السلام عليكم", "msg-1")
        second = send(client, session_id, "السلام عليكم", "msg-1")

        assert first.status_code == second.status_code == 200
        assert first.json()["reply"] == second.json()["reply"] == "أهلاً"
        assert first.json()["replayed"] is False
        assert second.json()["replayed"] is True

        # One API call, one customer turn, one pair of messages on record.
        assert len(fake.calls) == 1
        assert first.json()["turn"] == second.json()["turn"] == 1
        chat = app.state.store.get(session_id)
        assert chat.agent.user_turn == 1
        assert len(chat.history()) == 2


def test_an_apology_is_a_stored_result_like_any_other(seeded):
    """A transient API failure is something the customer was shown, not a gap
    to be filled in on retry. Replaying the id returns the apology; a real
    retry is a new id, which is a real new turn."""
    app = build(FakeClient(raises=transient_api_error()))
    with TestClient(app) as client:
        session_id = new_session(client)
        first = send(client, session_id, "مرحبا", "msg-1").json()
        assert first["reply"] == API_ERROR_MESSAGE
        assert first["reply_source"] == "loop_api_error"

        replay = send(client, session_id, "مرحبا", "msg-1").json()
        assert replay["reply"] == API_ERROR_MESSAGE
        assert replay["replayed"] is True
        assert replay["turn"] == first["turn"]


def test_two_concurrent_requests_with_one_id_run_the_loop_once(seeded):
    """The duplicate arrives while the first is still in the loop. It has to
    wait for it and get the same answer, not start a second turn."""
    started = threading.Event()
    release = threading.Event()
    fake = FakeClient(says("أهلاً"), says("ثانية"))
    scripted = fake.messages.create

    def slow_create(**kwargs):
        started.set()
        release.wait(timeout=5)
        return scripted(**kwargs)

    fake.messages.create = slow_create  # type: ignore[method-assign]

    app = build(fake)
    with TestClient(app) as client:
        session_id = new_session(client)
        results: list[dict] = []

        def fire():
            results.append(send(client, session_id, "مرحبا", "same-id").json())

        threads = [threading.Thread(target=fire) for _ in range(2)]
        threads[0].start()
        assert started.wait(timeout=5), "the first turn never reached the model"
        threads[1].start()
        release.set()
        for thread in threads:
            thread.join(timeout=10)

        assert len(fake.calls) == 1, "the loop ran twice"
        assert {result["reply"] for result in results} == {"أهلاً"}
        assert sorted(result["replayed"] for result in results) == [False, True]
        assert app.state.store.get(session_id).agent.user_turn == 1


def test_two_different_messages_on_one_session_are_serialised(seeded):
    """Not the same as idempotency: two genuinely different sends. They run
    one after the other, so the turn numbers are 1 and 2 and neither turn
    sees a half-built message list."""
    order: list[str] = []
    fake = FakeClient(says("أول"), says("ثاني"))
    scripted = fake.messages.create
    lock_held = threading.Lock()

    def create(**kwargs):
        acquired = lock_held.acquire(blocking=False)
        assert acquired, "two turns were inside the loop at once"
        try:
            order.append("in")
            return scripted(**kwargs)
        finally:
            order.append("out")
            lock_held.release()

    fake.messages.create = create  # type: ignore[method-assign]

    app = build(fake)
    with TestClient(app) as client:
        session_id = new_session(client)
        replies: list[dict] = []
        threads = [
            threading.Thread(
                target=lambda i=i: replies.append(send(client, session_id, f"س{i}", f"m{i}").json())
            )
            for i in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

    assert order == ["in", "out", "in", "out"]
    assert sorted(reply["turn"] for reply in replies) == [1, 2]


# --- The confirmation rule, over HTTP


def prepare_and_confirm_in_one_turn():
    return FakeClient(
        calls_tool("prepare_booking", {"when_id": WHEN_ID, "details": DETAILS}),
        calls_tool("confirm_action", {"confirmation_id": "REPLACED"}),
        says("تم الحجز."),
    )


def test_a_model_that_confirms_in_the_same_turn_is_refused(seeded):
    """The customer has not spoken since the summary was produced — they have
    not even been shown it yet."""
    fake = prepare_and_confirm_in_one_turn()
    app = build(fake)
    with TestClient(app) as client:
        session_id = new_session(client, identity="customer:1")
        chat = app.state.store.get(session_id)
        chat.agent.resolved[WHEN_ID] = make_when(chat.agent.policy, FAR_DAY)

        # The confirm_action id has to be the one prepare_booking hands out,
        # which does not exist until the first tool call has run. Patch it in
        # between the two responses, as a model reading the result would.
        _confirm_with_the_real_token(chat, fake)

        body = send(client, session_id, "احجز لي", "m1").json()

        assert body["reply"] == "تم الحجز."
        refusals = [
            call["result"]
            for call in body["events"]["tool_calls"]
            if call["name"] == "confirm_action"
        ]
        assert refusals and refusals[0]["error"] == "awaiting_customer_reply"
        assert _booked(chat) == [], "a booking was created without the customer replying"


def test_a_confirm_on_the_next_customer_turn_is_accepted(seeded):
    """The same tools, one message later. This has to work, or the fix has
    broken booking over HTTP."""
    app = build(lambda: FakeClient(calls_tool("prepare_booking", {"when_id": WHEN_ID, "details": DETAILS}), says("الملخص… أأكد؟")))
    with TestClient(app) as client:
        session_id = new_session(client, identity="customer:1")
        chat = app.state.store.get(session_id)
        chat.agent.resolved[WHEN_ID] = make_when(chat.agent.policy, FAR_DAY)

        send(client, session_id, "احجز لي", "m1")
        token = chat.db.scalars(select(Confirmation)).all()[-1]

        chat.client.messages._inner = FakeClient(
            calls_tool("confirm_action", {"confirmation_id": str(token.id)}),
            says("تم."),
        ).messages
        body = send(client, session_id, "نعم أكد", "m2").json()

        results = [
            call["result"]
            for call in body["events"]["tool_calls"]
            if call["name"] == "confirm_action"
        ]
        assert results and results[0]["ok"] is True, results
        assert len(_booked(chat)) == 1


def _booked(chat):
    """Only this test's booking. The seed puts one in Jeddah already, and
    counting every row would make the assertion about the fixture."""
    return chat.db.scalars(
        select(Booking).where(Booking.event_name == DETAILS["event_name"])
    ).all()


def _confirm_with_the_real_token(chat, fake):
    scripted = fake.messages.create

    def create(**kwargs):
        response = scripted(**kwargs)
        for block in response.content:
            if getattr(block, "name", None) == "confirm_action":
                token = chat.db.scalars(select(Confirmation)).all()[-1]
                block.input = {"confirmation_id": str(token.id)}
        return response

    fake.messages.create = create  # type: ignore[method-assign]


# --- Identity


def test_with_dev_off_a_client_cannot_become_staff_or_a_customer(seeded):
    app = build(lambda: FakeClient(says("أهلاً")), dev=False)
    with TestClient(app) as client:
        for spec in ("customer:1", "staff:1", "anon"):
            body = client.post("/chat/sessions", json={"identity": spec}).json()
            assert body["identity"] == "anonymous"
            assert body["identity_spec"] == "anon"
            assert body["dev"] is False
            # And the session really is anonymous, not merely labelled so:
            chat = app.state.store.get(body["session_id"])
            assert chat.agent.identity.contact_id is None
            assert chat.agent.identity.staff_id is None
            assert "prepare_booking" not in {
                schema["name"]
                for schema in __import__(
                    "app.tools", fromlist=["registry"]
                ).registry.schemas_for(chat.agent.identity)
            }


def test_with_dev_off_the_clock_cannot_be_moved(seeded):
    app = build(lambda: FakeClient(says("أهلاً")), dev=False)
    with TestClient(app) as client:
        body = client.post("/chat/sessions", json={"now": "2020-01-01T00:00"}).json()
        assert body["clock_overridden"] is False
        assert datetime.fromisoformat(body["now"]).year >= 2026


def test_with_dev_on_the_clock_starts_where_asked_and_then_moves(seeded, client):
    body = client.post("/chat/sessions", json={"now": "2026-09-11T14:05"}).json()
    assert body["clock_overridden"] is True

    chat = client.app.state.store.get(body["session_id"])
    first = chat.clock.now()
    second = chat.clock.now()
    assert first.astimezone(timezone.utc).date() == date(2026, 9, 11)
    assert second > first, "a frozen clock would never expire a confirmation token"


def test_dev_events_are_withheld_when_dev_is_off(seeded):
    app = build(lambda: FakeClient(says("أهلاً")), dev=False)
    with TestClient(app) as client:
        session_id = new_session(client)
        body = send(client, session_id, "مرحبا", "m1").json()
        assert body["events"] == {}
        assert client.get(f"/chat/sessions/{session_id}").json()["context_block"] is None


# --- The database guard


def test_the_server_refuses_a_database_that_gets_wiped(monkeypatch):
    """The real denylist, not the narrowed one the other tests run under."""
    monkeypatch.undo()
    from server.config import REFUSED_DATABASES

    assert REFUSED_DATABASES == {"assistant_test", "assistant_eval"}
    for name in sorted(REFUSED_DATABASES):
        url = LIVE_URL.replace("assistant_under_test", name)
        with pytest.raises(WrongDatabase, match=name):
            create_app(server_settings=ServerSettings(dev=True), database_url=url)


# --- History and ending


def test_a_reload_gets_the_conversation_back(seeded):
    app = build(lambda: FakeClient(says("أول"), says("ثاني")))
    with TestClient(app) as client:
        session_id = new_session(client)
        send(client, session_id, "وحدة", "m1")
        send(client, session_id, "ثنتين", "m2")

        body = client.get(f"/chat/sessions/{session_id}").json()
        assert [(m["role"], m["text"]) for m in body["messages"]] == [
            ("user", "وحدة"),
            ("assistant", "أول"),
            ("user", "ثنتين"),
            ("assistant", "ثاني"),
        ]
        assert body["turn"] == 2


def test_an_unknown_session_is_a_clean_refusal(client):
    response = client.get("/chat/sessions/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"
    assert response.json()["error"]["retryable"] is False


def test_ending_an_empty_session_writes_no_summary(seeded, sessions):
    """Nothing was said, so there is nothing to summarise and no Haiku call
    to pay for."""
    app = build(lambda: FakeClient(says("أهلاً")))
    with TestClient(app) as client:
        session_id = new_session(client)
        chat = app.state.store.get(session_id)
        interaction_id = chat.agent.interaction.id

        body = client.post(f"/chat/sessions/{session_id}/end", json={}).json()
        assert body["ended"] is True
        assert body["summary"] is None

        assert client.get(f"/chat/sessions/{session_id}").status_code == 404
    with sessions() as db:
        stored = db.get(Interaction, interaction_id)
        assert stored.ended_at is not None
        assert stored.summary is None


def test_a_broken_session_refuses_everything_after(seeded):
    """run_turn raised, so the session's state is not something to keep
    talking to. The widget is told not to retry."""
    app = build(FakeClient(raises=ValueError("a bug in our own code")))
    with TestClient(app) as client:
        session_id = new_session(client)
        first = send(client, session_id, "مرحبا", "m1")
        assert first.status_code == 409
        assert first.json()["error"]["code"] == "session_broken"
        assert first.json()["error"]["retryable"] is False

        again = send(client, session_id, "ثاني", "m2")
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "session_broken"


# --- Input limits


def test_a_message_over_the_limit_is_refused_before_the_model(seeded):
    fake = FakeClient(says("أهلاً"))
    app = build(fake, max_message_chars=50)
    with TestClient(app) as client:
        session_id = new_session(client)
        response = send(client, session_id, "ا" * 51, "m1")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "message_too_long"
        assert "50" in response.json()["error"]["message_ar"]
        assert fake.calls == [], "the model was called for a message we had already refused"


def test_an_empty_message_is_refused(client):
    session_id = new_session(client)
    response = send(client, session_id, "   ", "m1")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "empty_message"
