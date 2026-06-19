"""API tests: happy path, validation, and auth."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


async def test_create_and_get_task(client):
    resp = await client.post("/tasks", json={"title": "send receipt", "payload": {"order": 1}})
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "send receipt"
    assert body["status"] == "pending"
    assert body["retry_count"] == 0
    assert body["payload"] == {"order": 1}

    task_id = body["id"]
    got = await client.get(f"/tasks/{task_id}")
    assert got.status_code == 200
    assert got.json()["id"] == task_id


async def test_create_defaults_scheduled_at_and_ignores_server_fields(client):
    resp = await client.post("/tasks", json={"title": "t"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["scheduled_at"] is not None
    assert body["status"] == "pending"  # client cannot set this


async def test_list_with_filter_and_pagination(client):
    for i in range(3):
        await client.post("/tasks", json={"title": f"task {i}"})
    # Move one task to a non-pending status to test filtering.
    created = (await client.get("/tasks")).json()["items"][0]
    await client.patch(f"/tasks/{created['id']}/status", json={"status": "running"})

    pending = await client.get("/tasks", params={"status": "pending"})
    assert pending.status_code == 200
    assert pending.json()["total"] == 2

    page = await client.get("/tasks", params={"limit": 1, "offset": 0})
    assert page.json()["limit"] == 1
    assert len(page.json()["items"]) == 1
    assert page.json()["total"] == 3


@pytest.mark.parametrize(
    "payload",
    [
        {"title": ""},  # empty title
        {"title": "   "},  # blank after strip
        {"title": "x", "unexpected": 1},  # extra field rejected
        {},  # missing title
        {"title": "x", "payload": "not-an-object"},  # payload must be object
    ],
)
async def test_validation_errors(client, payload):
    resp = await client.post("/tasks", json=payload)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_payload_too_large(client):
    big = {"blob": "a" * 70_000}
    resp = await client.post("/tasks", json={"title": "x", "payload": big})
    assert resp.status_code == 422


async def test_scheduled_at_is_normalised_to_utc(client):
    future = datetime.now(UTC) + timedelta(hours=2)
    resp = await client.post("/tasks", json={"title": "later", "scheduled_at": future.isoformat()})
    assert resp.status_code == 201


async def test_get_missing_task_returns_404_envelope(client):
    resp = await client.get("/tasks/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


async def test_delete_task(client):
    task_id = (await client.post("/tasks", json={"title": "x"})).json()["id"]
    assert (await client.delete(f"/tasks/{task_id}")).status_code == 204
    assert (await client.get(f"/tasks/{task_id}")).status_code == 404


async def test_invalid_uuid_path_returns_422(client):
    resp = await client.get("/tasks/not-a-uuid")
    assert resp.status_code == 422


async def test_missing_api_key_is_rejected(client):
    resp = await client.post("/tasks", json={"title": "x"}, headers={"X-API-Key": ""})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


async def test_wrong_api_key_is_rejected(client):
    resp = await client.get("/tasks", headers={"X-API-Key": "wrong-key"})
    assert resp.status_code == 401


async def test_health_is_public(client):
    resp = await client.get("/health", headers={"X-API-Key": ""})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_liveness_is_public(client):
    resp = await client.get("/health/live", headers={"X-API-Key": ""})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_idempotency_key_returns_same_task(client):
    body = {"title": "charge card", "payload": {"amount": 10}, "idempotency_key": "abc-123"}
    first = await client.post("/tasks", json=body)
    second = await client.post("/tasks", json=body)
    assert first.status_code == 201
    assert second.status_code == 201
    # Same task returned, not a duplicate.
    assert first.json()["id"] == second.json()["id"]
    listing = await client.get("/tasks")
    keyed = [t for t in listing.json()["items"] if t["idempotency_key"] == "abc-123"]
    assert len(keyed) == 1


async def test_different_idempotency_keys_create_distinct_tasks(client):
    a = await client.post("/tasks", json={"title": "t", "idempotency_key": "k1"})
    b = await client.post("/tasks", json={"title": "t", "idempotency_key": "k2"})
    assert a.json()["id"] != b.json()["id"]
