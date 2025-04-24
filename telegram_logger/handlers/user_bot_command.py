import logging
import shlex  # 新增导入
from typing import Set, Dict, Any, Optional
from telethon import events, TelegramClient
from telethon.tl.types import Message as TelethonMessage

from .base_handler import BaseHandler
from telegram_logger.data.database import DatabaseManager
from telegram_logger.data.models import Message
from telegram_logger.services.user_bot_state import UserBotStateService

logger = logging.getLogger(__name__)

class UserBotCommandHandler(BaseHandler):
    """
    处理用户通过私聊发送的控制指令的 Handler。
    指令以 '.' 开头。
    """

    def __init__(
        self,
        client: TelegramClient,
        db: DatabaseManager,
        state_service: UserBotStateService,
        my_id: int,
        log_chat_id: int,
        ignored_ids: Set[int],
        **kwargs: Dict[str, Any]
    ):
        super().__init__(client=client, db=db, log_chat_id=log_chat_id, ignored_ids=ignored_ids, **kwargs)
        self.state_service = state_service
        logger.info(f"UserBotCommandHandler 初始化完成。 My ID: {self.my_id}")

    async def handle_command(self, event: events.NewMessage.Event):
        """
        处理来自用户私聊的新消息事件，解析并执行指令。
        """
        text = event.message.text
        if not text or not text.startswith('.'):
            # 不是指令，忽略
            return

        # 移除开头的 '.' 并使用 shlex 解析指令和参数
        try:
            parts = shlex.split(text[1:])
        except ValueError as e:
            logger.warning(f"解析指令时出错: {e} (原始文本: '{text}')")
            await event.reply(f"无法解析指令：请检查引号是否匹配。\n错误: {e}")
            return

        if not parts:
            # 只有 '.'，没有指令
            return

        command = parts[0].lower()  # 指令不区分大小写
        args = parts[1:]  # 参数列表

        logger.info(f"接收到指令: command='{command}', args={args}")

        # --- 指令执行逻辑将在阶段 3 第 5 步实现 ---
        # 暂时保留占位回复
        await event.reply(f"已解析指令: '{command}', 参数: {args}\n(执行逻辑待实现)")
        # --- 指令执行逻辑结束 ---

    async def process(self, event: events.common.EventCommon) -> Optional[Message]:
        """
        覆盖 BaseHandler 的抽象方法。
        """
        logger.debug("UserBotCommandHandler.process 被调用，但主要逻辑在 handle_command 中。")
        return None
