import asyncio
import logging
import os
import sys
from dotenv import load_dotenv
from typing import List, Dict

# 配置基础日志，用于显示环境变量检查信息
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

def check_env_variables():
    """检查必需的环境变量是否存在并记录日志"""
    logger.info("开始检查环境变量...")
    
    required_vars = {
        'API_ID': '整数类型的 Telegram API ID',
        'API_HASH': 'Telegram API Hash 字符串',
        'SESSION_NAME': '会话名称，默认为 db/user',
        'LOG_CHAT_ID': '日志频道 ID，默认为 0'
    }
    
    missing_vars = []
    env_status = {}
    
    # 检查每个环境变量
    for var, description in required_vars.items():
        value = os.getenv(var)
        if value is None:
            missing_vars.append(var)
            env_status[var] = "未设置"
        else:
            # 对于敏感信息，只显示长度和部分内容
            if var in ['API_HASH']:
                masked_value = f"{value[:4]}...{value[-4:]}" if len(value) > 8 else "***"
                env_status[var] = f"已设置 (值为: {masked_value})"
            elif var in ['API_ID']:
                env_status[var] = "已设置"
            else:
                env_status[var] = f"已设置 (值为: {value})"
    
    # 记录环境变量状态
    logger.info("环境变量检查结果:")
    for var, status in env_status.items():
        logger.info(f"- {var}: {status}")
    
    # 如果有缺失的环境变量，记录错误并退出
    if missing_vars:
        logger.error("缺少以下必需的环境变量:")
        for var in missing_vars:
            logger.error(f"- {var}: {required_vars[var]}")
        logger.error("请设置所有必需的环境变量后再启动程序")
        sys.exit(1)
    
    logger.info("环境变量检查完成，所有必需变量均已设置")

# 加载环境变量
load_dotenv()
logger.debug(f"Raw FORWARD_GROUP_IDS from os.getenv after load_dotenv: {os.getenv('FORWARD_GROUP_IDS')}")

# 检查环境变量
check_env_variables()

# 从环境变量加载配置
try:
    API_ID = int(os.getenv('API_ID'))
    API_HASH = os.getenv('API_HASH')
    SESSION_NAME = os.getenv('SESSION_NAME', 'db/user')
    LOG_CHAT_ID = int(os.getenv('LOG_CHAT_ID', 0))
except ValueError as e:
    logger.error(f"环境变量格式错误: {str(e)}")
    logger.error("请确保 API_ID 和 LOG_CHAT_ID 为有效的整数")
    sys.exit(1)

# Parse comma-separated IDs into sets
IGNORED_IDS = {int(x.strip()) for x in os.getenv('IGNORED_IDS', '-10000').split(',')}

raw_forward_user_ids = os.getenv('FORWARD_USER_IDS', '')
logger.debug(f"Raw FORWARD_USER_IDS before parsing: {raw_forward_user_ids}")
FORWARD_USER_IDS = [int(x.strip()) for x in raw_forward_user_ids.split(',') if x.strip()]
logger.debug(f"Parsed FORWARD_USER_IDS: {FORWARD_USER_IDS}")

raw_forward_group_ids = os.getenv('FORWARD_GROUP_IDS', '')
logger.debug(f"Raw FORWARD_GROUP_IDS before parsing: {raw_forward_group_ids}")
FORWARD_GROUP_IDS = [int(x.strip()) for x in raw_forward_group_ids.split(',') if x.strip()]
logger.debug(f"Parsed FORWARD_GROUP_IDS: {FORWARD_GROUP_IDS}")

# Read Markdown format setting
FORWARDER_USE_MARKDOWN = os.getenv('FORWARDER_USE_MARKDOWN', 'False').lower() == 'true'
logger.info(f"Forwarder Markdown format setting from env: {FORWARDER_USE_MARKDOWN}")

# Persistence times
PERSIST_TIME_IN_DAYS_USER = int(os.getenv('PERSIST_TIME_IN_DAYS_USER', '1'))
PERSIST_TIME_IN_DAYS_CHANNEL = int(os.getenv('PERSIST_TIME_IN_DAYS_CHANNEL', '1'))
PERSIST_TIME_IN_DAYS_GROUP = int(os.getenv('PERSIST_TIME_IN_DAYS_GROUP', '1'))
PERSIST_TIME_IN_DAYS_BOT = int(os.getenv('PERSIST_TIME_IN_DAYS_BOT', '1'))
from telegram_logger.services.client import TelegramClientService
from telegram_logger.services.cleanup import CleanupService
from telegram_logger.handlers import (
    NewMessageHandler,
    EditDeleteHandler,
    ForwardHandler
)
from telegram_logger.data.database import DatabaseManager
from telegram_logger.utils.logging import configure_logging

async def main():
    # Configure logging
    configure_logging()
    logging.info("Starting Telegram Logger service...")
    
    # Initialize core components
    db = DatabaseManager()
    
    # Create handlers
    persist_times = {
        'user': PERSIST_TIME_IN_DAYS_USER,
        'channel': PERSIST_TIME_IN_DAYS_CHANNEL,
        'group': PERSIST_TIME_IN_DAYS_GROUP,
        'bot': PERSIST_TIME_IN_DAYS_BOT
    }
    
    handlers = [
        NewMessageHandler(
            client=None,
            db=db,
            log_chat_id=LOG_CHAT_ID,
            ignored_ids=IGNORED_IDS,
            persist_times=persist_times
        ),
        EditDeleteHandler(
            client=None,
            db=db,
            log_chat_id=LOG_CHAT_ID,
            ignored_ids=IGNORED_IDS
        ),
        ForwardHandler(
            client=None,
            db=db,
            log_chat_id=LOG_CHAT_ID,
            ignored_ids=IGNORED_IDS,
            forward_user_ids=FORWARD_USER_IDS,
            forward_group_ids=FORWARD_GROUP_IDS,
            use_markdown_format=FORWARDER_USE_MARKDOWN
        )
    ]
    
    # Initialize services
    client_service = TelegramClientService(
        session_name=SESSION_NAME,
        api_id=API_ID,
        api_hash=API_HASH,
        handlers=handlers,
        log_chat_id=LOG_CHAT_ID
    )
    
    cleanup_service = CleanupService(db, persist_times)
    
    # Inject client dependency
    for handler in handlers:
        handler.client = client_service.client
    
    # Run services
    try:
        logging.info("Starting all services...")
        user_id = await client_service.initialize()
        await cleanup_service.start()
        
        logging.info("All services started successfully")
        logging.info(f"Client ID: {user_id}")
        logging.info("Cleanup service is running")
        
        await client_service.run()
    except Exception as e:
        logging.critical(f"Service startup failed: {str(e)}")
        raise
    except KeyboardInterrupt:
        logging.info("Received shutdown signal...")
    finally:
        logging.info("Shutting down services...")
        await cleanup_service.stop()
        db.close()
        logging.info("All services stopped")

if __name__ == "__main__":
    asyncio.run(main())
