"""Built-in tool: get_time — returns the current date and time.

This file is a reference implementation showing how to write a custom tool
for copilot-gateway. You can use it as a template for your own tools.

HOW TO WRITE A CUSTOM TOOL
==========================

1. Create a Python file (e.g., my_tool.py).

2. Define a Pydantic model for the tool's parameters:

       from pydantic import BaseModel, Field

       class MyParams(BaseModel):
           query: str = Field(description="The search query")

3. Create the tool function using @define_tool:

       from copilot.tools import define_tool

       @define_tool(description="What this tool does")
       async def my_tool_name(params: MyParams) -> dict:
           result = do_something(params.query)
           return {"answer": result}

4. Add your module path to the config.yaml tools.enabled list:

       tools:
         enabled:
           - my_custom_tools.my_tool

5. Mount your tool file into the Docker container and ensure it's
   importable (e.g., mount to /custom-tools/ and add that to PYTHONPATH).

That's it! The gateway will load your tool on startup and make it available
to the LLM during conversations.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from copilot.tools import define_tool


class GetTimeParams(BaseModel):
    """Parameters for the get_time tool."""

    timezone_name: str = Field(
        default="UTC",
        description="Timezone name (e.g., 'UTC', 'US/Eastern', 'Europe/London'). Defaults to UTC.",
    )


@define_tool(description="Get the current date and time. Useful when the user asks what time or date it is.")
async def get_time(params: GetTimeParams) -> dict:
    """Return the current date and time."""
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(params.timezone_name)
    except (ImportError, KeyError):
        tz = timezone.utc

    now = datetime.now(tz=tz)
    return {
        "datetime": now.isoformat(),
        "timezone": str(tz),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "day_of_week": now.strftime("%A"),
    }
