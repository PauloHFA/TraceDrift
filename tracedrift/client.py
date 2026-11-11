"""LLM Client for OpenAI-compatible providers with retries, token budgeting, and JSON parsing."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from openai import (
    APIConnectionError,
    AsyncOpenAI,
    AuthenticationError,
    InternalServerError,
    PermissionDeniedError,
    RateLimitError,
)
from openai.types.chat import ChatCompletionMessageParam
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)


class LLMClientError(Exception):
    """Base error for LLM client failures."""


class TokenBudgetExceededError(LLMClientError):
    """Raised when token usage exceeds configured budget."""


def _should_retry_exception(exc: BaseException) -> bool:
    """Retries only on transient errors (429, 5xx, connection timeouts), never on 401/403."""
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return False
    return bool(isinstance(exc, (RateLimitError, APIConnectionError, InternalServerError)))


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        max_tokens_budget: int | None = None,
        http_client: Any | None = None,
    ) -> None:
        self.api_key: str = api_key or os.getenv("OPENAI_API_KEY") or "dummy-key-for-local"
        self.base_url: str = base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        self.model: str = model or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
        self.max_tokens_budget = max_tokens_budget

        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens_used = 0

        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            http_client=http_client,
        )

    def extract_json(self, raw_text: str) -> dict[str, Any]:
        """Extracts JSON object from text, stripping markdown code blocks if present."""
        clean = raw_text.strip()
        if "```" in clean:
            matches = re.findall(r"```(?:json)?\s*(.*?)\s*```", clean, re.DOTALL)
            if matches:
                clean = matches[0].strip()

        try:
            parsed = json.loads(clean)
            if isinstance(parsed, dict):
                return parsed
            raise LLMClientError(
                f"A resposta do modelo não é um objeto JSON válido (tipo recebido: {type(parsed).__name__})."
            )
        except json.JSONDecodeError as err:
            raise LLMClientError(
                f"Erro ao decodificar JSON retornado pelo modelo: {err}. Conteúdo: {raw_text[:200]}"
            ) from err

    @retry(
        retry=retry_if_exception(_should_retry_exception),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1.0, max=30.0, jitter=1.0),
        reraise=True,
    )
    async def generate_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """Sends request to LLM and parses JSON response."""
        if self.max_tokens_budget and self.total_tokens_used >= self.max_tokens_budget:
            raise TokenBudgetExceededError(
                f"Orçamento máximo de tokens ({self.max_tokens_budget}) atingido. Total usado: {self.total_tokens_used}."
            )

        messages: list[ChatCompletionMessageParam] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )

        usage = response.usage
        if usage:
            self.total_prompt_tokens += usage.prompt_tokens
            self.total_completion_tokens += usage.completion_tokens
            self.total_tokens_used += usage.total_tokens

        content = response.choices[0].message.content or "{}"
        return self.extract_json(content)
