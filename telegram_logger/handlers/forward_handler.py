import logging
from typing import Optional
from telethon import events
from telegram_logger.handlers.base_handler import BaseHandler
from telegram_logger.utils.mentions import create_mention
from telegram_logger.data.models import Message
from telegram_logger.utils.media import save_media_as_file, retrieve_media_as_file
from telegram_logger.config import LOG_CHAT_ID

logger = logging.getLogger(__name__)

class ForwardHandler(BaseHandler):
    def __init__(self, client, db, log_chat_id, ignored_ids, forward_user_ids):
        super().__init__(client, db, log_chat_id, ignored_ids)
        self.forward_user_ids = forward_user_ids or []

    async def process(self, event: events.NewMessage.Event) -> Optional[Message]:
        """处理转发消息"""
        from_id = self._get_sender_id(event.message)
        if from_id not in self.forward_user_ids:
            return None

        try:
            # 创建消息内容
            mention_sender = await create_mention(self.client, from_id)
            mention_chat = await create_mention(self.client, event.chat_id, event.message.id)
            
            text = f"**📨转发消息来自: **{mention_sender}\n"
            text += f"在 {mention_chat}\n"
            
            if event.message.text:
                text += "**消息内容:** \n" + event.message.text

            # 处理媒体消息
            if event.message.media:
                await self._handle_media_message(event, text)
            else:
                await self.client.send_message(LOG_CHAT_ID, text)

            return await self._create_message_object(event)
            
        except Exception as e:
            logger.error(f"转发消息失败: {str(e)}")
            return None

    async def _handle_media_message(self, event, text):
        """处理包含媒体的消息"""
        noforwards = getattr(event.chat, 'noforwards', False) or \
                    getattr(event.message, 'noforwards', False)
        
        if noforwards:
            await save_media_as_file(self.client, event.message)
            with retrieve_media_as_file(
                event.message.id, 
                event.chat_id, 
                event.message.media, 
                noforwards
            ) as media_file:
                await self.client.send_message(LOG_CHAT_ID, text, file=media_file)
        else:
            await self.client.send_message(LOG_CHAT_ID, text, file=event.message.media)

    async def _create_message_object(self, event):
        """创建消息对象"""
        # 实现类似NewMessageHandler中的消息对象创建逻辑
        pass
