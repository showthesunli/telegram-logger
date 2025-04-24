# IMP 001: RFC 003 用户机器人实现计划

**状态:** 草稿
**关联 RFC:** [RFC/003-用户机器人设计.md](../RFC/003-用户机器人设计.md)
**创建日期:** 2025-04-23
**作者:** AI Assistant & User

## 1. 引言

本文档旨在详细规划和指导 **RFC 003: 用户账户提及自动回复机器人** 功能的实现过程。它基于 RFC 003 中定义的需求和设计决策，将其分解为具体的开发任务和步骤。

## 2. 架构概述

此功能将作为现有 `telegram-delete-logger` 系统的一个扩展模块。主要涉及以下组件：

-   **数据存储:** 需要扩展现有数据库 (`DatabaseManager`) 或引入新的存储机制来持久化用户配置和别名数据。
-   **状态管理:** 需要一个服务或管理器来加载、缓存和访问当前用户的配置状态。
-   **指令处理器 (`UserBotCommandHandler`):** 一个新的 Handler 类，继承自 `BaseHandler` 或类似基类，负责处理用户在私聊中发送的控制指令。
-   **事件监听器 (`MentionReplyHandler`):** 一个新的 Handler 类，继承自 `BaseHandler` 或类似基类，负责监听目标群组中的新消息事件，判断是否满足触发条件，并执行自动回复。
-   **AI 服务接口 (可选):** 如果需要与外部 AI 服务（如 OpenAI, Claude 等）交互，需要定义清晰的接口。
-   **事件注册:** 在应用初始化阶段，显式地将 Handler 类的方法注册到 `telethon` 客户端的事件分发器。

## 3. 数据存储设计

我们将扩展现有的 SQLite 数据库 (`db/messages.db`) 来存储用户机器人的配置。需要新增以下表：

**3.1. `user_bot_settings` 表 (单行表，存储全局设置)**

| 列名                  | 类型    | 描述                                     | 默认值             |
| :-------------------- | :------ | :--------------------------------------- | :----------------- |
| `user_id`             | INTEGER | 用户自己的 Telegram ID (主键, 通过 `client.get_me().id` 获取的真实、非零 ID) | N/A                |
| `enabled`             | BOOLEAN | 功能是否启用                             | `False`            |
| `reply_trigger_enabled` | BOOLEAN | 是否启用回复触发                         | `False`            |
| `ai_history_length`   | INTEGER | AI 生成回复时额外加载的历史消息数量 (0 表示不加载额外历史) | `1`                |
| `current_model_id`    | TEXT    | 当前选择的 AI 模型 ID 或别名             | `gpt-3.5-turbo`    |
| `current_role_alias`  | TEXT    | 当前选择的 AI 角色别名                   | `default_assistant` |
| `rate_limit_seconds`  | INTEGER | 同一群组内两次回复的最小间隔（秒）       | `60`               |

**3.2. `user_bot_target_groups` 表 (存储目标群组)**

| 列名      | 类型    | 描述                 |
| :-------- | :------ | :------------------- |
| `chat_id` | INTEGER | 目标群组的 ID (主键) |

**3.3. `user_bot_model_aliases` 表 (存储模型别名)**

| 列名      | 类型    | 描述                 |
| :-------- | :------ | :------------------- |
| `alias`   | TEXT    | 模型别名 (主键)      |
| `model_id`| TEXT    | 对应的官方模型 ID    |

**3.4. `user_bot_role_aliases` 表 (存储角色别名)**

| 列名             | 类型    | 描述                                                         |
| :--------------- | :------ | :----------------------------------------------------------- |
| `alias`          | TEXT    | 角色别名 (主键)                                              |
| `role_type`      | TEXT    | 角色类型 (`static` 或 `ai`)                                  |
| `description`    | TEXT    | 人类可读的角色描述 (适用于所有类型, 可选)                    |
| `static_content` | TEXT    | 静态回复内容 (仅用于 `static` 类型, 可选)                    |
| `system_prompt`  | TEXT    | AI 系统提示词 (仅用于 `ai` 类型, 可选)                       |
| `preset_messages`| TEXT    | AI 预设消息 (JSON 字符串列表，仅用于 `ai` 类型, 可选, 存储时需确保存储的是有效的 JSON 字符串) |

**3.5. 频率限制状态存储 (内存实现)**

