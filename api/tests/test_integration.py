import os
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

_TEST_USER = os.getenv("TEST_USER", "analyst")
_TEST_PASS = os.getenv("TEST_PASS", "Hunt3r$2026!")


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metrics():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "process_cpu_seconds_total" in response.text


def test_auth_login_success():
    payload = {"username": _TEST_USER, "password": _TEST_PASS}
    response = client.post("/auth/token", data=payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_auth_login_failure():
    payload = {"username": "admin", "password": "wrongpassword"}
    response = client.post("/auth/token", data=payload)
    assert response.status_code == 401


def test_protected_route_without_token():
    response = client.get("/events/search?srcip=1.1.1.1")
    assert response.status_code in [401, 403]


def test_protected_route_with_token():
    # 1. Login
    payload = {"username": _TEST_USER, "password": _TEST_PASS}
    login_res = client.post("/auth/token", data=payload)
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    # 2. Access protected route
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/events/search?srcip=59.166.0.1", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "count" in data
