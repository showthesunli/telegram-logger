import logging
from typing import Union # <- 添加这行
from telethon.tl.types import User, Channel, Chat

logger = logging.getLogger(__name__)


async def create_mention(client, entity_id: int, msg_id: int = None) -> str:
    """生成Telegram实体提及链接"""
    logger.debug(f"尝试为 ID {entity_id} 创建提及 (消息 ID: {msg_id})")
    
    # 特殊处理 entity_id 为 0 的情况 (通常代表自己)
    if entity_id == 0:
        try:
            me = await client.get_me()
            if me:
                logger.debug("entity_id 为 0，使用 client.get_me() 获取自身信息。")
                # 复用现有的用户提及格式化逻辑
                return _format_user_mention(me, msg_id)
            else:
                # get_me() 意外返回 None
                logger.warning("client.get_me() 返回 None，无法格式化 ID 为 0 的提及。")
                return "自己 (ID: 0)" # 提供一个明确的回退
        except Exception as me_err:
            logger.error(f"尝试使用 client.get_me() 获取自身信息时出错: {me_err}", exc_info=True)
            return "自己 (获取信息出错)" # 错误时的回退

    try:
        entity = await client.get_entity(entity_id)
        logger.debug(f"成功获取实体: 类型={type(entity).__name__}, ID={entity.id}")

        if isinstance(entity, (Channel, Chat)):
            mention = _format_channel_mention(entity, msg_id)
            logger.debug(f"格式化为频道/群组提及: {mention}")
            return mention
        elif isinstance(entity, User):
            mention = _format_user_mention(entity, msg_id) # msg_id 可能对用户提及无用，但保持一致性
            logger.debug(f"格式化为用户提及: {mention}")
            return mention
        else:
            logger.warning(f"获取到未知实体类型 {type(entity).__name__}，ID: {entity_id}")
            return str(entity_id) # 返回原始 ID 作为回退

    except ValueError as e:
        # Telethon 在找不到实体时可能抛出 ValueError
        logger.error(f"无法找到 ID 为 {entity_id} 的实体: {e}", exc_info=True)
        return str(entity_id) # 返回原始 ID
    except Exception as e:
        logger.error(f"为 ID {entity_id} 创建提及失败: {e}", exc_info=True)
        return str(entity_id) # 返回原始 ID


def _format_channel_mention(entity: Union[Channel, Chat], msg_id: int) -> str:
    """格式化频道/群组提及为 MarkdownV2 格式"""
    # 确保 entity.id 是整数，然后转换为字符串
    entity_id_str = str(entity.id)
    # 移除 Telegram 内部使用的 -100 前缀
    chat_id_for_link = entity_id_str.replace("-100", "")
    title = getattr(entity, 'title', f'未知频道/群组 {entity.id}') # 添加回退标题
    mention = f"[{title}](t.me/c/{chat_id_for_link}/{msg_id or 1})"
    logger.debug(f"格式化频道/群组提及: ID={entity.id}, Title='{title}', MsgID={msg_id}, Mention='{mention}'")
    return mention


def _format_user_mention(entity: User, msg_id: int) -> str:
    """
    格式化用户提及为 MarkdownV2 格式。
    显示用户的 first_name（如果可用），否则显示用户 ID。
    """
    # 优先使用 first_name，然后 last_name，最后是 ID
    display_name = entity.first_name
    if not display_name and entity.last_name:
        display_name = entity.last_name # 如果没有 first_name 但有 last_name
    if not display_name:
        display_name = f"用户 {entity.id}" # 如果两者都没有

    # 清理 display_name 中的 Markdown 特殊字符，例如 [ ] ( ) ~ ` > # + - = | { } . !
    # 仅转义必要的字符以避免破坏链接
    safe_display_name = display_name.replace('[', '\\[').replace(']', '\\]')

    # 优先使用用户名链接，其次是 ID 链接
    if entity.username:
        mention = f"[{safe_display_name}](@{entity.username})"
        logger.debug(f"格式化用户提及 (使用用户名): ID={entity.id}, Username='{entity.username}', Display='{safe_display_name}', Mention='{mention}'")
    else:
        mention = f"[{safe_display_name}](tg://user?id={entity.id})"
        logger.debug(f"格式化用户提及 (使用 ID): ID={entity.id}, Display='{safe_display_name}', Mention='{mention}'")

    return mention
