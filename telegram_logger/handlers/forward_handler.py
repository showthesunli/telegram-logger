
# --- Imports ---
import logging
import pickle
# Remove os, re, traceback if no longer directly used here
from typing import Optional, Union, List, Dict, Any
from telethon import events, errors
from telethon.tl.types import Message as TelethonMessage # Keep if needed for type hints
# Remove specific error types if handled by LogSender
# from telethon.errors import MessageTooLongError, MediaCaptionTooLongError

# Import BaseHandler and Message model
from telegram_logger.handlers.base_handler import BaseHandler
from telegram_logger.data.models import Message

# Import the new modules
from .message_formatter import MessageFormatter
from .log_sender import LogSender
from .media_handler import RestrictedMediaHandler

# Keep utils imports if still needed (e.g., for _create_message_object)
from telegram_logger.utils.media import save_media_as_file # Keep if used in _create_message_object
from telegram_logger.utils.mentions import create_mention # Keep if used in _create_message_object

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
        **kwargs: Dict[str, Any] # Added **kwargs to match BaseHandler if needed
    ):
        # Call super().__init__ correctly
        super().__init__(client, db, log_chat_id, ignored_ids, **kwargs)

        self.forward_user_ids = forward_user_ids or []
        self.forward_group_ids = forward_group_ids or []
        # Keep use_markdown_format if needed for logic within this class
        self.use_markdown_format = use_markdown_format

        # Instantiate the helper classes
        self.formatter = MessageFormatter(client, use_markdown_format)
        self.sender = LogSender(client, log_chat_id)
        self.media_handler = RestrictedMediaHandler(client)
        logger.info(
            f"ForwardHandler initialized with forward_user_ids: {self.forward_user_ids}"
        )
        logger.info(
            f"ForwardHandler initialized with forward_group_ids: {self.forward_group_ids}"
        )
        logger.info(
            f"ForwardHandler initialized with use_markdown_format: {self.use_markdown_format}" # <- 修改这一行
        )

    def set_client(self, client):
        """设置 Telethon 客户端实例并更新内部组件。"""
        super().set_client(client) # 调用父类的方法设置 self.client
        # 更新依赖客户端的内部组件
        if hasattr(self, 'sender') and self.sender:
            self.sender.client = client
            logger.debug("Updated client for LogSender in ForwardHandler")
        if hasattr(self, 'formatter') and self.formatter:
            self.formatter.client = client
            logger.debug("Updated client for MessageFormatter in ForwardHandler")
        if hasattr(self, 'media_handler') and self.media_handler:
            self.media_handler.client = client
            logger.debug("Updated client for RestrictedMediaHandler in ForwardHandler")
        logger.debug(f"Client set for {self.__class__.__name__}")

    # --- Remove old private helper methods ---
    # Remove: _format_forward_message_text
    # Remove: _is_sticker (now in formatter)
    # Remove: _has_noforwards (now in formatter)
    # Remove: _send_to_log_channel (now in sender)
    # Remove: _send_sticker_message
    # Remove: _send_restricted_media
    # Remove: _send_non_restricted_media
    # Remove: _send_forwarded_message

    # --- Keep handle_new_message ---
    async def handle_new_message(self, event):
        """处理新消息事件，这个方法名与client.py中的注册方法匹配"""
        if not self.client:
            logger.error("Handler not initialized, client is None")
            return None

        from_id = self._get_sender_id(event.message) # Use BaseHandler's method
        chat_id = event.chat_id
        logger.info(
            f"ForwardHandler received message from user {from_id} in chat {chat_id}"
        )
        # Call the refactored process method
        return await self.process(event)

    # --- Refactored process method ---
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
            # 1. Format the message text using the formatter
            # The formatter handles link conversion internally if use_markdown_format is true
            formatted_text = await self.formatter.format_message(event)

            # Determine parse mode for sending
            parse_mode = "md" if self.use_markdown_format else None

            # Prepare text for sending (apply markdown code block if needed)
            # The formatted_text already has converted links if markdown is enabled
            text_to_send = f"```markdown\n{formatted_text}\n```" if self.use_markdown_format else formatted_text

            # 2. Handle sending based on media type
            message = event.message
            if not message.media:
                # Text-only message
                logger.info("Sending text-only message.")
                await self.sender.send_message(text=text_to_send, parse_mode=parse_mode)
            else:
                # Message with media
                # Use formatter's helpers to check type
                is_sticker = self.formatter._is_sticker(message)
                has_noforwards = self.formatter._has_noforwards(message)

                if is_sticker:
                    logger.info("Handling sticker message.")
                    # Send text part first (potentially with markdown)
                    text_sent = await self.sender.send_message(text=text_to_send, parse_mode=parse_mode)
                    if text_sent:
                        # Send sticker file with empty caption
                        sticker_sent = await self.sender.send_message(text="", file=message.media)
                        if not sticker_sent:
                            logger.error("Failed to send sticker file after text was sent.")
                            await self.sender._send_minimal_error("⚠️ Note: Failed to send the sticker file itself.") # Use sender's helper
                    else:
                        logger.warning("Skipping sticker file because text part failed to send.")

                elif has_noforwards:
                    logger.info("Handling restricted media.")
                    media_sent = False
                    error_note = ""
                    try:
                        # Use the media handler's context manager
                        async with self.media_handler.prepare_media(message) as media_file:
                            logger.info(f"Attempting to send decrypted file: {getattr(media_file, 'name', 'unknown')}")
                            # Send with the potentially markdown-formatted text
                            media_sent = await self.sender.send_message(
                                text=text_to_send,
                                file=media_file,
                                parse_mode=parse_mode
                            )
                    except Exception as e:
                        logger.error(f"Failed to prepare or send restricted media: {e}", exc_info=True)
                        error_note = f"\n  Error: Exception during restricted media handling - {type(e).__name__}\n"

                    # If media sending failed, send text only with error note
                    if not media_sent:
                        logger.warning("Sending text only for restricted media due to errors.")
                        # Add error note to the *original* formatted text before markdown wrapping
                        text_with_error = formatted_text + error_note
                        # Apply markdown formatting if needed to the combined text+error
                        final_text = f"```markdown\n{text_with_error}\n```" if self.use_markdown_format else text_with_error
                        await self.sender.send_message(text=final_text, parse_mode=parse_mode)

                else:
                    # Non-restricted, non-sticker media
                    logger.info("Handling non-restricted media.")
                    await self.sender.send_message(
                        text=text_to_send,
                        file=message.media,
                        parse_mode=parse_mode
                    )

            # 3. Create and save database message object (Keep this logic here)
            db_message = await self._create_message_object(event)
            if db_message:
                await self.save_message(db_message) # Use BaseHandler's save_message
            return db_message # Return the created db object

        except Exception as e:
            logger.error(f"处理或转发消息时发生严重错误: {str(e)}", exc_info=True)
            # Attempt to send error notification using the sender
            try:
                error_message = f"⚠️ **错误:** 处理消息 {event.message.id} (来自 chat {event.chat_id}) 时出错。\n\n`{type(e).__name__}: {str(e)}`"
                # Use sender, ensuring parse_mode is set for markdown
                await self.sender.send_message(error_message, parse_mode="md")
            except Exception as send_err:
                logger.error(f"发送错误通知到日志频道失败: {send_err}")
            return None # Indicate failure

    # --- Keep _create_message_object and get_chat_type ---
    # (Make sure imports like pickle, save_media_as_file are present if needed)
    async def _create_message_object(
        self, event: events.NewMessage.Event
    ) -> Optional[Message]:
        """创建用于数据库存储的消息对象 (Keep as is, or refine media handling)"""
        from_id = self._get_sender_id(event.message)
        # Use formatter's helper for consistency
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
        # Decide if saving media for DB is still needed/wanted, especially with RestrictedMediaHandler
        # Maybe only store metadata instead of pickled object or file path?
        # For now, keep the existing logic but be aware of redundancy/potential issues.
        if event.message.media:
            try:
                # Example: Only attempt saving if restricted/destructing for logging purposes
                media_path = None
                if noforwards or self_destructing:
                    try:
                        # This might download again if RestrictedMediaHandler didn't cache/reuse
                        media_path = await save_media_as_file(self.client, event.message)
                        logger.info(f"媒体文件尝试保存于: {media_path} (用于数据库记录)")
                    except Exception as save_err:
                         logger.warning(f"为数据库记录保存媒体文件失败: {save_err}")

                # Serialize media object (Consider alternatives)
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
                media=media_content, # Storing pickled media
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
        """获取聊天类型代码 (Keep as is)"""
        if event.is_private:
            try:
                sender = await event.get_sender()
                if sender and sender.bot:
                    return 4  # bot
                return 1  # user
            except Exception as e:
                logger.warning(f"获取私聊发送者信息失败: {e}. 默认为 user.")
                return 1
        elif event.is_group:
             # Covers megagroups and basic groups
             return 2
        elif event.is_channel:
             # Covers broadcast channels specifically if not caught by is_group
             # Check if it's explicitly a broadcast channel
             if hasattr(event.chat, "broadcast") and event.chat.broadcast:
                 return 3 # broadcast channel
             # If it's a megagroup (often caught by is_group too, but check for safety)
             elif hasattr(event.chat, "megagroup") and event.chat.megagroup:
                 return 2 # megagroup treated as group
             else:
                 # Default channel case if not broadcast/megagroup explicitly identified
                 return 3 # channel
        return 0  # unknown type
