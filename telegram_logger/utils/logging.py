import logging
import sys
import os
from logging.handlers import TimedRotatingFileHandler
from dotenv import load_dotenv

load_dotenv()
DEBUG_MODE = os.getenv("DEBUG_MODE", "False") == "True"

def configure_logging():
    """配置全局日志记录，修改现有根记录器配置，自动按天轮转并保留1天日志"""
    level = logging.DEBUG if DEBUG_MODE else logging.INFO
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(log_format, datefmt=date_format)

    # 获取根记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(level) # 设置根记录器的级别

    # 清除可能由 main.py 初始 basicConfig 添加的默认处理器
    # (通常是一个 StreamHandler 输出到 stderr 或 stdout)
    # 这样可以避免重复输出到控制台
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close() # 关闭处理器以释放资源

    # 确保log目录存在
    os.makedirs("log", exist_ok=True)

    # --- 配置新的处理器 ---

    # 1. 文件处理器 (TimedRotatingFileHandler)
    try:
        file_handler = TimedRotatingFileHandler(
            filename=os.path.join("log", "tg_logger.log"),
            when="midnight",
            interval=1,
            backupCount=1, # 保留当天的和前一天的日志
            encoding="utf-8",
        )
        file_handler.suffix = "%Y-%m-%d"  # 备份文件后缀格式
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level) # 确保文件处理器也使用正确的级别
        root_logger.addHandler(file_handler)
    except Exception as e:
        # 如果文件处理器创建失败，至少打印错误到控制台
        print(f"错误：无法创建日志文件处理器: {e}", file=sys.stderr)


    # 2. 控制台处理器 (StreamHandler)
    try:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(level) # 确保控制台处理器也使用正确的级别
        root_logger.addHandler(stream_handler)
    except Exception as e:
        print(f"错误：无法创建控制台日志处理器: {e}", file=sys.stderr)


    # --- 设置特定库的日志级别 ---
    logging.getLogger("telethon").setLevel(logging.WARNING)

    # 添加一条 DEBUG 日志来确认配置是否生效
    # 这条日志应该能在 DEBUG_MODE=True 时看到
    logging.debug(f"日志系统已重新配置，根记录器级别设置为: {logging.getLevelName(level)}")

    # 记录一条 INFO 日志，确认处理器工作正常
    logging.info(f"日志配置完成。DEBUG 模式: {DEBUG_MODE}")
