from fastapi.testclient import TestClient

from sandstorm.main import app

client = TestClient(app)


def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200


def test_health_returns_status_ok():
    response = client.get("/health")
    assert response.json() == {"status": "ok"}
