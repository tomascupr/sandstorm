from fastapi.testclient import TestClient

from sandstorm.main import app

client = TestClient(app)


def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200


def test_health_returns_status_ok():
    response = client.get("/health")
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_health_deep_check():
    response = client.get("/health?deep=true")
    data = response.json()
    assert data["status"] in ("ok", "degraded")
    assert "version" in data
    assert "checks" in data
    assert "anthropic_api_key" in data["checks"]
    assert "e2b_api_key" in data["checks"]
    assert "e2b_api" in data["checks"]
