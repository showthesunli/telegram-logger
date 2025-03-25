import time
from telethon import TelegramClient, events
from typing import List, Optional
import logging
from telegram_logger.handlers.base_handler import BaseHandler

logger = logging.getLogger(__name__)

class TelegramClientService:
    def __init__(
        self,
        session_name: str,
        api_id: int,
        api_hash: str,
        handlers: List[BaseHandler],
        log_chat_id: int
    ):
        self.client = TelegramClient(session_name, api_id, api_hash)
        self.handlers = handlers
        self.log_chat_id = log_chat_id
        self._is_initialized = False
        self._start_time = time.time()
        self._last_error = None

    async def initialize(self) -> int:
        """Initialize client and return current user ID"""
        if not self._is_initialized:
            await self.client.start()
            self._register_handlers()
            self._is_initialized = True
            me = await self.client.get_me()
            logger.info(f"Client initialized for user {me.id}")
            return me.id
        return 0

    def _register_handlers(self):
        """Register all event handlers"""
        for handler in self.handlers:
            if hasattr(handler, 'handle_new_message'):
                self.client.add_event_handler(
                    handler.handle_new_message,
                    events.NewMessage()
                )
            if hasattr(handler, 'handle_message_edited'):
                self.client.add_event_handler(
                    handler.handle_message_edited,
                    events.MessageEdited()
                )
            if hasattr(handler, 'handle_message_deleted'):
                self.client.add_event_handler(
                    handler.handle_message_deleted,
                    events.MessageDeleted()
                )

    async def run(self):
        """Run client until disconnected"""
        await self.client.run_until_disconnected()
