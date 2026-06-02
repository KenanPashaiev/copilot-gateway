"""Tests for the admin virtual model handler."""

from __future__ import annotations

from copilot_gateway.routes.admin import (
    ADMIN_MODEL_ID,
    _cmd_help,
    _format_uptime,
    _get_last_user_text,
    _has_pending_device_flow,
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
        msgs = [{"role": "user", "content": "help"}]
        assert _parse_command(msgs) == ("help", "")

    def test_status(self):
        msgs = [{"role": "user", "content": "status"}]
        assert _parse_command(msgs) == ("status", "")

    def test_models(self):
        msgs = [{"role": "user", "content": "models"}]
        assert _parse_command(msgs) == ("models", "")

    def test_tools(self):
        msgs = [{"role": "user", "content": "tools"}]
        assert _parse_command(msgs) == ("tools", "")

    def test_restart(self):
        msgs = [{"role": "user", "content": "restart"}]
        assert _parse_command(msgs) == ("restart", "")

    def test_check(self):
        msgs = [{"role": "user", "content": "check"}]
        assert _parse_command(msgs) == ("check", "")

    def test_auth_status(self):
        msgs = [{"role": "user", "content": "auth"}]
        assert _parse_command(msgs) == ("auth", "")

    def test_auth_login(self):
        msgs = [{"role": "user", "content": "auth login"}]
        assert _parse_command(msgs) == ("auth_login", "")

    def test_auth_logout(self):
        msgs = [{"role": "user", "content": "auth logout"}]
        assert _parse_command(msgs) == ("auth_logout", "")

    def test_unrecognized_defaults_to_unknown(self):
        msgs = [{"role": "user", "content": "asdfghjkl"}]
        assert _parse_command(msgs) == ("unknown", "")

    def test_empty_messages(self):
        assert _parse_command([]) == ("unknown", "")

    def test_uses_last_user_message(self):
        msgs = [
            {"role": "user", "content": "help"},
            {"role": "assistant", "content": "some response"},
            {"role": "user", "content": "status"},
        ]
        assert _parse_command(msgs) == ("status", "")

    def test_case_insensitive(self):
        msgs = [{"role": "user", "content": "AUTH LOGIN"}]
        assert _parse_command(msgs) == ("auth_login", "")

    def test_pending_device_flow_any_message_becomes_check(self):
        msgs = [
            {"role": "user", "content": "auth login"},
            {"role": "assistant", "content": "Go to url... type **check** again"},
            {"role": "user", "content": "done"},
        ]
        assert _parse_command(msgs) == ("check", "")

    def test_no_pending_flow_unrecognized_stays_unknown(self):
        msgs = [
            {"role": "user", "content": "auth login"},
            {"role": "assistant", "content": "Here are the models"},
            {"role": "user", "content": "done"},
        ]
        assert _parse_command(msgs) == ("unknown", "")


class TestHasPendingDeviceFlow:
    def test_detects_check_prompt(self):
        msgs = [
            {"role": "assistant", "content": "Once done, type **check** and I'll complete the login."},
            {"role": "user", "content": "ok"},
        ]
        assert _has_pending_device_flow(msgs) is True

    def test_no_check_prompt(self):
        msgs = [
            {"role": "assistant", "content": "Here are the available models"},
            {"role": "user", "content": "ok"},
        ]
        assert _has_pending_device_flow(msgs) is False

    def test_empty(self):
        assert _has_pending_device_flow([]) is False


class TestGetLastUserText:
    def test_simple(self):
        msgs = [{"role": "user", "content": "hello"}]
        assert _get_last_user_text(msgs) == "hello"

    def test_multimodal(self):
        msgs = [
            {
                "role": "user",
                "content": [{"type": "text", "text": "status check"}],
            }
        ]
        assert _get_last_user_text(msgs) == "status check"

    def test_empty(self):
        assert _get_last_user_text([]) == ""

    def test_skips_assistant(self):
        msgs = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second"},
        ]
        assert _get_last_user_text(msgs) == "second"


class TestCmdHelp:
    def test_authenticated_help(self):
        result = _cmd_help(auth_ok=True)
        assert "auth" in result
        assert "status" in result
        assert "models" in result
        assert "tools" in result
        assert "restart" in result
        assert "help" in result
        assert "Not authenticated" not in result

    def test_unauthenticated_help(self):
        result = _cmd_help(auth_ok=False)
        assert "Not authenticated" in result
        assert "auth login" in result


class TestFormatUptime:
    def test_seconds(self):
        assert _format_uptime(45) == "45s"

    def test_minutes(self):
        assert _format_uptime(125) == "2m 5s"

    def test_hours(self):
        assert _format_uptime(3661) == "1h 1m"

    def test_zero(self):
        assert _format_uptime(0) == "0s"
