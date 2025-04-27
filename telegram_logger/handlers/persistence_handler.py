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
        my_id: Optional[int] = None, # 添加 my_id 参数
        **kwargs: Dict[str, Any]
    ):
        """
        初始化 PersistenceHandler。

        Args:
            db: 数据库管理器实例。
            log_chat_id: 日志频道 ID (基类可能需要)。
            ignored_ids: 要忽略的用户/频道 ID 集合 (基类可能需要)。
            my_id: 用户自己的 Telegram ID (可选, 基类需要)。
            **kwargs: 其他传递给基类的参数。
        """
        super().__init__(client=None, db=db, log_chat_id=log_chat_id, ignored_ids=ignored_ids, my_id=my_id, **kwargs) # 传递 my_id
        my_id_status = f"my_id={my_id}" if my_id is not None else "my_id 未提供 (将由 init 获取)"
        logger.info(f"PersistenceHandler 初始化完毕。{my_id_status}")

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
            # 注意：这里不返回 None，因为可能仍需保存文本信息
            # 但 save_media_as_file 会失败

        chat_id = message.chat_id
        from_id = self._get_sender_id(message) # 使用基类的方法获取发送者ID

        # 确定聊天类型
        sender_entity = await message.get_sender() # 获取发送者实体以检查是否为机器人
        is_bot = getattr(sender_entity, 'bot', False) if sender_entity else False
        is_private = message.is_private
        is_group = message.is_group
        is_channel = message.is_channel

        # 计算 msg_type
        msg_type = 0 # 默认为未知或不支持的类型
        if is_bot:
            msg_type = DatabaseManager.MSG_TYPE_MAP['bot']
        elif is_private:
            msg_type = DatabaseManager.MSG_TYPE_MAP['user']
        elif is_group:
            msg_type = DatabaseManager.MSG_TYPE_MAP['group']
        elif is_channel:
            msg_type = DatabaseManager.MSG_TYPE_MAP['channel']
        else:
            logger.warning(f"无法确定消息类型 (消息 ID: {message.id}, ChatID: {chat_id})")

        # 处理媒体
        media_path = None
        if message.media:
            try:
                # 确保 client 已设置
                if self.client:
                    media_path = await save_media_as_file(self.client, message)
                    logger.debug(f"媒体已保存: {media_path} (消息 ID: {message.id})")
                else:
                    logger.error(f"无法保存媒体，因为 client 未设置 (消息 ID: {message.id})")
            except Exception as e:
                logger.error(f"保存媒体文件失败 (消息 ID: {message.id}): {e}", exc_info=True)
                # 即使媒体保存失败，也继续保存消息文本

        # 获取 noforwards 状态 (Telethon v1.24+ 使用 noforwards)
        noforwards = getattr(message, 'noforwards', False)

        # 获取自毁状态 (检查 ttl_period 属性)
        self_destructing = getattr(message, 'ttl_period', None) is not None

        # 创建 Message 对象
        try:
            message_obj = Message(
                id=message.id,
                from_id=from_id,
                chat_id=chat_id or 0, # 确保 chat_id 不为 None
                msg_type=msg_type,
                msg_text=message.text or "", # 映射到 msg_text
                media_path=media_path, # 使用从 save_media_as_file 获取的路径
                noforwards=noforwards, # 映射到 noforwards
                self_destructing=self_destructing, # 设置自毁状态
                created_time=message.date, # 映射到 created_time
                # edit_date 仅在 MessageEdited 事件中存在, 映射到 edited_time
                edited_time=getattr(message, 'edit_date', None)
            )
            return message_obj
        except Exception as e:
            logger.error(f"创建 Message 对象失败 (消息 ID: {message.id}): {e}", exc_info=True)
            return None
