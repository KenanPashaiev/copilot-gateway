"""Tests for the admin virtual model handler."""

from __future__ import annotations

import pytest

from copilot_gateway.routes.admin import (
    ADMIN_MODEL_ID,
    _cmd_help,
    _format_uptime,
    _parse_command,
    admin_model_entry,
)


class TestAdminModelEntry:
    def test_returns_correct_id(self):
        entry = admin_model_entry()
        assert entry["id"] == ADMIN_MODEL_ID
        assert entry["object"] == "model"
        assert entry["owned_by"] == "copilot-gateway"


class TestParseCommand:
    def test_help(self):
        messages = [{"role": "user", "content": "help"}]
        assert _parse_command(messages) == "help"

    def test_status(self):
        messages = [{"role": "user", "content": "status"}]
        assert _parse_command(messages) == "status"

    def test_models(self):
        messages = [{"role": "user", "content": "show me the models"}]
        assert _parse_command(messages) == "models"

    def test_config(self):
        messages = [{"role": "user", "content": "config"}]
        assert _parse_command(messages) == "config"

    def test_tools(self):
        messages = [{"role": "user", "content": "what tools are loaded?"}]
        assert _parse_command(messages) == "tools"

    def test_unrecognized_defaults_to_help(self):
        messages = [{"role": "user", "content": "asdfghjkl"}]
        assert _parse_command(messages) == "help"

    def test_empty_messages_defaults_to_help(self):
        assert _parse_command([]) == "help"

    def test_uses_last_user_message(self):
        messages = [
            {"role": "user", "content": "help"},
            {"role": "assistant", "content": "some response"},
            {"role": "user", "content": "status"},
        ]
        assert _parse_command(messages) == "status"

    def test_multimodal_content(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "show me the status"},
                ],
            }
        ]
        assert _parse_command(messages) == "status"

    def test_case_insensitive(self):
        messages = [{"role": "user", "content": "STATUS"}]
        assert _parse_command(messages) == "status"


class TestCmdHelp:
    def test_contains_commands(self):
        result = _cmd_help()
        assert "status" in result
        assert "models" in result
        assert "config" in result
        assert "tools" in result
        assert "help" in result


class TestFormatUptime:
    def test_seconds(self):
        assert _format_uptime(45) == "45s"

    def test_minutes(self):
        assert _format_uptime(125) == "2m 5s"

    def test_hours(self):
        assert _format_uptime(3661) == "1h 1m"

    def test_zero(self):
        assert _format_uptime(0) == "0s"
