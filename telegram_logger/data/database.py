import sqlite3
import os
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
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
                media_path TEXT,
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
                message.media_path,
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
        except Exception as e:
            logger.error(f"保存消息时出错 (MsgID={message.id} ChatID={message.chat_id}): {e}", exc_info=True)
            self.conn.rollback()

    def get_message_by_id(self, message_id: int) -> Optional[Message]:
        """根据消息 ID 从数据库检索消息。"""
        try:
            cursor = self.conn.cursor()
            # 获取与该消息 ID 关联的最早记录（通常是原始消息）
            cursor.execute("SELECT * FROM messages WHERE id = ? ORDER BY created_time ASC LIMIT 1", (message_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_message(row)
            else:
                logger.debug(f"在数据库中未找到消息 ID: {message_id}")
                return None
        except sqlite3.Error as e:
            logger.error(f"从数据库检索消息 ID {message_id} 时出错: {e}", exc_info=True)
            return None

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
        """Delete expired messages by type and their associated media files"""
        now = datetime.now()
        conditions = []
        params = []
        media_paths_to_delete = set() # 使用集合存储待删除的媒体路径
        
        # 1. 收集所有过期消息的媒体路径，并构建删除条件
        for persist_type, days in persist_times.items():
            if persist_type not in self.MSG_TYPE_MAP:
                logger.warning(f"未知的消息类型: {persist_type}")
                continue
            
            cutoff = now - timedelta(days=days)
            type_val = self.MSG_TYPE_MAP[persist_type]
            
            # 添加数据库删除条件
            conditions.append("(type = ? AND created_time < ?)")
            params.extend([type_val, cutoff])

            # 查询需要删除的媒体文件路径
            try:
                cursor = self.conn.execute(
                    "SELECT media_path FROM messages "
                    "WHERE type = ? AND created_time < ? AND media_path IS NOT NULL",
                    (type_val, cutoff)
                )
                # 将查询到的非空路径添加到集合中
                for row in cursor:
                    media_paths_to_delete.add(row['media_path'])
            except sqlite3.Error as e:
                logger.error(f"查询过期媒体路径时出错 (类型: {persist_type}): {e}", exc_info=True)


        if not conditions:
            logger.info("没有有效的过期条件，无需删除。")
            return 0

        deleted_db_rows = 0
        deleted_files = 0

        # 2. 删除数据库记录
        try:
            query = f"DELETE FROM messages WHERE {' OR '.join(conditions)}"
            cursor = self.conn.execute(query, params)
            deleted_db_rows = cursor.rowcount # 获取实际删除的行数
            logger.info(f"数据库中删除了 {deleted_db_rows} 条过期消息记录。")
        except sqlite3.Error as e:
            logger.error(f"删除过期数据库记录时出错: {e}", exc_info=True)
            self.conn.rollback() # 发生错误时回滚
            return 0 # 返回0表示本次操作未成功删除

        # 3. 清理关联的媒体文件
        if media_paths_to_delete:
            media_dir = Path("media").resolve() # 使用绝对路径以提高安全性
            logger.info(f"开始清理 {len(media_paths_to_delete)} 个关联的媒体文件...")
            for media_path_str in media_paths_to_delete:
                try:
                    media_file = Path(media_path_str).resolve()
                    # 增强检查：确保文件存在且在 media_dir 目录下
                    if media_file.exists() and media_file.is_file() and media_dir in media_file.parents:
                        media_file.unlink()
                        deleted_files += 1
                        logger.debug(f"已删除媒体文件: {media_path_str}")
                    elif not media_file.exists():
                        logger.warning(f"尝试删除媒体文件但文件不存在: {media_path_str}")
                    elif media_dir not in media_file.parents:
                         logger.warning(f"媒体文件路径不在预期的 'media' 目录下，跳过删除: {media_path_str}")
                    # else: 文件存在但不是文件（例如目录），也跳过
                except OSError as e:
                    logger.error(f"删除媒体文件 {media_path_str} 时发生 OS 错误: {str(e)}")
                except Exception as e:
                    logger.error(f"删除媒体文件 {media_path_str} 时发生未知错误: {str(e)}", exc_info=True)

        self.conn.commit()
        logger.info(f"清理完成。数据库删除 {deleted_db_rows} 条记录，文件系统删除 {deleted_files} 个文件。")
        # 返回总共清理的项目数（数据库记录 + 文件）
        return deleted_db_rows + deleted_files

    def _row_to_message(self, row) -> Message:
        """Convert database row to Message object"""
        return Message(
            id=row['id'],
            from_id=row['from_id'],
            chat_id=row['chat_id'],
            msg_type=row['type'],
            msg_text=row['msg_text'],
            media_path=row['media_path'],
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

