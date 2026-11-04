from __future__ import annotations

from src.config import Settings


def test_auth_allowed_email_domains_accepts_plain_csv() -> None:
    settings = Settings(auth_allowed_email_domains="example.com, example.org")
    assert settings.auth_allowed_email_domains == ["example.com", "example.org"]


def test_auth_allowed_email_domains_accepts_json_array_string() -> None:
    settings = Settings(auth_allowed_email_domains='["example.com", "example.org"]')
    assert settings.auth_allowed_email_domains == ["example.com", "example.org"]


def test_auth_bypass_paths_accepts_json_array_string() -> None:
    settings = Settings(auth_bypass_paths='["/healthz", "/openapi.json"]')
    assert settings.auth_bypass_paths == ["/healthz", "/openapi.json"]


def test_auth_bypass_paths_falls_back_to_csv_when_not_valid_json() -> None:
    # Looks bracket-wrapped but isn't valid JSON — must not silently drop data,
    # falls back to comma-splitting the raw string.
    settings = Settings(auth_bypass_paths="[/healthz,/openapi.json]")
    assert settings.auth_bypass_paths == ["[/healthz", "/openapi.json]"]


def test_auth_allowed_email_domains_accepts_native_list() -> None:
    settings = Settings(auth_allowed_email_domains=["example.com"])
    assert settings.auth_allowed_email_domains == ["example.com"]
