import asyncio
import logging
import os
from dotenv import load_dotenv
from typing import List, Dict

# Load environment variables
load_dotenv()

# Configuration from environment variables
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
SESSION_NAME = os.getenv('SESSION_NAME', 'db/user')
LOG_CHAT_ID = int(os.getenv('LOG_CHAT_ID', 0))

# Parse comma-separated IDs into sets
IGNORED_IDS = {int(x.strip()) for x in os.getenv('IGNORED_IDS', '-10000').split(',')}
FORWARD_USER_IDS = [int(x.strip()) for x in os.getenv('FORWARD_USER_IDS', '').split(',') if x.strip()]
FORWARD_GROUP_IDS = [int(x.strip()) for x in os.getenv('FORWARD_GROUP_IDS', '').split(',') if x.strip()]

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
            forward_group_ids=FORWARD_GROUP_IDS
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
