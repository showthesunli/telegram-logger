import logging
import os
from contextlib import contextmanager
from typing import Union
from telethon.tl.types import (
    DocumentAttributeFilename,
    MessageMediaPhoto,
    MessageMediaContact,
    Contact,
    Photo
)
from .file_encrypt import encrypted, decrypted
from telegram_logger.config import MAX_IN_MEMORY_FILE_SIZE, FILE_PASSWORD

logger = logging.getLogger(__name__)

async def save_media_as_file(client, msg) -> str:
    """Save media from a message to an encrypted file
    
    Args:
        client: Telegram client
        msg: Message object containing media
        
    Returns:
        str: Path to the saved file
        
    Raises:
        Exception: If file is too large or media cannot be saved
    """
    msg_id = msg.id
    chat_id = msg.chat_id

    logger.info(f"开始保存媒体文件 - 消息ID: {msg_id}, 聊天ID: {chat_id}")

    if msg.media:
        # 记录媒体类型
        logger.info(f"媒体类型: {type(msg.media).__name__}")

        if msg.file:
            logger.info(f"文件大小: {msg.file.size} bytes")

        if msg.file and msg.file.size > MAX_IN_MEMORY_FILE_SIZE:
            logger.warning(
                f"文件太大无法保存 ({msg.file.size} bytes), 最大限制: {MAX_IN_MEMORY_FILE_SIZE} bytes"
            )
            raise Exception(f"File too large to save ({msg.file.size} bytes)")

        file_path = f"media/{msg_id}_{chat_id}"
        logger.info(f"保存文件路径: {file_path}")

        try:
            # 确保media目录存在
            os.makedirs("media", exist_ok=True)
            
            with encrypted(file_path, FILE_PASSWORD) as f:
                await client.download_media(msg.media, f)
            logger.info("媒体文件保存成功")
            return file_path
        except Exception as e:
            logger.error(f"保存媒体文件失败: {str(e)}")
            raise
    else:
        logger.info("消息不包含媒体内容")
        return None


@contextmanager 
def retrieve_media_as_file(file_path: str, is_restricted: bool = False):
    """Retrieve media from an encrypted file or use the original media
    
    Args:
        file_path: Path to the media file
        is_restricted: Whether the media is restricted (noforwards)
        
    Yields:
        The media file or None
    """
    try:
        if is_restricted and os.path.exists(file_path):
            logger.info(f"解密并读取媒体文件: {file_path}")
            with decrypted(file_path, FILE_PASSWORD) as f:
                f.name = _get_filename(f)
                yield f
        else:
            logger.info("无法获取媒体文件或不需要解密")
            yield None
    except Exception as e:
        logger.error(f"获取媒体文件时发生错误: {str(e)}")
        yield None


def _get_filename(media) -> str:
    """Get filename from media object
    
    Args:
        media: Media object
        
    Returns:
        str: Filename
    """
    if hasattr(media, 'document') and hasattr(media.document, 'attributes'):
        for attr in media.document.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                return attr.file_name
    
    # Default filenames based on media type
    if hasattr(media, 'document') and hasattr(media.document, 'mime_type'):
        mime_type = media.document.mime_type
        if mime_type == "audio/ogg":
            return "voicenote.ogg"
        elif mime_type == "video/mp4":
            return "video.mp4"
    elif isinstance(media, (MessageMediaPhoto, Photo)):
        return "photo.jpg"
    elif isinstance(media, (MessageMediaContact, Contact)):
        return "contact.vcf"
    
    return "file.bin"
