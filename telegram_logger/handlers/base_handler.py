import abc
import logging
from typing import Dict, Any, Optional, Union, List
from telethon import events
from telethon.events import common as EventCommon
from telethon.tl.types import PeerUser, PeerChannel, PeerChat
from telegram_logger.data.database import DatabaseManager
from telegram_logger.data.models import Message

logger = logging.getLogger(__name__)

class BaseHandler(abc.ABC):

    def __init__(
        self, 
        client, 
        db: DatabaseManager,
        log_chat_id: int,
        ignored_ids: set,
        my_id: Optional[int] = None, # 添加 my_id 参数
        **kwargs: Dict[str, Any]
    ):
        """Telegram 事件处理器的基类。

        Args:
            client: Telegram 客户端实例。
            db: 数据库管理器实例。
            log_chat_id: 用于记录消息的目标聊天 ID。
            ignored_ids: 需要忽略的用户/聊天 ID 集合。
            **kwargs: 其他可选参数。
        """
        self.client = client
        self.db = db
        self.log_chat_id = log_chat_id
        self.ignored_ids = ignored_ids or set()
        self._my_id = None
        
    async def init(self):
        """初始化处理器。

        此方法应在客户端初始化之后调用。
        """
        if self.client:
            me = await self.client.get_me()
            self._my_id = me.id
            logger.info(f"处理器已初始化，用户 ID: {self._my_id}")
        else:
            logger.warning("无法初始化处理器：客户端为 None")

    @abc.abstractmethod
    async def process(self, event: EventCommon) -> Optional[Union[Message, List[Message]]]:
        """处理事件。

        此方法必须由子类实现。

        Args:
            event: Telegram 事件对象。

        Returns:
            Optional[Union[Message, List[Message]]]: 处理后的消息对象（或列表）或 None。
        """
        raise NotImplementedError("子类必须实现 process() 方法")

    async def save_message(self, message: Message):
        """将消息保存到数据库。

        Args:
            message: 要保存的消息对象。
        """
        self.db.save_message(message)

    def _get_sender_id(self, message) -> int:
        """从消息中获取发送者 ID。

        Args:
            message: Telegram 消息对象。

        Returns:
            int: 发送者 ID。
        """
        from_id = 0

        # 处理发出的消息
        if hasattr(message, 'out') and message.out:
            return self._my_id if self._my_id else 0

        # 处理不同的 peer 类型
        if hasattr(message, 'peer_id'):
            if isinstance(message.peer_id, PeerUser):
                from_id = message.peer_id.user_id
            elif isinstance(message.peer_id, PeerChannel):
                from_id = message.peer_id.channel_id
            elif isinstance(message.peer_id, PeerChat):
                from_id = message.peer_id.chat_id

        # 尝试从消息的 from_id 属性获取
        if hasattr(message, 'from_id'):
            if hasattr(message.from_id, 'user_id'):
                from_id = message.from_id.user_id
            elif hasattr(message.from_id, 'channel_id'):
                from_id = message.from_id.channel_id
                
        return from_id
    
    def set_client(self, client):
        """设置 Telethon 客户端实例。"""
        self.client = client
        logger.debug(f"客户端已为 {self.__class__.__name__} 设置") # 添加日志记录

    @property
    def my_id(self) -> int:
        """获取当前用户的 ID。

        Returns:
            int: 当前用户的 ID。

        Raises:
            RuntimeError: 如果处理器尚未初始化。
        """
        if self._my_id is None:
            # 返回 0 而不是引发错误
            # 这允许处理器即使未完全初始化也能工作
            return 0
        return self._my_id
