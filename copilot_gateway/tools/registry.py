"""Tool registry — discovers and loads tool modules from config."""

from __future__ import annotations

import importlib
import logging

logger = logging.getLogger(__name__)


def load_tools(module_paths: list[str]) -> list:
    """Import each module in module_paths and collect tool definitions.

    Each tool module should either:
    1. Have a top-level TOOLS list of Copilot SDK Tool objects, or
    2. Use the @define_tool decorator (tools are collected automatically).

    Returns a flat list of all tools from all modules.
    """
    all_tools: list = []

    for module_path in module_paths:
        try:
            mod = importlib.import_module(module_path)
        except ImportError:
            logger.error("Failed to import tool module: %s", module_path)
            continue

        # Strategy 1: module has a TOOLS list
        if hasattr(mod, "TOOLS") and isinstance(mod.TOOLS, list):
            count = len(mod.TOOLS)
            all_tools.extend(mod.TOOLS)
            logger.info("Loaded %d tool(s) from %s (via TOOLS list)", count, module_path)
            continue

        # Strategy 2: scan module attributes for objects that look like tools
        # (i.e., have a 'name' and 'handler' attribute, or are decorated with @define_tool)
        found = 0
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if _is_tool(obj):
                all_tools.append(obj)
                found += 1

        if found > 0:
            logger.info("Loaded %d tool(s) from %s (via attribute scan)", found, module_path)
        else:
            logger.warning("No tools found in module: %s", module_path)

    return all_tools


def _is_tool(obj) -> bool:
    """Check if an object looks like a Copilot SDK tool.

    Copilot SDK tools created with @define_tool or Tool() have specific attributes.
    We check for common markers without importing the Tool class (to avoid
    circular imports or SDK version coupling).
    """
    if obj is None or isinstance(obj, type):
        return False
    # @define_tool decorated functions have _tool_metadata or similar markers
    # Tool() instances have 'name', 'description', 'handler' attributes
    has_name = hasattr(obj, "name") and isinstance(getattr(obj, "name", None), str)
    has_description = hasattr(obj, "description")
    has_handler = hasattr(obj, "handler") or callable(obj)
    return has_name and has_description and has_handler
