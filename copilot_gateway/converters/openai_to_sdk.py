"""Convert OpenAI API request format to Copilot SDK format."""

from __future__ import annotations


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


def extract_params(body: dict) -> dict:
    """Extract optional parameters from the OpenAI request body.

    Returns a dict of kwargs suitable for session creation.
    """
    params = {}
    if "temperature" in body:
        params["temperature"] = body["temperature"]
    if "top_p" in body:
        params["top_p"] = body["top_p"]
    if "max_tokens" in body:
        params["max_tokens"] = body["max_tokens"]
    if "max_completion_tokens" in body:
        params["max_tokens"] = body["max_completion_tokens"]
    return params
