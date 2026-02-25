"""LLM provider abstraction — stdlib only (urllib.request + json)."""
from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

TIMEOUT = 120  # seconds — LLM responses can be slow


class LLMError(Exception):
    """Raised on HTTP, connection, or API errors from an LLM provider."""


class LLMProvider(ABC):
    @abstractmethod
    def chat(self, messages: list[dict], system: str = "") -> str:
        """Send a chat completion request and return the assistant's reply text."""


class OpenAICompatProvider(LLMProvider):
    """POST /v1/chat/completions — works with OpenAI, Ollama, Groq, Together, etc."""

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model

    def chat(self, messages: list[dict], system: str = "") -> str:
        url = f"{self._base_url}/chat/completions"
        all_messages = list(messages)
        if system:
            all_messages.insert(0, {"role": "system", "content": system})

        payload = {
            "model": self._model,
            "messages": all_messages,
            "stream": False,
        }

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise LLMError(f"HTTP {exc.code} from {url}: {err_body}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"Connection error to {url}: {exc.reason}") from exc
        except Exception as exc:
            raise LLMError(f"Request failed: {exc}") from exc

        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"Unexpected response format: {body}") from exc


class AnthropicProvider(LLMProvider):
    """POST /v1/messages — Anthropic API."""

    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    def chat(self, messages: list[dict], system: str = "") -> str:
        payload: dict = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": messages,
        }
        if system:
            payload["system"] = system

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.API_URL, data=data, headers=headers, method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise LLMError(f"HTTP {exc.code} from Anthropic: {err_body}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"Connection error to Anthropic: {exc.reason}") from exc
        except Exception as exc:
            raise LLMError(f"Request failed: {exc}") from exc

        try:
            return body["content"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"Unexpected Anthropic response: {body}") from exc


# ── Provider presets ─────────────────────────────────────────────────────────

PROVIDER_PRESETS = {
    "ollama": {"base_url": "http://localhost:11434/v1", "api_key": "", "model": "llama3.2"},
    "openai": {"base_url": "https://api.openai.com/v1", "api_key": "", "model": "gpt-4o-mini"},
    "anthropic": {"base_url": "", "api_key": "", "model": "claude-sonnet-4-20250514"},
    "custom": {"base_url": "http://localhost:8080/v1", "api_key": "", "model": ""},
}


def create_provider(
    provider_type: str, base_url: str, api_key: str, model: str
) -> LLMProvider:
    """Factory: create the right LLMProvider for the given type."""
    if provider_type == "anthropic":
        if not api_key:
            raise LLMError("Anthropic provider requires an API key.")
        return AnthropicProvider(api_key=api_key, model=model)
    # Everything else uses OpenAI-compatible endpoint
    if not base_url:
        raise LLMError("Base URL is required for non-Anthropic providers.")
    return OpenAICompatProvider(base_url=base_url, api_key=api_key, model=model)
