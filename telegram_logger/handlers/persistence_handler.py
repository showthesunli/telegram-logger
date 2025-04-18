import logging
from typing import Optional, Union, cast, Set, Dict, Any

from telethon import events
from telethon.tl.types import Message as TelethonMessage

from ..data.database import DatabaseManager
from ..data.models import Message
from ..utils.media import save_media_as_file
from .base_handler import BaseHandler

logger = logging.getLogger(__name__)


class PersistenceHandler(BaseHandler):
    """
    负责将消息数据持久化到数据库的处理器。
    监听 NewMessage 和 MessageEdited 事件。
    """

    def __init__(
        self,
        db: DatabaseManager,
        log_chat_id: int,
        ignored_ids: Set[int],
        **kwargs: Dict[str, Any]
    ):
        """
        初始化 PersistenceHandler。

        Args:
            db: 数据库管理器实例。
            log_chat_id: 日志频道 ID (基类可能需要)。
            ignored_ids: 要忽略的用户/频道 ID 集合 (基类可能需要)。
            **kwargs: 其他传递给基类的参数。
        """
        super().__init__(client=None, db=db, log_chat_id=log_chat_id, ignored_ids=ignored_ids, **kwargs)
        logger.info("PersistenceHandler 初始化完毕。")

    async def process(self, event: events.common.EventCommon) -> Optional[Message]:
        """
        处理传入的 Telegram 事件，仅持久化 NewMessage 和 MessageEdited 事件。
        """
        try:
            if isinstance(event, (events.NewMessage.Event, events.MessageEdited.Event)):
                logger.debug(f"PersistenceHandler 正在处理事件: {type(event).__name__}")
                message_obj = await self._create_message_object(event)
                if message_obj:
                    await self.save_message(message_obj)
                    logger.info(f"消息已保存到数据库: ChatID={message_obj.chat_id}, MsgID={message_obj.id}")
                    return message_obj
                else:
                    logger.warning(f"无法为事件 {type(event).__name__} (ID: {event.message.id}) 创建消息对象。")
                    return None
            else:
                # 对于其他事件类型（如 MessageDeleted），此处理器不执行任何操作
                logger.debug(f"PersistenceHandler 忽略事件: {type(event).__name__}")
                return None
        except Exception:
            # 捕获通用异常以防止崩溃
            msg_id = getattr(event, 'message_id', getattr(getattr(event, 'original_update', None), 'message_id', '未知'))
            logger.exception(f"PersistenceHandler 处理事件 {type(event).__name__} (消息ID: {msg_id}) 时发生错误")
            return None


    async def _create_message_object(
        self, event: Union[events.NewMessage.Event, events.MessageEdited.Event]
    ) -> Optional[Message]:
        """
        根据 NewMessage 或 MessageEdited 事件创建 Message 数据对象。
        提取自旧的 NewMessageHandler._create_message_object。
        """
        message: TelethonMessage = event.message
        if not message:
            logger.warning(f"事件 {type(event).__name__} 不包含有效的 message 对象。")
            return None

        # 确保 self.client 存在 (应该在 process 调用时由 set_client 设置好)
        if message.media and not self.client:
            logger.error(f"尝试保存媒体时 client 尚未设置 (消息 ID: {message.id})")
        if not message:
            logger.warning(f"事件 {type(event).__name__} 不包含有效的 message 对象。")
            return None

        chat_id = message.chat_id
        from_id = self._get_sender_id(message) # 使用基类的方法获取发送者ID

        # 确定聊天类型
        is_bot = getattr(message.sender, 'bot', False) if message.sender else False
        is_private = message.is_private
        is_group = message.is_group
        is_channel = message.is_channel

        # 处理媒体
        media_path = None
        media_type = None
        is_restricted = False
        if message.media:
            try:
                # 检查是否有 noforwards 属性
                is_restricted = getattr(message, 'noforwards', False)
                media_path = await save_media_as_file(self.client, message)
                media_type = type(message.media).__name__
                logger.debug(f"媒体已保存: {media_path}, 类型: {media_type}, 受限: {is_restricted}")
            except Exception as e:
                logger.error(f"保存媒体文件失败 (消息 ID: {message.id}): {e}", exc_info=True)
                # 即使媒体保存失败，也继续保存消息文本

        # 创建 Message 对象
        try:
            message_obj = Message(
                id=message.id,
                chat_id=chat_id or 0, # 确保 chat_id 不为 None
                from_id=from_id,
                text=message.text or "",
                date=message.date,
                reply_to_msg_id=message.reply_to_msg_id,
                media_path=media_path,
                media_type=media_type,
                is_bot=is_bot,
                is_private=is_private,
                is_group=is_group,
                is_channel=is_channel,
                is_restricted=is_restricted,
                # edit_date 仅在 MessageEdited 事件中存在
                edit_date=getattr(message, 'edit_date', None)
            )
            return message_obj
        except Exception as e:
            logger.error(f"创建 Message 对象失败 (消息 ID: {message.id}): {e}", exc_info=True)
            return None
