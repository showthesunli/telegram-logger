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
FORWARD_USER_IDS = [int(x.strip()) for x in os.getenv('FORWARD_USER_IDS', '').split(',') if x.strip()]
FORWARD_GROUP_IDS = [int(x.strip()) for x in os.getenv('FORWARD_GROUP_IDS', '').split(',') if x.strip()]

# Persistence times
PERSIST_TIME_IN_DAYS_USER = int(os.getenv('PERSIST_TIME_IN_DAYS_USER', '1'))
PERSIST_TIME_IN_DAYS_CHANNEL = int(os.getenv('PERSIST_TIME_IN_DAYS_CHANNEL', '1'))
PERSIST_TIME_IN_DAYS_GROUP = int(os.getenv('PERSIST_TIME_IN_DAYS_GROUP', '1'))
PERSIST_TIME_IN_DAYS_BOT = int(os.getenv('PERSIST_TIME_IN_DAYS_BOT', '1'))

# Rate limiting configuration
DELETION_RATE_LIMIT_THRESHOLD = int(os.getenv('DELETION_RATE_LIMIT_THRESHOLD', '5'))
DELETION_RATE_LIMIT_WINDOW = int(os.getenv('DELETION_RATE_LIMIT_WINDOW', '60'))
DELETION_PAUSE_DURATION = int(os.getenv('DELETION_PAUSE_DURATION', '300'))
from telegram_logger.services.client import TelegramClientService
from telegram_logger.services.cleanup import CleanupService
# 导入 UserBot 服务
from telegram_logger.services.user_bot_state import UserBotStateService
# 导入 UserBot Handler 和 AI 服务
from telegram_logger.handlers.user_bot_command import UserBotCommandHandler
from telegram_logger.handlers.mention_reply import MentionReplyHandler
from telegram_logger.services.ai_service import AIService

from telegram_logger.handlers import (
    PersistenceHandler,
    OutputHandler,
    BaseHandler # 确保 BaseHandler 也被导入，如果需要类型检查
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
    
    persistence_handler = PersistenceHandler(
        db=db,
        log_chat_id=LOG_CHAT_ID,
        ignored_ids=IGNORED_IDS,
    )
    output_handler = OutputHandler(
        db=db,
        log_chat_id=LOG_CHAT_ID,
        ignored_ids=IGNORED_IDS,
        forward_user_ids=FORWARD_USER_IDS,
        forward_group_ids=FORWARD_GROUP_IDS,
        deletion_rate_limit_threshold=DELETION_RATE_LIMIT_THRESHOLD,
        deletion_rate_limit_window=DELETION_RATE_LIMIT_WINDOW,
        deletion_pause_duration=DELETION_PAUSE_DURATION
    )
    handlers = [persistence_handler, output_handler]
    
    # Initialize services
    client_service = TelegramClientService(
        session_name=SESSION_NAME,
        api_id=API_ID,
        api_hash=API_HASH,
        handlers=handlers,
        log_chat_id=LOG_CHAT_ID
    )
    
    cleanup_service = CleanupService(db, persist_times)
    
    # Run services
    try:
        logging.info("Starting all services...")
        user_id = await client_service.initialize() # 获取 user_id

        # --- UserBot 功能初始化 ---
        logger.info("正在初始化 UserBot 功能...")

        # 3. 创建 UserBotStateService 实例
        user_bot_state_service = UserBotStateService(db=db, my_id=user_id)
        logger.debug("UserBotStateService 已初始化。")

        # 4. 加载 UserBot 状态 (包含错误处理)
        try:
            await user_bot_state_service.load_state()
            logger.info("UserBot 状态加载成功。")
        except Exception as e:
            # load_state 内部应记录具体错误，这里记录关键错误并退出
            logger.critical(f"加载 UserBot 状态时发生致命错误: {e}", exc_info=True)
            logger.critical("由于无法加载 UserBot 状态，程序将退出。")
            sys.exit(1) # 退出程序

        # 6. 创建 AI 服务实例
        ai_service = AIService()
        logger.debug("AIService 已初始化。")

        # 7. 创建 UserBot Handler 实例并注入依赖
        user_bot_command_handler = UserBotCommandHandler(
            client=client_service.client, # 注入 client
            db=db,
            state_service=user_bot_state_service,
            my_id=user_id,
            log_chat_id=LOG_CHAT_ID, # 传递 log_chat_id
            ignored_ids=IGNORED_IDS  # 传递 ignored_ids
        )
        logger.debug("UserBotCommandHandler 已初始化。")

        mention_reply_handler = MentionReplyHandler(
            client=client_service.client, # 注入 client
            db=db,
            state_service=user_bot_state_service,
            my_id=user_id,
            ai_service=ai_service, # 注入 AI 服务
            log_chat_id=LOG_CHAT_ID, # 传递 log_chat_id
            ignored_ids=IGNORED_IDS  # 传递 ignored_ids
        )
        logger.debug("MentionReplyHandler 已初始化。")

        # --- UserBot 功能初始化结束 ---

        await cleanup_service.start()
        
        # Inject initialized client into handlers
        logging.info("Injecting initialized client into handlers...")
        for handler in handlers:
            if hasattr(handler, 'set_client'):
                handler.set_client(client_service.client)
            else:
                logging.warning(f"Handler {type(handler).__name__} does not have a set_client method.")

        logging.info("All services started successfully")
        logging.info(f"Client ID: {user_id}")
        logging.info("Cleanup service is running")
        
        await client_service.run()
    except Exception as e:
        logging.critical(f"Service execution failed: {str(e)}", exc_info=True)
    except KeyboardInterrupt:
        logging.info("Received shutdown signal...")
    finally:
        logging.info("Shutting down services...")
        if 'cleanup_service' in locals() and cleanup_service._task:
            await cleanup_service.stop()
        if 'db' in locals() and db.conn:
            db.close()
        logging.info("All services stopped")

if __name__ == "__main__":
    asyncio.run(main())
