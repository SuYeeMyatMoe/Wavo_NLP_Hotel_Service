from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from hotel import operations, service, store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "workspace.sqlite"))
    return TestClient(service.app)


@pytest.mark.parametrize("actor", ["demo-guest", "demo-maintenance", "demo-staff"])
def test_workspace_matches_individual_authorized_reads(client, actor, monkeypatch):
    headers = {"x-preview-user": actor}
    profile = client.get("/me", headers=headers).json()
    with store.transaction() as db:
        operations.notify(db, "demo", actor, None, "test", "Only this recipient", actor)
        if actor == "demo-guest":
            db.run("INSERT INTO guest_languages VALUES (?,?)", (actor, "my"))
            db.run(
                "INSERT INTO calls(id,hotel,guest,ticket,status,direction,operator,created) "
                "VALUES('expired','demo',?,NULL,'Ringing','Outbound','Reception','2000-01-01')",
                (actor,),
            )
    profile = client.get("/me", headers=headers).json()
    expected = dict(
        profile=profile,
        notifications=client.get("/notifications", headers=headers).json(),
        confirmations=[],
        active_calls=[],
        handoffs=[],
        alerts=[],
    )
    if profile["role"] != "guest":
        expected["alerts"] = client.get("/alerts", headers=headers).json()

    # Fetching inside a pipeline forces an early network flush. Guard every
    # result fetch to ensure the queued batch has fully exited first.
    original_rows = store.DB.rows

    def rows(cursor):
        assert not batching[0]
        return original_rows(cursor)

    batching = [False]
    original_batch = store.DB.batch

    @contextmanager
    def batch(db):
        with original_batch(db):
            batching[0] = True
            try:
                yield
            finally:
                batching[0] = False

    monkeypatch.setattr(store.DB, "batch", batch)
    monkeypatch.setattr(store.DB, "rows", staticmethod(rows))
    result = client.get("/workspace/updates", headers=headers)
    assert result.status_code == 200
    assert result.json() == expected
    if actor == "demo-guest":
        with store.transaction() as db:
            assert (
                db.one("SELECT status FROM calls WHERE id='expired'")["status"]
                == "Missed"
            )


def test_batch_failure_rolls_back_expiry_and_next_request_recovers(client, monkeypatch):
    client.get("/me")
    with store.transaction() as db:
        db.run(
            "INSERT INTO calls(id,hotel,guest,ticket,status,direction,operator,created) "
            "VALUES('expired','demo','demo-guest',NULL,'Ringing','Outbound','Reception','2000-01-01')"
        )
    original = store.DB.run

    def fail(db, sql, args=()):
        if sql.startswith("SELECT id,guest,ticket,status"):
            raise ValueError("Simulated database read failure")
        return original(db, sql, args)

    monkeypatch.setattr(store.DB, "run", fail)
    headers = {"x-preview-user": "demo-guest"}
    assert client.get("/workspace/updates", headers=headers).status_code == 422
    with store.transaction() as db:
        assert (
            db.one("SELECT status FROM calls WHERE id='expired'")["status"] == "Ringing"
        )
    monkeypatch.setattr(store.DB, "run", original)
    assert client.get("/workspace/updates", headers=headers).status_code == 200


def test_simultaneous_workspaces_do_not_share_recipient_data(client):
    actors = ["demo-guest", "demo-maintenance", "demo-staff"]
    client.get("/me")
    with store.transaction() as db:
        for actor in actors:
            operations.notify(db, "demo", actor, None, "test", actor, actor)

    def read(actor):
        r = client.get("/workspace/updates", headers={"x-preview-user": actor})
        assert r.status_code == 200
        assert r.json()["profile"]["id"] == actor
        assert [n["message"] for n in r.json()["notifications"]] == [actor]

    with ThreadPoolExecutor(3) as workers:
        list(workers.map(read, actors * 2))


def test_invalid_token_never_acquires_database(client, monkeypatch):
    from hotel import auth_http, db_pool

    monkeypatch.setenv("HOTEL_MODE", "connected")
    monkeypatch.setattr(auth_http, "user", lambda _: SimpleNamespace(ok=False))
    monkeypatch.setattr(
        db_pool, "pool", lambda: pytest.fail("Unauthorized database access")
    )
    assert (
        client.get(
            "/workspace/updates", headers={"Authorization": "Bearer invalid"}
        ).status_code
        == 401
    )
    assert client.get("/workspace/updates").status_code == 401
