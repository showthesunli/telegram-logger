# --- 导入 ---
import logging
import pickle

# 如果不再直接使用 os, re, traceback，则移除
from typing import Optional, Union, List, Dict, Any
from telethon import events, errors
from telethon import events, errors
from telethon.tl.types import Message as TelethonMessage  # 如果类型提示需要，则保留

# 如果 LogSender 处理了特定错误类型，则移除
# from telethon.errors import MessageTooLongError, MediaCaptionTooLongError

# 导入 BaseHandler 和 Message 模型
from telegram_logger.handlers.base_handler import BaseHandler
from telegram_logger.data.models import Message

# 导入新模块
from .message_formatter import MessageFormatter
from .log_sender import LogSender
from .media_handler import RestrictedMediaHandler

# 如果仍然需要 utils 导入（例如，用于 _create_message_object），则保留
from telegram_logger.utils.media import (
    save_media_as_file,
)  # 如果在 _create_message_object 中使用，则保留
from telegram_logger.utils.mentions import (
    create_mention,
)  # 如果在 _create_message_object 中使用，则保留

logger = logging.getLogger(__name__)


class ForwardHandler(BaseHandler):
    def __init__(
        self,
        client,
        db,
        log_chat_id,
        ignored_ids,
        forward_user_ids=None,
        forward_group_ids=None,
        # use_markdown_format: bool = False, # <- 删除这一行
        **kwargs: Dict[str, Any],  # 添加 **kwargs 以匹配 BaseHandler（如果需要）
    ):
        # 正确调用 super().__init__
        super().__init__(client, db, log_chat_id, ignored_ids, **kwargs)

        self.forward_user_ids = forward_user_ids or []
        self.forward_group_ids = forward_group_ids or []
        # self.use_markdown_format = use_markdown_format # <- 删除这一行

        # 实例化辅助类
        # 删除 use_markdown_format 参数
        self.formatter = MessageFormatter(client)  # <- 修改这里
        self.sender = LogSender(client, log_chat_id)
        self.media_handler = RestrictedMediaHandler(client)
        logger.info(f"ForwardHandler 初始化，转发用户 ID: {self.forward_user_ids}")
        logger.info(f"ForwardHandler 初始化，转发群组 ID: {self.forward_group_ids}")
        # logger.info( # <- 删除这个日志记录块
        #     f"ForwardHandler 初始化，使用 Markdown 格式: {self.use_markdown_format}"
        # )

    def set_client(self, client):
        """设置 Telethon 客户端实例并更新内部组件。"""
        super().set_client(client)  # 调用父类的方法设置 self.client
        # 更新依赖客户端的内部组件
        if hasattr(self, "sender") and self.sender:
            self.sender.client = client
            logger.debug("ForwardHandler 中 LogSender 的客户端已更新")
        if hasattr(self, "formatter") and self.formatter:
            self.formatter.client = client
            logger.debug("ForwardHandler 中 MessageFormatter 的客户端已更新")
        if hasattr(self, "media_handler") and self.media_handler:
            self.media_handler.client = client
            logger.debug("ForwardHandler 中 RestrictedMediaHandler 的客户端已更新")
        logger.debug(f"{self.__class__.__name__} 的客户端已设置")

    # --- 保留 handle_new_message ---
    async def handle_new_message(self, event):
        """处理新消息事件，这个方法名与client.py中的注册方法匹配"""
        if not self.client:
            logger.error("Handler 未初始化，client 为 None")
            return None

        from_id = self._get_sender_id(event.message)  # 使用 BaseHandler 的方法
        chat_id = event.chat_id
        logger.info(f"ForwardHandler 收到来自用户 {from_id} 在聊天 {chat_id} 中的消息")
        # 调用重构后的 process 方法
        return await self.process(event)

    # --- 重构后的 process 方法 ---
    async def process(self, event: events.NewMessage.Event) -> Optional[Message]:
        """处理转发消息"""
        from_id = self._get_sender_id(event.message)
        chat_id = event.chat_id

        is_target_user = from_id in self.forward_user_ids
        is_target_group = chat_id in self.forward_group_ids

        logger.info(
            f"处理消息 - 用户ID: {from_id}, 聊天ID: {chat_id}, 是目标用户: {is_target_user}, 是目标群组: {is_target_group}"
        )

        if not (is_target_user or is_target_group):
            logger.debug("消息不是来自目标用户或群组，跳过")
            return None

        try:
            # 1. 使用 formatter 格式化消息文本
            # 如果 use_markdown_format 为 true，formatter 会在内部处理链接转换
            formatted_text = await self.formatter.format_message(event)

            # 删除 parse_mode
            # parse_mode = "md" if self.use_markdown_format else None # <- 删除这一行

            # 准备要发送的文本 (移除 markdown 代码块)
            text_to_send = formatted_text  # <- 修改这里

            # 2. 根据媒体类型处理发送
            message = event.message
            if not message.media:
                # 纯文本消息
                logger.info("发送纯文本消息。")
                # 添加 parse_mode="md"
                await self.sender.send_message(text=text_to_send, parse_mode="md")
            else:
                # 带媒体的消息
                # 使用 formatter 的辅助方法检查类型
                is_sticker = self.formatter._is_sticker(message)
                has_noforwards = self.formatter._has_noforwards(message)

                if is_sticker:
                    logger.info("处理贴纸消息。")
                    # 删除 parse_mode
                    text_sent = await self.sender.send_message(
                        text=text_to_send  # <- 修改这里
                    )
                    if text_sent:
                        # 发送带有空标题的贴纸文件
                        sticker_sent = await self.sender.send_message(
                            text="", file=message.media
                        )
                        if not sticker_sent:
                            logger.error("发送文本后未能发送贴纸文件。")
                            await self.sender._send_minimal_error(
                                "⚠️ 注意：未能发送贴纸文件本身。"
                            )  # 使用 sender 的辅助方法
                    else:
                        logger.warning("由于文本部分发送失败，跳过贴纸文件。")

                elif has_noforwards:
                    logger.info("处理受限媒体。")
                    media_sent = False
                    error_note = ""
                    try:
                        # 使用 media handler 的上下文管理器
                        async with self.media_handler.prepare_media(
                            message
                        ) as media_file:
                            logger.info(
                                f"尝试发送解密文件: {getattr(media_file, 'name', 'unknown')}"
                            )
                            # 删除 parse_mode
                            media_sent = await self.sender.send_message(
                                text=text_to_send,
                                file=media_file,
                                # parse_mode=parse_mode, # <- 删除这一行
                            )
                    except Exception as e:
                        logger.error(f"准备或发送受限媒体失败: {e}", exc_info=True)
                        error_note = (
                            f"\n  错误：处理受限媒体时发生异常 - {type(e).__name__}\n"
                        )

                    # 如果媒体发送失败，则仅发送带有错误注释的文本
                    if not media_sent:
                        logger.warning("由于错误，仅为受限媒体发送文本。")
                        # 在 markdown 包装之前，将错误注释添加到 *原始* 格式化文本中
                        text_with_error = formatted_text + error_note
                        # 移除 markdown 格式
                        final_text = text_with_error  # <- 修改这里
                        # 删除 parse_mode
                        await self.sender.send_message(text=final_text)  # <- 修改这里

                else:
                    # 非受限、非贴纸媒体
                    logger.info("处理非受限媒体。")
                    # 删除 parse_mode
                    await self.sender.send_message(
                        text=text_to_send, file=message.media  # <- 修改这里
                    )

            return

        except Exception as e:
            logger.error(f"处理或转发消息时发生严重错误: {str(e)}", exc_info=True)
            # 尝试使用 sender 发送错误通知 (移除 markdown)
            try:
                # 移除 markdown 格式
                error_message = f"⚠️ 错误: 处理消息 {event.message.id} (来自 chat {event.chat_id}) 时出错。\n\n{type(e).__name__}: {str(e)}"  # <- 修改这里
                # 删除 parse_mode
                await self.sender.send_message(error_message)  # <- 修改这里
            except Exception as send_err:
                logger.error(f"发送错误通知到日志频道失败: {send_err}")
            return None  # 表示失败

    # --- 保留 _create_message_object 和 get_chat_type ---
    # (确保 pickle, save_media_as_file 等导入存在，如果需要)
    async def _create_message_object(
        self, event: events.NewMessage.Event
    ) -> Optional[Message]:
        """创建用于数据库存储的消息对象 (保持原样，或优化媒体处理)"""
        from_id = self._get_sender_id(event.message)
        # 使用 formatter 的辅助方法以保持一致性
        noforwards = self.formatter._has_noforwards(event.message)

        self_destructing = False
        ttl_seconds = None
        try:
            ttl_seconds = getattr(
                getattr(event.message, "media", None), "ttl_seconds", None
            )
            if ttl_seconds:
                self_destructing = True
        except AttributeError:
            pass

        media_content = None
        # 决定是否仍然需要/想要为数据库保存媒体，尤其是在使用 RestrictedMediaHandler 的情况下
        # 也许只存储元数据而不是 pickled 对象或文件路径？
        # 目前，保留现有逻辑，但要注意冗余/潜在问题。
        if event.message.media:
            try:
                # 示例：仅在受限/自毁时尝试保存以用于日志记录目的
                media_path = None
                if noforwards or self_destructing:
                    try:
                        # 如果 RestrictedMediaHandler 没有缓存/重用，这可能会再次下载
                        media_path = await save_media_as_file(
                            self.client, event.message
                        )
                        logger.info(
                            f"媒体文件尝试保存于: {media_path} (用于数据库记录)"
                        )
                    except Exception as save_err:
                        logger.warning(f"为数据库记录保存媒体文件失败: {save_err}")

                # 序列化媒体对象（考虑替代方案）
                try:
                    media_content = pickle.dumps(event.message.media)
                except (pickle.PicklingError, TypeError) as pe:
                    logger.warning(f"序列化媒体对象失败: {pe}. 将存储 None.")
                    media_content = None

            except Exception as e:
                logger.error(f"为数据库记录处理媒体时出错: {str(e)}")
                media_content = None

        # 获取聊天类型
        chat_type_code = await self.get_chat_type(event)

        try:
            return Message(
                id=event.message.id,
                from_id=from_id,
                chat_id=event.chat_id,
                msg_type=chat_type_code,
                media=media_content,  # 存储 pickled 媒体
                noforwards=noforwards,
                self_destructing=self_destructing,
                created_time=event.message.date,
                edited_time=event.message.edit_date,
                msg_text=event.message.message,
            )
        except Exception as e:
            logger.error(f"创建 Message 对象失败: {e}", exc_info=True)
            return None

    async def handle_message_edited(self, event: events.MessageEdited.Event):
        """处理来自被监控用户或群组的已编辑消息，并转发。"""
        message = event.message
        # 尝试获取发送者ID，如果不可用则为 None
        sender_id = getattr(message.sender, 'id', None)
        chat_id = message.chat_id

        # 检查消息是否来自需要转发的用户或群组
        # 注意：对于频道消息，sender_id 可能为 None，此时仅依赖 chat_id
        should_forward = (sender_id is not None and sender_id in self.forward_user_ids) or \
                         (chat_id in self.forward_group_ids)

        if should_forward:
            try:
                # 直接转发编辑后的消息
                await self.client.forward_messages(
                    self.log_chat_id,
                    messages=message.id,
                    from_peer=message.peer_id
                )
                logger.info(f"Forwarded edited message {message.id} from {sender_id or chat_id} to {self.log_chat_id}")
            except errors.MessageIdInvalidError:
                 logger.warning(f"Could not forward edited message {message.id}: Message ID invalid (possibly deleted or inaccessible).")
            except Exception as e:
                logger.error(f"Failed to forward edited message {message.id}: {e}", exc_info=True)
                # 尝试发送错误通知
                try:
                    error_text = f"⚠️ Failed to forward edited message {message.id} from chat {chat_id}. Error: {type(e).__name__}"
                    await self.sender.send_message(error_text)
                except Exception as send_err:
                    logger.error(f"Failed to send error notification about edited message forwarding: {send_err}")
        else:
             # 可选：添加调试日志，说明为何未转发
             logger.debug(f"Ignoring edited message {message.id}: sender {sender_id}, chat {chat_id} not in forward lists.")

    async def handle_message_deleted(self, event: events.MessageDeleted.Event):
        """处理来自被监控群组的消息删除事件，并发送通知。"""
        # MessageDeletedEvent 的 chat_id 属性可能为 None，需要从 peer 获取
        chat_id = event.chat_id
        if chat_id is None and event.peer:
             # 尝试从 peer 属性获取 chat_id (可能是负数)
             if hasattr(event.peer, 'channel_id'):
                 chat_id = -1000000000000 - event.peer.channel_id # Telethon 约定
             elif hasattr(event.peer, 'chat_id'):
                 chat_id = -event.peer.chat_id # Telethon 约定

        deleted_ids = event.deleted_ids

        # 确保我们获得了有效的 chat_id
        if chat_id is None:
            logger.warning(f"Could not determine chat_id for deletion event with IDs: {deleted_ids}. Skipping.")
            return

        # 仅当删除事件发生在被监控的群组时才处理
        if chat_id in self.forward_group_ids:
            try:
                # 为被监控的群组创建提及链接
                chat_mention = await create_mention(self.client, chat_id)
                # 构建通知文本
                text = (
                    f"🗑️ **Deleted Message(s) Notification**\n"
                    f"In Chat: {chat_mention}\n"
                    f"Message IDs: {', '.join(map(str, deleted_ids))}"
                )
                # 使用 LogSender 发送文本通知到日志频道
                await self.sender.send_message(text=text, parse_mode="md") # 使用 Markdown
                logger.info(f"Sent deletion notification for chat {chat_id} (IDs: {deleted_ids}) to {self.log_chat_id}")
            except Exception as e:
                logger.error(f"Failed to send deletion notification for chat {chat_id}: {e}", exc_info=True)
                # 尝试发送最小错误通知
                try:
                    error_text = f"⚠️ Failed to send deletion notification for chat {chat_id}."
                    await self.sender._send_minimal_error(error_text)
                except Exception as send_err:
                    logger.error(f"Failed to send minimal error notification about deletion: {send_err}")
        else:
            # 可选：添加调试日志
            logger.debug(f"Ignoring deletion event in chat {chat_id}: not in forward group list.")

    async def get_chat_type(self, event) -> int:
        """获取聊天类型代码 (保持原样)"""
        if event.is_private:
            try:
                sender = await event.get_sender()
                if sender and sender.bot:
                    return 4  # 机器人
                return 1  # 用户
            except Exception as e:
                logger.warning(f"获取私聊发送者信息失败: {e}. 默认为 user.")
                return 1
        elif event.is_group:
            # 涵盖超级群组和基本群组
            return 2
        elif event.is_channel:
            # 如果 is_group 未捕获，则特别涵盖广播频道
            # 检查它是否明确是广播频道
            if hasattr(event.chat, "broadcast") and event.chat.broadcast:
                return 3  # 广播频道
            # 如果是超级群组（通常也被 is_group 捕获，但为了安全起见检查）
            elif hasattr(event.chat, "megagroup") and event.chat.megagroup:
                return 2  # 超级群组视为群组
            else:
                # 如果未明确识别为广播/超级群组，则为默认频道情况
                return 3  # 频道
        return 0  # 未知类型
