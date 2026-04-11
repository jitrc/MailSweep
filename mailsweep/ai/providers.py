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
    "ollama": {"base_url": "http://localhost:11434/v1", "api_key": "", "model": "qwen3:8b"},
    "lm-studio": {"base_url": "http://localhost:1234/v1", "api_key": "", "model": ""},
    "openai": {"base_url": "https://api.openai.com/v1", "api_key": "", "model": "gpt-5.2"},
    "anthropic": {"base_url": "https://api.anthropic.com/v1", "api_key": "", "model": "claude-sonnet-4-6"},
    "custom": {"base_url": "http://localhost:8080/v1", "api_key": "", "model": ""},
}

PROVIDER_MODELS: dict[str, list[str]] = {
    "ollama": ["qwen3:8b", "llama3.3:70b", "deepseek-r1:8b", "gemma3:12b", "qwen3:32b", "phi4"],
    "lm-studio": [],
    "openai": ["gpt-5.2", "gpt-5.2-pro", "gpt-4.1", "gpt-4.1-mini", "o4-mini", "o3"],
    "anthropic": ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5", "claude-sonnet-4-5"],
    "custom": [],
}


def normalize_url(url: str) -> str:
    """Normalize a user-supplied URL or host:port to a full base URL ending in /v1.

    Accepts:
      - ``host:port``              → ``http://host:port/v1``
      - ``http://host:port``       → ``http://host:port/v1``
      - ``http://host:port/v1``    → unchanged
    """
    s = url.strip().rstrip("/")
    if not s:
        return s
    if not s.startswith(("http://", "https://")):
        return f"http://{s}/v1"
    # Has a scheme — ensure it ends with /v1
    if not s.endswith("/v1"):
        return f"{s}/v1"
    return s


def detect_and_fetch(base_url: str, api_key: str = "") -> tuple[str, list[str]]:
    """Probe *base_url* to detect the API type and return (label, models).

    Detection order:
      1. Ollama native  — GET /api/tags
      2. OpenAI-compat  — GET /v1/models
    Returns ("unknown", []) when neither probe succeeds.
    """
    full_url = normalize_url(base_url).rstrip("/")
    if not full_url:
        return ("unknown", [])

    # Derive base host (strip trailing /v1 if present)
    base_host = full_url[:-3] if full_url.endswith("/v1") else full_url

    # 1. Ollama native API
    try:
        req = urllib.request.Request(f"{base_host}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if "models" in body:
            models = sorted(m["name"] for m in body["models"])
            return ("Ollama (native API)", models)
    except Exception:
        logger.debug("detect_and_fetch: Ollama probe failed for %s", base_host, exc_info=True)

    # 2. OpenAI-compatible — /v1/models
    try:
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(f"{full_url}/models", headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if "data" in body:
            models = sorted(item["id"] for item in body["data"])
            return ("OpenAI-compatible", models)
    except Exception:
        logger.debug("detect_and_fetch: OpenAI-compat probe failed for %s", full_url, exc_info=True)

    return ("unknown", [])


def fetch_anthropic_models(api_key: str) -> list[str]:
    """Fetch available models from the Anthropic API."""
    url = "https://api.anthropic.com/v1/models"
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return sorted(item["id"] for item in body.get("data", []))
    except Exception:
        logger.debug("fetch_anthropic_models failed", exc_info=True)
        return []


def fetch_model_list(base_url: str, api_key: str = "") -> list[str]:
    """GET {base_url}/models and return sorted list of model IDs.

    Returns an empty list on any error (connection refused, timeout, etc.).
    """
    base_url = normalize_url(base_url)
    url = f"{base_url.rstrip('/')}/models"
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return sorted(item["id"] for item in body.get("data", []))
    except Exception:
        logger.debug("fetch_model_list failed for %s", url, exc_info=True)
        return []


def create_provider(
    provider_type: str, base_url: str, api_key: str, model: str
) -> LLMProvider:
    """Factory: create the right LLMProvider for the given type."""
    if provider_type == "anthropic":
        if not api_key:
            raise LLMError("Anthropic provider requires an API key.")
        return AnthropicProvider(api_key=api_key, model=model)
    # Everything else uses OpenAI-compatible endpoint
    base_url = normalize_url(base_url)
    if not base_url:
        raise LLMError("Base URL is required for non-Anthropic providers.")
    return OpenAICompatProvider(base_url=base_url, api_key=api_key, model=model)
