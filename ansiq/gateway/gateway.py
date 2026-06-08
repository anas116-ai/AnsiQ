"""Messaging Gateway — connect AnsiQ to Telegram, Discord, and Slack.

Enables agents to communicate across platforms and interact with users
through their preferred messaging channels.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class Message(BaseModel):
    """Universal message format across all platforms."""

    text: str
    sender: str
    chat_id: str
    platform: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class BaseGateway(ABC):
    """Abstract base for all messaging gateways."""

    def __init__(self, token: str, agent=None):
        self.token = token
        self.agent = agent
        self._handlers: list[Callable] = []
        self._running = False

    def on_message(self, handler: Callable) -> None:
        """Register a message handler."""
        self._handlers.append(handler)

    async def _process_message(self, message: Message) -> None:
        """Process incoming message through all handlers."""
        for handler in self._handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(message)
                else:
                    handler(message)
            except Exception as e:
                logger.error("Handler error: %s", e)

    @abstractmethod
    async def start(self) -> None:
        """Start the gateway."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the gateway."""
        ...

    @abstractmethod
    async def send_message(self, chat_id: str, text: str) -> None:
        """Send a message to a chat."""
        ...


class TelegramGateway(BaseGateway):
    """Telegram Bot API gateway."""

    def __init__(self, token: str, agent=None):
        super().__init__(token, agent)
        self._application = None

    async def start(self) -> None:
        try:
            from telegram.ext import Application, CommandHandler, MessageHandler, filters
        except ImportError:
            logger.error(
                "python-telegram-bot not installed. Install: pip install 'ansiq[telegram]'"
            )
            return

        self._application = Application.builder().token(self.token).build()

        async def handle_message(update, context):
            if update.message and update.message.text:
                msg = Message(
                    text=update.message.text,
                    sender=update.message.from_user.username or "unknown",
                    chat_id=str(update.effective_chat.id),
                    platform="telegram",
                )
                await self._process_message(msg)

                if self.agent:
                    response = await self.agent.chat(update.message.text)
                    await update.message.reply_text(response.content)

        self._application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
        )
        logger.info("Telegram gateway started")
        await self._application.initialize()
        await self._application.start()
        await self._application.updater.start_polling()

    async def stop(self) -> None:
        if self._application:
            await self._application.stop()
            await self._application.shutdown()

    async def send_message(self, chat_id: str, text: str) -> None:
        if self._application:
            await self._application.bot.send_message(chat_id=chat_id, text=text)


class DiscordGateway(BaseGateway):
    """Discord Bot gateway."""

    def __init__(self, token: str, agent=None):
        super().__init__(token, agent)
        self._client = None

    async def start(self) -> None:
        try:
            import discord
        except ImportError:
            logger.error("discord.py not installed. Install: pip install 'ansiq[discord]'")
            return

        intents = discord.Intents.default()
        intents.message_content = True

        class AnsiQClient(discord.Client):
            async def on_ready(self):
                logger.info("Discord gateway started as %s", self.user)

            async def on_message(self, message):
                if message.author == self.user:
                    return
                msg = Message(
                    text=message.content,
                    sender=str(message.author),
                    chat_id=str(message.channel.id),
                    platform="discord",
                )
                await self.gateway._process_message(msg)
                if self.gateway.agent:
                    response = await self.gateway.agent.chat(message.content)
                    await message.channel.send(response.content)

        client = AnsiQClient(intents=intents)
        client.gateway = self
        self._client = client
        await client.start(self.token)

    async def stop(self) -> None:
        if self._client:
            await self._client.close()

    async def send_message(self, chat_id: str, text: str) -> None:
        if self._client:
            channel = self._client.get_channel(int(chat_id))
            if channel:
                await channel.send(text)


class SlackGateway(BaseGateway):
    """Slack Bot gateway."""

    def __init__(self, token: str, agent=None, signing_secret: str = ""):
        super().__init__(token, agent)
        self.signing_secret = signing_secret
        self._client = None

    async def start(self) -> None:
        try:
            from slack_sdk.rtm import RTMClient
        except ImportError:
            logger.error("slack-sdk not installed. Install: pip install 'ansiq[slack]'")
            return

        @RTMClient.run_on(event="message")
        async def on_message(**payload):
            data = payload.get("data", {})
            text = data.get("text", "")
            if not text or data.get("bot_id"):
                return

            msg = Message(
                text=text,
                sender=data.get("user", "unknown"),
                chat_id=data.get("channel", ""),
                platform="slack",
            )
            await self._process_message(msg)
            if self.agent:
                response = await self.agent.chat(text)
                await self.send_message(msg.chat_id, response.content)

        self._client = RTMClient(token=self.token)
        self._client.on_message = on_message
        logger.info("Slack gateway started")
        asyncio.create_task(self._client.start())

    async def stop(self) -> None:
        if self._client:
            await self._client.stop()

    async def send_message(self, chat_id: str, text: str) -> None:
        try:
            from slack_sdk.web import WebClient

            client = WebClient(token=self.token)
            await asyncio.to_thread(
                client.chat_postMessage,
                channel=chat_id,
                text=text,
            )
        except Exception as e:
            logger.error("Slack send error: %s", e)
