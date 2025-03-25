import logging
import sys
import os
from logging.handlers import TimedRotatingFileHandler
from telegram_logger.config import DEBUG_MODE


def configure_logging():
    """配置全局日志记录，自动按天轮转并保留1天日志"""
    level = logging.DEBUG if DEBUG_MODE else logging.INFO

    # 确保log目录存在
    os.makedirs("log", exist_ok=True)

    # 设置每天午夜轮转日志，保留1个备份(当天+前一天)
    file_handler = TimedRotatingFileHandler(
        filename=os.path.join("log", "tg_logger.log"),
        when="midnight",
        interval=1,
        backupCount=1,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d"  # 备份文件后缀格式

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            file_handler,
            logging.StreamHandler(sys.stdout),
        ],
    )
    logging.getLogger("telethon").setLevel(logging.WARNING)
