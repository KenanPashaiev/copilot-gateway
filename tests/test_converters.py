"""Tests for the OpenAI <-> SDK converters."""

from __future__ import annotations

from copilot_gateway.converters.openai_to_sdk import (
    _extract_text_content,
    extract_params,
    messages_to_prompt,
)
from copilot_gateway.converters.sdk_to_openai import (
    make_chat_completion,
    make_error_response,
    make_stream_chunk,
)


# --- openai_to_sdk ---


class TestExtractTextContent:
    def test_string(self):
        assert _extract_text_content("hello") == "hello"

    def test_none(self):
        assert _extract_text_content(None) == ""

    def test_multimodal_list(self):
        content = [
            {"type": "text", "text": "Hello"},
            {"type": "image_url", "image_url": {"url": "https://example.com/img.png"}},
            {"type": "text", "text": "World"},
        ]
        assert _extract_text_content(content) == "Hello\nWorld"

    def test_empty_list(self):
        assert _extract_text_content([]) == ""


class TestMessagesToPrompt:
    def test_single_user_message(self):
        messages = [{"role": "user", "content": "Hello"}]
        system, prompt = messages_to_prompt(messages)
        assert system is None
        assert "[user]\nHello" in prompt

    def test_system_message_extracted(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        system, prompt = messages_to_prompt(messages)
        assert system == "You are helpful."
        assert "You are helpful." not in prompt
        assert "[user]\nHi" in prompt

    def test_multi_turn_preserved(self):
        messages = [
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
            {"role": "user", "content": "And 3+3?"},
        ]
        system, prompt = messages_to_prompt(messages)
        assert system is None
        assert "[user]\nWhat is 2+2?" in prompt
        assert "[assistant]\n4" in prompt
        assert "[user]\nAnd 3+3?" in prompt

    def test_tool_message(self):
        messages = [
            {"role": "tool", "content": '{"result": 42}', "tool_call_id": "call_abc"},
        ]
        _, prompt = messages_to_prompt(messages)
        assert "call_id=call_abc" in prompt
        assert '{"result": 42}' in prompt

    def test_empty_messages(self):
        system, prompt = messages_to_prompt([])
        assert system is None
        assert prompt == ""


class TestExtractParams:
    def test_unsupported_params_ignored(self):
        body = {"temperature": 0.7, "top_p": 0.9, "max_tokens": 100}
        params = extract_params(body)
        assert params == {}

    def test_max_completion_tokens_ignored(self):
        body = {"max_tokens": 100, "max_completion_tokens": 200}
        params = extract_params(body)
        assert params == {}

    def test_no_params(self):
        assert extract_params({"model": "gpt-4o"}) == {}


# --- sdk_to_openai ---


class TestMakeChatCompletion:
    def test_basic(self):
        result = make_chat_completion(model="gpt-4o", content="Hello!")
        assert result["object"] == "chat.completion"
        assert result["model"] == "gpt-4o"
        assert result["choices"][0]["message"]["content"] == "Hello!"
        assert result["choices"][0]["finish_reason"] == "stop"
        assert result["id"].startswith("chatcmpl-")

    def test_custom_finish_reason(self):
        result = make_chat_completion(model="m", content="", finish_reason="length")
        assert result["choices"][0]["finish_reason"] == "length"


class TestMakeStreamChunk:
    def test_role_chunk(self):
        chunk = make_stream_chunk("id1", "gpt-4o", role="assistant")
        assert chunk["choices"][0]["delta"] == {"role": "assistant"}
        assert chunk["choices"][0]["finish_reason"] is None

    def test_content_delta(self):
        chunk = make_stream_chunk("id1", "gpt-4o", delta_content="Hello")
        assert chunk["choices"][0]["delta"] == {"content": "Hello"}

    def test_finish_chunk(self):
        chunk = make_stream_chunk("id1", "gpt-4o", finish_reason="stop")
        assert chunk["choices"][0]["delta"] == {}
        assert chunk["choices"][0]["finish_reason"] == "stop"


class TestMakeErrorResponse:
    def test_basic(self):
        result = make_error_response("Something broke", "server_error")
        assert result["error"]["message"] == "Something broke"
        assert result["error"]["type"] == "server_error"
        assert "code" not in result["error"]

    def test_with_code(self):
        result = make_error_response("Bad auth", "auth_error", code="invalid_key")
        assert result["error"]["code"] == "invalid_key"
