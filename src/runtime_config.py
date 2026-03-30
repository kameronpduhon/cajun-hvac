import os
from dataclasses import dataclass


VALID_VOICE_MODES = {"pipeline", "gemini_realtime"}


@dataclass(frozen=True)
class RuntimeConfig:
    voice_mode: str
    compiled_playbook_path: str
    backend_url: str
    gemini_api_key: str | None
    gemini_realtime_model: str


def load_runtime_config() -> RuntimeConfig:
    voice_mode = os.environ.get("VOICE_MODE", "pipeline").strip().lower()
    if voice_mode not in VALID_VOICE_MODES:
        valid = ", ".join(sorted(VALID_VOICE_MODES))
        raise ValueError(
            f"Invalid VOICE_MODE '{voice_mode}'. Expected one of: {valid}."
        )

    gemini_api_key = (
        os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or None
    )
    gemini_realtime_model = os.environ.get(
        "GEMINI_REALTIME_MODEL", "gemini-2.5-flash"
    )

    if voice_mode == "gemini_realtime" and not gemini_api_key:
        raise ValueError(
            "VOICE_MODE is 'gemini_realtime' but neither GEMINI_API_KEY nor GOOGLE_API_KEY is set."
        )

    return RuntimeConfig(
        voice_mode=voice_mode,
        compiled_playbook_path=os.environ.get(
            "COMPILED_PLAYBOOK_PATH", "playbooks/cajun-hvac.compiled.json"
        ),
        backend_url=os.environ.get("BACKEND_URL", "http://localhost:8000"),
        gemini_api_key=gemini_api_key,
        gemini_realtime_model=gemini_realtime_model,
    )
