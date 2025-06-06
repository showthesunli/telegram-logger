import logging
import re
from telethon import events
from telethon.tl.types import (
    Message as TelethonMessage,
    DocumentAttributeSticker,
    MessageMediaDocument,
)
from telegram_logger.utils.mentions import create_mention
from telegram_logger.utils.media import (
    _get_filename,
)

logger = logging.getLogger(__name__)


class MessageFormatter:
    def __init__(self, client):
        self.client = client
        logger.info("MessageFormatter 已初始化。")  # <- 可选：更新日志消息

    async def format_message(self, event: events.NewMessage.Event) -> str:
        """格式化日志消息的文本内容。"""
        from_id = self._get_sender_id(
            event.message
        )  # 假设 _get_sender_id 可访问或已传入
        mention_sender = await create_mention(self.client, from_id)
        mention_chat = await create_mention(
            self.client, event.chat_id, event.message.id
        )
        timestamp = event.message.date.strftime("%Y-%m-%d %H:%M:%S UTC")

        # 第 1 部分：来源信息
        text = f"{mention_sender} 在 {mention_chat} 中，于 {timestamp}，发言：\n\n"

        # 第 2 部分：消息内容
        message_text = event.message.text or getattr(event.message, "caption", None)
        if message_text:
            text += message_text  # <- 确保这行存在且没有缩进
        else:
            text += "[无文本内容或标题]"

        # 第 3 部分：媒体信息部分
        media_section = self._format_media_info(event.message)
        text += media_section
        return text

    def _format_media_info(self, message: TelethonMessage) -> str:
        """格式化消息的媒体信息部分。"""
        media_section = ""
        if message.media:
            media_section += "\n--------------------\n"
            media_section += "MEDIA:\n"
            is_sticker = self._is_sticker(message)
            media_type = (
                "Sticker"  # 贴纸
                if is_sticker
                else type(message.media).__name__.replace("MessageMedia", "")
            )
            # 使用导入的 _get_filename 或根据需要在此处本地定义
            media_filename = None if is_sticker else _get_filename(message.media)

            media_section += f"  类型: {media_type}\n"
            if media_filename:
                media_section += f"  文件名: {media_filename}\n"

            noforwards = self._has_noforwards(message)
            if noforwards:
                media_section += "  注意: 受限内容。媒体文件将单独处理。\n"

            ttl_seconds = getattr(getattr(message, "media", None), "ttl_seconds", None)
            if ttl_seconds:
                media_section += f"  注意: 阅后即焚媒体 (TTL: {ttl_seconds}秒)。\n"
        return media_section

    def _is_sticker(self, message: TelethonMessage) -> bool:
        """检查消息媒体是否为贴纸。"""
        if isinstance(message.media, MessageMediaDocument):
            doc = getattr(message.media, "document", None)
            if doc and hasattr(doc, "attributes"):
                return any(
                    isinstance(attr, DocumentAttributeSticker)
                    for attr in doc.attributes
                )
        return False

    def _has_noforwards(self, message: TelethonMessage) -> bool:
        """检查消息或其聊天是否设置了 noforwards。"""
        try:
            chat_noforwards = (
                getattr(message.chat, "noforwards", False) if message.chat else False
            )
            message_noforwards = getattr(message, "noforwards", False)
            return chat_noforwards or message_noforwards
        except AttributeError:
            logger.warning(
                "检查 noforwards 时出现 AttributeError，默认为 False", exc_info=True
            )
            return False

    # 获取发送者 ID 的辅助函数
    def _get_sender_id(self, message: TelethonMessage) -> int:
        """从消息中获取发送者 ID（用户或频道）。"""
        sender_id = 0 # 默认值

        if message.from_id:
            # 尝试获取 user_id (适用于普通用户)
            sender_id = getattr(message.from_id, 'user_id', None)
            if sender_id:
                return sender_id

            # 如果不是用户，尝试获取 channel_id (适用于频道身份发送的消息)
            # Telethon 的 channel_id 通常是负数，我们直接返回它
            sender_id = getattr(message.from_id, 'channel_id', None)
            if sender_id:
                return sender_id

        # 如果 from_id 不存在或无法从中提取 ID (例如匿名管理员、旧消息)，
        # 尝试从 peer_id 获取。注意：这通常是 *聊天* ID，不一定是 *发送者* ID。
        # 这种回退逻辑的准确性有限，但作为最后的尝试。
        if not sender_id and message.peer_id:
            peer = message.peer_id
            # 优先检查 channel_id，然后是 chat_id，最后是 user_id
            sender_id = getattr(peer, 'channel_id', None)
            if sender_id:
                # logger.debug(f"从 peer_id 获取到 channel_id: {sender_id} 作为消息 {message.id} 的回退发送者")
                return sender_id
            sender_id = getattr(peer, 'chat_id', None)
            if sender_id:
                # logger.debug(f"从 peer_id 获取到 chat_id: {sender_id} 作为消息 {message.id} 的回退发送者")
                return sender_id # 注意：这可能是群组 ID
            sender_id = getattr(peer, 'user_id', None)
            if sender_id:
                # logger.debug(f"从 peer_id 获取到 user_id: {sender_id} 作为消息 {message.id} 的回退发送者")
                return sender_id

        # 如果所有尝试都失败了
        if not sender_id:
            logger.warning(f"无法确定消息 {message.id} 的发送者 ID，将返回 0")
            return 0

        # 理论上不应到达这里，因为前面的 return 会退出
        return sender_id