*   **注意:** 频率限制状态（最后回复时间戳）通常更适合存储在内存中（例如 Python 字典），以获得更好的性能。如果需要跨重启保持状态，可以考虑持久化，但这会增加 I/O 开销。**初步实现将使用内存缓存。**
    *   内存结构: `Dict[int, float]`  ( `chat_id` -> `last_reply_timestamp`)


**阶段 1: 数据模型与存储层 (`telegram_logger/data`)**

1.  `[x]` **[DB]** 在 `DatabaseManager._create_tables` 中添加创建上述 `user_bot_settings`, `user_bot_target_groups`, `user_bot_model_aliases`, `user_bot_role_aliases` 四个表的 SQL 语句。
2.  `[x]` **[DB]** 实现 `DatabaseManager` 中的异步方法 (`async def`) 来管理这些表：
    *   `[x]` `get_user_bot_settings(user_id: int) -> Optional[Dict]`：获取指定用户的设置。
    *   `[x]` `save_user_bot_settings(user_id: int, settings: Dict)`：保存或更新用户设置 (使用 `INSERT OR REPLACE`)。
    *   `[x]` `add_target_group(chat_id: int)`：添加目标群组。
    *   `[x]` `remove_target_group(chat_id: int)`：移除目标群组。
    *   `[x]` `get_target_groups() -> List[int]`：获取所有目标群组 ID。
    *   `[x]` `set_model_alias(alias: str, model_id: str)`：设置模型别名。
    *   `[x]` `remove_model_alias(alias: str)`：移除模型别名。
    *   `[x]` `get_model_aliases() -> Dict[str, str]`：获取所有模型别名。
    *   `[x]` `get_model_id_by_alias(alias: str) -> Optional[str]`：通过别名查找模型 ID。
    *   `[x]` `create_role_alias(alias: str, role_type: str, static_content: Optional[str] = None)`：创建角色别名，如果是 static 类型则同时设置内容。
    *   `[x]` `set_role_description(alias: str, description: str)`：设置角色描述。
    *   `[x]` `set_role_static_content(alias: str, content: str)`：更新 static 角色的内容。
    *   `[x]` `set_role_system_prompt(alias: str, prompt: str)`：设置 AI 角色的系统提示。
    *   `[x]` `set_role_preset_messages(alias: str, presets_json: str)`：设置 AI 角色的预设消息 (传入前需确保 `presets_json` 是有效的 JSON 字符串)。
    *   `[x]` `remove_role_alias(alias: str)`：删除角色别名及其配置。
    *   `[x]` `get_role_aliases() -> Dict[str, Dict[str, Any]]`：获取所有角色别名及其配置。
    *   `[x]` `get_role_details_by_alias(alias: str) -> Optional[Dict[str, Any]]`：获取指定角色别名的详细配置。
    *   `[x]` `async get_messages_before(chat_id: int, before_message_id: int, limit: int) -> List[Message]`：获取指定聊天中某条消息之前的N条消息（按id降序排列）。
3.  `[x]` **[Model]** (推荐) 创建 Dataclass `RoleDetails` 来表示从数据库读取的角色配置，包含 `alias`, `role_type`, `description`, `static_content`, `system_prompt`, `preset_messages` (原始 JSON 字符串) 字段。

**阶段 2: 状态管理 (`telegram_logger/services`)**

1.  `[x]` **[Service]** 创建 `UserBotStateService` 类。
2.  `[x]` **[Service]** 在 `UserBotStateService.__init__` 中接收 `DatabaseManager` 实例和用户自己的 ID (`my_id: int`)。
3.  `[x]` **[Service] [Init]** 实现异步方法 `async load_state()`，在服务启动时调用。此方法应：
    *   `[x]` 从数据库加载 `user_bot_settings` (使用 `my_id`)。如果记录不存在，则使用 RFC 定义的默认值（包括 `enabled=False`, `reply_trigger_enabled=False`, `ai_history_length=1`, `current_model_id='gpt-3.5-turbo'`, `current_role_alias='default_assistant'`, `rate_limit_seconds=60`）调用 `db.save_user_bot_settings` 创建记录，并加载这些默认值到内存。
    *   `[x]` 从数据库加载目标群组列表、模型别名、角色别名到内存属性 (例如 `Set`, `Dict`)。
    *   `[x]` 考虑是否在此处检查并创建默认的 `default_assistant` 角色别名（如果不存在）。
