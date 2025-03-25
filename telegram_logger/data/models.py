from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass(frozen=True)
class Message:
    id: int
    from_id: int
    chat_id: int
    msg_type: int
    msg_text: str
    media: bytes
    noforwards: bool
    self_destructing: bool
    created_time: datetime
    edited_time: Optional[datetime] = None

    @property
    def is_media(self) -> bool:
        return bool(self.media)
