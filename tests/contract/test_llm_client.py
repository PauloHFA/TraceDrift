"""Contract tests for LLMClient using respx to mock OpenAI API endpoints."""

import json

import httpx
import pytest
import respx
from openai import AuthenticationError

from tracedrift.client import LLMClient, TokenBudgetExceededError


@pytest.mark.asyncio
@respx.mock
async def test_llm_client_success_200() -> None:
    expected_payload = {
        "scenario": "Checkout Success",
        "anomaly_type": "normal",
        "spans": [],
    }
    response_body = {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1677652288,
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(expected_payload),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80},
    }

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=response_body)
    )

    async with httpx.AsyncClient() as http_client:
        client = LLMClient(api_key="test-key", http_client=http_client)
        result = await client.generate_json(prompt="Generate trace")
        assert result == expected_payload
        assert client.total_tokens_used == 80


@pytest.mark.asyncio
@respx.mock
async def test_llm_client_strips_markdown_codeblock() -> None:
    payload = {"scenario": "Markdown Wrapped"}
    wrapped_content = f"```json\n{json.dumps(payload)}\n```"

    response_body = {
        "id": "chatcmpl-456",
        "choices": [{"index": 0, "message": {"content": wrapped_content}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 20, "total_tokens": 40},
    }
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=response_body)
    )

    async with httpx.AsyncClient() as http_client:
        client = LLMClient(api_key="test-key", http_client=http_client)
        result = await client.generate_json(prompt="Generate trace")
        assert result == payload


@pytest.mark.asyncio
@respx.mock
async def test_llm_client_401_no_retry() -> None:
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": {"message": "Invalid API key"}})
    )

    async with httpx.AsyncClient() as http_client:
        client = LLMClient(api_key="invalid-key", http_client=http_client)
        with pytest.raises(AuthenticationError):
            await client.generate_json(prompt="Test")


@pytest.mark.asyncio
async def test_token_budget_exceeded() -> None:
    client = LLMClient(api_key="test-key", max_tokens_budget=100)
    client.total_tokens_used = 150  # Exceeded budget

    with pytest.raises(TokenBudgetExceededError):
        await client.generate_json(prompt="Test")
