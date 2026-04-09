import pytest
import httpx
import os

# Configuration (defaults to localhost for external testing)
API_URL = os.getenv("API_URL", "http://localhost:8000")

@pytest.fixture
def client():
    # Increase timeout for slow database queries
    with httpx.Client(base_url=API_URL, timeout=30.0) as client:
        yield client

def test_health(client):
    # Route is at root level based on main.py include_router(system.router) without prefix
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_metrics(client):
    # Route is at root level /metrics
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "process_cpu_seconds_total" in response.text

def test_auth_login_success(client):
    # Test getting a token
    payload = {
        "username": "analyst",
        "password": "analyst"
    }
    response = client.post("/auth/token", data=payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    # Return token for potential use, though fixtures are better for sharing state
    # Pytest warns if test returns value, so we assert and don't return, 
    # or rely on test_protected_route_with_token to do its own login.
    pass 

def test_auth_login_failure(client):
    payload = {
        "username": "admin",
        "password": "wrongpassword"
    }
    response = client.post("/auth/token", data=payload)
    assert response.status_code == 401

def test_protected_route_without_token(client):
    response = client.get("/events/search?srcip=1.1.1.1")
    # Should be 401 Unauthorized or 403 Forbidden
    assert response.status_code in [401, 403]

def test_protected_route_with_token(client):
    # 1. Login
    payload = {"username": "analyst", "password": "analyst"}
    login_res = client.post("/auth/token", data=payload)
    token = login_res.json()["access_token"]
    
    # 2. Access Protected Route
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/events/search?srcip=59.166.0.1", headers=headers)
    
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "count" in data
