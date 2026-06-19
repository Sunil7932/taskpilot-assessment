"""Status state-machine tests via PATCH /tasks/{id}/status."""

from __future__ import annotations

import pytest


async def _create(client) -> str:
    return (await client.post("/tasks", json={"title": "x"})).json()["id"]


async def test_valid_transition_pending_to_running(client):
    task_id = await _create(client)
    resp = await client.patch(f"/tasks/{task_id}/status", json={"status": "running"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


async def test_full_success_path(client):
    task_id = await _create(client)
    await client.patch(f"/tasks/{task_id}/status", json={"status": "running"})
    resp = await client.patch(f"/tasks/{task_id}/status", json={"status": "succeeded"})
    assert resp.status_code == 200


async def test_idempotent_same_status(client):
    task_id = await _create(client)
    resp = await client.patch(f"/tasks/{task_id}/status", json={"status": "pending"})
    assert resp.status_code == 200


@pytest.mark.parametrize("target", ["succeeded", "failed"])
async def test_invalid_transition_from_pending_returns_409(client, target):
    task_id = await _create(client)
    resp = await client.patch(f"/tasks/{task_id}/status", json={"status": target})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "invalid_transition"


async def test_terminal_succeeded_cannot_transition(client):
    task_id = await _create(client)
    await client.patch(f"/tasks/{task_id}/status", json={"status": "running"})
    await client.patch(f"/tasks/{task_id}/status", json={"status": "succeeded"})
    resp = await client.patch(f"/tasks/{task_id}/status", json={"status": "pending"})
    assert resp.status_code == 409


async def test_unknown_status_value_is_422(client):
    task_id = await _create(client)
    resp = await client.patch(f"/tasks/{task_id}/status", json={"status": "bogus"})
    assert resp.status_code == 422
