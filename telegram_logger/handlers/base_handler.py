import logging
from typing import Optional, Union
from telethon import events
from telethon.tl.types import PeerUser, PeerChannel
from telegram_logger.data.models import Message
from telegram_logger.data.database import DatabaseManager

logger = logging.getLogger(__name__)

class BaseHandler:
    def __init__(self, client, db: DatabaseManager):
        self.client = client
        self.db = db
        self.my_id = None  # 将在init中设置

    async def init(self):
        """初始化处理器"""
        me = await self.client.get_me()
        self.my_id = me.id
        logger.info(f"{self.__class__.__name__} initialized")

    async def process(self, event: events.Event) -> Optional[Union[Message, list]]:
        """处理事件并返回消息对象或列表"""
        raise NotImplementedError

    async def save_message(self, message: Message):
        """保存消息到数据库"""
        try:
            self.db.save_message(message)
            logger.debug(f"Message saved: {message.id}")
        except Exception as e:
            logger.error(f"Failed to save message: {str(e)}")

    def _get_sender_id(self, message):
        """从消息对象获取发送者ID"""
        if isinstance(message.peer_id, PeerUser):
            return self.my_id if message.out else message.peer_id.user_id
        elif isinstance(message.peer_id, PeerChannel):
            if isinstance(message.from_id, PeerUser):
                return message.from_id.user_id
            return message.from_id.channel_id if hasattr(message.from_id, 'channel_id') else 0
        return 0