4.  `[x]` **[Service]** 提供访问当前内存状态的属性或方法，例如 `is_enabled() -> bool`, `is_reply_trigger_enabled() -> bool`, `get_current_model_id() -> str`, `get_current_role_alias() -> str`, `get_target_group_ids() -> Set[int]`, `get_rate_limit() -> int`, `get_ai_history_length() -> int` 等。
5.  `[x]` **[Service]** 实现异步更新状态的方法 (`async def`)，这些方法应**先更新数据库** (调用 `DatabaseManager` 的方法)，**成功后再更新内存状态**。例如 `enable()`, `disable()`, `set_current_model(model_ref: str)`, `set_current_role(role_alias: str)`, `add_group(chat_id: int)`, `remove_group(chat_id: int)`, `set_rate_limit(seconds: int)`, `async set_ai_history_length(count: int)` 等。
6.  `[x]` **[Service]** 实现异步别名管理和解析逻辑：
    *   `[x]` `async set_model_alias(alias: str, model_id: str)`
    *   `[x]` `async remove_model_alias(alias: str)`
    *   `[x]` `async get_model_aliases() -> Dict[str, str]`
    *   `[x]` `async resolve_model_id(ref: str) -> Optional[str]` (根据别名或 ID 返回模型 ID)
    *   `[x]` `async create_role_alias(alias: str, role_type: str, static_content: Optional[str] = None)`
    *   `[x]` `async set_role_description(alias: str, description: str)`
    *   `[x]` `async set_role_static_content(alias: str, content: str)`
    *   `[x]` `async set_role_system_prompt(alias: str, prompt: str)`
    *   `[x]` `async set_role_preset_messages(alias: str, presets_json: str)` (内部调用 DB 前验证 JSON)
    *   `[x]` `async remove_role_alias(alias: str)`
    *   `[x]` `async get_role_aliases() -> Dict[str, Dict[str, Any]]`
    *   `[x]` `async resolve_role_details(alias: str) -> Optional[Dict[str, Any]]` (根据别名获取角色详情)
7.  `[x]` **[Service] [Limit]** 实现频率限制状态管理（内存字典 `Dict[int, float]`）：`check_rate_limit(chat_id: int) -> bool` 和 `update_rate_limit(chat_id: int)` (这些可以是同步方法，因为它们只操作内存)。

**阶段 3: 指令处理器 (`UserBotCommandHandler`)**

1.  `[x]` **[Handler Class]** 创建 `telegram_logger/handlers/user_bot_command.py` 文件并定义 `UserBotCommandHandler` 类。考虑继承自 `BaseHandler` 或创建一个新的基类。
2.  `[x]` **[Dependencies]** 在 `UserBotCommandHandler.__init__` 中接收依赖项：`client`, `db`, `UserBotStateService` 实例, `my_id`。
3.  `[x]` **[Handler Method]** 定义一个核心的异步方法，例如 `async def handle_command(self, event: events.NewMessage.Event):`。此方法将由事件分发器调用（在阶段 7 中注册）。
4.  `[x]` **[Parsing]** 在 `handle_command` 方法内部，检查 `event.message.text` 是否以 `.` 开头，并解析指令和参数。可以使用 `shlex.split` 处理带引号的参数。
5.  `[x]` **[Implementation]** 在 `handle_command` 方法内部，为 RFC 003 中定义的每个指令 (`.on`, `.off`, `.status`, `.replyon`, `.replyoff`, `.setmodel`, `.listmodels`, `.aliasmodel`, `.unaliasmodel`, `.setrole`, `.listroles`, `.aliasrole`, `.unaliasrole`, `.addgroup`, `.delgroup`, `.listgroups`, `.setlimit`, `.help`) 实现对应的处理逻辑。
    *   `[x]` 使用注入的 `self.state_service` 实例来读取或更新状态。
    *   `[x]` 实现输入验证（例如，`.addgroup` 验证群组，`.setlimit` 验证数字，`.setrolepreset` 验证 JSON 格式，`.sethistory` 验证数字范围，确保别名存在等）。
    *   `[x]` 调用 `await event.respond(...)` 或 `await self.client.send_message(event.chat_id, ...)` 将操作反馈发送回用户的私聊。
    *   `[ ]` `.listmodels`, `.listroles`, `.listgroups`, `.status`, `.help` 需要格式化输出信息，特别是 `.listroles` 需要显示所有新字段，`.status` 需要包含历史数量。
    *   `[ ]` **实现 `.sethistory <数量>` 指令处理:**
        *   解析 `<数量>` 参数。
        *   验证参数为非负整数，并进行上限检查 (例如 `0 <= count <= 20`)。若无效则回复错误信息。
        *   调用 `self.state_service.set_ai_history_length(count)`。
        *   回复确认消息，例如 `await event.respond(f"AI 上下文历史消息数量已设置为 {count}。")`。
    *   `[ ]` 确保 `.status` 指令调用 `self.state_service.get_ai_history_length()` 并将其包含在回复给用户的状态信息中。
    *   `[ ]` 将 `.sethistory <数量>` 指令及其描述添加到 `.help` 命令的输出中。
