import logging
import shlex
import json  # 新增导入
import sqlite3  # 新增导入
from typing import Set, Dict, Any, Optional, List  # 增加 List

from telethon import (
    TelegramClient,
    events,
    errors as telethon_errors,
)  # 增加 errors as telethon_errors
from telethon.tl.types import Message as TelethonMessage

from .base_handler import BaseHandler
from telegram_logger.data.database import DatabaseManager
from telegram_logger.data.models import Message
from telegram_logger.services.user_bot_state import UserBotStateService
from telegram_logger.services.ai_service import AIService

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
        ai_service: AIService,
        log_chat_id: int,  # 从 BaseHandler 继承
        ignored_ids: Set[int],  # 从 BaseHandler 继承
        my_id: Optional[int] = None, # 移动到后面
        **kwargs: Dict[str, Any],
    ):
        """
        初始化 MentionReplyHandler。

        Args:
            client: Telethon 客户端实例。
            db: DatabaseManager 实例。
            state_service: UserBotStateService 实例。
            ai_service: AI 服务实例。
            log_chat_id: 日志频道 ID。
            ignored_ids: 忽略的用户/群组 ID。
            my_id: 用户自己的 Telegram ID (可选, 基类需要)。
            **kwargs: 其他传递给 BaseHandler 的参数。
        """
        # 调用父类构造函数，注意 UserBot 功能可能不需要 log_chat_id 和 ignored_ids
        # 调用父类构造函数
        super().__init__(
            client=client,
            db=db,
            log_chat_id=log_chat_id,
            ignored_ids=ignored_ids,
            my_id=my_id, # 传递 my_id
            **kwargs,
        )
        self.state_service = state_service
        self.ai_service = ai_service  # 注入 AI 服务实例
        my_id_status = f"my_id={my_id}" if my_id is not None else "my_id 未提供 (错误? MentionReply 需要 my_id)"
        logger.info(f"MentionReplyHandler 初始化完成。{my_id_status}")
        if my_id is None:
            logger.error("MentionReplyHandler 初始化时未提供 my_id，可能导致后续操作失败！")


    async def init(self):
        """异步初始化，获取并设置 my_id。"""
        if self.client and not hasattr(self, "my_id"):
            try:
                me = await self.client.get_me()
                if me:
                    self.my_id = me.id
                    logger.info(
                        f"MentionReplyHandler 初始化完成，获取到 my_id: {self.my_id}"
                    )
                else:
                    logger.error(
                        "MentionReplyHandler 初始化失败：无法获取当前用户信息 (get_me 返回 None)。"
                    )
                    # 可能需要更健壮的处理，例如重试或退出
            except Exception as e:
                logger.error(
                    f"MentionReplyHandler 初始化获取 my_id 时发生错误: {e}",
                    exc_info=True,
                )
                # 处理初始化失败的情况
        elif hasattr(self, "my_id") and self.my_id is not None:
            logger.debug(f"MentionReplyHandler my_id ({self.my_id}) 已初始化。")
        elif not self.client:
            logger.error("MentionReplyHandler 初始化失败：client 未设置。")
        # 如果 my_id 已经存在，则不重新获取

    async def handle_event(self, event: events.NewMessage.Event):
        """
        处理新消息事件，判断是否需要自动回复。
        包含完整的错误处理逻辑。
        """
        try:
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
            # 注意：需要先获取 my_id
            if not hasattr(self, "my_id") or self.my_id is None:
                logger.warning(
                    "MentionReplyHandler 未初始化 my_id，无法检查是否为自己的消息。"
                )
                # 可以选择在这里 return 或者继续执行，取决于你的容错策略
                # return
            elif event.sender_id == self.my_id:
                logger.debug("事件来自自己，忽略。")
                return

            # --- 计算 is_reply_to_me ---
            is_mention = event.mentioned
            is_reply = event.is_reply
            replied_to_msg_id = event.reply_to_msg_id
            is_reply_to_me = False
            my_id = getattr(self, "my_id", None)  # 安全地获取 my_id

            logger.debug(
                f"事件详情: mentioned={is_mention}, is_reply={is_reply}, reply_to_msg_id={replied_to_msg_id}, my_id={my_id}"
            )

            if (
                is_reply and replied_to_msg_id and my_id is not None
            ):  # 增加 my_id is not None 检查
                try:
                    # 尝试从数据库获取被回复消息
                    replied_message_db = self.db.get_message_by_id(replied_to_msg_id)
                    if replied_message_db and replied_message_db.from_id == my_id:
                        is_reply_to_me = True
                        logger.debug(
                            f"从数据库确认: 消息 {event.id} 回复了我的消息 {replied_to_msg_id}"
                        )
                    elif replied_message_db:
                        logger.debug(
                            f"从数据库确认: 消息 {event.id} 回复了其他人 ({replied_message_db.from_id}) 的消息 {replied_to_msg_id}"
                        )
                    else:
                        # 如果数据库没有，再尝试 API 调用 (作为备选)
                        logger.debug(
                            f"数据库中未找到被回复消息 {replied_to_msg_id}，尝试 API 调用..."
                        )
                        replied_message_api = await event.get_reply_message()
                        if (
                            replied_message_api
                            and replied_message_api.sender_id == my_id
                        ):
                            is_reply_to_me = True
                            logger.debug(
                                f"从 API 确认: 消息 {event.id} 回复了我的消息 {replied_to_msg_id}"
                            )
                        elif replied_message_api:
                            logger.debug(
                                f"从 API 确认: 消息 {event.id} 回复了其他人 ({replied_message_api.sender_id}) 的消息 {replied_to_msg_id}"
                            )
                        else:
                            logger.warning(
                                f"无法获取被回复的消息 {replied_to_msg_id} 的详情"
                            )

                except telethon_errors.rpcerrorlist.MsgIdInvalidError:
                    logger.warning(
                        f"获取被回复消息 {replied_to_msg_id} 失败：消息 ID 无效或已被删除。"
                    )
                except Exception as e:
                    logger.warning(
                        f"获取或检查被回复消息 {replied_to_msg_id} 时出错: {e}",
                        exc_info=True,
                    )
                    # is_reply_to_me 保持 False
            elif my_id is None:
                logger.warning("无法计算 is_reply_to_me，因为 my_id 未设置。")

            # --- 根据 is_reply_trigger_enabled 决定触发逻辑 ---
            is_reply_trigger_enabled = self.state_service.is_reply_trigger_enabled()
            should_trigger = False  # 初始化触发标志

            if is_reply_trigger_enabled:
                # 规则: Flag 为 True 时，触发 "@提及" 或 "回复我"
                # 因为 "回复我" 必然导致 is_mention 为 True，所以条件简化为 is_mention
                if is_mention:
                    should_trigger = True
                    logger.debug(
                        f"触发条件满足 (reply_trigger=True): 消息提及了我 (is_mention=True)"
                    )
                else:
                    logger.debug(
                        f"触发条件不满足 (reply_trigger=True): 消息未提及我 (is_mention=False)"
                    )

            else:
                # 规则: Flag 为 False 时，触发 "@提及" 但 **不是** "回复我"
                if is_mention and not is_reply_to_me:
                    should_trigger = True
                    logger.debug(
                        f"触发条件满足 (reply_trigger=False): @提及且非回复我 (is_mention=True, is_reply_to_me=False)"
                    )
                else:
                    # 记录不触发的原因
                    if not is_mention:
                        logger.debug(
                            f"触发条件不满足 (reply_trigger=False): 事件未提及我 (is_mention=False)"
                        )
                    elif (
                        is_reply_to_me
                    ):  # is_mention is True here because is_reply_to_me implies is_mention
                        logger.debug(
                            f"触发条件不满足 (reply_trigger=False): 事件是回复我的消息 (is_reply_to_me=True)"
                        )
                    # else: # 理论上不会到这里

            # --- 如果不满足触发条件，则提前返回 ---
            if not should_trigger:
                logger.debug(
                    f"事件 (ID: {event.id}) 不满足基于 reply_trigger_enabled={is_reply_trigger_enabled} 的触发条件，忽略。"
                )
                return

            # --- 后续处理逻辑 ---

            # 5. 检查频率限制
            if not self.state_service.check_rate_limit(event.chat_id):
                logger.info(f"群组 {event.chat_id} 触发频率限制，本次忽略。")
                return

            # 6. 获取当前角色详情
            current_role_alias = self.state_service.get_current_role_alias()
            role_details = await self.state_service.resolve_role_details(
                current_role_alias
            )

            if not role_details:  # 检查返回值
                logger.error(
                    f"无法获取或解析当前角色 '{current_role_alias}' 的详情，无法生成回复。"
                )
                return

            logger.debug(
                f"使用角色 '{current_role_alias}' (类型: {role_details.get('role_type')}) 进行回复。"
            )

            # 7. 生成回复内容
            reply_text: Optional[str] = None
            role_type = role_details.get("role_type")

            if role_type == "static":
                reply_text = role_details.get("static_content")
                if not reply_text:
                    logger.warning(
                        f"静态角色 '{current_role_alias}' 没有设置回复内容，无法回复。"
                    )
                    return
                logger.debug(f"静态回复内容: '{reply_text[:50]}...'")

            elif role_type == "ai":
                # --- AI 回复逻辑 ---
                model_id = await self.state_service.resolve_model_id(
                    self.state_service.get_current_model_id()
                )
                if not model_id:  # 检查返回值
                    logger.error(
                        f"无法解析当前模型 '{self.state_service.get_current_model_id()}'，无法生成 AI 回复。"
                    )
                    return

                system_prompt = role_details.get("system_prompt")
                preset_messages_json = role_details.get("preset_messages")
                history_count = self.state_service.get_ai_history_length()
                current_message_text = event.message.text or ""  # 获取当前消息文本

                preset_messages: List[Dict[str, str]] = []
                if preset_messages_json:
                    try:
                        preset_messages = json.loads(preset_messages_json)
                        if not isinstance(preset_messages, list):
                            raise ValueError("预设消息 JSON 不是列表")
                        logger.debug(f"加载了 {len(preset_messages)} 条预设消息。")
                    except (json.JSONDecodeError, ValueError) as e:
                        logger.warning(
                            f"解析角色 '{current_role_alias}' 的预设消息失败: {e}，将忽略预设。"
                        )
                        preset_messages = []

                history_messages: List[Message] = []
                if history_count > 0:
                    try:  # 包裹数据库调用
                        # 注意：get_messages_before 返回的是按时间正序排列的列表
                        history_messages = await self.db.get_messages_before(
                            chat_id=event.chat_id,
                            before_message_id=event.message.id,
                            limit=history_count,
                        )
                        logger.debug(f"加载了 {len(history_messages)} 条历史消息。")
                    except sqlite3.Error as e:  # 捕获数据库错误
                        logger.error(
                            f"从数据库加载历史消息时发生 SQLite 错误: {e}",
                            exc_info=True,
                        )
                        return  # 数据库错误，终止处理
                    except Exception as e:  # 捕获其他可能的错误
                        logger.error(
                            f"从数据库加载历史消息时发生未知错误: {e}", exc_info=True
                        )
                        return  # 未知错误，终止处理

                # --- 构建发送给 AI 的消息列表 ---
                ai_messages: List[Dict[str, str]] = []

                # 1. 添加系统提示 (如果存在)
                if system_prompt:
                    ai_messages.append({"role": "system", "content": system_prompt})
                    logger.debug("已添加系统提示到 AI 消息列表。")

                # 2. 添加预设消息 (如果存在)
                ai_messages.extend(preset_messages)
                if preset_messages:
                    logger.debug(
                        f"已添加 {len(preset_messages)} 条预设消息到 AI 消息列表。"
                    )

                # 3. 添加历史消息 (按时间顺序)
                # 注意：数据库返回的是按时间倒序，需要反转
                for msg in reversed(history_messages):
                    # 假设 self.my_id 是机器人的 ID
                    # 使用数据库模型中的 from_id 属性
                    role = "assistant" if msg.from_id == self.my_id else "user"
                    content = (
                        msg.msg_text or "[空消息或非文本]"
                    )  # 确保有内容，使用 msg_text
                    ai_messages.append({"role": role, "content": content})
                if history_messages:
                    logger.debug(
                        f"已添加 {len(history_messages)} 条历史消息到 AI 消息列表。"
                    )

                # 4. 添加当前用户消息
                ai_messages.append({"role": "user", "content": current_message_text})
                logger.debug("已添加当前用户消息到 AI 消息列表。")

                # --- 调用 AI 服务 ---
                logger.debug(
                    f"准备调用 AI 模型 '{model_id}' 生成回复，共 {len(ai_messages)} 条消息。"
                )
                try:
                    reply_text = await self.ai_service.get_openai_completion(
                        model_id=model_id, messages=ai_messages
                    )
                    if reply_text is None:  # 检查返回值
                        logger.error(f"AI 模型 '{model_id}' 调用失败或返回了 None。")
                        return  # AI 调用失败，终止处理
                    elif not reply_text:
                        logger.warning(f"AI 模型 '{model_id}' 返回了空回复。")
                        reply_text = "抱歉，AI 暂时无法回复。"  # 提供一个默认回复
                    else:
                        logger.info(f"成功从 AI 模型 '{model_id}' 获取回复。")
                except Exception as e:  # 捕获 AI 服务内部未处理的异常 (理论上不应发生)
                    logger.error(f"调用 AI 服务时发生意外错误: {e}", exc_info=True)
                    return  # 意外错误，终止处理
                # --- AI 回复逻辑结束 ---

            else:
                logger.error(f"未知的角色类型 '{role_type}'，无法生成回复。")
                return

            if reply_text is None:  # 再次检查，确保 reply_text 已被赋值
                logger.error("未能生成有效的回复文本。")
                return

            logger.info(f"准备发送回复 (类型: {role_type})")

            # 8. 发送回复
            try:  # 包裹发送回复的调用
                await event.reply(reply_text)
                logger.info(
                    f"已成功发送回复到 ChatID={event.chat_id}, MsgID={event.id}"
                )

                # 9. 更新频率限制 (仅在发送成功后执行)
                self.state_service.update_rate_limit(event.chat_id)
                logger.debug(f"已更新群组 {event.chat_id} 的频率限制时间戳。")

            except (
                telethon_errors.rpcerrorlist.ChatWriteForbiddenError
            ) as e:  # 捕获特定权限错误
                logger.error(
                    f"发送回复到 ChatID={event.chat_id} 失败: 没有写入权限。 {e}",
                    exc_info=True,
                )
                # 权限问题，可能需要从目标群组移除？暂时只记录错误
            except telethon_errors.FloodWaitError as e:  # 捕获频率限制错误
                logger.warning(
                    f"发送回复到 ChatID={event.chat_id} 时遭遇 FloodWaitError: {e.seconds} 秒"
                )
                # 频率限制错误，不更新内部频率限制器状态
            except telethon_errors.RPCError as e:  # 捕获其他 Telegram RPC 错误
                logger.error(
                    f"发送回复到 ChatID={event.chat_id} 时发生 RPC 错误: {e}",
                    exc_info=True,
                )
            except Exception as e:  # 捕获其他意外错误
                logger.error(
                    f"发送回复到 ChatID={event.chat_id} 时发生未知错误: {e}",
                    exc_info=True,
                )
            # 发送失败不应阻止后续操作（如果有的话），但需要记录日志

        except Exception as e:  # 捕获顶层未处理异常
            logger.critical(
                f"MentionReplyHandler 处理事件时发生未捕获的异常: {e}", exc_info=True
            )
            # 确保处理流程安全终止
        return

    async def process(self, event: events.common.EventCommon) -> Optional[Message]:
        """
        覆盖 BaseHandler 的抽象方法。
        对于 MentionReplyHandler，主要逻辑在 handle_event 中，由 main.py 中的事件处理器直接调用。
        """
        # logger.debug("MentionReplyHandler.process 被调用，但无操作。")
        return None
