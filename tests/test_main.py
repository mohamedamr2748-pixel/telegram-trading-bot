from fastapi.testclient import TestClient

from main import app


def test_health_endpoint_is_available_without_database() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db_ready"] is False
