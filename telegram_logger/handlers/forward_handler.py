import logging
import pickle
import os  # 导入 os 模块以备将来可能的清理操作
import re  # 导入 re 模块用于链接转换
import traceback # For detailed error logging
from datetime import datetime
from typing import Optional, Union, List, Dict, Any
from telethon import events, errors
from telethon.tl.types import Message as TelethonMessage, DocumentAttributeSticker, MessageMediaDocument
from telethon.errors import MessageTooLongError, MediaCaptionTooLongError
from telegram_logger.handlers.base_handler import BaseHandler
from telegram_logger.utils.mentions import create_mention
from telegram_logger.data.models import Message

# 从 media 模块导入 _get_filename 函数
from telegram_logger.utils.media import (
    save_media_as_file,
    retrieve_media_as_file,
    _get_filename,
)

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
    ):
        super().__init__(client, db, log_chat_id, ignored_ids)
        self.forward_user_ids = forward_user_ids or []
        self.forward_group_ids = forward_group_ids or []
        self.use_markdown_format = use_markdown_format
        logger.info(
            f"ForwardHandler initialized with forward_user_ids: {self.forward_user_ids}"
        )
        logger.info(
            f"ForwardHandler initialized with forward_group_ids: {self.forward_group_ids}"
        )
        logger.info(
            f"ForwardHandler Markdown format enabled: {self.use_markdown_format}"
        )

    # --- 新增的辅助方法 ---

    async def _format_forward_message_text(self, event: events.NewMessage.Event) -> str:
        """Formats the text content for the forwarded message."""
        from_id = self._get_sender_id(event.message)
        mention_sender = await create_mention(self.client, from_id)
        mention_chat = await create_mention(
            self.client, event.chat_id, event.message.id
        )
        timestamp = event.message.date.strftime("%Y-%m-%d %H:%M:%S UTC")

        # Part 1: Source info
        text = f"{mention_sender} 在 {mention_chat} 中，于 {timestamp}，发言：\n\n"

        # Part 2: Message content
        message_text = event.message.text or getattr(event.message, "caption", None)
        if message_text:
            # Apply link conversion *before* wrapping in code block if markdown is used
            if self.use_markdown_format:
                try:
                    message_text = re.sub(
                        r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", message_text
                    )
                except Exception as re_err:
                    logger.warning(f"转换 Markdown 链接时出错: {re_err}")
            # Wrap the potentially modified text
            text += f"```\n{message_text}\n```"
        else:
            text += "[No text content or caption]"

        # Part 3: Media info section
        media_section = ""
        if event.message.media:
            media_section += "\n--------------------\n"
            media_section += "MEDIA:\n"
            is_sticker = self._is_sticker(event.message)
            media_type = "Sticker" if is_sticker else type(event.message.media).__name__.replace("MessageMedia", "")
            media_filename = None if is_sticker else _get_filename(event.message.media)

            media_section += f"  Type: {media_type}\n"
            if media_filename:
                media_section += f"  Filename: {media_filename}\n"

            noforwards = self._has_noforwards(event.message)
            if noforwards:
                media_section += "  Note: Restricted content. Media file will be handled separately.\n"

            ttl_seconds = getattr(getattr(event.message, "media", None), "ttl_seconds", None)
            if ttl_seconds:
                media_section += f"  Note: Self-destructing media (TTL: {ttl_seconds}s).\n"

        text += media_section
        text += "\n===================="
        return text

    def _is_sticker(self, message: TelethonMessage) -> bool:
        """Checks if the message media is a sticker."""
        if isinstance(message.media, MessageMediaDocument):
            doc = getattr(message.media, "document", None)
            if doc and hasattr(doc, "attributes"):
                return any(isinstance(attr, DocumentAttributeSticker) for attr in doc.attributes)
        return False

    def _has_noforwards(self, message: TelethonMessage) -> bool:
        """Checks if the message or its chat has noforwards set."""
        try:
            # Ensure message.chat is accessed safely
            chat_noforwards = getattr(message.chat, "noforwards", False) if message.chat else False
            message_noforwards = getattr(message, "noforwards", False)
            return chat_noforwards or message_noforwards
        except AttributeError:
             # This might happen if message object structure is unexpected
            logger.warning("AttributeError checking noforwards, defaulting to False", exc_info=True)
            return False

    async def _send_to_log_channel(self, text: str, file=None, parse_mode: Optional[str] = None) -> bool:
        """Sends a message or file to the log channel with error handling."""
        try:
            await self.client.send_message(
                self.log_chat_id,
                text,
                file=file,
                parse_mode=parse_mode
            )
            logger.debug(f"Successfully sent message/file to log channel {self.log_chat_id}.")
            return True
        except MessageTooLongError:
            logger.warning("Message text too long. Sending truncated version.")
            try:
                # Truncate text, preserving parse mode if possible
                limit = 4090 # Slightly less than 4096 for safety
                truncated_text = text[:limit] + "... [TRUNCATED]"
                # Re-apply markdown wrapper if needed (check original text format)
                if parse_mode == "md" and text.startswith("```markdown\n") and text.endswith("\n```"):
                     # Find the original content boundaries
                     original_content = text[len("```markdown\n"):-len("\n```")]
                     truncated_original = original_content[:limit - len("... [TRUNCATED]")] + "... [TRUNCATED]"
                     truncated_text = f"```markdown\n{truncated_original}\n```"
                elif parse_mode == "md" and text.startswith("```\n") and text.endswith("\n```"):
                     original_content = text[len("```\n"):-len("\n```")]
                     truncated_original = original_content[:limit - len("... [TRUNCATED]")] + "... [TRUNCATED]"
                     truncated_text = f"```\n{truncated_original}\n```"


                await self.client.send_message(
                    self.log_chat_id,
                    truncated_text,
                    file=file, # Still try sending file if present
                    parse_mode=parse_mode
                )
                logger.info("Successfully sent truncated message to log channel.")
                return True # Count as success even if truncated
            except Exception as e_trunc:
                logger.error(f"Failed to send truncated message: {e_trunc}", exc_info=True)
                # Try sending a minimal error message
                try:
                    await self.client.send_message(self.log_chat_id, "⚠️ Error: Original message was too long and could not be sent/truncated.")
                except Exception as e_min_err:
                     logger.error(f"Failed to send even the minimal error message: {e_min_err}")
                return False
        except MediaCaptionTooLongError:
            logger.warning("Media caption too long. Sending media without caption, then text separately.")
            try:
                # 1. Send file without caption
                await self.client.send_message(self.log_chat_id, file=file)
                # 2. Send text separately (might still be too long)
                caption_warning = "\n\n[Caption was too long and sent separately]"
                text_with_warning = text + caption_warning
                # Attempt to send the modified text (could trigger MessageTooLongError again)
                return await self._send_to_log_channel(text=text_with_warning, parse_mode=parse_mode)
            except Exception as e_fallback:
                logger.error(f"Failed during MediaCaptionTooLongError fallback: {e_fallback}", exc_info=True)
                try:
                    await self.client.send_message(self.log_chat_id, f"⚠️ Error: Media caption was too long, and fallback failed: {type(e_fallback).__name__}")
                except Exception as e_min_err:
                    logger.error(f"Failed to send even the minimal error message: {e_min_err}")
                return False
        except Exception as e:
            logger.error(f"Failed to send message/file to log channel: {e}", exc_info=True)
            # Try sending a minimal error message
            try:
                await self.client.send_message(self.log_chat_id, f"⚠️ Error sending message: {type(e).__name__}")
            except Exception as e_min_err:
                logger.error(f"Failed to send even the minimal error message: {e_min_err}")
            return False

    async def _send_sticker_message(self, message: TelethonMessage, formatted_text: str):
        """Handles sending sticker messages (text first, then sticker)."""
        logger.debug(f"Sending sticker message. Markdown: {self.use_markdown_format}")
        text_to_send = formatted_text
        parse_mode = None
        if self.use_markdown_format:
            # Apply markdown formatting *only* to the text part for stickers
            # The link conversion was already done in _format_forward_message_text
            # We need the raw formatted_text (with converted links) inside the markdown block
            text_to_send = f"```markdown\n{formatted_text}\n```"
            parse_mode = "md"

        # Send text part first
        logger.info("Sending sticker text part...")
        text_sent = await self._send_to_log_channel(text=text_to_send, parse_mode=parse_mode)

        # Send sticker file only if text was sent (or attempted)
        if text_sent:
            logger.info("Sending sticker file part...")
            # Send sticker with empty text caption to avoid potential caption errors
            sticker_sent = await self._send_to_log_channel(text="", file=message.media)
            if not sticker_sent:
                 logger.error("Failed to send sticker file after text was sent.")
                 # Optionally send a notification about the missing sticker file
                 await self._send_to_log_channel(text="⚠️ Note: Failed to send the sticker file itself.")
        else:
            logger.warning("Skipping sticker file because text part failed to send.")


    async def _send_restricted_media(self, message: TelethonMessage, formatted_text: str):
        """Handles downloading, decrypting, and sending restricted media."""
        logger.info("Handling restricted media.")
        file_path = None
        error_note = ""
        media_sent = False
        # Determine parse mode and text format based on use_markdown_format
        parse_mode = "md" if self.use_markdown_format else None
        # Apply markdown formatting *only* if enabled. Link conversion already done.
        text_to_send = f"```markdown\n{formatted_text}\n```" if self.use_markdown_format else formatted_text

        try:
            file_path = await save_media_as_file(self.client, message)
            if file_path:
                original_filename = _get_filename(message.media) or "restricted_media"
                logger.info(f"Restricted media saved to {file_path}. Original filename: {original_filename}")
                with retrieve_media_as_file(file_path, True) as media_file:
                    if media_file:
                        media_file.name = original_filename
                        logger.info(f"Attempting to send decrypted file: {media_file.name}")
                        # Send with the potentially markdown-formatted text
                        media_sent = await self._send_to_log_channel(
                            text=text_to_send,
                            file=media_file,
                            parse_mode=parse_mode # Use determined parse_mode
                        )
                    else:
                        logger.warning(f"Failed to retrieve/decrypt media from {file_path}")
                        error_note = "\n  Error: Failed to retrieve/decrypt restricted media file.\n"
            else:
                logger.warning("save_media_as_file failed for restricted media.")
                error_note = "\n  Error: Failed to save restricted media file.\n"

        except Exception as e:
            logger.error(f"Error processing restricted media: {e}", exc_info=True)
            error_note = f"\n  Error: Exception during restricted media handling - {type(e).__name__}: {e}\n"
        finally:
            # Optional: Cleanup temporary file
            # if file_path and os.path.exists(file_path):
            #     try: os.remove(file_path)
            #     except OSError as e: logger.error(f"Failed to clean up {file_path}: {e}")
            pass

        # If media sending failed or wasn't possible, send text with error note
        if not media_sent:
            logger.warning("Sending text only for restricted media due to previous errors.")
            # Add error note to the *original* formatted text before potential markdown wrapping
            text_with_error = formatted_text + error_note # Removed extra "====" as it's in formatted_text
            # Apply markdown formatting if needed to the combined text+error
            final_text = f"```markdown\n{text_with_error}\n```" if self.use_markdown_format else text_with_error
            await self._send_to_log_channel(text=final_text, parse_mode=parse_mode) # Use determined parse_mode


    async def _send_non_restricted_media(self, message: TelethonMessage, formatted_text: str):
        """Handles sending non-restricted, non-sticker media."""
        logger.debug(f"Sending non-restricted media. Markdown: {self.use_markdown_format}")
        # Determine parse mode and text format based on use_markdown_format
        parse_mode = "md" if self.use_markdown_format else None
        # Apply markdown formatting *only* if enabled. Link conversion already done.
        text_to_send = f"```markdown\n{formatted_text}\n```" if self.use_markdown_format else formatted_text

        await self._send_to_log_channel(
            text=text_to_send,
            file=message.media,
            parse_mode=parse_mode # Use determined parse_mode
        )

    async def _send_forwarded_message(self, event: events.NewMessage.Event, formatted_text: str):
        """Orchestrates sending the forwarded message based on its type."""
        message = event.message

        if not message.media:
            # Text-only message
            logger.info("Sending text-only message.")
            # Determine parse mode and text format based on use_markdown_format
            parse_mode = "md" if self.use_markdown_format else None
            # Apply markdown formatting *only* if enabled. Link conversion already done.
            text_to_send = f"```markdown\n{formatted_text}\n```" if self.use_markdown_format else formatted_text
            await self._send_to_log_channel(text=text_to_send, parse_mode=parse_mode)
        else:
            # Message with media
            is_sticker = self._is_sticker(message)
            has_noforwards = self._has_noforwards(message)

            # Pass the already formatted_text (with link conversions done) to helpers
            if is_sticker:
                await self._send_sticker_message(message, formatted_text)
            elif has_noforwards:
                await self._send_restricted_media(message, formatted_text)
            else:
                await self._send_non_restricted_media(message, formatted_text)

    # --- 现有方法继续 ---

    async def handle_new_message(self, event):
        """处理新消息事件，这个方法名与client.py中的注册方法匹配"""
        # 确保handler已初始化
        if not self.client:
            logger.error("Handler not initialized, client is None")
            return None

        from_id = self._get_sender_id(event.message)
        chat_id = event.chat_id
        logger.info(
            f"ForwardHandler received message from user {from_id} in chat {chat_id}"
        )
        return await self.process(event)

    async def process(self, event: events.NewMessage.Event) -> Optional[Message]:
        """处理转发消息"""
        from_id = self._get_sender_id(event.message)
        chat_id = event.chat_id

        # 检查是否来自目标用户或目标群组
        is_target_user = from_id in self.forward_user_ids
        is_target_group = chat_id in self.forward_group_ids

        logger.info(
            f"处理消息 - 用户ID: {from_id}, 聊天ID: {chat_id}, 是目标用户: {is_target_user}, 是目标群组: {is_target_group}"
        )

        if not (is_target_user or is_target_group):
            logger.debug("消息不是来自目标用户或群组，跳过")
            return None

        try:
            # 创建提及链接
            # create_mention should ideally return a formatted string like "[Name](link)" or "[ID](link)"
            mention_sender = await create_mention(self.client, from_id)
            mention_chat = await create_mention(
                self.client, event.chat_id, event.message.id
            )

            # 获取时间戳
            timestamp = event.message.date.strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )  # 使用UTC以保持一致

            # --- 第一部分: 消息来源信息 ---
            text = f"{mention_sender} 在 {mention_chat} 中，于 {timestamp}，发言：\n\n"

            # --- 第二部分: 消息内容 ---
            if event.message.text:
                text += f"```\n{event.message.text}\n```"  # 使用markdown格式包裹内容
            else:
                # 尝试获取媒体标题
                caption = getattr(event.message, "caption", None)
                if caption:
                    text += f"```\n{caption}\n```"  # 使用markdown格式包裹媒体标题
                else:
                    text += "[No text content or caption]"

            # 处理媒体指示 (纯文本)
            media_section = ""
            if event.message.media:
                media_section += "\n--------------------\n"
                media_section += "MEDIA:\n"
                # 检查是否是贴纸
                is_sticker = False
                if hasattr(event.message.media, "attributes"):
                    is_sticker = any(
                        isinstance(attr, DocumentAttributeSticker)
                        for attr in event.message.media.attributes
                    )

                if is_sticker:
                    media_type = "Sticker"
                    media_filename = None  # 贴纸通常没有用户可见的文件名
                else:
                    media_type = type(event.message.media).__name__.replace(
                        "MessageMedia", ""
                    )
                    media_filename = _get_filename(event.message.media)

                media_section += f"  Type: {media_type}\n"
                if media_filename:
                    media_section += f"  Filename: {media_filename}\n"

                # 添加关于限制或特性的注释
                noforwards = False
                try:
                    noforwards = getattr(event.chat, "noforwards", False) or getattr(
                        event.message, "noforwards", False
                    )
                except AttributeError:
                    pass

                if noforwards:
                    media_section += "  Note: Restricted content. Media file will be handled separately.\n"

                ttl_seconds = getattr(
                    getattr(event.message, "media", None), "ttl_seconds", None
                )
                if ttl_seconds:
                    media_section += (
                        f"  Note: Self-destructing media (TTL: {ttl_seconds}s).\n"
                    )

            text += media_section
            text += "\n===================="
            # --- 结构化纯文本构建结束 ---

            # --- 如果 use_markdown_format 为 True，转换链接格式 ---
            original_text_for_markdown = (
                text  # 保留一份原始文本用于可能的 Markdown 包裹
            )
            if self.use_markdown_format:
                try:
                    # 正则表达式查找 Markdown 链接 [text](url) 并替换为 text (url)
                    # 应用于将要被包裹在 ```markdown ... ``` 中的文本
                    original_text_for_markdown = re.sub(
                        r"\[([^\]]+)\]\(([^)]+)\)",
                        r"\1 (\2)",
                        original_text_for_markdown,
                    )
                    logger.debug(
                        "已将 Markdown 链接转换为纯文本格式，用于 Markdown 代码块"
                    )
                except Exception as re_err:
                    logger.warning(f"转换 Markdown 链接时出错: {re_err}")
            # --- 链接转换结束 ---

            # 处理发送逻辑
            if event.message.media:
                # 对于有媒体的消息，调用 _handle_media_message
                # 它将根据 use_markdown_format 决定是否包裹文本
                # 传递转换过链接格式的文本（如果 use_markdown_format 为 True）
                text_to_send_with_media = (
                    original_text_for_markdown if self.use_markdown_format else text
                )
                await self._handle_media_message(event.message, text_to_send_with_media)
            else:
                # 对于纯文本消息
                final_text_to_send = text  # 默认使用原始文本
                if self.use_markdown_format:
                    # 仅当标记为 True 时，包裹转换过链接格式的文本
                    final_text_to_send = (
                        f"```markdown\n{original_text_for_markdown}\n```"
                    )

                # 始终使用 Markdown 解析模式，以便 Telegram 能识别 ```markdown ... ``` 块
                await self.client.send_message(
                    self.log_chat_id, final_text_to_send, parse_mode="md"
                )
                logger.info(
                    f"成功发送纯文本转发消息到日志频道. Markdown包裹: {self.use_markdown_format}"
                )

            # 创建并保存数据库消息对象
            message = await self._create_message_object(event)
            if message:  # 确保对象创建成功
                await self.save_message(message)
            return message

        except Exception as e:
            logger.error(f"处理或转发消息时发生严重错误: {str(e)}", exc_info=True)
            # 尝试发送错误通知到日志频道
            try:
                error_message = f"⚠️ **错误:** 处理消息 {event.message.id} (来自 chat {event.chat_id}) 时出错。\n\n`{type(e).__name__}: {str(e)}`"
                await self.client.send_message(
                    self.log_chat_id, error_message, parse_mode="md"
                )
            except Exception as send_err:
                logger.error(f"发送错误通知到日志频道失败: {send_err}")
    async def _create_message_object(
        self, event: events.NewMessage.Event
    ) -> Optional[Message]:
        """创建用于数据库存储的消息对象"""
        from_id = self._get_sender_id(event.message)
        noforwards = False
        try:
            noforwards = getattr(event.chat, "noforwards", False) or getattr(
                event.message, "noforwards", False
            )
        except AttributeError:
            pass

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
        media_path = None  # 用于存储媒体文件的路径（如果保存了）

        if event.message.media:
            try:
                # 尝试保存媒体文件，即使是受保护的，也可能需要记录路径或元数据
                # 注意：save_media_as_file 现在主要用于受限媒体下载，
                # 对于数据库记录，我们可能只需要序列化基本信息或存储路径。
                # 这里我们仍然调用它，如果成功，可以记录路径。
                # 如果失败或非受限，media_path 将为 None 或不被使用。
                if (
                    noforwards or self_destructing
                ):  # 仅为受限或阅后即焚媒体尝试保存文件以记录
                    media_path = await save_media_as_file(self.client, event.message)
                    logger.info(f"媒体文件尝试保存于: {media_path} (用于数据库记录)")

                # 序列化媒体对象以存入数据库。这可能包含敏感信息或过大。
                # 考虑只存储媒体类型、文件名、大小等元数据，而不是整个对象。
                # 为了简化，暂时保持序列化，但要注意潜在问题。
                try:
                    media_content = pickle.dumps(event.message.media)
                except (pickle.PicklingError, TypeError) as pe:
                    logger.warning(f"序列化媒体对象失败: {pe}. 将存储 None.")
                    media_content = None  # 无法序列化则存 None

            except Exception as e:
                logger.error(f"为数据库记录处理媒体时出错: {str(e)}")
                media_content = None  # 出错则存 None

        # 获取聊天类型
        chat_type_code = await self.get_chat_type(event)

        try:
            return Message(
                id=event.message.id,
                from_id=from_id,
                chat_id=event.chat_id,
                msg_type=chat_type_code,
                media=media_content,  # 存储序列化后的媒体对象或 None
                # media_path=media_path, # 可以考虑增加这个字段存储文件路径
                noforwards=noforwards,
                self_destructing=self_destructing,
                # ttl_seconds=ttl_seconds, # 可以考虑增加这个字段
                created_time=event.message.date,  # 使用消息的原始时间
                edited_time=event.message.edit_date,  # 使用消息的编辑时间
                msg_text=event.message.message,  # 存储原始文本
            )
        except Exception as e:
            logger.error(f"创建 Message 对象失败: {e}", exc_info=True)
            return None

    async def get_chat_type(self, event) -> int:
        """获取聊天类型代码 (1: user, 2: group, 3: channel, 4: bot, 0: unknown)"""
        if event.is_private:
            try:
                sender = await event.get_sender()
                if sender and sender.bot:
                    return 4  # bot
                return 1  # user
            except Exception as e:
                logger.warning(f"获取私聊发送者信息失败: {e}. 默认为 user.")
                return 1  # 无法确定是否是 bot 时，默认为 user
        elif event.is_group:
            # Telethon 的 is_group 包含 megagroups 和 legacy groups
            # 通常我们想区分 channel (megagroup/broadcast) 和 group (legacy)
            # 但这里简单处理，都归为 group
            # 如果需要更细致区分，需要检查 event.chat.megagroup
            return 2  # group or megagroup
        elif event.is_channel:
            # is_channel 通常指 megagroups 或 broadcast channels
            # 如果 event.is_group 已经是 2，这里可能不会执行到
            # 但为了覆盖所有情况，如果能到这里，认为是 channel
            # 注意：Telethon 的定义可能随版本变化，需要验证
            # 假设 event.is_channel 且 not event.is_group 是 broadcast channel
            if hasattr(event.chat, "broadcast") and event.chat.broadcast:
                return 3  # broadcast channel
            elif hasattr(event.chat, "megagroup") and event.chat.megagroup:
                return 2  # megagroup (也算 group 类型)
            else:
                return 3  # 默认为 channel
        return 0  # unknown type
