import os
import re
import logging
from contextlib import contextmanager
from telethon.tl.types import *
from file_encrypt import encrypted, decrypted
from telegram_logger.config import MAX_IN_MEMORY_FILE_SIZE, FILE_PASSWORD

logger = logging.getLogger(__name__)

async def save_media(client, msg: 'Message') -> str:
    """保存媒体文件到本地"""
    file_path = f"media/{msg.id}_{msg.chat_id}"
    try:
        if msg.media:
            if msg.file.size > MAX_IN_MEMORY_FILE_SIZE:
                logger.warning(f"文件过大无法保存 ({msg.file.size} bytes)")
                raise ValueError("File exceeds size limit")
            
            with encrypted(file_path, FILE_PASSWORD) as f:
                await client.download_media(msg.media, f)
            logger.info(f"媒体文件保存成功: {file_path}")
            return file_path
    except Exception as e:
        logger.error(f"保存媒体失败: {str(e)}")
        raise

@contextmanager
def retrieve_media(file_path: str, is_restricted: bool):
    """根据限制状态获取媒体文件"""
    try:
        if is_restricted and os.path.exists(file_path):
            with decrypted(file_path, FILE_PASSWORD) as f:
                f.name = _get_filename(f)
                yield f
        else:
            yield None
    except Exception as e:
        logger.error(f"获取媒体失败: {str(e)}")
        yield None

def _get_filename(media) -> str:
    """解析媒体文件名"""
    if isinstance(media, Document):
        for attr in media.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                return attr.file_name
    return "file.bin"
