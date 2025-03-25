import asyncio
import logging
from typing import Dict
from telegram_logger.data.database import DatabaseManager

logger = logging.getLogger(__name__)

class CleanupService:
    def __init__(self, db: DatabaseManager, persist_times: Dict[str, int]):
        self.db = db
        self.persist_times = persist_times
        self._task = None
        self._running = False

    async def start(self):
        """启动清理服务"""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._run_cleanup())
            logger.info("消息清理服务已启动")

    async def stop(self):
        """停止清理服务"""
        if self._running:
            self._running = False
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("消息清理服务已停止")

    async def _run_cleanup(self):
        """定期删除过期消息和媒体文件"""
        try:
            while self._running:
                try:
                    # 添加存储空间检查
                    if self._is_disk_space_low():
                        logger.warning("存储空间不足，强制清理...")
                    
                    deleted_count = self.db.delete_expired_messages(self.persist_times)
                    if deleted_count > 0:
                        logger.info(f"已清理 {deleted_count} 条过期记录和关联文件")
                    
                    await asyncio.sleep(3600)  # 每小时运行一次
                except sqlite3.Error as e:
                    logger.error(f"数据库错误: {str(e)}")
                    await asyncio.sleep(300)  # 数据库错误等待5分钟
                except OSError as e:
                    logger.error(f"文件系统错误: {str(e)}")
                    await asyncio.sleep(600)  # 文件错误等待10分钟
                except Exception as e:
                    logger.error(f"未知错误: {str(e)}", exc_info=True)
                    await asyncio.sleep(60)

    def _is_disk_space_low(self) -> bool:
        """检查媒体目录所在磁盘空间是否不足(小于5GB)"""
        try:
            media_path = Path("media")
            if not media_path.exists():
                return False
                
            usage = shutil.disk_usage(media_path)
            return usage.free < 5 * 1024 * 1024 * 1024  # 5GB阈值
        except Exception:
            logger.warning("无法检测磁盘空间", exc_info=True)
            return False
        except asyncio.CancelledError:
            logger.debug("清理任务被取消")
