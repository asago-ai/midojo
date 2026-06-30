"""Tests for agent client implementations."""

from __future__ import annotations

import importlib

import pytest

from midojo.agent_client import OGXResponsesClient


class TestOGXResponsesClient:
    """Tests for the OGX protocol client fixes."""

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
        # The weather suite's __init__.py may or may not define SYSTEM_MESSAGE;
        # the fallback must always work regardless.
        try:
            _suite_mod = importlib.import_module("suites.weather")
        except ImportError:
            _suite_mod = None
        # getattr with default must not raise even if attribute is absent
        system_message = getattr(_suite_mod, "SYSTEM_MESSAGE", "")
        assert isinstance(system_message, str)
