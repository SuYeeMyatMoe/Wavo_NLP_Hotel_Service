from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from hotel.service import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("CONCIERGE_MODE", "local")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "rooms.sqlite"))
    return TestClient(app)


@pytest.mark.parametrize("room", ["402", "512"])
def test_separate_guest_reservations_and_assignment(client, room):
    guest = {"x-preview-user": "demo-guest-" + room}
    assert client.get("/me", headers=guest).json()["room"] == room
    created = client.post(
        "/tickets",
        headers=guest,
        json={
            "text": "The air conditioner is broken. Please send maintenance.",
            "room": "305",
            "key": str(uuid4()),
        },
    )
    created.raise_for_status()
    ref = created.json()["id"]
    item = client.get(f"/tickets/{ref}", headers=guest).json()
    assert item["room"] == room
    staff_item = client.get(f"/tickets/{ref}").json()
    assert staff_item["work"]["extraction"]["verified_room"] == room
    assert item["assignment"]["staff"] == "demo-maintenance"
    assert (
        client.get(
            f"/tickets/{ref}", headers={"x-preview-user": "demo-guest"}
        ).status_code
        == 403
    )
    report = client.post(
        "/work-assistant/turns",
        headers={"x-preview-user": "demo-maintenance"},
        json={
            "turn_id": str(uuid4()),
            "text": f"I started the AC repair in Room {room}.",
        },
    )
    report.raise_for_status()
    assert report.json()["changed"]


def test_manager_room_change_updates_new_calls_not_historical_work(client):
    guest = {"x-preview-user": "demo-guest-402"}
    old = client.post(
        "/tickets",
        headers=guest,
        json={
            "text": "The AC is broken. Please send maintenance.",
            "key": str(uuid4()),
        },
    ).json()["id"]
    reservation = {
        "guest": "demo-guest-402",
        "room": "718A",
        "starts": "2020-01-01",
        "ends": "2099-01-01",
        "version": 1,
    }
    assert (
        client.put(
            "/operations/reservations", headers=guest, json=reservation
        ).status_code
        == 403
    )
    client.put("/operations/reservations", json=reservation).raise_for_status()
    assert client.put("/operations/reservations", json=reservation).status_code == 422
    assert client.get("/me", headers=guest).json()["room"] == "718A"
    assert client.get(f"/tickets/{old}", headers=guest).json()["room"] == "402"
    call = client.post("/calls", headers=guest)
    call.raise_for_status()
    key = call.json()["id"]
    response = client.post(
        f"/calls/{key}/turn",
        headers=guest,
        json={
            "text": "The air conditioner is broken. Please send maintenance.",
            "turn_id": str(uuid4()),
        },
    )
    response.raise_for_status()
    agreed = client.post(
        f"/calls/{key}/turn",
        headers=guest,
        json={
            "text": "Yes, send maintenance.",
            "turn_id": str(uuid4()),
        },
    )
    agreed.raise_for_status()
    ref = agreed.json()["ticket"]
    assert ref and client.get(f"/tickets/{ref}", headers=guest).json()["room"] == "718A"
    assert "718A" in agreed.json()["reply"]
    client.post(f"/calls/{key}/end", headers=guest).raise_for_status()


def test_room_change_during_call_does_not_silently_redirect_service(client):
    guest = {"x-preview-user": "demo-guest-512"}
    key = client.post("/calls", headers=guest).json()["id"]
    client.post(
        f"/calls/{key}/turn",
        headers=guest,
        json={
            "text": "The AC is broken.",
            "turn_id": str(uuid4()),
        },
    ).raise_for_status()
    client.put(
        "/operations/reservations",
        json={
            "guest": "demo-guest-512",
            "room": "620",
            "starts": "2020-01-01",
            "ends": "2099-01-01",
            "version": 1,
        },
    ).raise_for_status()
    response = client.post(
        f"/calls/{key}/turn",
        headers=guest,
        json={
            "text": "Yes, send maintenance.",
            "turn_id": str(uuid4()),
        },
    )
    assert response.status_code == 422 and "room changed" in response.json()["detail"]
    assert client.get("/tickets", headers=guest).json() == []
