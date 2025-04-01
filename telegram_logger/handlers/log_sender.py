import logging
from typing import Optional
from telethon.errors import MessageTooLongError, MediaCaptionTooLongError

logger = logging.getLogger(__name__)

class LogSender:
    def __init__(self, client, log_chat_id: int):
        self.client = client
        self.log_chat_id = log_chat_id
        logger.info(f"LogSender initialized for chat_id: {self.log_chat_id}")

    async def send_message(self, text: str, file=None, parse_mode: Optional[str] = None) -> bool:
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
                limit = 4090 # Slightly less than 4096 for safety
                # Basic truncation, doesn't preserve markdown block structure perfectly if truncated within
                truncated_text = text[:limit] + "... [TRUNCATED]"

                await self.client.send_message(
                    self.log_chat_id,
                    truncated_text,
                    file=file, # Still try sending file if present
                    parse_mode=parse_mode # Keep original parse mode if possible
                )
                logger.info("Successfully sent truncated message to log channel.")
                return True # Count as success even if truncated
            except Exception as e_trunc:
                logger.error(f"Failed to send truncated message: {e_trunc}", exc_info=True)
                await self._send_minimal_error("⚠️ Error: Original message was too long and could not be sent/truncated.")
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
                return await self.send_message(text=text_with_warning, parse_mode=parse_mode) # Recursive call handles potential MessageTooLongError
            except Exception as e_fallback:
                logger.error(f"Failed during MediaCaptionTooLongError fallback: {e_fallback}", exc_info=True)
                await self._send_minimal_error(f"⚠️ Error: Media caption was too long, and fallback failed: {type(e_fallback).__name__}")
                return False
        except Exception as e:
            logger.error(f"Failed to send message/file to log channel: {e}", exc_info=True)
            await self._send_minimal_error(f"⚠️ Error sending message: {type(e).__name__}")
            return False

    async def _send_minimal_error(self, error_text: str):
        """Attempts to send a minimal error message to the log channel."""
        try:
            await self.client.send_message(self.log_chat_id, error_text)
        except Exception as e_min_err:
            logger.error(f"Failed to send even the minimal error message: {e_min_err}")
