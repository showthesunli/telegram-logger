import logging
from typing import List, Union
from telethon import events
from telegram_logger.handlers.base_handler import BaseHandler
from telegram_logger.utils.mentions import create_mention
from telegram_logger.data.models import Message
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
import logging
import re
from typing import List, Optional, Union
from telethon import events
from telethon.tl.types import *
from telegram_logger.handlers.base_handler import BaseHandler
from telegram_logger.data.models import Message
from telegram_logger.config import (
    LOG_CHAT_ID,
    IGNORED_IDS,
    SAVE_EDITED_MESSAGES,
    DELETE_SENT_GIFS_FROM_SAVED,
    DELETE_SENT_STICKERS_FROM_SAVED,
    RATE_LIMIT_NUM_MESSAGES
)

logger = logging.getLogger(__name__)

class EditDeleteHandler(BaseHandler):
    """Handler for edited and deleted messages"""
    
    async def process(
        self, 
        event: Union[events.MessageEdited.Event, events.MessageDeleted.Event]
    ) -> List[Message]:
        """Process message edit or delete event"""
        if isinstance(event, events.MessageEdited.Event) and not SAVE_EDITED_MESSAGES:
            return []

        message_ids = self._get_message_ids(event)
        messages = self.db.get_messages(
            chat_id=event.chat_id,
            message_ids=message_ids
        )
        
        valid_messages = [
            msg for msg in messages 
            if not (msg.from_id in IGNORED_IDS or 
                   msg.chat_id in IGNORED_IDS or
                   msg.msg_type == self.MSG_TYPE_MAP['bot'])
        ]

        for message in valid_messages:
            await self._log_message(event, message)
            await self._handle_special_media(message)

        return valid_messages

    def _get_message_ids(self, event):
        """Get message IDs from event"""
        if isinstance(event, events.MessageDeleted.Event):
            return event.deleted_ids[:RATE_LIMIT_NUM_MESSAGES]
        return [event.message.id]

    async def _log_message(self, event, message: Message):
        """Log the message edit/delete event"""
        event_type = "deleted" if isinstance(event, events.MessageDeleted.Event) else "edited"
        mention_sender = await create_mention(self.client, message.from_id)
        mention_chat = await create_mention(self.client, message.chat_id, message.id)

        text = self._build_message_text(event_type, message, mention_sender, mention_chat)
        if isinstance(event, events.MessageEdited.Event):
            text += f"\n\n**Edited message:**\n{event.message.text}"

        media = pickle.loads(message.media) if message.media else None
        await self._send_appropriate_message(text, media, message)

    def _build_message_text(self, event_type: str, message: Message, 
                          mention_sender: str, mention_chat: str) -> str:
        """Build the base message text"""
        text = f"**{'Deleted' if event_type == 'deleted' else '✏Edited'} message from: **{mention_sender}\n"
        text += f"in {mention_chat}\n"
        if message.msg_text:
            text += f"**{'Message' if event_type == 'deleted' else 'Original message'}:**\n{message.msg_text}"
        return text

    async def _send_appropriate_message(self, text: str, media, message: Message):
        """Send message with appropriate media handling"""
        is_restricted = message.noforwards or message.self_destructing
        with retrieve_media_as_file(
            self.client,
            message.id,
            message.chat_id,
            media,
            is_restricted
        ) as media_file:
            if media_file:
                await self.client.send_message(LOG_CHAT_ID, text, file=media_file)
            else:
                await self.client.send_message(LOG_CHAT_ID, text)

    async def _handle_special_media(self, message: Message):
        """Handle special media types (GIFs/stickers)"""
        if not message.media:
            return

        media = pickle.loads(message.media)
        if not hasattr(media, 'document'):
            return

        doc = media.document
        is_gif = any(
            isinstance(attr, DocumentAttributeAnimated) 
            for attr in doc.attributes
        )
        is_sticker = any(
            isinstance(attr, DocumentAttributeSticker)
            for attr in doc.attributes
        )

        if is_gif and DELETE_SENT_GIFS_FROM_SAVED:
            await self._delete_from_saved_gifs(doc)
        if is_sticker and DELETE_SENT_STICKERS_FROM_SAVED:
            await self._delete_from_saved_stickers(doc)

    async def _delete_from_saved_gifs(self, doc):
        """Delete GIF from saved items"""
        await self.client(
            SaveGifRequest(
                id=InputDocument(
                    id=doc.id,
                    access_hash=doc.access_hash,
                    file_reference=doc.file_reference,
                ),
                unsave=True,
            )
        )

    async def _delete_from_saved_stickers(self, doc):
        """Delete sticker from saved items"""
        await self.client(
            SaveRecentStickerRequest(
                id=InputDocument(
                    id=doc.id,
                    access_hash=doc.access_hash,
                    file_reference=doc.file_reference,
                ),
                unsave=True,
            )
        )
