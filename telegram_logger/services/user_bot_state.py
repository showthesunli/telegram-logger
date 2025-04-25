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
        logger.info(f"开始为用户 {self.my_id} 加载 UserBot 状态...")
        # 加载用户设置
        try:
            settings = await self.db.get_user_bot_settings(self.my_id)
            settings = await self.db.get_user_bot_settings(self.my_id)
            if settings is None: # 返回 None 现在明确表示数据库错误
                 logger.critical(f"从数据库加载用户 {self.my_id} 的设置时发生错误。")
                 # 抛出异常，阻止服务在不可靠状态下运行
                 raise RuntimeError(f"从数据库加载用户 {self.my_id} 的 UserBot 设置时发生错误。")
            elif not settings: # 返回空字典 {} 表示未找到记录
                logger.info(f"数据库中未找到用户 {self.my_id} 的设置，将创建默认设置。")
                default_settings = {
                    'enabled': False, # 保持默认禁用
                    'reply_trigger_enabled': False,
                    'ai_history_length': 1,
                    'current_model_id': 'gpt-3.5-turbo',
                    'current_role_alias': 'default_assistant',
                    'rate_limit_seconds': 60
                }
                # Attempt to save defaults
                if not await self.db.save_user_bot_settings(self.my_id, default_settings):
                    logger.critical(f"无法为用户 {self.my_id} 保存初始默认设置到数据库。服务可能无法正常运行。")
                    # 抛出异常
                    raise RuntimeError(f"无法为用户 {self.my_id} 创建默认 UserBot 设置，数据库写入失败。")
                
                # 重新加载以确保写入成功并获取完整数据
                settings = await self.db.get_user_bot_settings(self.my_id)
                if settings is None: # 检查是否在重新加载时发生数据库错误
                    logger.critical(f"创建默认设置后，重新加载用户 {self.my_id} 的设置时发生数据库错误！")
                    raise RuntimeError(f"为用户 {self.my_id} 创建默认设置后，数据库读取失败。")
                elif not settings: # 如果仍然是空字典，说明保存操作未生效但未报错？
                    logger.critical(f"创建默认设置后仍无法加载用户 {self.my_id} 的设置！数据库可能无法写入。")
                    raise RuntimeError(f"无法为用户 {self.my_id} 加载或创建 UserBot 设置，数据库写入可能失败。")
                logger.info(f"已为用户 {self.my_id} 创建并加载默认设置。")

        except Exception as e: # 捕获 get_user_bot_settings 或 save_user_bot_settings 中的其他意外错误
             logger.critical(f"加载用户 {self.my_id} 设置时发生意外错误: {e}", exc_info=True)
             # 抛出异常，而不是继续使用可能不一致的状态
             raise RuntimeError(f"加载用户 {self.my_id} UserBot 设置时发生意外错误。") from e

        # --- 只有在 settings 成功加载或创建后才继续 ---

        # Apply settings (不再需要 .get() 的默认值，因为 settings 保证非空)
        self._enabled = bool(settings['enabled'])
        self._reply_trigger_enabled = bool(settings['reply_trigger_enabled'])
        self._ai_history_length = int(settings['ai_history_length'])
        self._current_model_id = settings['current_model_id']
        self._current_role_alias = settings['current_role_alias']
        self._rate_limit_seconds = int(settings['rate_limit_seconds'])
        logger.info(f"用户 {self.my_id} 设置已加载: enabled={self._enabled}, reply_trigger={self._reply_trigger_enabled}, history={self._ai_history_length}, model={self._current_model_id}, role={self._current_role_alias}, limit={self._rate_limit_seconds}")

        # 加载目标群组
        try:
            target_groups_list = await self.db.get_target_groups()
            # get_target_groups returns [] on DB error, log it
            if not target_groups_list and await self._check_db_error_flag(self.db.get_target_groups): # Heuristic check
                 logger.error(f"加载目标群组列表时可能发生数据库错误 (返回空列表)。")
            self._target_groups = set(target_groups_list)
            logger.info(f"已加载 {len(self._target_groups)} 个目标群组。")
        except Exception as e:
            logger.error(f"加载目标群组时发生意外错误: {e}", exc_info=True)
            self._target_groups = set() # Use empty set on error

        # 加载模型别名
        try:
            self._model_aliases = await self.db.get_model_aliases()
            # get_model_aliases returns {} on DB error, log it
            if not self._model_aliases and await self._check_db_error_flag(self.db.get_model_aliases): # Heuristic check
                 logger.error(f"加载模型别名时可能发生数据库错误 (返回空字典)。")
            logger.info(f"已加载 {len(self._model_aliases)} 个模型别名。")
        except Exception as e:
            logger.error(f"加载模型别名时发生意外错误: {e}", exc_info=True)
            self._model_aliases = {} # Use empty dict on error

        # 加载角色别名
        try:
            self._role_aliases = await self.db.get_role_aliases()
            # get_role_aliases returns {} on DB error, log it
            if not self._role_aliases and await self._check_db_error_flag(self.db.get_role_aliases): # Heuristic check
                 logger.error(f"加载角色别名时可能发生数据库错误 (返回空字典)。")
            logger.info(f"已加载 {len(self._role_aliases)} 个角色别名。")
        except Exception as e:
            logger.error(f"加载角色别名时发生意外错误: {e}", exc_info=True)
            self._role_aliases = {} # Use empty dict on error

        # 检查并创建默认角色
        if 'default_assistant' not in self._role_aliases:
            logger.info("未找到默认角色 'default_assistant'，尝试创建...")
            try:
                created = await self.db.create_role_alias(
                    alias='default_assistant',
                    role_type='ai',
                )
                if created:
                    described = await self.db.set_role_description(
                        alias='default_assistant',
                        description='你是一个通用 AI 助手，请根据对话上下文进行回复。'
                    )
                    if described:
                        logger.info("已成功创建并描述默认角色 'default_assistant'。")
                        # Reload roles after creation
                        self._role_aliases = await self.db.get_role_aliases()
                        if not self._role_aliases and await self._check_db_error_flag(self.db.get_role_aliases):
                             logger.error("重新加载角色别名时可能发生数据库错误。")
                    else:
                        logger.error("创建默认角色 'default_assistant' 后设置描述失败。")
                else:
                    logger.error("创建默认角色 'default_assistant' 失败。")
            except Exception as e:
                 logger.error(f"创建默认角色 'default_assistant' 时发生意外错误: {e}", exc_info=True)

        logger.info(f"UserBot 状态加载完成。")

    # Helper to check if a DB method likely failed (returned empty collection)
    async def _check_db_error_flag(self, db_method, *args, **kwargs) -> bool:
        # This is a heuristic. Assumes DB methods log errors when they return empty due to DB issues.
        # A more robust way would require DB methods to return a more specific error indicator.
        # For now, we just check if the method itself might have logged an error recently.
        # This is NOT reliable.
        # Consider adding a specific return value or exception from DB methods on error.
        return False # Placeholder - reliable check is difficult without DB method changes

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

    # --- 状态更新方法 (返回 bool 表示成功/失败) ---
    async def _update_setting(self, key: str, value: Any) -> bool:
        """Helper to update a single setting in the database and memory."""
        current_settings = await self.db.get_user_bot_settings(self.my_id)
        if current_settings is None:
            logger.error(f"无法获取用户 {self.my_id} 的当前设置以更新 '{key}'。数据库可能存在问题。")
            return False
        
        new_settings = {**current_settings, key: value}
        
        success = await self.db.save_user_bot_settings(self.my_id, new_settings)
        if success:
            setattr(self, f"_{key}", value) # Update in-memory state
            logger.info(f"用户 {self.my_id} 设置 '{key}' 已更新为: {value}")
            return True
        else:
            logger.error(f"更新用户 {self.my_id} 设置 '{key}' 到数据库失败。")
            return False

    async def enable(self) -> bool:
        return await self._update_setting('enabled', True)

    async def disable(self) -> bool:
        return await self._update_setting('enabled', False)

    async def set_reply_trigger(self, enabled: bool) -> bool:
        return await self._update_setting('reply_trigger_enabled', enabled)

    async def set_ai_history_length(self, count: int) -> bool:
        if not (0 <= count <= 20):
            logger.warning(f"尝试设置无效的历史消息数量: {count} (必须在 0-20 之间)")
            # raise ValueError("历史消息数量必须在0-20之间") # Don't raise, return False
            return False
        return await self._update_setting('ai_history_length', count)

    async def set_current_model(self, model_ref: str) -> bool:
        model_id = await self.resolve_model_id(model_ref)
        if not model_id:
            logger.warning(f"尝试设置当前模型，但无法解析引用: {model_ref}")
            # raise ValueError(f"无效的模型引用: {model_ref}") # Don't raise, return False
            return False
        return await self._update_setting('current_model_id', model_id)

    async def set_current_role(self, role_alias: str) -> bool:
        # Check if alias exists locally first for speed, then double-check with DB result
        if role_alias not in self._role_aliases:
             # Maybe it was just created? Check DB again.
             role_details = await self.db.get_role_details_by_alias(role_alias)
             if role_details is None: # DB error or not found
                 logger.warning(f"尝试设置当前角色，但别名 '{role_alias}' 不存在或数据库查询失败。")
                 # raise ValueError(f"无效的角色别名: {role_alias}") # Don't raise, return False
                 return False
             else: # Found in DB, update local cache
                 self._role_aliases[role_alias] = role_details

        return await self._update_setting('current_role_alias', role_alias)

    async def set_rate_limit(self, seconds: int) -> bool:
        if seconds < 0:
            logger.warning(f"尝试设置无效的频率限制: {seconds} (不能为负数)")
            # raise ValueError("频率限制不能为负数") # Don't raise, return False
            return False
        return await self._update_setting('rate_limit_seconds', seconds)

    # --- 群组管理方法 ---
    async def add_group(self, chat_id: int) -> bool:
        success = await self.db.add_target_group(chat_id)
        if success:
            self._target_groups.add(chat_id)
            logger.info(f"目标群组 {chat_id} 已添加。")
            return True
        else:
            # add_target_group logs error on failure
            logger.warning(f"添加目标群组 {chat_id} 失败 (可能已存在或数据库错误)。")
            return False

    async def remove_group(self, chat_id: int) -> bool:
        success = await self.db.remove_target_group(chat_id)
        if success:
            self._target_groups.discard(chat_id)
            logger.info(f"目标群组 {chat_id} 已移除。")
            return True
        else:
            # remove_target_group logs error on failure
            logger.warning(f"移除目标群组 {chat_id} 失败 (可能不存在或数据库错误)。")
            return False

    # --- 别名管理方法 ---
    async def set_model_alias(self, alias: str, model_id: str) -> bool:
        success = await self.db.set_model_alias(alias, model_id)
        if success:
            self._model_aliases[alias] = model_id
            # No need to log here, db method logs success
            return True
        else:
            # db method logs error
            return False

    async def remove_model_alias(self, alias: str) -> bool:
        success = await self.db.remove_model_alias(alias)
        if success:
            removed_value = self._model_aliases.pop(alias, None)
            if removed_value:
                 logger.info(f"模型别名 '{alias}' 已移除。")
            else:
                 logger.warning(f"尝试移除模型别名 '{alias}'，但在内存缓存中未找到。数据库操作可能已成功。")
            return True
        else:
            # db method logs error
            logger.warning(f"移除模型别名 '{alias}' 失败 (可能不存在或数据库错误)。")
            return False

    async def get_model_aliases(self) -> Dict[str, str]:
        # Consider reloading from DB if cache might be stale? For now, return cache.
        return self._model_aliases.copy()

    async def resolve_model_id(self, ref: str) -> Optional[str]:
        """根据别名或ID解析模型ID"""
        if not ref:
            return None
        if ref in self._model_aliases:
            resolved_id = self._model_aliases[ref]
            logger.debug(f"模型引用 '{ref}' 解析为别名，ID: {resolved_id}")
            return resolved_id
        # 假设ref本身就是有效的模型ID，直接返回
        logger.debug(f"模型引用 '{ref}' 未找到别名，假定其为模型 ID。")
        return ref

    # --- 角色管理方法 ---
    async def create_role_alias(self, alias: str, role_type: str, static_content: Optional[str] = None) -> bool:
        if role_type not in ('static', 'ai'):
            logger.warning(f"尝试创建角色别名 '{alias}' 时使用了无效的角色类型: {role_type}")
            # raise ValueError("角色类型必须是 'static' 或 'ai'") # Don't raise
            return False

        success = await self.db.create_role_alias(alias, role_type, static_content)
        if success:
            # Reload roles after successful creation/update
            await self._reload_role_aliases()
            return True
        else:
            # db method logs error
            return False

    async def set_role_description(self, alias: str, description: str) -> bool:
        success = await self.db.set_role_description(alias, description)
        if success:
            await self._reload_role_aliases() # Reload to update cache
            logger.info(f"角色 '{alias}' 描述已更新。")
            return True
        else:
            logger.warning(f"更新角色 '{alias}' 描述失败 (可能别名不存在或数据库错误)。")
            return False

    async def set_role_static_content(self, alias: str, content: str) -> bool:
        success = await self.db.set_role_static_content(alias, content)
        if success:
            await self._reload_role_aliases()
            logger.info(f"角色 '{alias}' (static) 内容已更新。")
            return True
        else:
            logger.warning(f"更新角色 '{alias}' (static) 内容失败 (可能别名不存在、类型不是 static 或数据库错误)。")
            return False

    async def set_role_system_prompt(self, alias: str, prompt: str) -> bool:
        success = await self.db.set_role_system_prompt(alias, prompt)
        if success:
            await self._reload_role_aliases()
            logger.info(f"角色 '{alias}' (ai) 系统提示已更新。")
            return True
        else:
            logger.warning(f"更新角色 '{alias}' (ai) 系统提示失败 (可能别名不存在、类型不是 ai 或数据库错误)。")
            return False

    async def set_role_preset_messages(self, alias: str, presets_json: str) -> bool:
        try:
            json.loads(presets_json)  # 验证JSON
        except json.JSONDecodeError as e:
            logger.warning(f"为角色 '{alias}' 设置的预设消息不是有效的 JSON 字符串: {e}")
            # raise ValueError("预设消息必须是有效的JSON字符串") # Don't raise
            return False

        success = await self.db.set_role_preset_messages(alias, presets_json)
        if success:
            await self._reload_role_aliases()
            logger.info(f"角色 '{alias}' (ai) 预设消息已更新。")
            return True
        else:
            logger.warning(f"更新角色 '{alias}' (ai) 预设消息失败 (可能别名不存在、类型不是 ai 或数据库错误)。")
            return False

    async def remove_role_alias(self, alias: str) -> bool:
        success = await self.db.remove_role_alias(alias)
        if success:
            removed_value = self._role_aliases.pop(alias, None)
            if removed_value:
                 logger.info(f"角色别名 '{alias}' 已移除。")
            else:
                 logger.warning(f"尝试移除角色别名 '{alias}'，但在内存缓存中未找到。数据库操作可能已成功。")
            # No need to reload here, just removed from cache
            return True
        else:
            logger.warning(f"移除角色别名 '{alias}' 失败 (可能不存在或数据库错误)。")
            return False

    async def get_role_aliases(self) -> Dict[str, Dict[str, Any]]:
        # Consider reloading from DB if cache might be stale? For now, return cache.
        return self._role_aliases.copy()

    async def resolve_role_details(self, alias: str) -> Optional[Dict[str, Any]]:
        """根据别名获取角色详情"""
        if not alias:
            return None
        # Check cache first
        if alias in self._role_aliases:
            logger.debug(f"角色别名 '{alias}' 在缓存中找到。")
            return self._role_aliases[alias]
        
        # If not in cache, try DB (might have been added externally or cache is stale)
        logger.debug(f"角色别名 '{alias}' 不在缓存中，尝试从数据库获取...")
        details = await self.db.get_role_details_by_alias(alias)
        if details is None:
            # get_role_details_by_alias logs error if DB error occurred
            logger.warning(f"无法通过别名 '{alias}' 获取角色详情 (别名不存在或数据库错误)。")
            return None
        else:
            # Found in DB, update cache
            logger.info(f"从数据库加载了角色别名 '{alias}' 的详情并更新缓存。")
            self._role_aliases[alias] = details
            return details

    async def _reload_role_aliases(self):
        """Helper to reload role aliases from DB into memory cache."""
        logger.debug("重新加载角色别名缓存...")
        try:
            self._role_aliases = await self.db.get_role_aliases()
            if not self._role_aliases and await self._check_db_error_flag(self.db.get_role_aliases):
                 logger.error("重新加载角色别名时可能发生数据库错误。")
            logger.debug(f"角色别名缓存已更新，共 {len(self._role_aliases)} 个。")
        except Exception as e:
            logger.error(f"重新加载角色别名时发生意外错误: {e}", exc_info=True)
            # Keep the old cache in case of error? Or clear it? Keeping old for now.


    # --- 频率限制方法 ---
    def check_rate_limit(self, chat_id: int) -> bool:
        """检查是否允许在当前群组发送回复"""
        last_time = self._rate_limit_cache.get(chat_id, 0)
        return (time.time() - last_time) >= self._rate_limit_seconds

    def update_rate_limit(self, chat_id: int):
        """更新群组的最后回复时间"""
        self._rate_limit_cache[chat_id] = time.time()
