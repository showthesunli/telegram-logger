import logging
import re
from telethon import events
from telethon.tl.types import (
    Message as TelethonMessage,
    DocumentAttributeSticker,
    MessageMediaDocument,
)
from telegram_logger.utils.mentions import create_mention
from telegram_logger.utils.media import (
    _get_filename,
)

logger = logging.getLogger(__name__)


class MessageFormatter:
    def __init__(self, client):
        self.client = client
        logger.info("MessageFormatter initialized.")  # <- 可选：更新日志消息

    async def format_message(self, event: events.NewMessage.Event) -> str:
        """Formats the text content for the log message."""
        from_id = self._get_sender_id(
            event.message
        )  # Assuming _get_sender_id is accessible or passed
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
            text += message_text  # <- 确保这行存在且没有缩进
        else:
            text += "[No text content or caption]"

        # Part 3: Media info section
        media_section = self._format_media_info(event.message)
        text += media_section
        text += "\n===================="
        return text

    def _format_media_info(self, message: TelethonMessage) -> str:
        """Formats the media information part of the message."""
        media_section = ""
        if message.media:
            media_section += "\n--------------------\n"
            media_section += "MEDIA:\n"
            is_sticker = self._is_sticker(message)
            media_type = (
                "Sticker"
                if is_sticker
                else type(message.media).__name__.replace("MessageMedia", "")
            )
            # Use the imported _get_filename or define it locally if preferred
            media_filename = None if is_sticker else _get_filename(message.media)

            media_section += f"  Type: {media_type}\n"
            if media_filename:
                media_section += f"  Filename: {media_filename}\n"

            noforwards = self._has_noforwards(message)
            if noforwards:
                media_section += "  Note: Restricted content. Media file will be handled separately.\n"

            ttl_seconds = getattr(getattr(message, "media", None), "ttl_seconds", None)
            if ttl_seconds:
                media_section += (
                    f"  Note: Self-destructing media (TTL: {ttl_seconds}s).\n"
                )
        return media_section

    def _is_sticker(self, message: TelethonMessage) -> bool:
        """Checks if the message media is a sticker."""
        if isinstance(message.media, MessageMediaDocument):
            doc = getattr(message.media, "document", None)
            if doc and hasattr(doc, "attributes"):
                return any(
                    isinstance(attr, DocumentAttributeSticker)
                    for attr in doc.attributes
                )
        return False

    def _has_noforwards(self, message: TelethonMessage) -> bool:
        """Checks if the message or its chat has noforwards set."""
        try:
            chat_noforwards = (
                getattr(message.chat, "noforwards", False) if message.chat else False
            )
            message_noforwards = getattr(message, "noforwards", False)
            return chat_noforwards or message_noforwards
        except AttributeError:
            logger.warning(
                "AttributeError checking noforwards, defaulting to False", exc_info=True
            )
            return False

    # Helper to get sender ID, assuming BaseHandler._get_sender_id logic is simple
    # Or pass sender_id directly to format_message if needed
    def _get_sender_id(self, message: TelethonMessage) -> int:
        """Gets the sender ID from a message."""
        if message.from_id:
            # For user messages or channel posts where from_id is set
            peer_id = getattr(message.from_id, "user_id", None)
            if peer_id:
                return peer_id
        # For messages in channels without specific author or other cases
        peer = getattr(message, "peer_id", None)
        if peer:
            peer_id = getattr(
                peer,
                "channel_id",
                getattr(peer, "chat_id", getattr(peer, "user_id", None)),
            )
            if peer_id:
                return peer_id
        # Fallback or if sender info is unavailable
        logger.warning(f"Could not determine sender ID for message {message.id}")
        return 0  # Or raise an error, or return a specific placeholder ID
