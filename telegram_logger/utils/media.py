import logging
import os
from contextlib import contextmanager
import logging
import os
from contextlib import contextmanager
from telethon.tl.types import (
    DocumentAttributeFilename,
    MessageMediaPhoto,
    MessageMediaContact,
    Contact,
    Photo,
    Document, # 导入 Document
    MessageMediaDocument # 导入 MessageMediaDocument
)
from .file_encrypt import encrypted, decrypted
# import os # os 已在上面导入
from dotenv import load_dotenv

load_dotenv()
MAX_IN_MEMORY_FILE_SIZE = int(os.getenv("MAX_IN_MEMORY_FILE_SIZE", "5242880"))  # 默认5MB
FILE_PASSWORD = os.getenv("FILE_PASSWORD", "default-weak-password")  # 统一使用 FILE_PASSWORD

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
    """
    Retrieve media from an encrypted file or use the original media.
    Yields a file-like object (handle).
    """
    file_handle = None
    decrypted_cm = None # 用于持有 decrypted 上下文管理器

    try:
        if not os.path.exists(file_path):
             raise FileNotFoundError(f"Media file not found at path: {file_path}")

        # 尝试从路径获取基础文件名，作为后备
        base_filename = os.path.basename(file_path)

        if is_restricted:
            logger.info(f"解密并读取受限媒体文件: {file_path}")
            # 使用 decrypted 上下文管理器
            decrypted_cm = decrypted(file_path, FILE_PASSWORD)
            file_handle = decrypted_cm.__enter__() # 进入上下文
            if not file_handle:
                 raise IOError(f"Decryption failed or returned None for {file_path}")
            # 尝试设置文件名 (decrypted 可能不会设置)
            try:
                if not getattr(file_handle, 'name', None):
                     file_handle.name = base_filename
            except AttributeError:
                 logger.warning(f"Could not set name attribute on decrypted file object for {base_filename}")
            yield file_handle # 在 decrypted 上下文内产生
        else:
            # 对于非受限文件（或我们假设未加密的文件）
            logger.info(f"直接读取媒体文件: {file_path}")
            # 直接打开文件
            file_handle = open(file_path, 'rb')
            # 尝试设置文件名
            try:
                file_handle.name = base_filename
            except AttributeError:
                 logger.warning(f"Could not set name attribute on file object for {base_filename}")
            yield file_handle # 产生文件句柄
    except Exception as e:
        logger.error(f"获取媒体文件 {file_path} 时发生错误: {str(e)}", exc_info=True)
        # 确保即使出错也尝试产生 None 或重新抛出，取决于调用者期望
        # 这里选择重新抛出异常
        raise
    finally:
        # 清理：
        # 如果是受限文件，退出 decrypted 上下文管理器 (它会关闭文件)
        if decrypted_cm:
            try:
                decrypted_cm.__exit__(None, None, None)
                logger.debug(f"Exited decrypted context for {file_path}")
            except Exception as e_exit:
                 logger.error(f"Error exiting decrypted context for {file_path}: {e_exit}")
        # 如果是非受限文件，且句柄已打开，需要在这里关闭句柄
        elif file_handle and not is_restricted:
            try:
                file_handle.close()
                logger.debug(f"Closed non-restricted file handle: {file_path}")
            except Exception as e_close:
                 logger.error(f"Error closing non-restricted file handle {file_path}: {e_close}")


def _get_filename(media) -> str:
    """Get filename from media object"""
    filename = None
    # 优先处理 Document 类型
    doc = getattr(media, 'document', None)
    if isinstance(doc, Document) and hasattr(doc, 'attributes'):
        for attr in doc.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                filename = attr.file_name
                break
        # 如果没有文件名属性，但有 mime 类型，可以尝试生成扩展名
        if not filename and hasattr(doc, 'mime_type'):
             mime_type = doc.mime_type
             # 简单的 mime 类型到扩展名的映射 (可以扩展)
             ext_map = {
                 "audio/ogg": ".ogg",
                 "video/mp4": ".mp4",
                 "image/jpeg": ".jpg",
                 "image/png": ".png",
                 "image/webp": ".webp",
                 "audio/mpeg": ".mp3",
                 "application/pdf": ".pdf",
                 "application/zip": ".zip",
                 "audio/opus": ".opus", # 添加 opus
                 "video/webm": ".webm", # 添加 webm
                 "image/gif": ".gif",   # 添加 gif
             }
             ext = ext_map.get(mime_type)
             if ext:
                 # 使用更通用的名称，避免潜在冲突
                 filename = f"media_file{ext}"

    # 处理照片类型 (MessageMediaPhoto 或 Photo)
    elif isinstance(media, (MessageMediaPhoto, Photo)):
        filename = "photo.jpg" # 默认为 jpg
        # Photo 对象可能有 sizes，但通常不包含原始文件名

    # 处理联系人
    elif isinstance(media, (MessageMediaContact, Contact)):
        filename = "contact.vcf"

    # 如果所有尝试都失败，返回一个默认名称
    return filename or "unknown_media.bin"
