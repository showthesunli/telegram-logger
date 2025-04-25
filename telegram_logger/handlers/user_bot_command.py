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

            elif command == "listmodels":
                if args:
                    await self._safe_respond(event, "错误：`.listmodels` 指令不需要参数。")
                    return

                model_aliases = await self.state_service.get_model_aliases()

                if not model_aliases:
                    await self._safe_respond(event, "ℹ️ 当前没有设置任何模型别名。\n\n你可以使用 `.aliasmodel <模型ID> <别名>` 来设置模型别名。")
                else:
                    # 按字母顺序排序别名，使输出更有条理
                    sorted_aliases = sorted(model_aliases.items())
                    response_lines = ["📚 **可用模型别名**："]
                    for alias, model_id in sorted_aliases:
                        response_lines.append(f"- `{alias}` → `{model_id}`")
                    await self._safe_respond(event, "\n".join(response_lines))

            elif command == "aliasmodel":
                # 参数验证
                if len(args) != 2:
                    await self._safe_respond(event, "错误：`.aliasmodel` 指令需要两个参数。\n用法: `.aliasmodel <模型ID> <别名>`")
                    return

                model_id = args[0]
                alias = args[1]
                
                # 验证别名格式
                if not alias.isalnum() and not (alias.replace('-', '').isalnum() and '-' in alias):
                    await self._safe_respond(event, f"错误：别名 '{alias}' 格式无效。别名只能包含字母、数字和连字符(-)。")
                    return
                
                # 检查别名是否与现有模型ID冲突
                existing_aliases = await self.state_service.get_model_aliases()
                for existing_alias, existing_model in existing_aliases.items():
                    if existing_model.lower() == alias.lower():
                        await self._safe_respond(event, f"错误：别名 '{alias}' 与现有模型ID '{existing_model}' 冲突。")
                        return
                
                # 设置模型别名
                if await self.state_service.set_model_alias(alias=alias, model_id=model_id):
                    logger.info(f"已为模型 '{model_id}' 设置别名 '{alias}'")
                    await self._safe_respond(event, f"✅ 已为模型 `{model_id}` 设置别名 `{alias}`。")
                else:
                    logger.error(f"设置模型别名失败: model_id='{model_id}', alias='{alias}'")
                    await self._safe_respond(event, f"❌ 设置模型别名 `{alias}` 失败（可能是数据库错误）。")

            elif command == "unaliasmodel":
                # 参数验证
                if len(args) != 1:
                    await self._safe_respond(event, "错误：`.unaliasmodel` 指令需要一个参数。\n用法: `.unaliasmodel <别名>`")
                    return

                alias = args[0]
                
                # 检查别名是否存在
                model_aliases = await self.state_service.get_model_aliases()
                if alias not in model_aliases:
                    await self._safe_respond(event, f"错误：模型别名 '{alias}' 不存在。")
                    return
                
                # 删除模型别名
                if await self.state_service.remove_model_alias(alias):
                    logger.info(f"已删除模型别名 '{alias}'")
                    await self._safe_respond(event, f"✅ 模型别名 `{alias}` 已删除。")
                else:
                    logger.error(f"删除模型别名失败: alias='{alias}'")
                    await self._safe_respond(event, f"❌ 删除模型别名 `{alias}` 失败（可能是数据库错误）。")

            elif command == "setroleprompt":
                # 参数验证
                if len(args) < 2:
                    await self._safe_respond(event, "错误：`.setroleprompt` 指令需要两个参数。\n用法: `.setroleprompt <别名> \"<系统提示词>\"`")
                    return
                
                alias = args[0]
                # 将剩余参数合并为系统提示词（以防提示词中有空格且未用引号包裹）
                prompt = " ".join(args[1:])
                
                # 检查角色别名是否存在
                role_details = await self.state_service.resolve_role_details(alias)
                if not role_details:
                    await self._safe_respond(event, f"错误：角色别名 '{alias}' 不存在。")
                    return
                
                # 检查角色类型是否为 AI
                if role_details.get('role_type') != 'ai':
                    await self._safe_respond(event, f"错误：角色 '{alias}' 不是 AI 类型，无法设置系统提示词。")
                    return
                
                # 设置系统提示词
                if await self.state_service.set_role_system_prompt(alias, prompt):
                    logger.info(f"已更新角色 '{alias}' 的系统提示词")
                    await self._safe_respond(event, f"✅ 已更新角色 '{alias}' 的系统提示词。")
                else:
                    logger.error(f"设置角色 '{alias}' 的系统提示词失败")
                    await self._safe_respond(event, f"❌ 设置角色 '{alias}' 的系统提示词失败（可能是数据库错误）。")

            elif command == "setrole":
                # 参数验证
                if len(args) != 1:
                    await self._safe_respond(event, "错误：`.setrole` 指令需要一个参数。\n用法: `.setrole <别名>`")
                    return

                alias = args[0]

                # 设置当前角色
                success = await self.state_service.set_current_role(alias)

                if success:
                    # 获取角色详情以在反馈中显示类型
                    role_details = await self.state_service.resolve_role_details(alias)
                    role_type_str = ""
                    if role_details:
                        role_type = role_details.get('role_type', '未知')
                        role_type_str = f" ({role_type.upper()})"
                    
                    logger.info(f"用户已将当前角色设置为 '{alias}'{role_type_str}")
                    await self._safe_respond(event, f"✅ AI 角色已设置为 '{alias}'{role_type_str}。")
                else:
                    # 失败可能是因为别名不存在或数据库错误
                    logger.error(f"设置当前角色为 '{alias}' 失败")
                    await self._safe_respond(event, f"❌ 设置角色失败。角色别名 '{alias}' 不存在，或发生数据库错误。")

            elif command == "listroles":
                if args:
                    await self._safe_respond(event, "错误：`.listroles` 指令不需要参数。")
                    return

                role_aliases_details = await self.state_service.get_role_aliases()

                if not role_aliases_details:
                    await self._safe_respond(event, "ℹ️ 当前没有定义任何角色别名。\n\n你可以使用 `.aliasrole <别名> --type <ai|static> [\"<内容>\"]` 来创建角色。")
                else:
                    response_lines = ["🎭 **可用角色别名**："]
                    # 按别名排序
                    sorted_aliases = sorted(role_aliases_details.items())

                    for alias, details in sorted_aliases:
                        role_type = details.get('role_type', '未知').upper()
                        description = details.get('description') or "无描述"
                        
                        role_line = f"\n🔹 **`{alias}`** ({role_type}):\n   - 描述: {description}"

                        if role_type == 'STATIC':
                            content = details.get('static_content') or "(未设置)"
                            role_line += f"\n   - 内容: {content}"
                        elif role_type == 'AI':
                            prompt = details.get('system_prompt') or "(未设置)"
                            presets_json = details.get('preset_messages')
                            presets_summary = "(未设置)"
                            if presets_json:
                                try:
                                    presets = json.loads(presets_json)
                                    if isinstance(presets, list) and presets:
                                        presets_summary = f"({len(presets)} 条预设)"
                                    elif isinstance(presets, list) and not presets:
                                         presets_summary = "(空列表)"
                                    else:
                                        presets_summary = "(无效格式)"
                                except json.JSONDecodeError:
                                    presets_summary = "(无效JSON)"

                            role_line += f"\n   - 系统提示: {prompt}"
                            role_line += f"\n   - 预设消息: {presets_summary}"
                        
                        response_lines.append(role_line)

                    await self._safe_respond(event, "\n".join(response_lines))

            elif command == "aliasrole":
                # 手动解析参数，因为 shlex.split 已经处理了引号
                alias = None
                role_type = None
                static_content = None
                type_index = -1

                # 查找 --type 参数
                try:
                    type_index = args.index("--type")
                    if type_index + 1 < len(args):
                        role_type = args[type_index + 1].lower()
                        if role_type not in ('static', 'ai'):
                            raise ValueError("类型必须是 'static' 或 'ai'")
                    else:
                        raise ValueError("--type 参数后需要指定类型 ('static' 或 'ai')")
                except ValueError:
                    await self._safe_respond(event, "错误：缺少或无效的 `--type` 参数。\n用法: `.aliasrole <别名> [--type <static|ai>] [\"<内容>\"]`")
                    return

                # 提取别名和可能的静态内容
                if type_index == 0: # --type 是第一个参数，缺少别名
                     await self._safe_respond(event, "错误：缺少角色别名。\n用法: `.aliasrole <别名> --type <static|ai> [\"<内容>\"]`")
                     return
                elif type_index > 0:
                    alias = args[0]
                    # 别名和 --type 之间的参数被视为静态内容（如果类型是 static）
                    if role_type == 'static' and type_index > 1:
                        static_content = " ".join(args[1:type_index])
                    elif role_type == 'ai' and type_index > 1:
                         await self._safe_respond(event, "错误：AI 类型的角色别名不应提供静态内容参数。")
                         return
                else: # 不应该发生，因为前面已经处理了 type_index < 0 的情况
                    await self._safe_respond(event, "错误：无法解析指令参数。")
                    return

                # 验证别名格式
                if not alias or not alias.isalnum() and not (alias.replace('-', '').isalnum() and '-' in alias):
                    await self._safe_respond(event, f"错误：别名 '{alias}' 格式无效。别名只能包含字母、数字和连字符(-)。")
                    return

                # 检查静态内容是否提供（对于 static 类型）
                if role_type == 'static' and static_content is None:
                    await self._safe_respond(event, "错误：Static 类型的角色别名需要提供静态回复文本。\n用法: `.aliasrole <别名> \"<静态回复文本>\" --type static`")
                    return

                # 调用服务创建别名
                success = await self.state_service.create_role_alias(
                    alias=alias,
                    role_type=role_type,
                    static_content=static_content # 如果是 ai 类型，此值为 None
                )

                if success:
                    if role_type == 'static':
                        logger.info(f"已创建静态角色别名 '{alias}' 并设置内容。")
                        await self._safe_respond(event, f"✅ 已创建静态角色别名 '{alias}' 并设置内容。")
                    else: # role_type == 'ai'
                        logger.info(f"已创建 AI 角色别名 '{alias}'。")
                        await self._safe_respond(event, f"✅ 已创建 AI 角色别名 '{alias}'。")
                else:
                    # 失败可能是因为别名已存在或数据库错误
                    logger.error(f"创建角色别名 '{alias}' (类型: {role_type}) 失败。")
                    await self._safe_respond(event, f"❌ 创建角色别名 '{alias}' 失败。别名可能已存在，或发生数据库错误。")

            elif command == "setroledesc":
                # 参数验证
                if len(args) < 2:
                    await self._safe_respond(event, "错误：`.setroledesc` 指令需要两个参数。\n用法: `.setroledesc <别名> \"<角色描述文本>\"`")
                    return
                
                alias = args[0]
                # 将剩余参数合并为描述（以防描述中有空格且未用引号包裹）
                description = " ".join(args[1:])

                # 检查角色别名是否存在（可选但推荐，服务层也会检查）
                role_details = await self.state_service.resolve_role_details(alias)
                if not role_details:
                    await self._safe_respond(event, f"错误：角色别名 '{alias}' 不存在。")
                    return

                # 设置角色描述
                success = await self.state_service.set_role_description(alias, description)

                if success:
                    logger.info(f"已更新角色 '{alias}' 的描述。")
                    await self._safe_respond(event, f"✅ 已更新角色 '{alias}' 的描述。")
                else:
                    # 失败可能是因为别名不存在或数据库错误
                    logger.error(f"设置角色 '{alias}' 的描述失败。")
                    await self._safe_respond(event, f"❌ 设置角色 '{alias}' 的描述失败（可能是数据库错误）。")

            elif command == "setrolepreset":
                # 参数验证
                if len(args) < 2:
                    await self._safe_respond(event, "错误：`.setrolepreset` 指令需要两个参数。\n用法: `.setrolepreset <别名> '<JSON格式的预设消息列表>'`")
                    return
                
                alias = args[0]
                # 将剩余参数合并为 JSON 字符串（假设 JSON 用单引号包裹或不含空格）
                # shlex 会处理引号，所以这里直接合并
                presets_json = " ".join(args[1:])

                # 验证 JSON 格式
                try:
                    # 尝试解析 JSON 以验证其有效性
                    parsed_presets = json.loads(presets_json)
                    # 进一步验证是否为列表（可选，但推荐）
                    if not isinstance(parsed_presets, list):
                         raise ValueError("预设消息必须是一个 JSON 列表。")
                    # 可以在这里添加对列表内容的更详细验证，例如检查每个元素是否为 {"role": "...", "content": "..."} 格式
                    
                except json.JSONDecodeError as e:
                    logger.warning(f"为角色 '{alias}' 设置的预设消息 JSON 格式无效: {e}")
                    await self._safe_respond(event, f"错误：提供的预设消息不是有效的 JSON 格式。\n请确保使用正确的 JSON 语法，并用单引号包裹整个 JSON 字符串（如果包含空格）。\n错误详情: {e}")
                    return
                except ValueError as e: # 捕获自定义的验证错误
                    logger.warning(f"为角色 '{alias}' 设置的预设消息内容无效: {e}")
                    await self._safe_respond(event, f"错误：预设消息内容无效。\n{e}")
                    return

                # 检查角色别名是否存在
                role_details = await self.state_service.resolve_role_details(alias)
                if not role_details:
                    await self._safe_respond(event, f"错误：角色别名 '{alias}' 不存在。")
                    return
                
                # 检查角色类型是否为 AI
                if role_details.get('role_type') != 'ai':
                    await self._safe_respond(event, f"错误：角色 '{alias}' 不是 AI 类型，无法设置预设消息。")
                    return

                # 设置预设消息
                # 注意：服务层现在不进行 JSON 验证，所以这里的验证很重要
                success = await self.state_service.set_role_preset_messages(alias, presets_json)

                if success:
                    logger.info(f"已更新角色 '{alias}' 的预设消息。")
                    await self._safe_respond(event, f"✅ 已更新角色 '{alias}' 的预设消息。")
                else:
                    # 失败可能是因为别名不存在或数据库错误
                    logger.error(f"设置角色 '{alias}' 的预设消息失败。")
                    await self._safe_respond(event, f"❌ 设置角色 '{alias}' 的预设消息失败（可能是数据库错误）。")

            elif command == "unaliasrole":
                # 参数验证
                if len(args) != 1:
                    await self._safe_respond(event, "错误：`.unaliasrole` 指令需要一个参数。\n用法: `.unaliasrole <别名>`")
                    return

                alias = args[0]

                # 检查别名是否存在（可选，服务层也会检查，但提前检查可以提供更友好的错误信息）
                role_details = await self.state_service.resolve_role_details(alias)
                if not role_details:
                    await self._safe_respond(event, f"错误：角色别名 '{alias}' 不存在。")
                    return
                
                # 检查是否正在删除当前使用的角色
                current_role = self.state_service.get_current_role_alias()
                if alias == current_role:
                    await self._safe_respond(event, f"⚠️ 警告：你正在删除当前使用的角色 '{alias}'。\n请稍后使用 `.setrole` 选择一个新角色。")
                    # 注意：这里不阻止删除，只是提醒用户

                # 删除角色别名
                success = await self.state_service.remove_role_alias(alias)

                if success:
                    logger.info(f"已删除角色别名 '{alias}'。")
                    await self._safe_respond(event, f"✅ 角色别名 '{alias}' 已删除。")
                else:
                    # 失败可能是因为别名不存在（虽然我们检查了）或数据库错误
                    logger.error(f"删除角色别名 '{alias}' 失败。")
                    await self._safe_respond(event, f"❌ 删除角色别名 '{alias}' 失败（可能是数据库错误）。")

            elif command == "addgroup":
                # 参数验证
                if len(args) != 1:
                    await self._safe_respond(event, "错误：`.addgroup` 指令需要一个参数。\n用法: `.addgroup <群组ID或群组链接>`")
                    return

                group_ref = args[0]
                entity = None
                chat_id = None
                group_title = group_ref # 默认标题为用户输入

                try:
                    # 尝试解析为整数 ID
                    try:
                        chat_id_int = int(group_ref)
                        # 对于负数 ID，Telethon 通常需要 -100 前缀，但 get_entity 可以处理
                        entity = await self.client.get_entity(chat_id_int)
                    except ValueError:
                        # 如果不是整数，则尝试作为链接或用户名处理
                        entity = await self.client.get_entity(group_ref)

                    # 验证实体类型
                    if not isinstance(entity, (types.Chat, types.Channel)):
                        await self._safe_respond(event, f"错误：'{group_ref}' 不是一个有效的群组或频道。")
                        return

                    chat_id = entity.id
                    group_title = entity.title

                except (ValueError, errors.UsernameInvalidError, errors.ChannelPrivateError, errors.ChatAdminRequiredError, errors.UserDeactivatedError, errors.AuthKeyError, errors.UserBannedInChannelError) as e:
                    logger.warning(f"无法解析或访问群组 '{group_ref}': {e}")
                    await self._safe_respond(event, f"错误：无法找到或访问群组/频道 '{group_ref}'。\n请确保 ID/链接正确，且你有权限访问。\n错误详情: {type(e).__name__}")
                    return
                except Exception as e: # 捕获其他可能的 Telethon 或网络错误
                    logger.error(f"获取群组实体 '{group_ref}' 时发生意外错误: {e}", exc_info=True)
                    await self._safe_respond(event, f"错误：获取群组信息时发生意外错误。请检查日志。")
                    return

                # 添加到目标列表
                if chat_id is not None:
                    success = await self.state_service.add_group(chat_id)
                    if success:
                        logger.info(f"已将群组 '{group_title}' (ID: {chat_id}) 添加到目标列表。")
                        await self._safe_respond(event, f"✅ 群组 '{group_title}' 已添加到目标列表。")
                    else:
                        # 可能是数据库错误，或者群组已存在（add_group 返回 False）
                        # 检查群组是否已存在
                        if chat_id in self.state_service.get_target_group_ids():
                             await self._safe_respond(event, f"ℹ️ 群组 '{group_title}' 已在目标列表中。")
                        else:
                            logger.error(f"添加目标群组 {chat_id} ('{group_title}') 到数据库时失败。")
                            await self._safe_respond(event, f"❌ 添加群组 '{group_title}' 失败（可能是数据库错误）。")
                else:
                    # 理论上不应到达这里，因为前面有检查
                    logger.error(f"未能从实体 '{group_ref}' 中提取 chat_id。")
                    await self._safe_respond(event, f"错误：无法处理群组 '{group_ref}'。")

            elif command == "delgroup":
                # 参数验证
                if len(args) != 1:
                    await self._safe_respond(event, "错误：`.delgroup` 指令需要一个参数。\n用法: `.delgroup <群组ID或群组链接>`")
                    return

                group_ref = args[0]
                chat_id = None
                group_title = group_ref # 默认标题为用户输入

                # 尝试解析 chat_id
                try:
                    # 尝试直接解析为整数 ID
                    try:
                        chat_id_int = int(group_ref)
                        # 尝试获取实体以验证 ID 并获取名称
                        try:
                            entity = await self.client.get_entity(chat_id_int)
                            if isinstance(entity, (types.Chat, types.Channel)):
                                chat_id = entity.id
                                group_title = entity.title
                            else:
                                # 是有效实体但不是群组/频道，也认为 ID 无效
                                await self._safe_respond(event, f"错误：ID '{group_ref}' 对应的实体不是群组或频道。")
                                return
                        except (ValueError, errors.RPCError) as e:
                            # 获取实体失败，但 ID 是整数，可能群组不存在或无权访问
                            # 仍然尝试使用该 ID 删除，因为可能之前添加过但现在无法访问
                            logger.warning(f"无法获取群组实体 (ID: {chat_id_int})，但仍尝试使用此 ID 删除: {e}")
                            chat_id = chat_id_int
                            # group_title 保持为原始输入 ID
                        
                    except ValueError:
                        # 不是整数，尝试作为链接或用户名处理
                        try:
                            entity = await self.client.get_entity(group_ref)
                            if isinstance(entity, (types.Chat, types.Channel)):
                                chat_id = entity.id
                                group_title = entity.title
                            else:
                                await self._safe_respond(event, f"错误：'{group_ref}' 不是一个有效的群组或频道。")
                                return
                        except (ValueError, errors.RPCError) as e:
                            logger.warning(f"无法解析或访问群组 '{group_ref}': {e}")
                            await self._safe_respond(event, f"错误：无法找到或访问群组/频道 '{group_ref}'。\n请确保 ID/链接正确。\n错误详情: {type(e).__name__}")
                            return
                        
                except Exception as e: # 捕获其他意外错误
                    logger.error(f"解析群组引用 '{group_ref}' 时发生意外错误: {e}", exc_info=True)
                    await self._safe_respond(event, f"错误：处理群组引用时发生意外错误。请检查日志。")
                    return

                # 执行删除
                if chat_id is not None:
                    success = await self.state_service.remove_group(chat_id)
                    if success:
                        logger.info(f"已将群组 '{group_title}' (ID: {chat_id}) 从目标列表移除。")
                        await self._safe_respond(event, f"✅ 群组 '{group_title}' 已从目标列表移除。")
                    else:
                        # 可能是数据库错误，或者群组原本就不在列表中
                        if chat_id not in self.state_service.get_target_group_ids():
                             await self._safe_respond(event, f"ℹ️ 群组 '{group_title}' 不在目标列表中。")
                        else:
                            logger.error(f"从数据库移除目标群组 {chat_id} ('{group_title}') 时失败。")
                            await self._safe_respond(event, f"❌ 移除群组 '{group_title}' 失败（可能是数据库错误）。")
                else:
                    # 如果 chat_id 仍然是 None，说明解析失败
                    logger.error(f"未能从输入 '{group_ref}' 中解析出有效的 chat_id 进行删除。")
                    # 此处错误已在 try...except 中处理并返回给用户，理论上不会执行到这里
                    # 但为保险起见，添加一个通用错误
                    await self._safe_respond(event, f"错误：无法处理输入 '{group_ref}' 以进行删除。")

            elif command == "listgroups":
                # 参数验证
                if args:
                    await self._safe_respond(event, "错误：`.listgroups` 指令不需要参数。")
                    return

                target_group_ids = self.state_service.get_target_group_ids()

                if not target_group_ids:
                    await self._safe_respond(event, "ℹ️ 当前没有设置任何目标群组。\n\n你可以使用 `.addgroup <群组ID或链接>` 来添加。")
                else:
                    response_lines = ["🎯 **当前目标群组列表**："]
                    # 按 ID 排序（可选，但更一致）
                    sorted_group_ids = sorted(list(target_group_ids))

                    for chat_id in sorted_group_ids:
                        group_name = f"ID: {chat_id}" # 默认显示 ID
                        try:
                            entity = await self.client.get_entity(chat_id)
                            if isinstance(entity, (types.Chat, types.Channel)):
                                group_name = f"'{entity.title}' ({chat_id})"
                            else:
                                group_name = f"未知类型实体 ({chat_id})"
                        except (ValueError, errors.RPCError) as e:
                            logger.warning(f"获取目标群组 {chat_id} 信息时出错: {e}")
                            group_name = f"无法访问的群组 ({chat_id})"
                        except Exception as e:
                            logger.error(f"获取目标群组 {chat_id} 信息时发生意外错误: {e}", exc_info=True)
                            group_name = f"获取信息出错 ({chat_id})"
                        
                        response_lines.append(f"- {group_name}")

                    await self._safe_respond(event, "\n".join(response_lines))


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
