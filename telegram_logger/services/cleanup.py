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
        """定期删除过期消息"""
        try:
            while self._running:
                try:
                    deleted_count = self.db.delete_expired_messages(self.persist_times)
                    if deleted_count > 0:
                        logger.info(f"已清理 {deleted_count} 条过期消息")
                    await asyncio.sleep(3600)  # 每小时运行一次
                except Exception as e:
                    logger.error(f"清理过程中发生错误: {str(e)}")
                    await asyncio.sleep(60)  # 出错后等待1分钟再重试
        except asyncio.CancelledError:
            logger.debug("清理任务被取消")
