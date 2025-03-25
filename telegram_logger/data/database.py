import sqlite3
import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from .models import Message

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_path: str = "db/messages.db"):
        self.db_path = db_path
        self.conn = self._init_db()
        self.conn.row_factory = sqlite3.Row

    def _init_db(self):
        """Initialize database connection and create tables"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        self._create_tables(conn)
        return conn

    def _create_tables(self, conn):
        """Create database schema"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER, 
                from_id INTEGER, 
                chat_id INTEGER,
                type INTEGER, 
                msg_text TEXT, 
                media BLOB, 
                noforwards INTEGER DEFAULT 0, 
                self_destructing INTEGER DEFAULT 0, 
                created_time TIMESTAMP, 
                edited_time TIMESTAMP,
                PRIMARY KEY (chat_id, id, edited_time)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_msg_created 
            ON messages (created_time DESC)
        """)
        conn.commit()

    def save_message(self, message: Message):
        """Save message to database"""
        try:
            params = (
                message.id,
                message.from_id,
                message.chat_id,
                message.msg_type,
                message.msg_text,
                message.media,
                int(message.noforwards),
                int(message.self_destructing),
                message.created_time,
                message.edited_time
            )
            self.conn.execute(
                "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                params
            )
            self.conn.commit()
            logger.debug(f"Message saved: MsgID={message.id} ChatID={message.chat_id}")
        except sqlite3.IntegrityError:
            logger.warning(f"Duplicate message ignored: MsgID={message.id} ChatID={message.chat_id}")
            self.conn.rollback()

    def get_messages(
        self, 
        chat_id: int, 
        message_ids: List[int], 
        limit: int = 100
    ) -> List[Message]:
        """Get latest versions of messages by IDs"""
        query = f"""
            SELECT * FROM (
                SELECT * FROM messages 
                WHERE chat_id = ? AND id IN ({','.join('?'*len(message_ids))}) 
                ORDER BY edited_time DESC LIMIT ?
            ) GROUP BY chat_id, id 
            ORDER BY created_time ASC
        """
        params = [chat_id, *message_ids, limit]
        cursor = self.conn.execute(query, params)
        return [self._row_to_message(row) for row in cursor]

    def delete_expired_messages(
        self, 
        persist_times: Dict[str, int]
    ) -> int:
        """Delete expired messages by type"""
        now = datetime.now()
        conditions = []
        params = []
        
        for persist_type, days in persist_times.items():
            if persist_type not in self.MSG_TYPE_MAP:
                logger.warning(f"未知的消息类型: {persist_type}")
                continue
            cutoff = now - timedelta(days=days)
            conditions.append("(type = ? AND created_time < ?)")
            params.extend([self.MSG_TYPE_MAP[persist_type], cutoff])
        
        query = f"DELETE FROM messages WHERE {' OR '.join(conditions)}"
        self.conn.execute(query, params)
        self.conn.commit()
        return self.conn.total_changes

    def _row_to_message(self, row) -> Message:
        """Convert database row to Message object"""
        return Message(
            id=row['id'],
            from_id=row['from_id'],
            chat_id=row['chat_id'],
            msg_type=row['type'],
            msg_text=row['msg_text'],
            media=row['media'],
            noforwards=bool(row['noforwards']),
            self_destructing=bool(row['self_destructing']),
            created_time=datetime.fromisoformat(row['created_time']),
            edited_time=datetime.fromisoformat(row['edited_time']) if row['edited_time'] else None
        )

    def close(self):
        """Close database connection"""
        self.conn.close()

    # Message type constants and validation
    MSG_TYPE_MAP = {
        'user': 1,
        'channel': 2,
        'group': 3,
        'bot': 4
    }

