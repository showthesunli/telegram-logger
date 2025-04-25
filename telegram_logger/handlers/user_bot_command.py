import logging
import shlex
import json
from typing import Set, Dict, Any, Optional
from telethon import events, TelegramClient, errors
from telethon.tl import types # 新增导入
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

            elif command == "status":
                if args:
                    await self._safe_respond(event, "错误：`.status` 指令不需要参数。")
                    return

                # 获取所有状态信息
                enabled = self.state_service.is_enabled()
                reply_trigger = self.state_service.is_reply_trigger_enabled()
                current_model_ref = self.state_service.get_current_model_id() # 可能为别名或 ID
                current_role_alias = self.state_service.get_current_role_alias()
                target_group_ids = self.state_service.get_target_group_ids()
                rate_limit = self.state_service.get_rate_limit()
                history_length = self.state_service.get_ai_history_length()

                # 解析模型信息
                model_id = await self.state_service.resolve_model_id(current_model_ref)
                model_aliases = await self.state_service.get_model_aliases()
                model_alias_str = ""
                # 反向查找别名
                for alias, m_id in model_aliases.items():
                    if m_id == model_id:
                        model_alias_str = f" (别名: {alias})"
                        break
                model_display = f"{model_id or '未设置'}{model_alias_str}"

                # 解析角色信息
                role_details = await self.state_service.resolve_role_details(current_role_alias)
                role_display = f"'{current_role_alias}'"
                if role_details:
                    role_type = role_details.get('role_type', '未知')
                    role_display += f" ({role_type.upper()})"
                    if role_type == 'static':
                        content = role_details.get('static_content')
                        role_display += f" (内容: {content[:30] + '...' if content and len(content) > 30 else content or '未设置'})"
                    elif role_type == 'ai':
                        prompt = role_details.get('system_prompt')
                        role_display += f" (提示: {prompt[:30] + '...' if prompt and len(prompt) > 30 else prompt or '未设置'})"
                else:
                    role_display += " (未找到或未设置)"


                # 获取目标群组名称 (摘要)
                group_names = []
                if target_group_ids:
                    # 只获取前几个群组的名称以避免消息过长
                    max_groups_to_show = 3
                    count = 0
                    for group_id in target_group_ids:
                        if count >= max_groups_to_show:
                            group_names.append("...")
                            break
                        try:
                            entity = await self.client.get_entity(group_id)
                            if isinstance(entity, (types.Chat, types.Channel)):
                                group_names.append(f"'{entity.title}'")
                            else:
                                group_names.append(f"ID:{group_id}")
                        except Exception:
                            logger.warning(f"获取群组 {group_id} 信息时出错", exc_info=True)
                            group_names.append(f"ID:{group_id}")
                        count += 1
                groups_display = f"[{', '.join(group_names)}]" if group_names else "无"


                # 格式化最终状态字符串
                status_message = (
                    f"📊 **用户机器人状态**\n\n"
                    f"🔹 **核心功能:** {'✅ 已启用' if enabled else '❌ 已禁用'}\n"
                    f"🔹 **回复触发:** {'✅ 已启用' if reply_trigger else '❌ 已禁用'}\n"
                    f"🔹 **当前模型:** {model_display}\n"
                    f"🔹 **当前角色:** {role_display}\n"
                    f"🔹 **AI历史数量:** {history_length}\n"
                    f"🔹 **目标群组:** {groups_display}\n"
                    f"🔹 **频率限制:** {rate_limit} 秒"
                )

                await self._safe_respond(event, status_message)

            # --- 其他指令的占位符 ---
            elif command == "setmodel":
                if len(args) != 1:
                    await self._safe_respond(event, "错误：`.setmodel` 指令需要一个参数。\n用法: `.setmodel <模型ID或别名>`")
                    return

                model_ref = args[0]
                success = await self.state_service.set_current_model(model_ref)

                if success:
                    # 获取实际的模型 ID 和可能的别名以用于反馈
                    resolved_model_id = await self.state_service.resolve_model_id(model_ref)
                    model_aliases = await self.state_service.get_model_aliases()
                    model_alias_str = ""
                    if resolved_model_id: # 确保模型ID已成功解析
                        # 反向查找别名
                        user_input_alias_found = False
                        any_alias_found = ""
                        for alias, m_id in model_aliases.items():
                            if m_id == resolved_model_id:
                                if alias.lower() == model_ref.lower(): # 优先匹配用户输入的别名
                                    model_alias_str = f" (别名: {alias})"
                                    user_input_alias_found = True
                                    break # 找到用户输入的，直接用
                                elif not any_alias_found: # 记录第一个找到的别名
                                    any_alias_found = f" (别名: {alias})"

                        if not user_input_alias_found and any_alias_found: # 如果没找到用户输入的，但有其他别名
                            model_alias_str = any_alias_found

                    model_display = f"{resolved_model_id or model_ref}{model_alias_str}" # 如果解析失败，显示原始输入
                    await self._safe_respond(event, f"✅ AI 模型已设置为 {model_display}。")
                else:
                    # 失败可能是因为别名/ID不存在，或者数据库错误
                    await self._safe_respond(event, f"❌ 设置模型失败。模型ID或别名 '{model_ref}' 不存在，或发生数据库错误。")

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
