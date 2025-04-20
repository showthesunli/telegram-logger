import logging
import os
import tempfile # 用于后备下载的临时文件
from contextlib import contextmanager, asynccontextmanager
from telethon.tl.types import Message as TelethonMessage
# Import necessary functions from utils.media
from telegram_logger.utils.media import (
    retrieve_media_as_file,
    _get_filename,
    MAX_IN_MEMORY_FILE_SIZE, # 需要导入限制大小
)

logger = logging.getLogger(__name__)

class RestrictedMediaHandler:
    def __init__(self, client):
        self.client = client
        logger.info("RestrictedMediaHandler initialized.")

    @asynccontextmanager
    async def prepare_media_from_path(self, media_path: str):
        """
        从给定的已持久化路径解密并提供媒体文件句柄。
        现在只负责解密，不再下载或保存。
        """
        media_file = None
        # retrieve_media_as_file 返回一个同步上下文管理器
        # 我们需要在异步上下文中使用它
        cm = retrieve_media_as_file(media_path, is_restricted=True)
        try:
            media_file = cm.__enter__() # 手动进入同步上下文
            if not media_file:
                raise ValueError(f"Failed to retrieve/decrypt media from {media_path}")

            # 文件名应该由 retrieve_media_as_file 尝试设置
            filename = getattr(media_file, 'name', os.path.basename(media_path))
            logger.info(f"Yielding decrypted file handle from path: {filename}")
            yield media_file # 产生文件句柄

        except FileNotFoundError:
             logger.error(f"Media file not found at path: {media_path}")
             raise # 文件不存在，直接抛出异常
        except Exception as e:
            logger.error(f"Error preparing media from path {media_path}: {e}", exc_info=True)
            raise # 重新抛出异常，让调用者知道失败了
        finally:
            # 手动退出同步上下文
            if 'cm' in locals(): # 确保 cm 已定义
                try:
                    cm.__exit__(None, None, None) # 清理同步上下文（例如关闭文件）
                    if media_file:
                         logger.info(f"Finished processing media from path: {getattr(media_file, 'name', 'unknown')}")
                except Exception as exit_e:
                     logger.error(f"Error exiting retrieve_media_as_file context for {media_path}: {exit_e}")
            if not media_file:
                 logger.warning(f"Media preparation from path context finished, but no media file was yielded successfully.")


    @asynccontextmanager
    async def download_and_yield_temporary(self, message: TelethonMessage):
        """
        后备方法：临时下载媒体（到内存或临时文件），并提供文件句柄。
        不进行永久保存或加密。
        """
        temp_file_handle = None
        temp_file_path = None
        downloaded_to_memory = False

        try:
            if not message.media or not message.file:
                raise ValueError("Message has no media or file attribute for temporary download.")

            file_size = message.file.size
            filename = _get_filename(message.media) or f"temp_{message.id}"

            # 使用 aenter/aexit 管理临时文件生命周期更安全
            if file_size <= MAX_IN_MEMORY_FILE_SIZE:
                # 下载到内存
                logger.debug(f"Downloading media (ID: {message.id}) temporarily to memory.")
                content = await self.client.download_media(message.media, file=bytes)
                # 使用 NamedTemporaryFile 包装内存数据
                # delete=True (默认) 让文件在关闭时自动删除
                temp_file_handle = tempfile.NamedTemporaryFile(delete=True)
                temp_file_handle.write(content)
                temp_file_handle.seek(0)
                temp_file_handle.name = filename # 设置文件名
                temp_file_path = temp_file_handle.name # 获取临时文件路径 (仅用于日志)
                downloaded_to_memory = True
                logger.info(f"Media (ID: {message.id}) downloaded temporarily to memory, wrapped in temp file.")
                yield temp_file_handle # 产生内存包装的文件句柄
            else:
                # 下载到临时文件
                logger.debug(f"Downloading media (ID: {message.id}) temporarily to file (size: {file_size}).")
                # 创建一个带特定后缀的临时文件
                suffix = os.path.splitext(filename)[1]
                # delete=True (默认)
                temp_file_handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=True)
                temp_file_path = temp_file_handle.name
                # 先关闭句柄，让 download_media 写入 (Telethon 需要路径)
                temp_file_handle.close()
                await self.client.download_media(message.media, file=temp_file_path)
                # 重新以二进制读模式打开文件以供产生
                temp_file_handle = open(temp_file_path, 'rb')
                # 尝试设置文件名 (虽然句柄是新的，但路径是已知的)
                try:
                    temp_file_handle.name = filename
                except AttributeError:
                    pass # 忽略普通文件句柄设置名称失败
                logger.info(f"Media (ID: {message.id}) downloaded temporarily to file: {temp_file_path}")
                yield temp_file_handle # 产生文件句柄

        except Exception as e:
            logger.error(f"Error during temporary media download (ID: {message.id}): {e}", exc_info=True)
            raise # 重新抛出异常
        finally:
            # 清理：关闭文件句柄。临时文件由 NamedTemporaryFile(delete=True) 或手动 os.remove 处理
            if temp_file_handle:
                try:
                    temp_file_handle.close()
                    logger.debug(f"Closed temporary file handle for message {message.id}.")
                    # 如果是下载到文件的情况 (非内存)，NamedTemporaryFile 可能不会自动删除
                    # 因为我们重新打开了它。需要手动删除。
                    if not downloaded_to_memory and temp_file_path and os.path.exists(temp_file_path):
                         try:
                             os.remove(temp_file_path)
                             logger.info(f"Cleaned up temporary file: {temp_file_path} (message ID: {message.id})")
                         except OSError as e_clean:
                             logger.error(f"Failed to clean up temporary file {temp_file_path} (message ID: {message.id}): {e_clean}")

                except Exception as e_close:
                     logger.error(f"Error closing/cleaning temporary file handle for message {message.id}: {e_close}")
