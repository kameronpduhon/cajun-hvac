import os

import pytest

from src.runtime_config import load_runtime_config


@pytest.fixture(autouse=True)
def clear_runtime_env(monkeypatch):
    for key in [
        "VOICE_MODE",
        "COMPILED_PLAYBOOK_PATH",
        "BACKEND_URL",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_REALTIME_MODEL",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_load_runtime_config_defaults_to_pipeline():
    config = load_runtime_config()

    assert config.voice_mode == "pipeline"
    assert config.compiled_playbook_path == "playbooks/cajun-hvac.compiled.json"
    assert config.backend_url == "http://localhost:8000"
    assert config.gemini_api_key is None
    assert config.gemini_realtime_model == "gemini-2.5-flash"


def test_load_runtime_config_accepts_pipeline_case_insensitive(monkeypatch):
    monkeypatch.setenv("VOICE_MODE", "PIPELINE")

    config = load_runtime_config()

    assert config.voice_mode == "pipeline"


def test_load_runtime_config_rejects_unknown_mode(monkeypatch):
    monkeypatch.setenv("VOICE_MODE", "something_else")

    with pytest.raises(ValueError, match="Invalid VOICE_MODE"):
        load_runtime_config()


def test_gemini_realtime_requires_api_key(monkeypatch):
    monkeypatch.setenv("VOICE_MODE", "gemini_realtime")

    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        load_runtime_config()


def test_gemini_realtime_accepts_gemini_api_key(monkeypatch):
    monkeypatch.setenv("VOICE_MODE", "gemini_realtime")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    config = load_runtime_config()

    assert config.voice_mode == "gemini_realtime"
    assert config.gemini_api_key == "test-key"


def test_gemini_realtime_accepts_google_api_key_fallback(monkeypatch):
    monkeypatch.setenv("VOICE_MODE", "gemini_realtime")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")

    config = load_runtime_config()

    assert config.voice_mode == "gemini_realtime"
    assert config.gemini_api_key == "google-key"


def test_load_runtime_config_respects_overrides(monkeypatch):
    monkeypatch.setenv("COMPILED_PLAYBOOK_PATH", "/tmp/custom-playbook.json")
    monkeypatch.setenv("BACKEND_URL", "https://example.com")
    monkeypatch.setenv("GEMINI_REALTIME_MODEL", "gemini-live-2.5")

    config = load_runtime_config()

    assert config.compiled_playbook_path == "/tmp/custom-playbook.json"
    assert config.backend_url == "https://example.com"
    assert config.gemini_realtime_model == "gemini-live-2.5"
