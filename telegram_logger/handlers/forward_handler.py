import logging
import pickle
from datetime import datetime
from typing import Optional
from telethon import events
from telegram_logger.handlers.base_handler import BaseHandler
from telegram_logger.utils.mentions import create_mention
from telegram_logger.data.models import Message
from telegram_logger.utils.media import save_media_as_file, retrieve_media_as_file

logger = logging.getLogger(__name__)

class ForwardHandler(BaseHandler):
    def __init__(self, client, db, log_chat_id, ignored_ids, forward_user_ids=None, forward_group_ids=None):
        super().__init__(client, db, log_chat_id, ignored_ids)
        self.forward_user_ids = forward_user_ids or []
        self.forward_group_ids = forward_group_ids or []
        logger.info(f"ForwardHandler initialized with forward_user_ids: {self.forward_user_ids}")
        logger.info(f"ForwardHandler initialized with forward_group_ids: {self.forward_group_ids}")

    async def handle_new_message(self, event):
        """处理新消息事件，这个方法名与client.py中的注册方法匹配"""
        # 确保handler已初始化
        if not self.client:
            logger.error("Handler not initialized, client is None")
            return None
            
        from_id = self._get_sender_id(event.message)
        chat_id = event.chat_id
        logger.info(f"ForwardHandler received message from user {from_id} in chat {chat_id}")
        return await self.process(event)

    async def process(self, event: events.NewMessage.Event) -> Optional[Message]:
        """处理转发消息"""
        from_id = self._get_sender_id(event.message)
        chat_id = event.chat_id
        
        # 检查是否来自目标用户或目标群组
        is_target_user = from_id in self.forward_user_ids
        is_target_group = chat_id in self.forward_group_ids
        
        logger.info(f"处理消息 - 用户ID: {from_id}, 聊天ID: {chat_id}, 是目标用户: {is_target_user}, 是目标群组: {is_target_group}")
        
        if not (is_target_user or is_target_group):
            logger.debug(f"消息不是来自目标用户或群组，跳过")
            return None

        try:
            # 创建消息内容
            mention_sender = await create_mention(self.client, from_id)
            mention_chat = await create_mention(self.client, event.chat_id, event.message.id)
            
            # 根据来源构建不同的消息前缀
            if is_target_user:
                text = f"**📨转发用户消息来自: **{mention_sender}\n"
            else:
                text = f"**📨转发群组消息来自: **{mention_sender}\n"
                
            text += f"在 {mention_chat}\n"
            
            if event.message.text:
                text += "**消息内容:** \n" + event.message.text

            # 处理媒体消息
            if event.message.media:
                await self._handle_media_message(event.message, text)
            else:
                await self.client.send_message(self.log_chat_id, text)

            message = await self._create_message_object(event)
            await self.save_message(message)
            return message
            
        except Exception as e:
            logger.error(f"转发消息失败: {str(e)}", exc_info=True)
            return None

    async def _handle_media_message(self, message, text):
        """处理包含媒体的消息"""
        noforwards = False
        try:
            noforwards = getattr(message.chat, 'noforwards', False) or \
                        getattr(message, 'noforwards', False)
        except AttributeError:
            pass
        
        if noforwards:
            file_path = await save_media_as_file(self.client, message)
            if file_path:
                with retrieve_media_as_file(file_path, True) as media_file:
                    await self.client.send_message(self.log_chat_id, text, file=media_file)
            else:
                await self.client.send_message(self.log_chat_id, text)
        else:
            await self.client.send_message(self.log_chat_id, text, file=message.media)

    async def _create_message_object(self, event):
        """创建消息对象"""
        from_id = self._get_sender_id(event.message)
        noforwards = False
        try:
            noforwards = getattr(event.chat, 'noforwards', False) or \
                        getattr(event.message, 'noforwards', False)
        except AttributeError:
            pass
            
        self_destructing = False
        try:
            self_destructing = bool(getattr(getattr(event.message, 'media', None), 'ttl_seconds', False))
        except AttributeError:
            pass
        
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
            msg_type=await self.get_chat_type(event),
            media=media,
            noforwards=noforwards,
            self_destructing=self_destructing,
            created_time=datetime.now(),
            edited_time=None,
            msg_text=event.message.message
        )
        
    async def get_chat_type(self, event):
        """获取消息类型"""
        if event.is_group:  # chats and megagroups
            return 2  # group
        elif event.is_channel:  # megagroups and channels
            return 3  # channel
        elif event.is_private:
            if (await event.get_sender()).bot:
                return 4  # bot
            return 1  # user
        return 0  # unknown type
