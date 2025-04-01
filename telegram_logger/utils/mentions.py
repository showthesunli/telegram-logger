import logging
from telethon.tl.types import *

logger = logging.getLogger(__name__)


async def create_mention(client, entity_id: int, msg_id: int = None) -> str:
    """生成Telegram实体提及链接"""
    try:
        entity = await client.get_entity(entity_id)
        if isinstance(entity, (Channel, Chat)):
            return _format_channel_mention(entity, msg_id)
        return _format_user_mention(entity, msg_id)
    except Exception as e:
        logger.warning(f"创建提及失败: {str(e)}")
        return str(entity_id)


def _format_channel_mention(entity, msg_id: int) -> str:
    """格式化频道/群组提及为 Markdown 超链接"""
    chat_id = str(entity.id).replace("-100", "")
    # 使用标准的 Markdown 链接格式
    return f"[{entity.title}](t.me/c/{chat_id}/{msg_id or 1})"


def _format_user_mention(entity, msg_id: int) -> str:
    """
    格式化用户提及为 Markdown 超链接。
    显示用户的 first_name（如果可用），否则显示用户 ID。
    链接指向 tg://user?id=<user_id>。
    """
    display_name = entity.first_name if entity.first_name else str(entity.id)
    return f"[{display_name}](tg://user?id={entity.id})"
