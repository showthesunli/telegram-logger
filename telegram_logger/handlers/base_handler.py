import logging
import pickle
from typing import Optional, Union, List, Dict, Any
from telethon import events
from telethon.tl.types import PeerUser, PeerChannel, PeerChat
from telegram_logger.data.models import Message
from telegram_logger.data.database import DatabaseManager
from telegram_logger.utils.media import save_media_as_file, retrieve_media_as_file

logger = logging.getLogger(__name__)

class BaseHandler:
    MSG_TYPE_MAP = {
        'user': 1,
        'channel': 2,
        'group': 3,
        'bot': 4
    }

    def __init__(
        self, 
        client, 
        db: DatabaseManager,
        log_chat_id: int,
        ignored_ids: set,
        **kwargs: Dict[str, Any]
    ):
        self.client = client
        self.db = db
        self.log_chat_id = log_chat_id
        self.ignored_ids = ignored_ids
        self._my_id: Optional[int] = None

    async def init(self):
        """Initialize handler with client user ID"""
        me = await self.client.get_me()
        self._my_id = me.id
        logger.info(f"{self.__class__.__name__} initialized")

    async def process(self, event: events.Event) -> Optional[Union[Message, List[Message]]]:
        """Process event and return message object(s)"""
        raise NotImplementedError

    async def save_message(self, message: Message):
        """Save message to database"""
        try:
            self.db.save_message(message)
            logger.debug(f"Message saved: {message.id}")
        except Exception as e:
            logger.error(f"Failed to save message: {str(e)}")
            raise

    def _get_sender_id(self, message) -> int:
        """Get sender ID from message object"""
        if isinstance(message.peer_id, PeerUser):
            return self.my_id if message.out else message.peer_id.user_id
        elif isinstance(message.peer_id, (PeerChannel, PeerChat)):
            if hasattr(message, 'from_id') and message.from_id:
                if isinstance(message.from_id, PeerUser):
                    return message.from_id.user_id
                if isinstance(message.from_id, PeerChannel):
                    return message.from_id.channel_id
        return 0

    async def _handle_media_message(self, message: Message, text: str):
        """Handle message with media content"""
        if not message.is_media:
            await self.client.send_message(self.log_chat_id, text)
            return

        try:
            media = pickle.loads(message.media)
            with retrieve_media_as_file(
                message.id,
                message.chat_id,
                media,
                message.noforwards or message.self_destructing
            ) as media_file:
                await self.client.send_message(
                    self.log_chat_id,
                    text,
                    file=media_file
                )
        except Exception as e:
            logger.error(f"Failed to handle media message: {str(e)}")
            await self.client.send_message(self.log_chat_id, text)

    @property
    def my_id(self) -> int:
        """Get authenticated user ID"""
        if self._my_id is None:
            raise RuntimeError("Handler not initialized")
        return self._my_id
import logging
import pickle
from abc import ABC, abstractmethod
from typing import Optional, Any, Union, List
from datetime import datetime
from telethon import TelegramClient, events
from telethon.tl.types import *
from telegram_logger.data.database import DatabaseManager
from telegram_logger.data.models import Message
from telegram_logger.utils.media import save_media, retrieve_media
from telegram_logger.utils.mentions import create_mention
from telegram_logger.config import IGNORED_IDS, LOG_CHAT_ID

logger = logging.getLogger(__name__)

