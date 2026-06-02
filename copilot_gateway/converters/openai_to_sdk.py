"""Convert OpenAI API request format to Copilot SDK format."""

from __future__ import annotations

import base64
import re


def last_user_prompt(messages: list[dict]) -> tuple[str | None, str]:
    """Extract the system message and only the last user message.

    Used when resuming a session — the SDK already has the conversation
    history, so we only need the newest user message.

    Returns (system_message, prompt).
    """
    system_message: str | None = None
    last_user_content: str = ""

    for msg in messages:
        role = msg.get("role", "user")
        content = _extract_text_content(msg.get("content", ""))
        if role == "system":
            system_message = content
        elif role == "user":
            last_user_content = content

    return system_message, last_user_content


def messages_to_prompt(messages: list[dict]) -> tuple[str | None, str]:
    """Extract system message and user prompt from OpenAI-format messages.

    Returns (system_message, prompt) where system_message may be None.
    The prompt is built from all non-system messages, preserving conversation
    history with clear role boundaries.
    """
    system_message: str | None = None
    conversation_parts: list[str] = []

    for msg in messages:
        role = msg.get("role", "user")
        content = _extract_text_content(msg.get("content", ""))

        if role == "system":
            # Use last system message if multiple exist
            system_message = content
        elif role == "assistant":
            conversation_parts.append(f"[assistant]\n{content}")
        elif role == "tool":
            tool_call_id = msg.get("tool_call_id", "unknown")
            conversation_parts.append(
                f"[tool result (call_id={tool_call_id})]\n{content}"
            )
        else:
            # user or any other role
            conversation_parts.append(f"[user]\n{content}")

    prompt = "\n\n".join(conversation_parts) if conversation_parts else ""
    return system_message, prompt


def _extract_text_content(content: str | list | None) -> str:
    """Extract text from content that may be a string or multimodal list."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(part.get("text", ""))
        return "\n".join(text_parts)
    return str(content)


# Matches data URIs like "data:image/png;base64,iVBOR..."
_DATA_URI_RE = re.compile(
    r"^data:(?P<mime>image/[a-zA-Z0-9.+-]+);base64,(?P<data>.+)$",
    re.DOTALL,
)


def extract_image_attachments(messages: list[dict]) -> list[dict]:
    """Extract image attachments from OpenAI-format messages.

    Scans all messages for content parts with type "image_url" and converts
    them to Copilot SDK attachment format.

    Supports:
    - Base64 data URIs: data:image/png;base64,... → blob attachment
    - HTTP(S) URLs: https://example.com/img.png → url attachment

    Returns a list of SDK-format attachment dicts.
    """
    attachments: list[dict] = []

    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            image_url_obj = part.get("image_url", {})
            url = image_url_obj.get("url", "") if isinstance(image_url_obj, dict) else ""
            if not url:
                continue

            match = _DATA_URI_RE.match(url)
            if match:
                attachments.append({
                    "type": "blob",
                    "data": match.group("data"),
                    "mimeType": match.group("mime"),
                })
            elif url.startswith(("http://", "https://")):
                attachments.append({
                    "type": "url",
                    "url": url,
                })

    return attachments


def extract_params(body: dict) -> dict:
    """Extract optional parameters from the OpenAI request body.

    Returns a dict of kwargs suitable for session creation.
    Note: temperature, top_p, max_tokens, and max_completion_tokens are
    accepted by the OpenAI API but not supported by CopilotClient.create_session(),
    so they are intentionally excluded.
    """
    params = {}
    if "reasoning_effort" in body:
        params["reasoning_effort"] = body["reasoning_effort"]
    return params
