"""Settings validation — production fail-closed guard."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import INSECURE_DEFAULT_API_KEY, Settings


def test_production_rejects_default_api_key():
    with pytest.raises(ValidationError):
        Settings(ENVIRONMENT="production", API_KEY=INSECURE_DEFAULT_API_KEY)


def test_production_accepts_strong_api_key():
    settings = Settings(ENVIRONMENT="production", API_KEY="a-strong-secret-value")
    assert settings.is_production is True


def test_development_allows_default_api_key():
    settings = Settings(ENVIRONMENT="development", API_KEY=INSECURE_DEFAULT_API_KEY)
    assert settings.is_production is False


def test_cors_origins_parsed_from_csv():
    settings = Settings(CORS_ALLOW_ORIGINS="https://a.com, https://b.com")
    assert settings.cors_origins == ["https://a.com", "https://b.com"]