6.  `[ ]` **[Registration]** 事件注册将在阶段 7 中通过 `client.add_event_handler` 显式完成，而不是在此处使用装饰器。

**阶段 4: 自动回复逻辑 (`MentionReplyHandler`)**

1.  `[ ]` **[Handler Class]** 创建 `telegram_logger/handlers/mention_reply.py` 文件并定义 `MentionReplyHandler` 类。考虑继承自 `BaseHandler` 或一个新的基类。
2.  `[ ]` **[Dependencies]** 在 `MentionReplyHandler.__init__` 中接收依赖项：`client`, `db`, `UserBotStateService` 实例, `my_id`。
3.  `[ ]` **[Handler Method]** 定义一个核心的异步方法，例如 `async def handle_event(self, event: events.NewMessage.Event):`。此方法将由事件分发器调用（在阶段 7 中注册）。
4.  `[ ]` **[Filtering]** 在 `handle_event` 方法内部实现过滤逻辑：
    *   `[ ]` 使用注入的 `self.state_service` 实例。
    *   `[ ]` 检查 `self.state_service.is_enabled()` 是否为 `True`。
    *   `[ ]` 检查 `event.chat_id` 是否在 `self.state_service.get_target_group_ids()` 中。
    *   `[ ]` 使用注入的 `self.my_id`。检查 `event.sender_id == self.my_id` (忽略自己发的消息)。
    *   `[ ]` 检查是否满足触发条件：
        *   `[ ]` `event.mentioned` (是否 @ 了自己)
        *   `[ ]` 或者 (`self.state_service.is_reply_trigger_enabled()` 且 `event.is_reply` 且 `event.reply_to_msg_id` 对应的消息是自己发的 - 可能需要 `reply_msg = await event.get_reply_message()` 然后检查 `reply_msg.sender_id == self.my_id`)。
    *   `[ ]` 如果同时满足 @ 和回复，确保只处理一次。
5.  `[ ]` **[Rate Limit]** 调用 `self.state_service.check_rate_limit(event.chat_id)`。如果受限，则 `return` 停止处理。
6.  `[ ]` **[Get Role]** 获取当前角色详情 `role_details = await self.state_service.resolve_role_details(self.state_service.get_current_role_alias())`。如果角色为空或获取失败，则 `return` 停止处理。
7.  `[ ]` **[Generate Reply]**
    *   `[ ]` **If `role_details['role_type'] == 'static'`:** 直接使用 `reply_text = role_details.get('static_content', '')`。
    *   `[ ]` **If `role_details['role_type'] == 'ai'`:**
        *   `[ ]` 获取当前模型 ID `model_id = self.state_service.get_current_model_id()`。
        *   `[ ]` **准备 AI 请求上下文:**
            *   `[ ]` 获取系统提示 `system_prompt = role_details.get('system_prompt')`。
            *   `[ ]` 获取并解析预设消息 `preset_messages_json = role_details.get('preset_messages')`。如果存在且有效，解析为列表。
            *   `[ ]` 获取配置的历史数量: `history_count = self.state_service.get_ai_history_length()`。
            *   `[ ]` **If `history_count > 0`:**
                *   `[ ]` 从数据库获取历史消息: `past_messages = await self.db.get_messages_before(chat_id=event.chat_id, before_message_id=event.message.id, limit=history_count)`。
                *   `[ ]` 将获取的消息按时间正序排列: `history_context_messages = reversed(past_messages)`。
            *   `[ ]` 获取当前触发消息 `event.message.text`。
        *   `[ ]` **构建消息列表:** 按照 AI 服务要求的格式，组合系统提示、预设消息、历史消息和当前用户消息。
        *   `[ ]` 调用 AI 服务接口 (见阶段 5)，传入模型 ID 和构建好的消息列表，获取生成的 `reply_text`。
        *   `[ ]` 处理 AI 服务可能发生的错误 (例如，记录日志并 `return`)。
