import asyncio
import logging
from telegram_logger.config import (
    API_ID,
    API_HASH,
    SESSION_NAME,
    LOG_CHAT_ID,
    FORWARD_USER_IDS,
    PERSIST_TIME_IN_DAYS_USER,
    PERSIST_TIME_IN_DAYS_CHANNEL,
    PERSIST_TIME_IN_DAYS_GROUP,
    PERSIST_TIME_IN_DAYS_BOT
)
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
        NewMessageHandler(db=db, persist_times=persist_times),
        EditDeleteHandler(db=db, log_chat_id=LOG_CHAT_ID),
        ForwardHandler(db=db, forward_user_ids=FORWARD_USER_IDS, log_chat_id=LOG_CHAT_ID)
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
        await asyncio.gather(
            client_service.initialize(),
            cleanup_service.start()
        )
        await client_service.run()
    except KeyboardInterrupt:
        logging.info("Shutting down gracefully...")
    finally:
        await cleanup_service.stop()
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
