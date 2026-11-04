from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

_SENSITIVE_KEYS = {"huggingFaceToken", "hugging_face_token", "hfToken", "hf_token"}

# Interactive prompt/response bodies must never be persisted beyond the user session
# or environment teardown (FR-060/FR-084, data-model.md Cross-Cutting Rules). The
# internal orchestration callback API (contracts/api.md) rejects any progress/
# completion payload shaped like one with 400.
_INTERACTIVE_PROMPT_KEYS = {
    "prompt",
    "promptText",
    "prompt_text",
    "response",
    "responseText",
    "response_text",
    "interactivePrompt",
    "interactive_prompt",
    "interactiveResponse",
    "interactive_response",
}


@dataclass(slots=True, frozen=True)
class HfAccessToken:
    value: str

    def __repr__(self) -> str:
        return "HfAccessToken(**redacted**)"

    __str__ = __repr__


def accept_hf_token(value: str | None) -> HfAccessToken | None:
    if value is None:
        return None
    token = value.strip()
    if not token:
        return None
    return HfAccessToken(token)


def assert_hf_token_not_persisted(payload: Mapping[str, Any] | None) -> None:
    if payload is None:
        return
    for key, value in payload.items():
        if key in _SENSITIVE_KEYS and value:
            raise ValueError("Hugging Face credentials must not be persisted or returned.")
        if isinstance(value, Mapping):
            assert_hf_token_not_persisted(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, Mapping):
                    assert_hf_token_not_persisted(item)


def assert_no_interactive_prompt_payload(payload: Mapping[str, Any] | None) -> None:
    """Reject a payload carrying an interactive prompt/response body (FR-060/FR-084)."""
    if payload is None:
        return
    for key, value in payload.items():
        if key in _INTERACTIVE_PROMPT_KEYS and value:
            raise ValueError("Interactive prompt/response bodies must not be persisted.")
        if isinstance(value, Mapping):
            assert_no_interactive_prompt_payload(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, Mapping):
                    assert_no_interactive_prompt_payload(item)


@contextmanager
def forwarded_hf_token(token: HfAccessToken | None) -> Iterator[str | None]:
    yield None if token is None else token.value
