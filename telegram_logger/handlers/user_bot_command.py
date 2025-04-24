import logging
import shlex
import json  # 新增导入
from typing import Set, Dict, Any, Optional
from telethon import events, TelegramClient, errors # 新增导入 errors
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

    async def _safe_respond(self, event: events.NewMessage.Event, message: str):
        """安全地发送回复消息，处理可能的 Telethon 错误。"""
        try:
            await event.reply(message)
        except errors.FloodWaitError as e:
            logger.warning(f"发送回复时遭遇 FloodWaitError: {e.seconds} 秒")
            # 可以选择通知用户稍后重试，但通常私聊中不那么关键
        except errors.RPCError as e:
            logger.error(f"发送回复时发生 RPC 错误: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"发送回复时发生未知错误: {e}", exc_info=True)

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
            await self._safe_respond(event, f"无法解析指令：请检查引号是否匹配。\n错误: {e}")
            return

        if not parts:
            # 只有 '.'，没有指令
            return

        command = parts[0].lower()  # 指令不区分大小写
        args = parts[1:]  # 参数列表

        logger.info(f"接收到指令: command='{command}', args={args}")

        # --- 指令执行逻辑 ---
        try:
            if command == "on":
                if args:
                    await self._safe_respond(event, "错误：`.on` 指令不需要参数。")
                    return
                if await self.state_service.enable():
                    await self._safe_respond(event, "✅ 自动回复已启用。")
                else:
                    await self._safe_respond(event, "❌ 启用自动回复失败（可能是数据库错误）。")

            elif command == "off":
                if args:
                    await self._safe_respond(event, "错误：`.off` 指令不需要参数。")
                    return
                if await self.state_service.disable():
                    await self._safe_respond(event, "✅ 自动回复已禁用。")
                else:
                    await self._safe_respond(event, "❌ 禁用自动回复失败（可能是数据库错误）。")

            elif command == "replyon":
                if args:
                    await self._safe_respond(event, "错误：`.replyon` 指令不需要参数。")
                    return
                if await self.state_service.enable_reply_trigger():
                    await self._safe_respond(event, "✅ 回复触发已启用。")
                else:
                    await self._safe_respond(event, "❌ 启用回复触发失败（可能是数据库错误）。")

            elif command == "replyoff":
                if args:
                    await self._safe_respond(event, "错误：`.replyoff` 指令不需要参数。")
                    return
                if await self.state_service.disable_reply_trigger():
                    await self._safe_respond(event, "✅ 回复触发已禁用。")
                else:
                    await self._safe_respond(event, "❌ 禁用回复触发失败（可能是数据库错误）。")

            elif command == "sethistory":
                if len(args) != 1:
                    await self._safe_respond(event, "错误：`.sethistory` 指令需要一个参数。\n用法: `.sethistory <数量>`")
                    return
                try:
                    count = int(args[0])
                    if not (0 <= count <= 20): # RFC 003 定义的范围
                        raise ValueError("数量必须在 0 到 20 之间。")
                except ValueError as e:
                    logger.warning(f"无效的 .sethistory 参数: {args[0]} - {e}")
                    await self._safe_respond(event, f"错误：无效的数量 '{args[0]}'。\n请提供一个 0 到 20 之间的整数。\n{e}")
                    return

                if await self.state_service.set_ai_history_length(count):
                    await self._safe_respond(event, f"✅ AI 上下文历史消息数量已设置为 {count}。")
                else:
                    await self._safe_respond(event, f"❌ 设置历史数量失败（可能是数据库错误）。")

            # --- 其他指令的占位符 ---
            # elif command == "status":
            #     # 实现获取并格式化状态信息
            #     await self._safe_respond(event, "状态信息待实现...")
            # elif command == "setmodel":
            #     # 实现设置模型逻辑
            #     await self._safe_respond(event, "设置模型待实现...")
            # elif command == "listmodels":
            #     # 实现列出模型逻辑
            #     await self._safe_respond(event, "列出模型待实现...")
            # ... 其他指令 ...

            else:
                logger.warning(f"收到未知指令: '{command}'")
                await self._safe_respond(event, f"未知指令: '{command}'。 输入 `.help` 查看可用指令。")

        except IndexError:
            # 这个通常在参数数量检查后不应该发生，但作为保险
            logger.warning(f"处理指令 '{command}' 时发生参数索引错误 (参数: {args})")
            await self._safe_respond(event, f"处理指令 '{command}' 时参数不足。请检查指令格式。")
        except Exception as e:
            # 捕获指令处理逻辑中未预料的错误
            logger.error(f"处理指令 '{command}' 时发生意外错误: {e}", exc_info=True)
            await self._safe_respond(event, f"处理指令 '{command}' 时发生内部错误。请检查日志。")

        # --- 指令执行逻辑结束 ---

    # process 方法保持不变
    async def process(self, event: events.common.EventCommon) -> Optional[Message]:
        """
        覆盖 BaseHandler 的抽象方法。
        """
        logger.debug("UserBotCommandHandler.process 被调用，但主要逻辑在 handle_command 中。")
        return None
