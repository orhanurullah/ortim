# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Ollama provider wiring tests (Roadmap 2.2, infra-only).

Covers registry presence, pricing, no-auth contract, OLLAMA_BASE_URL
override, and end-to-end call dispatch through the OpenAI-shape path
with httpx mocked. No live HTTP — proof-point against a real Ollama
instance is deferred to a separate session once the operator has
Ollama installed locally.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.llm.client import LLMClient  # noqa: E402
from ortim.llm.providers import (  # noqa: E402
    PROVIDERS,
    pricing_for,
    resolve_provider,
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_ollama_in_registry() -> None:
    assert "ollama" in PROVIDERS


def test_ollama_provider_uses_openai_api_kind() -> None:
    cfg = PROVIDERS["ollama"]
    assert cfg.api_kind == "openai"
    assert cfg.base_url == "http://localhost:11434/v1"
    assert cfg.default_model.startswith("qwen") or cfg.default_model.startswith("deepseek")


def test_ollama_pricing_is_zero() -> None:
    in_p, out_p = pricing_for("ollama", "qwen2.5-coder:7b")
    assert in_p == 0.0
    assert out_p == 0.0


def test_ollama_api_key_env_is_none() -> None:
    """Local providers carry api_key_env=None so the client knows to
    skip the auth check."""
    assert PROVIDERS["ollama"].api_key_env is None


def test_resolve_provider_accepts_ollama_via_env() -> None:
    prev = os.environ.get("LLM_PROVIDER")
    os.environ["LLM_PROVIDER"] = "ollama"
    try:
        cfg = resolve_provider()
        assert cfg.name == "ollama"
    finally:
        if prev is None:
            os.environ.pop("LLM_PROVIDER", None)
        else:
            os.environ["LLM_PROVIDER"] = prev


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------


def test_client_ollama_constructs_without_api_key() -> None:
    """Ollama doesn't need any env-set credential. The pre-2.2 contract
    raised on missing API key for every provider; the new path must
    short-circuit when api_key_env is None."""
    # Defensive — guard against any test leaking an OLLAMA_API_KEY into env.
    prev = os.environ.pop("OLLAMA_API_KEY", None)
    try:
        client = LLMClient(provider="ollama")
        assert client.api_key is None
        assert client.provider == "ollama"
        assert client.model.startswith("qwen") or client.model.startswith("deepseek")
    finally:
        if prev is not None:
            os.environ["OLLAMA_API_KEY"] = prev


def test_client_ollama_honors_OLLAMA_BASE_URL_env_override() -> None:
    """Operator with Ollama on a remote host overrides the URL via
    OLLAMA_BASE_URL. Verifies the env override path."""
    prev = os.environ.get("OLLAMA_BASE_URL")
    os.environ["OLLAMA_BASE_URL"] = "http://gpu-box.local:11434/v1"
    try:
        client = LLMClient(provider="ollama")
        assert client.base_url == "http://gpu-box.local:11434/v1"
    finally:
        if prev is None:
            os.environ.pop("OLLAMA_BASE_URL", None)
        else:
            os.environ["OLLAMA_BASE_URL"] = prev


def test_client_ollama_anthropic_sdk_client_is_not_initialized() -> None:
    """Openai-kind providers should NOT spin up an anthropic.Anthropic
    instance — it's wasted construction + holds a session pool."""
    client = LLMClient(provider="ollama")
    assert client.client is None


def test_client_anthropic_kind_still_initializes_sdk() -> None:
    """Regression: existing anthropic + deepseek providers still build
    the anthropic SDK client at construction time."""
    prev_key = os.environ.get("DEEPSEEK_API_KEY")
    os.environ["DEEPSEEK_API_KEY"] = "sk-test-fake-key-not-real"
    try:
        client = LLMClient(provider="deepseek")
        assert client.client is not None
        assert client.api_key == "sk-test-fake-key-not-real"
    finally:
        if prev_key is None:
            os.environ.pop("DEEPSEEK_API_KEY", None)
        else:
            os.environ["DEEPSEEK_API_KEY"] = prev_key


# ---------------------------------------------------------------------------
# Call dispatch — OpenAI-shape path
# ---------------------------------------------------------------------------


def _fake_openai_response(content: str, prompt_tokens: int = 42, completion_tokens: int = 17) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
    }
    resp.raise_for_status = MagicMock(return_value=None)
    return resp


def test_ollama_call_posts_to_chat_completions_endpoint() -> None:
    """The OpenAI-kind path posts to `<base_url>/chat/completions`
    with the correct system + user message shape."""
    client = LLMClient(provider="ollama")
    with patch("ortim.llm.client.httpx.post") as mock_post:
        mock_post.return_value = _fake_openai_response("hello back")
        result = client.call(system="be terse", user="hi", max_tokens=128)

    assert mock_post.call_count == 1
    args, kwargs = mock_post.call_args
    assert args[0] == "http://localhost:11434/v1/chat/completions"
    payload = kwargs["json"]
    assert payload["model"] == client.model
    assert payload["messages"] == [
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "hi"},
    ]
    assert payload["max_tokens"] == 128
    assert payload["temperature"] == 0.0
    # No auth header on a local-key-less provider.
    assert "Authorization" not in kwargs["headers"]

    assert result.text == "hello back"
    assert result.provider == "ollama"
    assert result.input_tokens == 42
    assert result.output_tokens == 17


def test_ollama_call_handles_missing_usage_block_gracefully() -> None:
    """Some Ollama builds omit `usage` on non-streaming responses.
    Token counts default to 0 instead of crashing the call."""
    client = LLMClient(provider="ollama")
    resp = MagicMock()
    resp.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        # no `usage` key
    }
    resp.raise_for_status = MagicMock(return_value=None)
    with patch("ortim.llm.client.httpx.post", return_value=resp):
        result = client.call(system="s", user="u")
    assert result.text == "ok"
    assert result.input_tokens == 0
    assert result.output_tokens == 0


def test_ollama_call_raises_helpful_error_on_unexpected_response_shape() -> None:
    """When the local server returns a non-OpenAI-shaped payload (often
    means: wrong URL, wrong server, model not loaded), the client must
    surface a debuggable error — not an opaque KeyError."""
    client = LLMClient(provider="ollama")
    resp = MagicMock()
    resp.json.return_value = {"error": "model 'qwen' not found"}
    resp.raise_for_status = MagicMock(return_value=None)
    with patch("ortim.llm.client.httpx.post", return_value=resp):
        try:
            client.call(system="s", user="u")
        except RuntimeError as exc:
            assert "ollama" in str(exc).lower()
            assert "unexpected response shape" in str(exc).lower()
            return
    raise AssertionError("Expected RuntimeError on malformed response")


def test_ollama_call_passes_api_key_when_present_via_openai_base_url() -> None:
    """Different OpenAI-compatible local server requiring auth: when an
    api_key is provided explicitly, the Authorization header is set."""
    client = LLMClient(
        provider="ollama",
        api_key="sk-local-test",
    )
    with patch("ortim.llm.client.httpx.post") as mock_post:
        mock_post.return_value = _fake_openai_response("ok")
        client.call(system="s", user="u")
    headers = mock_post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer sk-local-test"
