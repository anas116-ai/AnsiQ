"""Tests for the messaging gateway system."""

from __future__ import annotations

import pytest

from ansiq.gateway import BaseGateway, Message


class TestMessage:
    def test_create_basic_message(self):
        """Test creating a basic message."""
        msg = Message(
            text="Hello, world!",
            sender="user_1",
            chat_id="chat_123",
            platform="telegram",
        )
        assert msg.text == "Hello, world!"
        assert msg.sender == "user_1"
        assert msg.chat_id == "chat_123"
        assert msg.platform == "telegram"

    def test_message_with_metadata(self):
        """Test creating a message with metadata."""
        msg = Message(
            text="Data message",
            sender="bot_1",
            chat_id="channel_456",
            platform="discord",
            metadata={"message_type": "command", "timestamp": "2026-01-01"},
        )
        assert msg.metadata["message_type"] == "command"

    def test_message_default_metadata(self):
        """Test message default metadata is empty dict."""
        msg = Message(
            text="Test",
            sender="user",
            chat_id="chat",
            platform="slack",
        )
        assert msg.metadata == {}


class TestBaseGateway:
    def test_cannot_instantiate_abstract(self):
        """Test that BaseGateway cannot be directly instantiated."""

        class MinimalGateway(BaseGateway):
            async def start(self):
                pass

            async def stop(self):
                pass

            async def send_message(self, chat_id, text):
                pass

        # Should not raise
        gateway = MinimalGateway(token="test_token")
        assert gateway.token == "test_token"

    def test_abstract_methods(self):
        """Test that abstract methods must be implemented."""
        with pytest.raises(TypeError):
            BaseGateway(token="test")  # type: ignore

    def test_on_message_handler(self):
        """Test registering a message handler."""
        class TestGateway(BaseGateway):
            async def start(self):
                pass
            async def stop(self):
                pass
            async def send_message(self, chat_id, text):
                pass

        gateway = TestGateway(token="test")

        async def my_handler(msg):
            pass

        gateway.on_message(my_handler)
        assert len(gateway._handlers) == 1
