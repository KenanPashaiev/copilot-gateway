"""Route-level tests for POST /v1/chat/completions — session reuse behavior."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from copilot_gateway.routes import chat


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@dataclass
class _ServerConfig:
    api_key: str = ""


@dataclass
class _CopilotConfig:
    default_model: str = "gpt-4o"


@dataclass
class _FakeConfig:
    server: _ServerConfig = field(default_factory=_ServerConfig)
    copilot: _CopilotConfig = field(default_factory=_CopilotConfig)


def _make_fake_session(session_id: str = "sdk-session-1") -> MagicMock:
    session = AsyncMock()
    session.session_id = session_id
    session.disconnect = AsyncMock()

    # send_and_wait returns an object with .data.content
    result = MagicMock()
    result.data.content = "Hello from the model"
    session.send_and_wait = AsyncMock(return_value=result)
    return session


def _make_streaming_session(session_id: str = "sdk-stream-1") -> MagicMock:
    """Create a fake session that works with the streaming code path.

    ``session.on(callback)`` captures the event handler.
    ``session.send(prompt)`` fires an assistant.message event (which
    marks the stream as done) so the generator completes.
    """
    session = AsyncMock()
    session.session_id = session_id
    session.disconnect = AsyncMock()

    captured_handler = {}

    def fake_on(handler):
        captured_handler["fn"] = handler

    def fake_send(prompt):
        # Simulate the SDK firing assistant.message so the loop exits.
        msg_event = MagicMock()
        msg_event.type.value = "assistant.message"
        captured_handler["fn"](msg_event)

    session.on = MagicMock(side_effect=fake_on)
    session.send = AsyncMock(side_effect=fake_send)
    return session


def _make_app() -> FastAPI:
    app = FastAPI()
    app.state.config = _FakeConfig()
    app.state.tools = []
    app.include_router(chat.router)
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBlockingSessionReuse:
    """Non-streaming POST /v1/chat/completions with session reuse."""

    def test_response_includes_x_session_id(self):
        """First request (no header) should return X-Session-Id in the response."""
        fake_session = _make_fake_session("new-session-abc")

        with patch(
            "copilot_gateway.routes.chat.get_or_create_session",
            new=AsyncMock(return_value=(fake_session, "new-session-abc", True)),
        ), patch("copilot_gateway.routes.chat.disconnect_session", new_callable=AsyncMock):
            client = TestClient(_make_app())
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            )

        assert resp.status_code == 200
        assert resp.headers["x-session-id"] == "new-session-abc"

    def test_x_session_id_header_triggers_resume(self):
        """Passing X-Session-Id should call get_or_create_session with that ID."""
        fake_session = _make_fake_session("existing-session")

        mock_get_or_create = AsyncMock(
            return_value=(fake_session, "existing-session", False),
        )

        with patch(
            "copilot_gateway.routes.chat.get_or_create_session",
            mock_get_or_create,
        ), patch("copilot_gateway.routes.chat.disconnect_session", new_callable=AsyncMock):
            client = TestClient(_make_app())
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "messages": [
                        {"role": "user", "content": "First question"},
                        {"role": "assistant", "content": "First answer"},
                        {"role": "user", "content": "Follow-up question"},
                    ],
                },
                headers={"X-Session-Id": "existing-session"},
            )

        assert resp.status_code == 200
        # Verify session ID was forwarded to get_or_create_session
        call_args = mock_get_or_create.call_args
        assert call_args[0][0] == "existing-session"

    def test_resumed_session_sends_only_last_user_message(self):
        """When a session is resumed (is_new=False), only the last user message
        should be sent as the prompt, not the full conversation history."""
        fake_session = _make_fake_session("resumed-session")

        with patch(
            "copilot_gateway.routes.chat.get_or_create_session",
            new=AsyncMock(return_value=(fake_session, "resumed-session", False)),
        ), patch("copilot_gateway.routes.chat.disconnect_session", new_callable=AsyncMock):
            client = TestClient(_make_app())
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "messages": [
                        {"role": "system", "content": "Be helpful"},
                        {"role": "user", "content": "What is 2+2?"},
                        {"role": "assistant", "content": "4"},
                        {"role": "user", "content": "And 3+3?"},
                    ],
                },
                headers={"X-Session-Id": "resumed-session"},
            )

        assert resp.status_code == 200
        # send_and_wait should have been called with only the last user message
        prompt_sent = fake_session.send_and_wait.call_args[0][0]
        assert prompt_sent == "And 3+3?"
        # Should NOT contain the earlier conversation turns
        assert "What is 2+2?" not in prompt_sent
        assert "[assistant]" not in prompt_sent

    def test_new_session_sends_full_history(self):
        """When a session is new (is_new=True), the full conversation history
        should be sent as the prompt."""
        fake_session = _make_fake_session("brand-new")

        with patch(
            "copilot_gateway.routes.chat.get_or_create_session",
            new=AsyncMock(return_value=(fake_session, "brand-new", True)),
        ), patch("copilot_gateway.routes.chat.disconnect_session", new_callable=AsyncMock):
            client = TestClient(_make_app())
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "messages": [
                        {"role": "user", "content": "What is 2+2?"},
                        {"role": "assistant", "content": "4"},
                        {"role": "user", "content": "And 3+3?"},
                    ],
                },
            )

        assert resp.status_code == 200
        prompt_sent = fake_session.send_and_wait.call_args[0][0]
        # Full history should be present
        assert "What is 2+2?" in prompt_sent
        assert "[assistant]\n4" in prompt_sent
        assert "And 3+3?" in prompt_sent

    def test_session_disconnected_after_request(self):
        """Session should always be disconnected after a request completes."""
        fake_session = _make_fake_session("cleanup-test")
        mock_disconnect = AsyncMock()

        with patch(
            "copilot_gateway.routes.chat.get_or_create_session",
            new=AsyncMock(return_value=(fake_session, "cleanup-test", True)),
        ), patch(
            "copilot_gateway.routes.chat.disconnect_session",
            mock_disconnect,
        ):
            client = TestClient(_make_app())
            client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "Hi"}]},
            )

        mock_disconnect.assert_awaited_once_with(fake_session)


def _parse_sse_events(content: str) -> list[dict]:
    """Parse SSE text into a list of JSON-decoded data payloads."""
    events = []
    for line in content.splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            events.append(json.loads(line[len("data: "):]))
    return events


class TestStreamingSessionReuse:
    """Streaming POST /v1/chat/completions with session reuse."""

    def test_first_chunk_includes_x_session_id(self):
        """The first SSE chunk should contain x_session_id with the session ID."""
        fake_session = _make_streaming_session("stream-session-1")

        with patch(
            "copilot_gateway.routes.chat.get_or_create_session",
            new=AsyncMock(return_value=(fake_session, "stream-session-1", True)),
        ), patch("copilot_gateway.routes.chat.disconnect_session", new_callable=AsyncMock):
            client = TestClient(_make_app())
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "Hello"}],
                    "stream": True,
                },
            )

        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        assert len(events) >= 1
        first = events[0]
        assert first["x_session_id"] == "stream-session-1"
        assert first["choices"][0]["delta"] == {"role": "assistant"}

    def test_streaming_x_session_id_header_triggers_resume(self):
        """Passing X-Session-Id in streaming mode should resume the session."""
        fake_session = _make_streaming_session("stream-resume")

        mock_get_or_create = AsyncMock(
            return_value=(fake_session, "stream-resume", False),
        )

        with patch(
            "copilot_gateway.routes.chat.get_or_create_session",
            mock_get_or_create,
        ), patch("copilot_gateway.routes.chat.disconnect_session", new_callable=AsyncMock):
            client = TestClient(_make_app())
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "messages": [
                        {"role": "user", "content": "First"},
                        {"role": "assistant", "content": "Answer"},
                        {"role": "user", "content": "Second"},
                    ],
                    "stream": True,
                },
                headers={"X-Session-Id": "stream-resume"},
            )

        assert resp.status_code == 200
        # Verify session ID was forwarded
        assert mock_get_or_create.call_args[0][0] == "stream-resume"
        # Verify first chunk has the session ID
        events = _parse_sse_events(resp.text)
        assert events[0]["x_session_id"] == "stream-resume"

    def test_streaming_resumed_session_sends_only_last_user_message(self):
        """In streaming mode, resumed sessions should only send the last user message."""
        fake_session = _make_streaming_session("stream-resumed")

        with patch(
            "copilot_gateway.routes.chat.get_or_create_session",
            new=AsyncMock(return_value=(fake_session, "stream-resumed", False)),
        ), patch("copilot_gateway.routes.chat.disconnect_session", new_callable=AsyncMock):
            client = TestClient(_make_app())
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "messages": [
                        {"role": "user", "content": "What is 2+2?"},
                        {"role": "assistant", "content": "4"},
                        {"role": "user", "content": "And 3+3?"},
                    ],
                    "stream": True,
                },
                headers={"X-Session-Id": "stream-resumed"},
            )

        assert resp.status_code == 200
        prompt_sent = fake_session.send.call_args[0][0]
        assert prompt_sent == "And 3+3?"
        assert "What is 2+2?" not in prompt_sent

    def test_streaming_session_disconnected_after_request(self):
        """Session should be disconnected after a streaming request completes."""
        fake_session = _make_streaming_session("stream-cleanup")
        mock_disconnect = AsyncMock()

        with patch(
            "copilot_gateway.routes.chat.get_or_create_session",
            new=AsyncMock(return_value=(fake_session, "stream-cleanup", True)),
        ), patch(
            "copilot_gateway.routes.chat.disconnect_session",
            mock_disconnect,
        ):
            client = TestClient(_make_app())
            client.post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "Hi"}],
                    "stream": True,
                },
            )

        mock_disconnect.assert_awaited_once_with(fake_session)
