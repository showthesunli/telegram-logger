import logging
import re
import pickle
from datetime import datetime
from typing import Union
from telethon import events
from telethon.tl.types import Message
from telegram_logger.handlers.base_handler import BaseHandler
from telegram_logger.utils.media import save_media_as_file
from telegram_logger.config import LOG_CHAT_ID, IGNORED_IDS

logger = logging.getLogger(__name__)

class NewMessageHandler(BaseHandler):
    def __init__(self, client, db, log_chat_id, ignored_ids, persist_times):
        super().__init__(client, db, log_chat_id, ignored_ids)
        self.persist_times = persist_times

    async def process(self, event: Union[events.NewMessage.Event, events.MessageEdited.Event]) -> Optional[Message]:
        """处理新消息和编辑消息"""
        chat_id = event.chat_id
        from_id = self._get_sender_id(event.message)
        msg_id = event.message.id

        if await self._should_ignore_message(event, chat_id, from_id):
            return None

        message = await self._create_message_object(event)
        await self.db.save_message(message)
        return message

    async def _should_ignore_message(self, event, chat_id, from_id) -> bool:
        """判断是否应该忽略消息"""
        if await self._is_special_link_message(event, chat_id, from_id):
            return True
        return from_id in IGNORED_IDS or chat_id in IGNORED_IDS

    async def _is_special_link_message(self, event, chat_id, from_id) -> bool:
        """处理特殊消息链接"""
        if (chat_id == LOG_CHAT_ID and from_id == self.my_id and event.message.text and
            (re.match(r"^(https:\/\/)?t\.me\/(?:c\/)?[\d\w]+\/[\d]+", event.message.text) or
             re.match(r"^tg:\/\/openmessage\?user_id=\d+&message_id=\d+", event.message.text))):
            await self._save_restricted_messages(event.message.text)
            return True
        return False

    async def _create_message_object(self, event) -> Message:
        """创建消息对象"""
        noforwards = getattr(event.chat, 'noforwards', False) or getattr(event.message, 'noforwards', False)
        self_destructing = bool(getattr(getattr(event.message, 'media', None), 'ttl_seconds', False))

        media = None
        if event.message.media or (noforwards or self_destructing):
            try:
                media_path = await save_media_as_file(self.client, event.message)
                media = pickle.dumps(event.message.media)
            except Exception as e:
                logger.error(f"保存媒体失败: {str(e)}")

        return Message(
            id=event.message.id,
            from_id=self._get_sender_id(event.message),
            chat_id=event.chat_id,
            msg_type=await self._get_chat_type(event),
            msg_text=event.message.message,
            media=media,
            noforwards=noforwards,
            self_destructing=self_destructing,
            created_time=datetime.now(),
            edited_time=datetime.now() if isinstance(event, events.MessageEdited.Event) else None
        )

    async def _save_restricted_messages(self, link: str):
        """保存受限消息"""
        # 实现类似原save_restricted_msg的功能
        pass
