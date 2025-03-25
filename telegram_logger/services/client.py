import time
from telethon import TelegramClient, events
from typing import List, Optional
import logging
from telegram_logger.handlers.base_handler import BaseHandler
from telegram_logger.handlers.forward_handler import ForwardHandler

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
            # 特殊处理 ForwardHandler
            if isinstance(handler, ForwardHandler):
                # 检查是否有用户ID需要转发
                if handler.forward_user_ids:
                    # 为每个转发用户ID单独注册处理器
                    for user_id in handler.forward_user_ids:
                        self.client.add_event_handler(
                            handler.handle_new_message,
                            events.NewMessage(from_users=user_id)
                        )
                    logger.info(f"Registered ForwardHandler for users: {handler.forward_user_ids}")
                
                # 检查是否有群组ID需要转发
                if handler.forward_group_ids:
                    # 为每个转发群组ID单独注册处理器
                    for group_id in handler.forward_group_ids:
                        self.client.add_event_handler(
                            handler.handle_new_message,
                            events.NewMessage(chats=group_id)
                        )
                    logger.info(f"Registered ForwardHandler for groups: {handler.forward_group_ids}")
                
                # 如果没有配置任何转发目标，记录警告
                if not (handler.forward_user_ids or handler.forward_group_ids):
                    logger.warning("ForwardHandler has empty forward_user_ids and forward_group_ids lists")
            else:
                # 处理其他类型的处理器
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

    async def health_check(self) -> dict:
        """检查服务健康状态
        
        返回:
            dict: 包含以下健康指标:
                - connected (bool): 是否连接服务器
                - handlers (int): 注册的事件处理器数量
                - logged_in (bool): 是否完成登录
                - uptime (float): 运行时间(秒)
                - last_error (str): 最后错误信息(如果有)
        """
        try:
            me = await self.client.get_me() if self._is_initialized else None
            return {
                'connected': await self.client.is_connected(),
                'handlers': len(self.client.list_event_handlers()),
                'logged_in': self._is_initialized,
                'user_id': me.id if me else None,
                'uptime': (time.time() - self._start_time) if hasattr(self, '_start_time') else 0,
                'last_error': getattr(self, '_last_error', None)
            }
        except Exception as e:
            self._last_error = str(e)
            return {
                'connected': False,
                'handlers': 0,
                'logged_in': False,
                'user_id': None,
                'uptime': 0,
                'last_error': str(e)
            }

    async def run(self):
        """Run client until disconnected"""
        await self.client.run_until_disconnected()
