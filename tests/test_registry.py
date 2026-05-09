"""Tests for the tool registry."""

from __future__ import annotations

from copilot_gateway.tools.registry import _is_tool


class TestIsTool:
    def test_none_rejected(self):
        assert _is_tool(None) is False

    def test_class_rejected(self):
        class Foo:
            name = "foo"
            description = "bar"
            handler = lambda: None
        assert _is_tool(Foo) is False

    def test_primitives_rejected(self):
        assert _is_tool(42) is False
        assert _is_tool("hello") is False
        assert _is_tool(True) is False

    def test_plain_function_rejected(self):
        def my_func():
            pass
        assert _is_tool(my_func) is False

    def test_tool_like_object_accepted(self):
        class FakeTool:
            name = "my_tool"
            description = "does stuff"
            handler = lambda self: None
        assert _is_tool(FakeTool()) is True

    def test_missing_handler_rejected(self):
        class NoHandler:
            name = "my_tool"
            description = "does stuff"
        assert _is_tool(NoHandler()) is False
