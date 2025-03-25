import logging
import pickle
from datetime import datetime
from typing import Optional, List
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
        logger.info(f"ForwardHandler initialized with forward_user_ids: {self.forward_user_ids}")

    async def handle_new_message(self, event):
        """处理新消息事件，这个方法名与client.py中的注册方法匹配"""
        from_id = self._get_sender_id(event.message)
        logger.info(f"ForwardHandler received message from user {from_id}")
        return await self.process(event)

    async def process(self, event: events.NewMessage.Event) -> Optional[Message]:
        """处理转发消息"""
        from_id = self._get_sender_id(event.message)
        logger.info(f"处理来自用户 {from_id} 的消息，转发目标用户列表: {self.forward_user_ids}")
        
        if from_id not in self.forward_user_ids:
            logger.debug(f"用户 {from_id} 不在转发列表中，跳过")
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
                await self._handle_media_message(event.message, text)
            else:
                await self.client.send_message(LOG_CHAT_ID, text)

            message = await self._create_message_object(event)
            await self.save_message(message)
            return message
            
        except Exception as e:
            logger.error(f"转发消息失败: {str(e)}", exc_info=True)
            return None

    async def _handle_media_message(self, message, text):
        """处理包含媒体的消息"""
        noforwards = getattr(message.chat, 'noforwards', False) or \
                    getattr(message, 'noforwards', False)
        
        if noforwards:
            await save_media_as_file(self.client, message)
            with retrieve_media_as_file(
                message.id, 
                message.chat_id, 
                message.media, 
                noforwards
            ) as media_file:
                await self.client.send_message(self.log_chat_id, text, file=media_file)
        else:
            await self.client.send_message(self.log_chat_id, text, file=message.media)

    async def _create_message_object(self, event):
        """创建消息对象"""
        from_id = self._get_sender_id(event.message)
        noforwards = getattr(event.chat, 'noforwards', False) or \
                    getattr(event.message, 'noforwards', False)
        self_destructing = bool(getattr(getattr(event.message, 'media', None), 'ttl_seconds', False))
        
        media = None
        if event.message.media:
            try:
                await save_media_as_file(self.client, event.message)
                media = pickle.dumps(event.message.media)
            except Exception as e:
                logger.error(f"保存媒体失败: {str(e)}")
        
        return Message(
            id=event.message.id,
            from_id=from_id,
            chat_id=event.chat_id,
            msg_type=await self._get_chat_type(event),
            msg_text=event.message.message,
            media=media,
            noforwards=noforwards,
            self_destructing=self_destructing,
            created_time=datetime.now(),
            edited_time=None
        )
