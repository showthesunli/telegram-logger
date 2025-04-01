
# --- 导入 ---
import logging
import pickle
# 如果不再直接使用 os, re, traceback，则移除
from typing import Optional, Union, List, Dict, Any
from telethon import events, errors
from telethon.tl.types import Message as TelethonMessage # 如果类型提示需要，则保留
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
from telegram_logger.utils.media import save_media_as_file # 如果在 _create_message_object 中使用，则保留
from telegram_logger.utils.mentions import create_mention # 如果在 _create_message_object 中使用，则保留

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
        use_markdown_format: bool = False,
        **kwargs: Dict[str, Any] # 添加 **kwargs 以匹配 BaseHandler（如果需要）
    ):
        # 正确调用 super().__init__
        super().__init__(client, db, log_chat_id, ignored_ids, **kwargs)

        self.forward_user_ids = forward_user_ids or []
        self.forward_group_ids = forward_group_ids or []
        # 如果此类中的逻辑需要，则保留 use_markdown_format
        self.use_markdown_format = use_markdown_format

        # 实例化辅助类
        self.formatter = MessageFormatter(client, use_markdown_format)
        self.sender = LogSender(client, log_chat_id)
        self.media_handler = RestrictedMediaHandler(client)
        logger.info(
            f"ForwardHandler 初始化，转发用户 ID: {self.forward_user_ids}"
        )
        logger.info(
            f"ForwardHandler 初始化，转发群组 ID: {self.forward_group_ids}"
        )
        logger.info(
            f"ForwardHandler 初始化，使用 Markdown 格式: {self.use_markdown_format}" # <- 修改这一行
        )

    def set_client(self, client):
        """设置 Telethon 客户端实例并更新内部组件。"""
        super().set_client(client) # 调用父类的方法设置 self.client
        # 更新依赖客户端的内部组件
        if hasattr(self, 'sender') and self.sender:
            self.sender.client = client
            logger.debug("ForwardHandler 中 LogSender 的客户端已更新")
        if hasattr(self, 'formatter') and self.formatter:
            self.formatter.client = client
            logger.debug("ForwardHandler 中 MessageFormatter 的客户端已更新")
        if hasattr(self, 'media_handler') and self.media_handler:
            self.media_handler.client = client
            logger.debug("ForwardHandler 中 RestrictedMediaHandler 的客户端已更新")
        logger.debug(f"{self.__class__.__name__} 的客户端已设置")

    # --- 移除旧的私有辅助方法 ---
    # 移除: _format_forward_message_text
    # 移除: _is_sticker (现在在 formatter 中)
    # 移除: _has_noforwards (现在在 formatter 中)
    # 移除: _send_to_log_channel (现在在 sender 中)
    # 移除: _send_sticker_message
    # 移除: _send_restricted_media
    # 移除: _send_non_restricted_media
    # 移除: _send_forwarded_message

    # --- 保留 handle_new_message ---
    async def handle_new_message(self, event):
        """处理新消息事件，这个方法名与client.py中的注册方法匹配"""
        if not self.client:
            logger.error("Handler 未初始化，client 为 None")
            return None

        from_id = self._get_sender_id(event.message) # 使用 BaseHandler 的方法
        chat_id = event.chat_id
        logger.info(
            f"ForwardHandler 收到来自用户 {from_id} 在聊天 {chat_id} 中的消息"
        )
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

            # 确定发送时的解析模式
            parse_mode = "md" if self.use_markdown_format else None

            # 准备要发送的文本（如果需要，应用 markdown 代码块）
            # 如果启用了 markdown，formatted_text 已经转换了链接
            text_to_send = f"```markdown\n{formatted_text}\n```" if self.use_markdown_format else formatted_text

            # 2. 根据媒体类型处理发送
            message = event.message
            if not message.media:
                # 纯文本消息
                logger.info("发送纯文本消息。")
                await self.sender.send_message(text=text_to_send, parse_mode=parse_mode)
            else:
                # 带媒体的消息
                # 使用 formatter 的辅助方法检查类型
                is_sticker = self.formatter._is_sticker(message)
                has_noforwards = self.formatter._has_noforwards(message)

                if is_sticker:
                    logger.info("处理贴纸消息。")
                    # 首先发送文本部分（可能带有 markdown）
                    text_sent = await self.sender.send_message(text=text_to_send, parse_mode=parse_mode)
                    if text_sent:
                        # 发送带有空标题的贴纸文件
                        sticker_sent = await self.sender.send_message(text="", file=message.media)
                        if not sticker_sent:
                            logger.error("发送文本后未能发送贴纸文件。")
                            await self.sender._send_minimal_error("⚠️ 注意：未能发送贴纸文件本身。") # 使用 sender 的辅助方法
                    else:
                        logger.warning("由于文本部分发送失败，跳过贴纸文件。")

                elif has_noforwards:
                    logger.info("处理受限媒体。")
                    media_sent = False
                    error_note = ""
                    try:
                        # 使用 media handler 的上下文管理器
                        async with self.media_handler.prepare_media(message) as media_file:
                            logger.info(f"尝试发送解密文件: {getattr(media_file, 'name', 'unknown')}")
                            # 发送可能带有 markdown 格式的文本
                            media_sent = await self.sender.send_message(
                                text=text_to_send,
                                file=media_file,
                                parse_mode=parse_mode
                            )
                    except Exception as e:
                        logger.error(f"准备或发送受限媒体失败: {e}", exc_info=True)
                        error_note = f"\n  错误：处理受限媒体时发生异常 - {type(e).__name__}\n"

                    # 如果媒体发送失败，则仅发送带有错误注释的文本
                    if not media_sent:
                        logger.warning("由于错误，仅为受限媒体发送文本。")
                        # 在 markdown 包装之前，将错误注释添加到 *原始* 格式化文本中
                        text_with_error = formatted_text + error_note
                        # 如果需要，将 markdown 格式应用于组合的文本+错误
                        final_text = f"```markdown\n{text_with_error}\n```" if self.use_markdown_format else text_with_error
                        await self.sender.send_message(text=final_text, parse_mode=parse_mode)

                else:
                    # 非受限、非贴纸媒体
                    logger.info("处理非受限媒体。")
                    await self.sender.send_message(
                        text=text_to_send,
                        file=message.media,
                        parse_mode=parse_mode
                    )

            # 3. 创建并保存数据库消息对象（在此处保留此逻辑）
            db_message = await self._create_message_object(event)
            if db_message:
                await self.save_message(db_message) # 使用 BaseHandler 的 save_message
            return db_message # 返回创建的数据库对象

        except Exception as e:
            logger.error(f"处理或转发消息时发生严重错误: {str(e)}", exc_info=True)
            # 尝试使用 sender 发送错误通知
            try:
                error_message = f"⚠️ **错误:** 处理消息 {event.message.id} (来自 chat {event.chat_id}) 时出错。\n\n`{type(e).__name__}: {str(e)}`"
                # 使用 sender，确保为 markdown 设置了 parse_mode
                await self.sender.send_message(error_message, parse_mode="md")
            except Exception as send_err:
                logger.error(f"发送错误通知到日志频道失败: {send_err}")
            return None # 表示失败

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
                        media_path = await save_media_as_file(self.client, event.message)
                        logger.info(f"媒体文件尝试保存于: {media_path} (用于数据库记录)")
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
                media=media_content, # 存储 pickled 媒体
                noforwards=noforwards,
                self_destructing=self_destructing,
                created_time=event.message.date,
                edited_time=event.message.edit_date,
                msg_text=event.message.message,
            )
        except Exception as e:
            logger.error(f"创建 Message 对象失败: {e}", exc_info=True)
            return None

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
                 return 3 # 广播频道
             # 如果是超级群组（通常也被 is_group 捕获，但为了安全起见检查）
             elif hasattr(event.chat, "megagroup") and event.chat.megagroup:
                 return 2 # 超级群组视为群组
             else:
                 # 如果未明确识别为广播/超级群组，则为默认频道情况
                 return 3 # 频道
        return 0  # 未知类型
