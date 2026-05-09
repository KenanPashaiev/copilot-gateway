# Custom Tools Guide

copilot-gateway supports a plugin system for tools. Tools are Python modules that define functions the LLM can call during a conversation — for example, searching the web, looking up data, or performing calculations.

## How It Works

1. You write a Python file that defines one or more tools using the Copilot SDK's `@define_tool` decorator.
2. You add the module path to the `tools.enabled` list in `config.yaml`.
3. The gateway loads the tools on startup and makes them available to the LLM.

The LLM decides when to call a tool based on the user's prompt and the tool's description.

## Writing a Tool — Step by Step

### 1. Create a Python file

```python
# my_tools/calculator.py

from pydantic import BaseModel, Field
from copilot.tools import define_tool


class CalculateParams(BaseModel):
    """Parameters for the calculator tool."""
    expression: str = Field(description="A mathematical expression to evaluate, e.g. '2 + 3 * 4'")


@define_tool(description="Evaluate a mathematical expression. Use this when the user asks you to calculate something.")
async def calculate(params: CalculateParams) -> dict:
    """Evaluate a math expression safely."""
    # Only allow safe characters
    allowed = set("0123456789+-*/.() ")
    if not all(c in allowed for c in params.expression):
        return {"error": "Invalid characters in expression"}

    try:
        result = eval(params.expression)  # safe due to character whitelist above
        return {"expression": params.expression, "result": result}
    except Exception as e:
        return {"error": str(e)}
```

### 2. Key Rules

- **Use `@define_tool`** from `copilot.tools` — this is the Copilot SDK's decorator.
- **Use a Pydantic model** for parameters — each field must have a `description` so the LLM knows what to pass.
- **The function must be `async`** — use `asyncio.to_thread()` for blocking I/O.
- **Return a `dict`** — this is serialized and sent back to the LLM as the tool result.
- **Write a good `description`** in `@define_tool()` — this is what the LLM reads to decide when to use the tool.

### 3. Register the tool

Add the module path to `config.yaml`:

```yaml
tools:
  enabled:
    - copilot_gateway.tools.builtins.get_time
    - copilot_gateway.tools.builtins.web_search
    - my_tools.calculator   # ← your custom tool
```

### 4. Make it available to the container

Mount your tools directory into the container and ensure it's on the Python path:

```yaml
# docker-compose.yml
services:
  copilot-gateway:
    image: copilot-gateway:latest
    volumes:
      - ./config.yaml:/config/config.yaml:ro
      - ./my_tools:/custom-tools/my_tools:ro  # ← mount here
    environment:
      - COPILOT_GITHUB_TOKEN=${COPILOT_GITHUB_TOKEN}
```

The Dockerfile adds `/custom-tools` to `PYTHONPATH` automatically, so `my_tools.calculator` is importable.

## Alternative: Using a TOOLS List

Instead of `@define_tool`, you can export a `TOOLS` list with manually constructed `Tool` objects:

```python
# my_tools/lookup.py

from copilot.tools import Tool, ToolInvocation, ToolResult


async def lookup_handler(invocation: ToolInvocation) -> ToolResult:
    item_id = invocation.arguments["id"]
    # ... your lookup logic ...
    return ToolResult(
        text_result_for_llm=f"Item {item_id}: some data here",
        result_type="success",
    )


TOOLS = [
    Tool(
        name="lookup_item",
        description="Look up an item by its ID",
        parameters={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "The item ID to look up"},
            },
            "required": ["id"],
        },
        handler=lookup_handler,
    ),
]
```

This approach gives you more control over the JSON schema but is more verbose.

## Built-in Tools Reference

### `copilot_gateway.tools.builtins.get_time`

Returns the current date and time.

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `timezone_name` | string | `"UTC"` | Timezone name (e.g., `US/Eastern`, `Europe/London`) |

**Returns:**
```json
{
  "datetime": "2026-05-09T14:30:00+00:00",
  "timezone": "UTC",
  "date": "2026-05-09",
  "time": "14:30:00",
  "day_of_week": "Saturday"
}
```

### `copilot_gateway.tools.builtins.web_search`

Searches the web using DuckDuckGo (no API key required).

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `query` | string | *(required)* | Search query |
| `max_results` | int | `5` | Max results (1–10) |

**Returns:**
```json
{
  "query": "latest Python release",
  "results": [
    {"title": "...", "url": "...", "snippet": "..."}
  ],
  "result_count": 5
}
```

## Tips

- **Keep tool descriptions clear and specific.** The LLM uses the description to decide when to call the tool.
- **Validate inputs.** Don't trust the LLM to always pass valid data.
- **Return structured data.** Dicts with clear keys help the LLM interpret results.
- **Use `asyncio.to_thread()` for blocking calls** (HTTP requests, file I/O, etc.) to avoid blocking the event loop.
- **Test tools locally** before deploying — you can run the gateway locally with `uvicorn` and try them out.
