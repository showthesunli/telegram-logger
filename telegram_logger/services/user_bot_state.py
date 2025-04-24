import logging
import time
from typing import Dict, Set, Optional, Any
import asyncio
import json

logger = logging.getLogger(__name__)

class UserBotStateService:
    """管理用户机器人状态的服务类"""
    
    def __init__(self, db, my_id: int):
        """初始化服务
        
        Args:
            db: DatabaseManager 实例
            my_id: 用户自己的 Telegram ID
        """
        self.db = db
        self.my_id = my_id
        
        # 内存状态
        self._enabled = False
        self._reply_trigger_enabled = False
        self._ai_history_length = 1
        self._current_model_id = 'gpt-3.5-turbo'
        self._current_role_alias = 'default_assistant'
        self._rate_limit_seconds = 60
        self._target_groups: Set[int] = set()
        self._model_aliases: Dict[str, str] = {}
        self._role_aliases: Dict[str, Dict[str, Any]] = {}
        self._rate_limit_cache: Dict[int, float] = {}  # chat_id -> last_reply_timestamp

    async def load_state(self):
        """从数据库加载初始状态"""
        # 加载用户设置
        settings = await self.db.get_user_bot_settings(self.my_id)
        if not settings:
            # 初始化默认设置
            settings = {
                'enabled': False,
                'reply_trigger_enabled': False,
                'ai_history_length': 1,
                'current_model_id': 'gpt-3.5-turbo',
                'current_role_alias': 'default_assistant',
                'rate_limit_seconds': 60
            }
            await self.db.save_user_bot_settings(self.my_id, settings)
        
        self._enabled = bool(settings['enabled'])
        self._reply_trigger_enabled = bool(settings['reply_trigger_enabled'])
        self._ai_history_length = int(settings['ai_history_length'])
        self._current_model_id = settings['current_model_id']
        self._current_role_alias = settings['current_role_alias']
        self._rate_limit_seconds = int(settings['rate_limit_seconds'])

        # 加载目标群组
        self._target_groups = set(await self.db.get_target_groups())

        # 加载模型别名
        self._model_aliases = await self.db.get_model_aliases()

        # 加载角色别名
        self._role_aliases = await self.db.get_role_aliases()
        
        # 检查并创建默认角色
        if 'default_assistant' not in self._role_aliases:
            await self.db.create_role_alias(
                alias='default_assistant',
                role_type='ai',
            )
            await self.db.set_role_description(
                alias='default_assistant',
                description='你是一个通用 AI 助手，请根据对话上下文进行回复。'
            )
            self._role_aliases = await self.db.get_role_aliases()

    # 状态访问方法
    def is_enabled(self) -> bool:
        return self._enabled

    def is_reply_trigger_enabled(self) -> bool:
        return self._reply_trigger_enabled

    def get_current_model_id(self) -> str:
        return self._current_model_id

    def get_current_role_alias(self) -> str:
        return self._current_role_alias

    def get_target_group_ids(self) -> Set[int]:
        return self._target_groups.copy()

    def get_rate_limit(self) -> int:
        return self._rate_limit_seconds

    def get_ai_history_length(self) -> int:
        return self._ai_history_length

    # 状态更新方法
    async def enable(self):
        await self.db.save_user_bot_settings(self.my_id, {
            **await self.db.get_user_bot_settings(self.my_id),
            'enabled': True
        })
        self._enabled = True

    async def disable(self):
        await self.db.save_user_bot_settings(self.my_id, {
            **await self.db.get_user_bot_settings(self.my_id),
            'enabled': False
        })
        self._enabled = False

    async def set_reply_trigger(self, enabled: bool):
        await self.db.save_user_bot_settings(self.my_id, {
            **await self.db.get_user_bot_settings(self.my_id),
            'reply_trigger_enabled': enabled
        })
        self._reply_trigger_enabled = enabled

    async def set_ai_history_length(self, count: int):
        if count < 0 or count > 20:
            raise ValueError("历史消息数量必须在0-20之间")
        await self.db.save_user_bot_settings(self.my_id, {
            **await self.db.get_user_bot_settings(self.my_id),
            'ai_history_length': count
        })
        self._ai_history_length = count

    async def set_current_model(self, model_ref: str):
        model_id = await self.resolve_model_id(model_ref)
        if not model_id:
            raise ValueError(f"无效的模型引用: {model_ref}")
        
        await self.db.save_user_bot_settings(self.my_id, {
            **await self.db.get_user_bot_settings(self.my_id),
            'current_model_id': model_id
        })
        self._current_model_id = model_id

    async def set_current_role(self, role_alias: str):
        if role_alias not in self._role_aliases:
            raise ValueError(f"无效的角色别名: {role_alias}")
        
        await self.db.save_user_bot_settings(self.my_id, {
            **await self.db.get_user_bot_settings(self.my_id),
            'current_role_alias': role_alias
        })
        self._current_role_alias = role_alias

    async def set_rate_limit(self, seconds: int):
        if seconds < 0:
            raise ValueError("频率限制不能为负数")
        
        await self.db.save_user_bot_settings(self.my_id, {
            **await self.db.get_user_bot_settings(self.my_id),
            'rate_limit_seconds': seconds
        })
        self._rate_limit_seconds = seconds

    # 群组管理方法
    async def add_group(self, chat_id: int):
        await self.db.add_target_group(chat_id)
        self._target_groups.add(chat_id)

    async def remove_group(self, chat_id: int):
        await self.db.remove_target_group(chat_id)
        self._target_groups.discard(chat_id)

    # 别名管理方法
    async def set_model_alias(self, alias: str, model_id: str):
        await self.db.set_model_alias(alias, model_id)
        self._model_aliases[alias] = model_id

    async def remove_model_alias(self, alias: str):
        await self.db.remove_model_alias(alias)
        self._model_aliases.pop(alias, None)

    async def get_model_aliases(self) -> Dict[str, str]:
        return self._model_aliases.copy()

    async def resolve_model_id(self, ref: str) -> Optional[str]:
        """根据别名或ID解析模型ID"""
        if ref in self._model_aliases:
            return self._model_aliases[ref]
        # 假设ref本身就是有效的模型ID
        return ref if ref else None

    # 角色管理方法
    async def create_role_alias(self, alias: str, role_type: str, static_content: Optional[str] = None):
        if role_type not in ('static', 'ai'):
            raise ValueError("角色类型必须是 'static' 或 'ai'")
        
        await self.db.create_role_alias(alias, role_type, static_content)
        self._role_aliases = await self.db.get_role_aliases()

    async def set_role_description(self, alias: str, description: str):
        await self.db.set_role_description(alias, description)
        self._role_aliases = await self.db.get_role_aliases()

    async def set_role_static_content(self, alias: str, content: str):
        await self.db.set_role_static_content(alias, content)
        self._role_aliases = await self.db.get_role_aliases()

    async def set_role_system_prompt(self, alias: str, prompt: str):
        await self.db.set_role_system_prompt(alias, prompt)
        self._role_aliases = await self.db.get_role_aliases()

    async def set_role_preset_messages(self, alias: str, presets_json: str):
        try:
            json.loads(presets_json)  # 验证JSON
        except json.JSONDecodeError:
            raise ValueError("预设消息必须是有效的JSON字符串")
        
        await self.db.set_role_preset_messages(alias, presets_json)
        self._role_aliases = await self.db.get_role_aliases()

    async def remove_role_alias(self, alias: str):
        await self.db.remove_role_alias(alias)
        self._role_aliases = await self.db.get_role_aliases()

    async def get_role_aliases(self) -> Dict[str, Dict[str, Any]]:
        return self._role_aliases.copy()

    async def resolve_role_details(self, alias: str) -> Optional[Dict[str, Any]]:
        """根据别名获取角色详情"""
        return await self.db.get_role_details_by_alias(alias)

    # 频率限制方法
    def check_rate_limit(self, chat_id: int) -> bool:
        """检查是否允许在当前群组发送回复"""
        last_time = self._rate_limit_cache.get(chat_id, 0)
        return (time.time() - last_time) >= self._rate_limit_seconds

    def update_rate_limit(self, chat_id: int):
        """更新群组的最后回复时间"""
        self._rate_limit_cache[chat_id] = time.time()
