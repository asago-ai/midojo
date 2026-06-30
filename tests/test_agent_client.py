"""Tests for agent client implementations."""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from midojo.agent_client import OGXResponsesClient, OpenAIResponsesAgentClient


class TestOGXResponsesClient:
    """Tests for the OGX protocol client fixes (PR #93)."""

    def test_mcp_server_label_stored(self):
        """mcp_server_label is stored and not hardcoded to 'weather'."""
        client = OGXResponsesClient(
            ogx_url="http://localhost:8321",
            model="llama-scout-17b",
            mcp_server_url="http://localhost:8082/mcp",
            mcp_server_label="minibank",
        )
        assert client.mcp_server_label == "minibank"

    def test_mcp_server_label_default(self):
        """mcp_server_label defaults to 'midojo' when not given."""
        client = OGXResponsesClient(
            ogx_url="http://localhost:8321",
            model="llama-scout-17b",
            mcp_server_url="http://localhost:8082/mcp",
        )
        assert client.mcp_server_label == "midojo"

    def test_mcp_server_label_override(self):
        """mcp_server_label can be overridden from suite_name default."""
        client = OGXResponsesClient(
            ogx_url="http://localhost:8321",
            model="llama-scout-17b",
            mcp_server_url="http://localhost:8082/mcp",
            mcp_server_label="my-custom-label",
        )
        assert client.mcp_server_label == "my-custom-label"

    def test_suite_module_import_missing(self):
        """Protocol dispatch: missing suite module falls back to empty SYSTEM_MESSAGE."""
        try:
            _suite_mod = importlib.import_module("suites.nonexistent_suite_xyz")
        except ImportError:
            _suite_mod = None
        system_message = getattr(_suite_mod, "SYSTEM_MESSAGE", "")
        assert system_message == ""

    def test_suite_module_import_no_system_message(self):
        """Protocol dispatch: suite module without SYSTEM_MESSAGE falls back to empty."""
        try:
            _suite_mod = importlib.import_module("suites.weather")
        except ImportError:
            _suite_mod = None
        system_message = getattr(_suite_mod, "SYSTEM_MESSAGE", "")
        assert isinstance(system_message, str)


class TestOpenAIResponsesAgentClient:
    """Tests for the native OpenAI Responses API client (--protocol openai, PR #94)."""

    def test_constructor_stores_fields(self):
        client = OpenAIResponsesAgentClient(
            base_url="http://localhost:8321/v1",
            model="gpt-4o-mini",
            mcp_server_url="http://localhost:8082/mcp",
            mcp_server_label="weather",
            api_key="sk-test",
            instructions="Be concise.",
            timeout=60.0,
        )
        assert client.base_url == "http://localhost:8321/v1"
        assert client.model == "gpt-4o-mini"
        assert client.mcp_server_url == "http://localhost:8082/mcp"
        assert client.mcp_server_label == "weather"
        assert client.api_key == "sk-test"
        assert client.instructions == "Be concise."
        assert client.timeout == 60.0

    def test_constructor_defaults(self):
        client = OpenAIResponsesAgentClient(
            base_url="http://localhost:8321/v1",
            model="gpt-4o-mini",
            mcp_server_url="http://localhost:8082/mcp",
        )
        assert client.mcp_server_label == "midojo"
        assert client.api_key == "x"
        assert client.instructions == ""
        assert client.timeout == 120.0

    @pytest.mark.asyncio
    async def test_send_task_calls_responses_create(self):
        """send_task calls AsyncOpenAI.responses.create with the correct arguments."""
        client = OpenAIResponsesAgentClient(
            base_url="http://localhost:8321/v1",
            model="gpt-4o-mini",
            mcp_server_url="http://localhost:8082/mcp",
            mcp_server_label="weather",
            api_key="x",
        )

        mock_response = MagicMock()
        mock_response.output_text = "It is 72°F and sunny in New York."

        mock_responses = MagicMock()
        mock_responses.create = AsyncMock(return_value=mock_response)

        mock_openai_instance = MagicMock()
        mock_openai_instance.responses = mock_responses
        mock_openai_instance.__aenter__ = AsyncMock(return_value=mock_openai_instance)
        mock_openai_instance.__aexit__ = AsyncMock(return_value=None)

        with patch("openai.AsyncOpenAI", return_value=mock_openai_instance):
            result = await client.send_task("What is the weather in New York?")

        assert result == "It is 72°F and sunny in New York."
        mock_responses.create.assert_called_once()
        call_kwargs = mock_responses.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o-mini"
        assert call_kwargs["input"] == "What is the weather in New York?"
        assert call_kwargs["stream"] is False
        tools = call_kwargs["tools"]
        assert len(tools) == 1
        assert tools[0]["type"] == "mcp"
        assert tools[0]["server_label"] == "weather"
        assert tools[0]["server_url"] == "http://localhost:8082/mcp"
        assert tools[0]["require_approval"] == "never"

    @pytest.mark.asyncio
    async def test_send_task_passes_instructions(self):
        """instructions is forwarded to the API call."""
        client = OpenAIResponsesAgentClient(
            base_url="http://localhost:8321/v1",
            model="gpt-4o-mini",
            mcp_server_url="http://localhost:8082/mcp",
            instructions="You are a weather assistant.",
        )
        mock_response = MagicMock(output_text="sunny")
        mock_openai_instance = MagicMock()
        mock_openai_instance.responses.create = AsyncMock(return_value=mock_response)
        mock_openai_instance.__aenter__ = AsyncMock(return_value=mock_openai_instance)
        mock_openai_instance.__aexit__ = AsyncMock(return_value=None)

        with patch("openai.AsyncOpenAI", return_value=mock_openai_instance):
            await client.send_task("weather?")

        call_kwargs = mock_openai_instance.responses.create.call_args.kwargs
        assert call_kwargs["instructions"] == "You are a weather assistant."
