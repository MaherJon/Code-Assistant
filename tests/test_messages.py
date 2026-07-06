"""Tests for the message system and memory."""

import pytest

from mahe.core.message import Message, MessageRole, MessageHistory
from mahe.context.memory import SessionMemory


class TestMessage:
    """Tests for Message dataclass."""

    def test_system_message(self):
        msg = Message.system("You are a helpful assistant.")
        assert msg.role == MessageRole.SYSTEM
        assert msg.content == "You are a helpful assistant."
        assert msg.tool_call_id is None
        assert msg.tool_calls is None

    def test_user_message(self):
        msg = Message.user("Hello!")
        assert msg.role == MessageRole.USER
        assert msg.content == "Hello!"

    def test_assistant_message(self):
        msg = Message.assistant("Hi there!")
        assert msg.role == MessageRole.ASSISTANT
        assert msg.content == "Hi there!"

    def test_assistant_with_tool_calls(self):
        tool_calls = [{"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"test.py"}'}}]
        msg = Message.assistant("Let me read that.", tool_calls)
        assert msg.tool_calls == tool_calls

    def test_tool_result_message(self):
        msg = Message.tool_result("call_1", "file contents here", tool_name="read_file")
        assert msg.role == MessageRole.TOOL
        assert msg.tool_call_id == "call_1"
        assert msg.content == "file contents here"

    def test_to_dict(self):
        msg = Message.user("test")
        d = msg.to_dict()
        assert d == {"role": "user", "content": "test"}

    def test_to_dict_with_tool_call(self):
        msg = Message.tool_result("call_x", "result")
        d = msg.to_dict()
        assert d["role"] == "tool"
        assert d["tool_call_id"] == "call_x"


class TestMessageHistory:
    """Tests for MessageHistory."""

    def test_add_and_retrieve(self):
        history = MessageHistory()
        history.add(Message.system("system"))
        history.add(Message.user("user"))
        history.add(Message.assistant("assistant"))

        assert len(history.get_all()) == 3
        assert history.get_recent(2)[0].content == "user"

    def test_to_dict_list(self):
        history = MessageHistory()
        history.add(Message.user("hello"))
        history.add(Message.assistant("hi"))

        result = history.to_dict_list()
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"

    def test_trim_preserves_system(self):
        history = MessageHistory(max_tokens=1000)
        history.add(Message.system("system"))
        # Add many messages to force trim
        for i in range(100):
            history.add(Message.user(f"message {i}" * 50))

        history.trim_to_fit(500)
        messages = history.get_all()
        # System message should be preserved
        assert any(m.role == MessageRole.SYSTEM for m in messages)

    def test_clear_keeps_system(self):
        history = MessageHistory()
        history.add(Message.system("system"))
        history.add(Message.user("user"))

        history.clear(keep_system=True)
        messages = history.get_all()
        assert len(messages) == 1
        assert messages[0].role == MessageRole.SYSTEM

    def test_clear_all(self):
        history = MessageHistory()
        history.add(Message.system("system"))
        history.add(Message.user("user"))

        history.clear(keep_system=False)
        assert len(history.get_all()) == 0


class TestSessionMemory:
    """Tests for SessionMemory."""

    def test_init_with_system_prompt(self):
        memory = SessionMemory(system_prompt="You are MAHE.")
        messages = memory.get_messages_for_llm()
        assert len(messages) == 1
        assert messages[0]["role"] == "system"
        assert "MAHE" in messages[0]["content"]

    def test_add_messages(self):
        memory = SessionMemory(system_prompt="system")
        memory.add_user_message("user query")
        memory.add_assistant_message("assistant response")

        messages = memory.get_messages_for_llm()
        assert len(messages) == 3
        assert messages[1]["role"] == "user"
        assert messages[2]["role"] == "assistant"

    def test_add_tool_result(self):
        memory = SessionMemory(system_prompt="system")
        memory.add_user_message("read file")
        memory.add_assistant_message("reading...", tool_calls=[
            {"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
        ])
        memory.add_tool_result("call_1", "file contents")

        messages = memory.get_messages_for_llm()
        assert len(messages) == 4
        assert messages[3]["role"] == "tool"
        assert messages[3]["tool_call_id"] == "call_1"

    def test_clear(self):
        memory = SessionMemory(system_prompt="system")
        memory.add_user_message("user query")
        memory.clear()

        messages = memory.get_messages_for_llm()
        assert len(messages) == 1  # Only system remains

    def test_reset(self):
        memory = SessionMemory(system_prompt="old")
        memory.add_user_message("query")
        memory.reset(new_system_prompt="new system")

        messages = memory.get_messages_for_llm()
        assert len(messages) == 1
        assert "new system" in messages[0]["content"]
