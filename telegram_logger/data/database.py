import sqlite3
import os
import logging
import asyncio
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
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

        # --- 新增用户机器人配置表 ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_bot_settings (
                user_id INTEGER PRIMARY KEY,
                enabled BOOLEAN DEFAULT 0,
                reply_trigger_enabled BOOLEAN DEFAULT 0,
                ai_history_length INTEGER DEFAULT 1,
                current_model_id TEXT DEFAULT 'gpt-3.5-turbo',
                current_role_alias TEXT DEFAULT 'default_assistant',
                rate_limit_seconds INTEGER DEFAULT 60
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_bot_target_groups (
                chat_id INTEGER PRIMARY KEY
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_bot_model_aliases (
                alias TEXT PRIMARY KEY,
                model_id TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_bot_role_aliases (
                alias TEXT PRIMARY KEY,
                role_type TEXT NOT NULL CHECK(role_type IN ('static', 'ai')),
                description TEXT,
                static_content TEXT,
                system_prompt TEXT,
                preset_messages TEXT -- 存储 JSON 字符串
            )
        """)
        # --- 新增表结束 ---

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

    async def create_role_alias(self, alias: str, role_type: str, static_content: Optional[str] = None):
        """创建角色别名，如果是 static 类型则同时设置内容。"""
        def _sync_create():
            if role_type not in ('static', 'ai'):
                raise ValueError("role_type 必须是 'static' 或 'ai'")
            try:
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO user_bot_role_aliases 
                    (alias, role_type, static_content) 
                    VALUES (?, ?, ?)
                    """,
                    (alias, role_type, static_content if role_type == 'static' else None)
                )
                if role_type == 'static' and static_content is not None:
                     self.conn.execute(
                         "UPDATE user_bot_role_aliases SET static_content = ? WHERE alias = ? AND role_type = 'static'",
                         (static_content, alias)
                     )
                self.conn.commit()
                logger.info(f"已创建或更新角色别名: {alias} (类型: {role_type})")
            except sqlite3.Error as e:
                logger.error(f"创建角色别名 '{alias}' 时出错: {e}", exc_info=True)
                self.conn.rollback()
                raise
        await asyncio.to_thread(_sync_create)

    async def set_role_description(self, alias: str, description: str):
        """设置角色描述。"""
        def _sync_set():
            try:
                cursor = self.conn.execute("UPDATE user_bot_role_aliases SET description = ? WHERE alias = ?", (description, alias))
                self.conn.commit()
                if cursor.rowcount > 0:
                    logger.info(f"已更新角色 '{alias}' 的描述。")
                else:
                    logger.warning(f"尝试更新角色 '{alias}' 的描述，但未找到该别名。")
            except sqlite3.Error as e:
                logger.error(f"更新角色 '{alias}' 描述时出错: {e}", exc_info=True)
                self.conn.rollback()
                raise
        await asyncio.to_thread(_sync_set)

    async def set_role_static_content(self, alias: str, content: str):
        """更新 static 角色的内容。"""
        def _sync_set():
            try:
                cursor = self.conn.execute(
                    "UPDATE user_bot_role_aliases SET static_content = ? WHERE alias = ? AND role_type = 'static'",
                    (content, alias)
                )
                self.conn.commit()
                if cursor.rowcount > 0:
                    logger.info(f"已更新 static 角色 '{alias}' 的内容。")
                else:
                    logger.warning(f"尝试更新 static 角色 '{alias}' 的内容，但未找到该别名或类型不匹配。")
            except sqlite3.Error as e:
                logger.error(f"更新 static 角色 '{alias}' 内容时出错: {e}", exc_info=True)
                self.conn.rollback()
                raise
        await asyncio.to_thread(_sync_set)

    async def set_role_system_prompt(self, alias: str, prompt: str):
        """设置 AI 角色的系统提示。"""
        def _sync_set():
            try:
                cursor = self.conn.execute(
                    "UPDATE user_bot_role_aliases SET system_prompt = ? WHERE alias = ? AND role_type = 'ai'",
                    (prompt, alias)
                )
                self.conn.commit()
                if cursor.rowcount > 0:
                    logger.info(f"已更新 AI 角色 '{alias}' 的系统提示。")
                else:
                    logger.warning(f"尝试更新 AI 角色 '{alias}' 的系统提示，但未找到该别名或类型不匹配。")
            except sqlite3.Error as e:
                logger.error(f"更新 AI 角色 '{alias}' 系统提示时出错: {e}", exc_info=True)
                self.conn.rollback()
                raise
        await asyncio.to_thread(_sync_set)

    async def set_role_preset_messages(self, alias: str, presets_json: str):
        """设置 AI 角色的预设消息 (传入前需确保 presets_json 是有效的 JSON 字符串)。"""
        try:
            json.loads(presets_json)
        except json.JSONDecodeError:
             logger.error(f"为角色 '{alias}' 设置的预设消息不是有效的 JSON 字符串。")
             raise ValueError("预设消息必须是有效的 JSON 字符串")

        def _sync_set():
            try:
                cursor = self.conn.execute(
                    "UPDATE user_bot_role_aliases SET preset_messages = ? WHERE alias = ? AND role_type = 'ai'",
                    (presets_json, alias)
                )
                self.conn.commit()
                if cursor.rowcount > 0:
                    logger.info(f"已更新 AI 角色 '{alias}' 的预设消息。")
                else:
                    logger.warning(f"尝试更新 AI 角色 '{alias}' 的预设消息，但未找到该别名或类型不匹配。")
            except sqlite3.Error as e:
                logger.error(f"更新 AI 角色 '{alias}' 预设消息时出错: {e}", exc_info=True)
                self.conn.rollback()
                raise
        await asyncio.to_thread(_sync_set)

    async def remove_role_alias(self, alias: str):
        """删除角色别名及其配置。"""
        def _sync_remove():
            try:
                cursor = self.conn.execute("DELETE FROM user_bot_role_aliases WHERE alias = ?", (alias,))
                self.conn.commit()
                if cursor.rowcount > 0:
                    logger.info(f"已删除角色别名: {alias}")
                else:
                    logger.warning(f"尝试删除角色别名 '{alias}'，但未找到该记录。")
            except sqlite3.Error as e:
                logger.error(f"删除角色别名 '{alias}' 时出错: {e}", exc_info=True)
                self.conn.rollback()
                raise
        await asyncio.to_thread(_sync_remove)

    async def get_role_aliases(self) -> Dict[str, Dict[str, Any]]:
        """获取所有角色别名及其配置。"""
        def _sync_get():
            roles = {}
            try:
                cursor = self.conn.execute("SELECT * FROM user_bot_role_aliases")
                for row in cursor:
                    roles[row['alias']] = dict(row)
            except sqlite3.Error as e:
                logger.error(f"获取角色别名列表时出错: {e}", exc_info=True)
            return roles
        return await asyncio.to_thread(_sync_get)

    async def get_role_details_by_alias(self, alias: str) -> Optional[Dict[str, Any]]:
        """获取指定角色别名的详细配置。"""
        def _sync_get():
            try:
                cursor = self.conn.cursor()
                cursor.execute("SELECT * FROM user_bot_role_aliases WHERE alias = ?", (alias,))
                row = cursor.fetchone()
                return dict(row) if row else None
            except sqlite3.Error as e:
                logger.error(f"获取角色 '{alias}' 详情时出错: {e}", exc_info=True)
                return None
        return await asyncio.to_thread(_sync_get)

    async def get_messages_before(
        self, chat_id: int, before_message_id: int, limit: int
    ) -> List[Message]:
        """获取指定聊天中某条消息之前的N条消息（按消息ID降序，即时间倒序）。"""
        def _sync_get():
            messages = []
            try:
                query = """
                    SELECT * FROM messages 
                    WHERE chat_id = ? AND id < ? 
                    ORDER BY id DESC 
                    LIMIT ?
                """
                params = [chat_id, before_message_id, limit]
                cursor = self.conn.execute(query, params)
                messages = [self._row_to_message(row) for row in cursor]
                messages.reverse()
            except sqlite3.Error as e:
                logger.error(f"获取 chat_id={chat_id} 中消息 {before_message_id} 之前的消息时出错: {e}", exc_info=True)
            return messages
        return await asyncio.to_thread(_sync_get)

    def close(self):
        """Close database connection"""
        self.conn.close()

    # --- User Bot Settings Methods ---
    
    async def get_user_bot_settings(self, user_id: int) -> Optional[Dict[str, Any]]:
        """获取指定用户的机器人设置。"""
        def _sync_get():
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM user_bot_settings WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        try:
            return await asyncio.to_thread(_sync_get)
        except sqlite3.Error as e:
            logger.error(f"获取用户 {user_id} 机器人设置时出错: {e}", exc_info=True)
            return None

    async def save_user_bot_settings(self, user_id: int, settings: Dict[str, Any]):
        """保存或更新用户机器人设置 (使用 INSERT OR REPLACE)。"""
        def _sync_save():
            data = (
                user_id,
                settings.get('enabled', 0),
                settings.get('reply_trigger_enabled', 0),
                settings.get('ai_history_length', 1),
                settings.get('current_model_id', 'gpt-3.5-turbo'),
                settings.get('current_role_alias', 'default_assistant'),
                settings.get('rate_limit_seconds', 60)
            )
            try:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO user_bot_settings 
                    (user_id, enabled, reply_trigger_enabled, ai_history_length, current_model_id, current_role_alias, rate_limit_seconds) 
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    data
                )
                self.conn.commit()
                logger.info(f"已保存用户 {user_id} 的机器人设置。")
            except sqlite3.Error as e:
                logger.error(f"保存用户 {user_id} 机器人设置时出错: {e}", exc_info=True)
                self.conn.rollback()
                raise

        await asyncio.to_thread(_sync_save)

    async def add_target_group(self, chat_id: int):
        """添加目标群组。"""
        def _sync_add():
            try:
                self.conn.execute("INSERT OR IGNORE INTO user_bot_target_groups (chat_id) VALUES (?)", (chat_id,))
                self.conn.commit()
                logger.info(f"已添加目标群组: {chat_id}")
            except sqlite3.Error as e:
                logger.error(f"添加目标群组 {chat_id} 时出错: {e}", exc_info=True)
                self.conn.rollback()
                raise
        await asyncio.to_thread(_sync_add)

    async def remove_target_group(self, chat_id: int):
        """移除目标群组。"""
        def _sync_remove():
            try:
                cursor = self.conn.execute("DELETE FROM user_bot_target_groups WHERE chat_id = ?", (chat_id,))
                self.conn.commit()
                if cursor.rowcount > 0:
                     logger.info(f"已移除目标群组: {chat_id}")
                else:
                     logger.warning(f"尝试移除目标群组 {chat_id}，但未找到该记录。")
            except sqlite3.Error as e:
                logger.error(f"移除目标群组 {chat_id} 时出错: {e}", exc_info=True)
                self.conn.rollback()
                raise
        await asyncio.to_thread(_sync_remove)

    async def get_target_groups(self) -> List[int]:
        """获取所有目标群组 ID。"""
        def _sync_get():
            try:
                cursor = self.conn.execute("SELECT chat_id FROM user_bot_target_groups")
                return [row['chat_id'] for row in cursor]
            except sqlite3.Error as e:
                logger.error(f"获取目标群组列表时出错: {e}", exc_info=True)
                return []
        return await asyncio.to_thread(_sync_get)

    # Message type constants and validation
    MSG_TYPE_MAP = {
        'user': 1,
        'channel': 2,
        'group': 3,
        'bot': 4
    }

    async def set_model_alias(self, alias: str, model_id: str):
        """设置模型别名。"""
        def _sync_set():
            try:
                self.conn.execute("INSERT OR REPLACE INTO user_bot_model_aliases (alias, model_id) VALUES (?, ?)", (alias, model_id))
                self.conn.commit()
                logger.info(f"已设置模型别名: {alias} -> {model_id}")
            except sqlite3.Error as e:
                logger.error(f"设置模型别名 '{alias}' 时出错: {e}", exc_info=True)
                self.conn.rollback()
                raise
        await asyncio.to_thread(_sync_set)

    async def remove_model_alias(self, alias: str):
        """移除模型别名。"""
        def _sync_remove():
            try:
                cursor = self.conn.execute("DELETE FROM user_bot_model_aliases WHERE alias = ?", (alias,))
                self.conn.commit()
                if cursor.rowcount > 0:
                    logger.info(f"已移除模型别名: {alias}")
                else:
                    logger.warning(f"尝试移除模型别名 '{alias}'，但未找到该记录。")
            except sqlite3.Error as e:
                logger.error(f"移除模型别名 '{alias}' 时出错: {e}", exc_info=True)
                self.conn.rollback()
                raise
        await asyncio.to_thread(_sync_remove)

    async def get_model_aliases(self) -> Dict[str, str]:
        """获取所有模型别名。"""
        def _sync_get():
            aliases = {}
            try:
                cursor = self.conn.execute("SELECT alias, model_id FROM user_bot_model_aliases")
                for row in cursor:
                    aliases[row['alias']] = row['model_id']
            except sqlite3.Error as e:
                logger.error(f"获取模型别名列表时出错: {e}", exc_info=True)
            return aliases
        return await asyncio.to_thread(_sync_get)

    async def get_model_id_by_alias(self, alias: str) -> Optional[str]:
        """通过别名查找模型 ID。"""
        def _sync_get():
            try:
                cursor = self.conn.cursor()
                cursor.execute("SELECT model_id FROM user_bot_model_aliases WHERE alias = ?", (alias,))
                row = cursor.fetchone()
                return row['model_id'] if row else None
            except sqlite3.Error as e:
                logger.error(f"通过别名 '{alias}' 查找模型 ID 时出错: {e}", exc_info=True)
                return None
        return await asyncio.to_thread(_sync_get)

