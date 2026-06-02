"""Tests for the session helper functions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from copilot_gateway.copilot.sessions import (
    disconnect_session,
    get_or_create_session,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_session(session_id: str = "sdk-123") -> MagicMock:
    session = AsyncMock()
    session.session_id = session_id
    session.disconnect = AsyncMock()
    session.on = MagicMock()
    session.send = AsyncMock()
    session.send_and_wait = AsyncMock()
    return session


def _make_mock_client():
    client = AsyncMock()
    client.create_session = AsyncMock()
    client.resume_session = AsyncMock()
    client.delete_session = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# get_or_create_session
# ---------------------------------------------------------------------------

class TestGetOrCreateSession:
    @pytest.mark.asyncio
    async def test_creates_new_when_no_id(self):
        mock_client = _make_mock_client()
        fake = _make_fake_session("sdk-abc")
        mock_client.create_session.return_value = fake

        with patch("copilot_gateway.copilot.sessions.get_copilot_client", new=AsyncMock(return_value=mock_client)):
            session, sid, is_new = await get_or_create_session(
                None, model="gpt-4o",
            )

        assert is_new is True
        assert sid == "sdk-abc"
        assert session is fake
        mock_client.create_session.assert_awaited_once()
        mock_client.resume_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resumes_when_id_provided(self):
        mock_client = _make_mock_client()
        fake = _make_fake_session("existing-id")
        mock_client.resume_session.return_value = fake

        with patch("copilot_gateway.copilot.sessions.get_copilot_client", new=AsyncMock(return_value=mock_client)):
            session, sid, is_new = await get_or_create_session(
                "existing-id", model="gpt-4o",
            )

        assert is_new is False
        assert sid == "existing-id"
        assert session is fake
        mock_client.resume_session.assert_awaited_once()
        mock_client.create_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_falls_back_to_create_on_resume_failure(self):
        mock_client = _make_mock_client()
        mock_client.resume_session.side_effect = RuntimeError("gone")
        fake = _make_fake_session("sdk-new")
        mock_client.create_session.return_value = fake

        with patch("copilot_gateway.copilot.sessions.get_copilot_client", new=AsyncMock(return_value=mock_client)):
            session, sid, is_new = await get_or_create_session(
                "stale-id", model="gpt-4o",
            )

        assert is_new is True
        assert sid == "sdk-new"
        assert session is fake

    @pytest.mark.asyncio
    async def test_passes_system_message_and_tools(self):
        mock_client = _make_mock_client()
        fake = _make_fake_session("sdk-1")
        mock_client.create_session.return_value = fake

        with patch("copilot_gateway.copilot.sessions.get_copilot_client", new=AsyncMock(return_value=mock_client)):
            await get_or_create_session(
                None,
                model="gpt-4o",
                system_message="Be helpful",
                tools=["tool1"],
                streaming=True,
            )

        call_kwargs = mock_client.create_session.call_args.kwargs
        assert call_kwargs["system_message"] == {"content": "Be helpful"}
        assert call_kwargs["tools"] == ["tool1"]
        assert call_kwargs["streaming"] is True


# ---------------------------------------------------------------------------
# disconnect_session
# ---------------------------------------------------------------------------

class TestDisconnectSession:
    @pytest.mark.asyncio
    async def test_calls_disconnect(self):
        session = _make_fake_session()
        await disconnect_session(session)
        session.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_suppresses_errors(self):
        session = _make_fake_session()
        session.disconnect.side_effect = RuntimeError("oops")
        # Should not raise
        await disconnect_session(session)
