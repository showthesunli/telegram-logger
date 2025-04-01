import logging
from typing import Dict, Any, Optional, Union, List
from telethon.events import common as EventCommon
from telethon.tl.types import PeerUser, PeerChannel, PeerChat
from telegram_logger.data.database import DatabaseManager
from telegram_logger.data.models import Message

logger = logging.getLogger(__name__)

class BaseHandler:

    def __init__(
        self, 
        client, 
        db: DatabaseManager,
        log_chat_id: int,
        ignored_ids: set,
        **kwargs: Dict[str, Any]
    ):
        """Base handler for Telegram events
        
        Args:
            client: Telegram client
            db: Database manager
            log_chat_id: Chat ID to log messages to
            ignored_ids: Set of user/chat IDs to ignore
            **kwargs: Additional arguments
        """
        self.client = client
        self.db = db
        self.log_chat_id = log_chat_id
        self.ignored_ids = ignored_ids or set()
        self._my_id = None
        
    async def init(self):
        """Initialize handler
        
        This method should be called after client is initialized
        """
        if self.client:
            me = await self.client.get_me()
            self._my_id = me.id
            logger.info(f"Handler initialized with user ID: {self._my_id}")
        else:
            logger.warning("Cannot initialize handler: client is None")
    
    async def process(self, event: EventCommon) -> Optional[Union[Message, List[Message]]]:
        """Process event
        
        This method should be implemented by subclasses
        
        Args:
            event: Telegram event
            
        Returns:
            Optional[Union[Message, List[Message]]]: Processed message(s) or None
        """
        raise NotImplementedError("Subclasses must implement process()")
    
    async def save_message(self, message: Message):
        """Save message to database
        
        Args:
            message: Message to save
        """
        self.db.save_message(message)
    
    def _get_sender_id(self, message) -> int:
        """Get sender ID from message
        
        Args:
            message: Telegram message
            
        Returns:
            int: Sender ID
        """
        from_id = 0
        
        # Handle outgoing messages
        if hasattr(message, 'out') and message.out:
            return self._my_id if self._my_id else 0
            
        # Handle different peer types
        if hasattr(message, 'peer_id'):
            if isinstance(message.peer_id, PeerUser):
                from_id = message.peer_id.user_id
            elif isinstance(message.peer_id, PeerChannel):
                from_id = message.peer_id.channel_id
            elif isinstance(message.peer_id, PeerChat):
                from_id = message.peer_id.chat_id
                
        # Try to get from_id from message
        if hasattr(message, 'from_id'):
            if hasattr(message.from_id, 'user_id'):
                from_id = message.from_id.user_id
            elif hasattr(message.from_id, 'channel_id'):
                from_id = message.from_id.channel_id
                
        return from_id
    
    def set_client(self, client):
        """设置 Telethon 客户端实例。"""
        self.client = client
        logger.debug(f"Client set for {self.__class__.__name__}") # 添加日志记录

    @property
    def my_id(self) -> int:
        """Get current user ID
        
        Returns:
            int: Current user ID
            
        Raises:
            RuntimeError: If handler is not initialized
        """
        if self._my_id is None:
            # Return 0 instead of raising an error
            # This allows the handler to work even if not fully initialized
            return 0
        return self._my_id
