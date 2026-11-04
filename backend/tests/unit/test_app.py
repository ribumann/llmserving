from src.api.app import create_app


def test_app_bootstraps_with_health_route() -> None:
    app = create_app()
    routes = set(app.openapi()["paths"])
    assert "/healthz" in routes
    assert "/profiles" in routes
    assert "/catalog" in routes
    assert "/environments/preview" in routes
