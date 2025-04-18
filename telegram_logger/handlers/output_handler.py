import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional, Set, Union

from telethon import events
from telethon.errors import (ChannelPrivateError, ChatAdminRequiredError,
                             MessageIdInvalidError, UserIsBlockedError)
from telethon.tl.types import (DocumentAttributeFilename,
                               DocumentAttributeSticker, Message as TelethonMessage,
                               PeerChannel, PeerChat, PeerUser)

from ..data.database import DatabaseManager
from ..data.models import Message
from ..utils.media import retrieve_media_as_file
from ..utils.mentions import create_mention
from .base_handler import BaseHandler
from .log_sender import LogSender
from .media_handler import RestrictedMediaHandler
from .message_formatter import MessageFormatter

logger = logging.getLogger(__name__)

class OutputHandler(BaseHandler):
    """
    负责根据配置过滤事件、格式化消息、处理媒体并将其发送到日志频道的处理器。
    合并了原 EditDeleteHandler 和 ForwardHandler 的输出相关功能。
    监听 NewMessage, MessageEdited, MessageDeleted 事件。
    """

    def __init__(
        self,
        db: DatabaseManager,
        log_chat_id: int,
        ignored_ids: Set[int],
        forward_user_ids: Optional[List[int]] = None,
        forward_group_ids: Optional[List[int]] = None,
        deletion_rate_limit_threshold: int = 5,
        deletion_rate_limit_window: int = 10,   # 单位：秒
        deletion_pause_duration: int = 5,       # 单位：秒
        **kwargs: Dict[str, Any]
    ):
        """初始化 OutputHandler。"""
        super().__init__(None, db, log_chat_id, ignored_ids, **kwargs)
        self.forward_user_ids = set(forward_user_ids) if forward_user_ids else set()
        self.forward_group_ids = set(forward_group_ids) if forward_group_ids else set()

        # 删除事件的速率限制配置
        self.deletion_rate_limit_threshold = deletion_rate_limit_threshold
        self.deletion_rate_limit_window = timedelta(seconds=deletion_rate_limit_window)
        self.deletion_pause_duration = timedelta(seconds=deletion_pause_duration)
        self._deletion_timestamps: Deque[datetime] = deque()
        self._rate_limit_paused_until: Optional[datetime] = None

        # 辅助类的占位符，将在 set_client 中初始化
        self.log_sender: Optional[LogSender] = None
        self.formatter: Optional[MessageFormatter] = None
        self.restricted_media_handler: Optional[RestrictedMediaHandler] = None

        logger.info(
            f"OutputHandler 初始化完毕。转发用户: {self.forward_user_ids}, "
            f"群组: {self.forward_group_ids}, 忽略 ID: {self.ignored_ids}, "
            f"删除速率限制: {self.deletion_rate_limit_threshold} 事件 / "
            f"{self.deletion_rate_limit_window.total_seconds()} 秒, 暂停: "
            f"{self.deletion_pause_duration.total_seconds()} 秒"
        )

    def set_client(self, client):
        """设置客户端并初始化依赖客户端的辅助类。"""
        super().set_client(client)
        if self.client:
            if not self.log_chat_id:
                 logger.error("OutputHandler 无法初始化辅助类：log_chat_id 未设置。")
                 return

            self.log_sender = LogSender(self.client, self.log_chat_id)
            self.formatter = MessageFormatter(self.client)
            self.restricted_media_handler = RestrictedMediaHandler(self.client)
            logger.info("OutputHandler 的辅助类 (LogSender, MessageFormatter, RestrictedMediaHandler) 已初始化。")
        else:
            logger.warning("无法初始化 OutputHandler 辅助类：客户端为 None。")

    async def process(self, event: events.common.EventCommon) -> Optional[Message]:
        """
        处理传入的 Telegram 事件。
        根据事件类型调用相应的内部处理方法。
        此处理器不返回 Message 对象，而是执行发送操作。
        """
        if not self.client or not self.log_sender or not self.formatter or not self.restricted_media_handler:
            logger.error("OutputHandler 无法处理事件：客户端或辅助类尚未初始化。")
            return None

        try:
            if isinstance(event, events.NewMessage.Event):
                await self._process_new_message(event)
            elif isinstance(event, events.MessageEdited.Event):
                await self._process_edited_message(event)
            elif isinstance(event, events.MessageDeleted.Event):
                await self._process_deleted_message(event)
            else:
                logger.debug(f"OutputHandler 忽略事件类型: {type(event).__name__}")
            return None
        except Exception as e:
            event_type = type(event).__name__
            msg_id = getattr(event, 'message_id', None)
            if msg_id is None and hasattr(event, 'deleted_ids'):
                msg_id = event.deleted_ids
            if msg_id is None and hasattr(event, 'original_update'):
                 msg_id = getattr(getattr(event.original_update, 'message', None), 'id', '未知')

            logger.exception(f"OutputHandler 处理 {event_type} (相关消息ID: {msg_id}) 时发生严重错误: {e}")
            return None

    # ... (rest of the implementation remains the same as provided)
