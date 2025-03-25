import logging
from typing import List, Union
from telethon import events
from telegram_logger.handlers.base_handler import BaseHandler
from telegram_logger.utils.mentions import create_mention
from telegram_logger.config import (
    LOG_CHAT_ID,
    IGNORED_IDS,
    SAVE_EDITED_MESSAGES,
    DELETE_SENT_GIFS_FROM_SAVED,
    DELETE_SENT_STICKERS_FROM_SAVED
)

logger = logging.getLogger(__name__)

class EditDeleteHandler(BaseHandler):
    async def process(
        self, 
        event: Union[events.MessageDeleted.Event, events.MessageEdited.Event]
    ) -> List[Message]:
        if isinstance(event, events.MessageEdited.Event) and not SAVE_EDITED_MESSAGES:
            return []

        message_ids = self._get_message_ids(event)
        messages = self.db.get_messages(
            chat_id=event.chat_id,
            message_ids=message_ids
        )
        
        for message in messages:
            if not self._should_process_message(message):
                continue
                
            await self._log_message(event, message)
            await self._handle_special_media(message)
        
        return messages

    def _get_message_ids(self, event):
        if isinstance(event, events.MessageDeleted.Event):
            return event.deleted_ids
        return [event.message.id]

    def _should_process_message(self, message):
        return not (message.from_id in IGNORED_IDS or 
                   message.chat_id in IGNORED_IDS or
                   message.msg_type == 4)  # 4是bot消息类型

    async def _log_message(self, event, message):
        """记录删除/编辑的消息"""
        event_type = "deleted" if isinstance(event, events.MessageDeleted.Event) else "edited"
        mention_sender = await create_mention(self.client, message.from_id)
        mention_chat = await create_mention(self.client, message.chat_id, message.id)

        text = f"**{'Deleted' if event_type == 'deleted' else '✏Edited'} message from: **{mention_sender}\n"
        text += f"in {mention_chat}\n"
        
        if message.msg_text:
            text += f"**{'Message' if event_type == 'deleted' else 'Original message'}:**\n{message.msg_text}"
        
        if isinstance(event, events.MessageEdited.Event) and event.message.text:
            text += f"\n\n**Edited message:**\n{event.message.text}"

        await self._send_log_message(message, text)

    async def _handle_special_media(self, message):
        """处理特殊媒体类型（GIF/贴纸）"""
        # 实现原有的GIF和贴纸处理逻辑
        pass
