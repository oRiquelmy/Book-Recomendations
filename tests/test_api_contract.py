from fastapi.testclient import TestClient

from main import app


def test_health_and_version_contract() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["version"] == "0.3.0"


def test_author_routes_are_exposed_in_openapi() -> None:
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
    assert "/authors/search" in schema["paths"]
    assert "/authors/{author_id}/works" in schema["paths"]


def test_author_only_recommendation_returns_actionable_422() -> None:
    with TestClient(app) as client:
        response = client.get("/recommend", params={"author": "Clarice Lispector"})
    assert response.status_code == 422
    assert "busca por autor" in response.json()["detail"].casefold()


def test_invalid_numeric_ranges_are_rejected_before_provider_calls() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/recommend",
            params={"q": "Dune", "min_pages": 500, "max_pages": 100},
        )
    assert response.status_code == 422
    assert response.json()["detail"] == "min_pages não pode ser maior que max_pages"