8.  `[ ]` **[Send Reply]** 调用 `await event.reply(reply_text)` 发送回复。
9.  `[ ]` **[Update Limit]** 如果发送成功，调用 `self.state_service.update_rate_limit(event.chat_id)`。
10. `[ ]` **[Registration]** 事件注册将在阶段 7 中通过 `client.add_event_handler` 显式完成，而不是在此处使用装饰器。

**阶段 5: AI 集成 (OpenAI) (`telegram_logger/services` 或 `telegram_logger/utils`)**

1.  `[ ]` **[Dependency]** 在 `pyproject.toml` 中添加 `openai` 依赖。
2.  `[ ]` **[Config]** 在 `.env.example` 和 `.env` 中添加 OpenAI 配置：
    *   `OPENAI_API_KEY`: 必需，用于 API 认证。
    *   `OPENAI_BASE_URL`: 可选，用于指定自定义的 OpenAI API 端点（例如代理或兼容服务）。
3.  `[ ]` **[Interface/Implementation]** 创建一个 AI 服务类或模块，例如 `AIService` 或 `ai_service.py`。
4.  `[ ]` **[Implementation]** 在该服务中实现一个核心的异步函数，例如 `async def get_openai_completion(model_id: str, messages: List[Dict[str, str]]) -> Optional[str]:`。
    *   此函数接收 OpenAI 兼容的模型 ID 和一个消息列表（格式如 `[{"role": "system", "content": "..."}, {"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]`）。
    *   内部使用 `openai` 库与 OpenAI API 进行交互。
    *   从环境变量加载 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL` (如果设置了)。
    *   处理 API 调用可能出现的异常（例如 `openai.APIError`, `openai.AuthenticationError`, `openai.RateLimitError` 等），记录错误日志并返回 `None` 或抛出自定义异常。
    *   解析 API 响应，提取生成的文本内容并返回。
5.  `[ ]` **[Integration]** 在阶段 4 的 `handle_mention_or_reply` 函数中，当角色类型为 `ai` 时：
    *   `[ ]` 导入并（可能需要实例化）`AIService`。
    *   `[ ]` **构建消息列表:** 按照 OpenAI 格式，正确组合系统提示 (`system_prompt`)、预设消息 (`preset_messages`)、历史对话消息 (`history_context_messages`) 和当前用户消息 (`event.message.text`)。确保角色 (`system`, `user`, `assistant`) 分配正确。
    *   `[ ]` 调用 `await ai_service.get_openai_completion(model_id=model_id, messages=constructed_messages)` 获取回复。
    *   `[ ]` **(补充) 转换历史消息:** 需要明确如何将从数据库获取的 `Message` 对象列表 (`history_context_messages`) 转换为 OpenAI 需要的 `{"role": "...", "content": "..."}` 格式列表，根据 `message.from_id == self.my_id` 判断 `role` 是 `assistant` 还是 `user`。

**阶段 6: 错误处理与日志**

1.  `[ ]` 在数据库操作、API 调用、消息发送等关键步骤添加 `try...except` 块。
2.  `[ ]` 使用 `logging` 模块记录错误信息和关键执行步骤。
3.  `[ ]` 确保用户指令处理失败时（如无效输入、权限问题）向用户返回友好的错误提示。
4.  `[ ]` 确保自动回复过程中的内部错误（如 AI 服务失败、发送消息失败）只记录日志，不打扰用户或群组。

**阶段 7: 应用初始化与依赖注入 (`telegram_logger/main.py`)**

1.  `[ ]` **[Init]** 在 `main()` 函数中，获取 `TelegramClientService` 实例 (`client_service`)。
2.  `[ ]` **[Init]** 调用 `user_id = await client_service.initialize()` 并存储返回的用户 ID。
3.  `[ ]` **[Init]** 创建 `UserBotStateService` 实例，将 `DatabaseManager` 实例 (`db`) 和获取到的 `user_id` 传递给其构造函数。
    ```python
    # 示例
    from telegram_logger.services.user_bot_state import UserBotStateService # 需要创建这个文件和类
    user_bot_state_service = UserBotStateService(db=db, my_id=user_id)
    ```
4.  `[ ]` **[Init]** 调用 `await user_bot_state_service.load_state()` 来加载 UserBot 的初始状态。
5.  `[ ]` **[Init]** 导入新的 Handler 类。
    ```python
    from telegram_logger.handlers.user_bot_command import UserBotCommandHandler # 需要创建
    from telegram_logger.handlers.mention_reply import MentionReplyHandler # 需要创建
    # 假设 AIService 在 telegram_logger.services.ai_service
    from telegram_logger.services.ai_service import AIService # 需要创建
    ```
6.  `[ ]` **[Init]** (可选) 创建 AI 服务实例。
    ```python
    ai_service = AIService() # 如果需要实例化
    ```
7.  `[ ]` **[Init]** 创建新的 Handler 实例，并注入所有必要的依赖。
    ```python
    # 示例
    user_bot_command_handler = UserBotCommandHandler(
        client=client_service.client, # 注入 client
        db=db,
        state_service=user_bot_state_service,
        my_id=user_id
        # log_chat_id=LOG_CHAT_ID, # 如果需要
        # ignored_ids=IGNORED_IDS, # 如果需要
    )
    mention_reply_handler = MentionReplyHandler(
        client=client_service.client, # 注入 client
        db=db,
        state_service=user_bot_state_service,
        my_id=user_id,
        ai_service=ai_service # 注入 AI 服务
        # log_chat_id=LOG_CHAT_ID, # 如果需要
        # ignored_ids=IGNORED_IDS, # 如果需要
    )
    ```
8.  `[ ]` **[Registration]** 使用 `client_service.client.add_event_handler` 显式注册 Handler 的方法。
    ```python
    # 注册处理用户命令的方法
    client_service.client.add_event_handler(
        user_bot_command_handler.handle_command, # Handler 实例的方法
        events.NewMessage(from_users=user_id, chats='me') # 事件过滤器
    )
    # 注册处理提及/回复的方法
    client_service.client.add_event_handler(
        mention_reply_handler.handle_event, # Handler 实例的方法
        events.NewMessage() # 更精细的过滤在 handle_event 方法内部完成
    )
    ```
9.  `[ ]` **[Management]** (可选) 如果需要统一管理所有 Handler，可以将新创建的 Handler 实例添加到 `client_service` 的 `handlers` 列表中（如果 `TelegramClientService` 设计支持）。
    ```python
    # client_service.handlers.extend([user_bot_command_handler, mention_reply_handler])
    ```

**阶段 8: 测试 (`tests/`)**

1.  `[ ]` **[Unit Tests]** 为指令解析逻辑、状态服务中的方法（特别是别名解析、状态更新、`set_ai_history_length` 输入验证）、频率限制逻辑编写单元测试。
2.  `[ ]` **[Integration Tests]** 编写集成测试：
    *   `[ ]` 模拟用户发送指令，验证状态是否正确更新以及反馈消息是否符合预期。
    *   `[ ]` **[Integration Test]** 测试 `.sethistory` 指令：发送指令（包括有效和无效参数），验证状态服务中的值是否更新，验证用户收到的反馈消息。
    *   `[ ]` **[Integration Test]** 测试 `.status` 指令的输出是否正确包含了更新后的历史数量。
    *   `[ ]` 模拟群组中的 @ 提及和回复事件，验证自动回复是否按预期触发（或不触发）、内容是否正确（区分 static/ai）、频率限制是否生效。
    *   `[ ]` **[Integration Test]** (可能需要 Mock) 测试自动回复逻辑：设置不同的历史数量，触发回复，验证传递给 AI 服务接口的上下文消息数量是否符合预期（可以通过 Mock `db.get_messages_before` 或检查日志来验证）。

## 5. 依赖项

-   **必需:** `openai` - 用于与 OpenAI API 交互。
-   其他依赖项应尽量复用项目中已有的库。

## 6. 配置

-   需要在 `.env.example` 和 `.env` 中添加以下环境变量：
    -   `OPENAI_API_KEY`: (必需) 你的 OpenAI API 密钥。
    -   `OPENAI_BASE_URL`: (可选) 自定义的 OpenAI API 端点 URL。如果留空，将使用 OpenAI 官方默认端点。
-   默认的模型 ID (`gpt-3.5-turbo`) 和角色别名 (`default_assistant`) 在代码或数据库初始化逻辑中定义。

## 7. (已移除) 待讨论/决策点

(本章节原包含的决策点已整合入文档相关部分。)

## 8. 后续步骤

1.  根据此 IMP 文档，逐步实现各个阶段的功能。
2.  在实现过程中，根据实际情况细化或调整具体实现细节。
3.  编写相应的单元测试和集成测试。
4.  更新 `README.md` 和 `.env.example` 以反映新功能和配置。
