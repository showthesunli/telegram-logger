import logging
import shlex
from typing import Set, Dict, Any, Optional

from telethon import TelegramClient, events
from telethon.tl.types import Message as TelethonMessage

from .base_handler import BaseHandler
from telegram_logger.data.database import DatabaseManager
from telegram_logger.data.models import Message
from telegram_logger.services.user_bot_state import UserBotStateService
# from telegram_logger.services.ai_service import AIService # 稍后在阶段 5 添加

logger = logging.getLogger(__name__)

class MentionReplyHandler(BaseHandler):
    """
    处理目标群组中提及或回复用户消息的事件，并根据配置自动回复。
    """

    def __init__(
        self,
        client: TelegramClient,
        db: DatabaseManager,
        state_service: UserBotStateService,
        my_id: int,
        # ai_service: AIService, # 稍后在阶段 5 添加
        log_chat_id: int, # 从 BaseHandler 继承，但可能不需要
        ignored_ids: Set[int], # 从 BaseHandler 继承，但可能不需要
        **kwargs: Dict[str, Any]
    ):
        """
        初始化 MentionReplyHandler。

        Args:
            client: Telethon 客户端实例。
            db: DatabaseManager 实例。
            state_service: UserBotStateService 实例。
            my_id: 用户自己的 Telegram ID。
            ai_service: AI 服务实例 (稍后添加)。
            log_chat_id: 日志频道 ID (可能未使用)。
            ignored_ids: 忽略的用户/群组 ID (可能未使用)。
            **kwargs: 其他传递给 BaseHandler 的参数。
        """
        # 调用父类构造函数，注意 UserBot 功能可能不需要 log_chat_id 和 ignored_ids
        # 但为了兼容 BaseHandler 签名，暂时传入
        super().__init__(client=client, db=db, log_chat_id=log_chat_id, ignored_ids=ignored_ids, **kwargs)
        self.state_service = state_service
        self.my_id = my_id
        # self.ai_service = ai_service # 稍后在阶段 5 添加
        logger.info(f"MentionReplyHandler 初始化完成。 My ID: {self.my_id}")

    async def handle_event(self, event: events.NewMessage.Event):
        """
        处理新消息事件，判断是否需要自动回复。
        """
        logger.debug(f"MentionReplyHandler 收到事件: ChatID={event.chat_id}, MsgID={event.id}, SenderID={event.sender_id}")

        # 1. 检查功能是否启用
        if not self.state_service.is_enabled():
            logger.debug("功能未启用，忽略事件。")
            return

        # 2. 检查是否为目标群组
        target_groups = self.state_service.get_target_group_ids()
        if event.chat_id not in target_groups:
            logger.debug(f"事件来自非目标群组 {event.chat_id}，忽略。")
            return

        # 3. 忽略自己发送的消息
        if event.sender_id == self.my_id:
            logger.debug("事件来自自己，忽略。")
            return

        # 4. 检查触发条件：@提及 或 回复
        is_mention = event.mentioned
        is_reply = event.is_reply
        is_reply_trigger_enabled = self.state_service.is_reply_trigger_enabled()
        is_reply_to_me = False

        if is_reply and is_reply_trigger_enabled:
            try:
                reply_msg = await event.get_reply_message()
                if reply_msg and reply_msg.sender_id == self.my_id:
                    is_reply_to_me = True
                    logger.debug(f"事件是对我的消息 (MsgID: {reply_msg.id}) 的回复。")
                else:
                    logger.debug("事件是回复，但不是回复我的消息。")
            except Exception as e:
                # 获取回复消息失败，可能已被删除或权限问题
                logger.warning(f"获取回复消息失败 (可能已被删除): {e}", exc_info=True)
                # 即使获取失败，如果被 @ 了，仍然可以继续处理

        if not is_mention and not is_reply_to_me:
            logger.debug("事件既不是 @提及 也不是对我的回复（或回复触发未启用），忽略。")
            return

        # 如果同时满足 @ 和回复，也只处理一次
        logger.info(f"事件满足触发条件 (Mention: {is_mention}, ReplyToMe: {is_reply_to_me})，继续处理...")

        # 5. 检查频率限制
        if self.state_service.check_rate_limit(event.chat_id):
            logger.info(f"群组 {event.chat_id} 触发频率限制，本次忽略。")
            return

        # --- 后续逻辑：获取角色、生成回复等将在后续步骤实现 ---
        pass # 占位符

    async def process(self, event: events.common.EventCommon) -> Optional[Message]:
        """
        覆盖 BaseHandler 的抽象方法。
        对于 MentionReplyHandler，主要逻辑在 handle_event 中，由 main.py 中的事件处理器直接调用。
        """
        # logger.debug("MentionReplyHandler.process 被调用，但无操作。")
        return None
