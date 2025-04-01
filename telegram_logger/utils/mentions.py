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
    chat_id = str(entity.id).replace("-100", "")
    return f"( {entity.title} )[ t.me/c/{chat_id}/{msg_id or 1} ]"


def _format_user_mention(entity, msg_id: int) -> str:
    """格式化用户提及，优先使用 username，其次 first_name，最后 id"""
    if entity.username:
        # 优先使用 @username 进行提及 (Telegram 会自动链接)
        return f"@{entity.username}"
    elif entity.first_name:
        # 其次使用 first_name 进行 Markdown 链接提及
        return f"[{entity.first_name}](tg://user?id={entity.id})"
    else:
        # 如果都没有，则使用 id 作为链接文本
        return f"[{entity.id}](tg://user?id={entity.id})"
