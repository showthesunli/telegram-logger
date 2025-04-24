from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any

@dataclass(frozen=True)
class Message:
    id: int
    from_id: int
    chat_id: int
    msg_type: int
    msg_text: str
    media_path: Optional[str]
    noforwards: bool
    self_destructing: bool
    created_time: datetime
    edited_time: Optional[datetime] = None

    @property
    def is_media(self) -> bool:
        return bool(self.media_path)


@dataclass(frozen=True)
class RoleDetails:
    """表示从数据库读取的角色配置的数据类。"""
    alias: str
    role_type: str  # 'static' 或 'ai'
    description: Optional[str] = None
    static_content: Optional[str] = None  # 仅用于 static 类型
    system_prompt: Optional[str] = None  # 仅用于 ai 类型
    preset_messages: Optional[str] = None  # 存储原始 JSON 字符串, 仅用于 ai 类型