class BaseHandler(ABC):
    """Base handler class for all message handlers"""
    
    MSG_TYPE_MAP = {
        'user': 1,
        'channel': 2,
        'group': 3,
        'bot': 4
    }

    def __init__(self, client: TelegramClient, db: DatabaseManager):
        self.client = client
        self.db = db
        self._my_id: Optional[int] = None

    async def init(self):
        """Initialize handler with client user ID"""
        me = await self.client.get_me()
        self._my_id = me.id
        logger.info(f"{self.__class__.__name__} initialized")

    @abstractmethod
    async def process(self, event: Any) -> Optional[Union[Message, List[Message]]]:
        """Process the event and return Message object(s) if handled"""
        pass

    def _get_sender_id(self, message) -> int:
        """Get sender ID from message object"""
        if hasattr(message, 'out') and message.out:
            return self.my_id
        if isinstance(message.peer_id, PeerUser):
            return message.peer_id.user_id
        if hasattr(message, 'from_id'):
            if isinstance(message.from_id, PeerUser):
                return message.from_id.user_id
            if isinstance(message.from_id, PeerChannel):
                return message.from_id.channel_id
        return 0

    async def _get_chat_type(self, event) -> int:
        """Determine message type from event"""
        if event.is_group:
            return self.MSG_TYPE_MAP['group']
        elif event.is_channel:
            return self.MSG_TYPE_MAP['channel']
        elif event.is_private:
            sender = await event.get_sender()
            return self.MSG_TYPE_MAP['bot'] if sender.bot else self.MSG_TYPE_MAP['user']
        return 0

    async def _save_message(self, message: Message):
        """Save message to database"""
        try:
            self.db.save_message(message)
            logger.debug(f"Message saved: {message.id}")
        except Exception as e:
            logger.error(f"Failed to save message: {str(e)}")
            raise

    @property
    def my_id(self) -> int:
        """Get authenticated user ID"""
        if self._my_id is None:
            raise RuntimeError("Handler not initialized")
        return self._my_id
import logging
import pickle
from contextlib import contextmanager
from typing import Optional, Union, List, Dict, Any
from datetime import datetime

from telethon import TelegramClient, events
from telethon.tl.types import PeerUser, PeerChannel, PeerChat

from telegram_logger.data.database import DatabaseManager
from telegram_logger.data.models import Message
from telegram_logger.utils.media import save_media, retrieve_media
from telegram_logger.config import (
    FILE_PASSWORD,
    LOG_CHAT_ID,
    IGNORED_IDS
)

logger = logging.getLogger(__name__)

class BaseHandler:
    """Base class for all message handlers providing common functionality"""
    
    MSG_TYPE_MAP = {
        'user': 1,
        'channel': 2,
        'group': 3,
        'bot': 4
    }

    def __init__(
        self, 
        client: TelegramClient, 
        db: DatabaseManager,
        **kwargs: Dict[str, Any]
    ):
        self.client = client
        self.db = db
        self._my_id: Optional[int] = None

    async def init(self):
        """Initialize handler with client user ID"""
        me = await self.client.get_me()
        self._my_id = me.id
        logger.info(f"{self.__class__.__name__} initialized")

    async def process(self, event: events.Event) -> Optional[Union[Message, List[Message]]]:
        """Process event and return message object(s) (to be implemented by subclasses)"""
        raise NotImplementedError

    async def save_message(self, message: Message):
        """Save message to database"""
        try:
            self.db.save_message(message)
            logger.debug(f"Message saved: {message.id}")
        except Exception as e:
            logger.error(f"Failed to save message: {str(e)}")
            raise

    def _get_sender_id(self, message) -> int:
        """Get sender ID from message object"""
        if hasattr(message, 'out') and message.out:
            return self.my_id
        if isinstance(message.peer_id, PeerUser):
            return message.peer_id.user_id
        if hasattr(message, 'from_id'):
            if isinstance(message.from_id, PeerUser):
                return message.from_id.user_id
            if isinstance(message.from_id, PeerChannel):
                return message.from_id.channel_id
        return 0

    async def _get_chat_type(self, event) -> int:
        """Determine message type from event"""
        if event.is_group:
            return self.MSG_TYPE_MAP['group']
        elif event.is_channel:
            return self.MSG_TYPE_MAP['channel']
        elif event.is_private:
            sender = await event.get_sender()
            return self.MSG_TYPE_MAP['bot'] if sender.bot else self.MSG_TYPE_MAP['user']
        return 0

    @contextmanager
    def _retrieve_media(self, file_path: str, is_restricted: bool):
        """Context manager for retrieving media files"""
        try:
            if is_restricted:
                with retrieve_media(file_path, FILE_PASSWORD) as f:
                    yield f
            else:
                yield None
        except Exception as e:
            logger.error(f"Error retrieving media: {str(e)}")
            yield None

    @property
    def my_id(self) -> int:
        """Get authenticated user ID"""
        if self._my_id is None:
            raise RuntimeError("Handler not initialized")
        return self._my_id
