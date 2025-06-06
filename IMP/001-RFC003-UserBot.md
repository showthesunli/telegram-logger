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
    *   `[x]` `.listmodels`, `.listroles`, `.listgroups`, `.status`, `.help` 需要格式化输出信息，特别是 `.listroles` 需要显示所有新字段，`.status` 需要包含历史数量。
    *   `[x]` **实现 `.sethistory <数量>` 指令处理:**
        *   `[x]` 解析 `<数量>` 参数。
        *   `[x]` 验证参数为非负整数，并进行上限检查 (例如 `0 <= count <= 20`)。若无效则回复错误信息。
        *   `[x]` 调用 `self.state_service.set_ai_history_length(count)`。
        *   `[x]` 回复确认消息，例如 `await event.respond(f"AI 上下文历史消息数量已设置为 {count}。")`。
    *   `[x]` 确保 `.status` 指令调用 `self.state_service.get_ai_history_length()` 并将其包含在回复给用户的状态信息中。
    *   `[x]` 将 `.sethistory <数量>` 指令及其描述添加到 `.help` 命令的输出中。

6.  `[x]` **[Implementation - Remaining Commands]** 继续在 `handle_command` 方法中，为 RFC 003 中定义的剩余指令实现处理逻辑：

    *   `[x]` **`.status`**:
        *   检查参数：确保没有额外参数。
        *   调用 `self.state_service` 的多个 getter 方法获取当前状态：`is_enabled()`, `is_reply_trigger_enabled()`, `get_current_model_id()`, `get_current_role_alias()`, `get_target_group_ids()`, `get_rate_limit()`, `get_ai_history_length()`。
        *   调用 `await self.state_service.resolve_model_id()` 获取当前模型的实际 ID（如果当前设置是别名）。
        *   调用 `await self.state_service.get_model_aliases()` 查找当前模型 ID 对应的别名（如果有）。
        *   调用 `await self.state_service.resolve_role_details()` 获取当前角色的详细信息（类型、描述/提示）。
        *   格式化状态信息字符串，包含 RFC 003 要求的所有字段（启用状态、回复触发、模型ID和别名、角色别名和类型/内容摘要、历史数量、目标群组列表摘要、频率限制）。
        *   使用 `await self._safe_respond(event, formatted_status)` 回复。

    *   `[x]` **`.setmodel <模型ID或别名>`**:
        *   检查参数：确保只有一个参数 `<模型ID或别名>`。
        *   调用 `await self.state_service.set_current_model(args[0])`。
        *   检查返回的布尔值。
        *   如果成功，调用 `await self.state_service.resolve_model_id(args[0])` 和 `await self.state_service.get_model_aliases()` 来获取模型 ID 和对应的别名（如果有）。
        *   构造确认消息，如 "✅ AI 模型已设置为 gpt-4o (别名: 4o)。" 或 "✅ AI 模型已设置为 gpt-4o (无别名)。"
        *   使用 `await self._safe_respond(...)` 回复确认或错误信息。

    *   `[x]` **`.listmodels`**:
        *   检查参数：确保没有额外参数。
        *   调用 `await self.state_service.get_model_aliases()` 获取别名字典。
        *   格式化输出字符串，列出所有模型 ID 及其别名，格式如 RFC 003 所示。
        *   使用 `await self._safe_respond(event, formatted_list)` 回复。

    *   `[x]` **`.aliasmodel <模型ID> <别名>`**:
        *   检查参数：确保有两个参数 `<模型ID>` 和 `<别名>`。
        *   调用 `await self.state_service.set_model_alias(alias=args[1], model_id=args[0])`。
        *   检查返回的布尔值。
        *   使用 `await self._safe_respond(...)` 回复确认或错误信息，如 "✅ 已为模型 gpt-4o 设置别名 4o。"

    *   `[x]` **`.unaliasmodel <别名>`**:
        *   检查参数：确保只有一个参数 `<别名>`。
        *   调用 `await self.state_service.remove_model_alias(args[0])`。
        *   检查返回的布尔值。
        *   使用 `await self._safe_respond(...)` 回复确认或错误信息，如 "✅ 模型别名 4o 已删除。"

    *   `[x]` **`.setrole <别名>`**:
        *   检查参数：确保只有一个参数 `<别名>`。
        *   调用 `await self.state_service.set_current_role(args[0])`。
        *   检查返回的布尔值。
        *   如果成功，可以调用 `await self.state_service.resolve_role_details(args[0])` 获取角色类型以包含在确认消息中。
        *   使用 `await self._safe_respond(...)` 回复确认或错误信息，如 "✅ AI 角色已设置为 'helper' (AI)。"

    *   `[x]` **`.listroles`**:
        *   检查参数：确保没有额外参数。
        *   调用 `await self.state_service.get_role_aliases()` 获取所有角色详情的字典。
        *   遍历字典，为每个角色格式化输出字符串，包含别名、类型、描述、静态内容（如果是 static）、系统提示和预设消息摘要（如果是 ai），格式如 RFC 003 所示。注意处理 `None` 值。
        *   使用 `await self._safe_respond(event, formatted_list)` 回复。

    *   `[x]` **`.aliasrole <别名> "<内容>" --type static` 或 `.aliasrole <别名> --type ai`**:
        *   参数解析较为复杂，建议使用 `argparse` 或手动解析。
        *   提取 `<别名>`。
        *   查找 `--type` 参数及其值 (`static` 或 `ai`)，并验证。
        *   如果类型是 `static`，查找并提取可选的 `"<静态回复文本>"` 参数。
        *   调用 `await self.state_service.create_role_alias(alias=alias, role_type=role_type, static_content=static_content_if_any)`。
        *   检查返回的布尔值。
        *   根据类型和操作结果构造确认消息，如 "✅ 已创建静态角色别名 'meeting' 并设置内容。" 或 "✅ 已创建 AI 角色别名 'helper'。"
        *   使用 `await self._safe_respond(...)` 回复确认或错误信息。

    *   `[x]` **`.setroledesc <别名> "<角色描述文本>"`**:
        *   检查参数：确保有两个参数 `<别名>` 和 `"<角色描述文本>"`。
        *   调用 `await self.state_service.set_role_description(alias=args[0], description=args[1])`。
        *   检查返回的布尔值。
        *   使用 `await self._safe_respond(...)` 回复确认或错误信息，如 "✅ 已更新角色 'helper' 的描述。"

    *   `[x]` **`.setroleprompt <别名> "<系统提示词>"`**:
        *   检查参数：确保有两个参数 `<别名>` 和 `"<系统提示词>"`。
        *   调用 `await self.state_service.set_role_system_prompt(alias=args[0], prompt=args[1])`。
        *   检查返回的布尔值。
        *   使用 `await self._safe_respond(...)` 回复确认或错误信息，如 "✅ 已更新角色 'helper' 的系统提示。"

    *   `[x]` **`.setrolepreset <别名> '<JSON格式的预设消息列表>'`**:
        *   检查参数：确保有两个参数 `<别名>` 和 `'<JSON格式的预设消息列表>'`。
        *   **重要**: 在调用服务前，使用 `json.loads(args[1])` 尝试解析 JSON 字符串。如果失败（捕获 `json.JSONDecodeError`），则回复用户错误信息，提示 JSON 格式无效，然后 `return`。
        *   如果 JSON 有效，调用 `await self.state_service.set_role_preset_messages(alias=args[0], presets_json=args[1])`。
        *   检查返回的布尔值。
        *   使用 `await self._safe_respond(...)` 回复确认或错误信息，如 "✅ 已更新角色 'helper' 的预设消息。"

    *   `[x]` **`.unaliasrole <别名>`**:
        *   检查参数：确保只有一个参数 `<别名>`。
        *   调用 `await self.state_service.remove_role_alias(args[0])`。
        *   检查返回的布尔值。
        *   使用 `await self._safe_respond(...)` 回复确认或错误信息，如 "✅ 角色别名 'helper' 已删除。"

    *   `[x]` **`.addgroup <群组ID或群组链接>`**:
        *   检查参数：确保只有一个参数 `<群组ID或群组链接>`。
        *   使用 `try...except` 块调用 `entity = await self.client.get_entity(args[0])` 来验证输入并获取实体对象。
        *   处理可能的异常 (`ValueError` 表示无效 ID/链接, `telethon.errors` 如 `ChannelPrivateError` 等)。如果验证失败，回复错误信息并 `return`。
        *   检查 `entity` 是否为群组或频道 (`isinstance(entity, (types.Chat, types.Channel))`)。如果不是，回复错误信息并 `return`。
        *   获取 `chat_id = entity.id`。
        *   调用 `await self.state_service.add_group(chat_id)`。
        *   检查返回的布尔值。
        *   构造确认消息，可以包含群组名称 `entity.title`，如 "✅ 群组 '项目讨论' 已添加到目标列表。"
        *   使用 `await self._safe_respond(...)` 回复确认或错误信息。

    *   `[x]` **`.delgroup <群组ID或群组链接>`**:
        *   检查参数：确保只有一个参数 `<群组ID或群组链接>`。
        *   使用 `try...except` 调用 `entity = await self.client.get_entity(args[0])` 获取实体信息（主要是为了获取名称用于反馈）。如果获取失败，可以尝试直接将参数转为 `int` 作为 ID，或者提示用户 ID/链接无效。
        *   尝试将 `args[0]` 解析为 `chat_id` (可能是整数 ID 或从 `entity` 获取)。
        *   调用 `await self.state_service.remove_group(chat_id)`。 # 修正：之前写成了 state_state_service
        *   检查返回的布尔值。
        *   构造确认消息，如果之前成功获取了 `entity`，可以包含群组名称，如 "✅ 群组 '项目讨论' 已从目标列表移除。"
        *   使用 `await self._safe_respond(...)` 回复确认或错误信息。

    *   `[x]` **`.listgroups`**:
        *   检查参数：确保没有额外参数。
        *   调用 `target_ids = await self.state_service.get_target_group_ids()`。
        *   如果列表为空，回复 "当前没有设置目标群组。"
        *   如果列表不为空，遍历 `target_ids`。对于每个 `chat_id`：
            *   使用 `try...except` 调用 `entity = await self.client.get_entity(chat_id)` 获取群组名称。
            *   构建包含群组名称和 ID 的行，如 `- 项目讨论 (-100123456789)`。如果 `get_entity` 失败，则显示 `- 未知群组 (ID: -100...)`。
        *   组合所有行成为最终的列表字符串。
        *   使用 `await self._safe_respond(event, formatted_list)` 回复。

    *   `[x]` **`.setlimit <秒数>`**:
        *   检查参数：确保只有一个参数 `<秒数>`。
        *   使用 `try...except ValueError` 验证参数是否为非负整数。如果无效，回复错误信息并 `return`。
        *   调用 `await self.state_service.set_rate_limit(int(args[0]))`。
        *   检查返回的布尔值。
        *   使用 `await self._safe_respond(...)` 回复确认或错误信息，如 "✅ 频率限制已设置为 120 秒。"

    *   `[x]` **`.help`**:
        *   检查参数：确保没有额外参数。
        *   创建一个包含**所有**已实现指令（包括本步骤中实现的）及其用法描述的多行字符串。确保描述与 RFC 003 一致。
        *   使用 `await self._safe_respond(event, help_message)` 回复。

7.  `[x]` **[Registration]** 事件注册将在阶段 7 中通过 `client.add_event_handler` 显式完成，而不是在此处使用装饰器。 (已确认，无代码实现)

**阶段 4: 自动回复逻辑 (`MentionReplyHandler`)**

1.  `[x]` **[Handler Class]** 创建 `telegram_logger/handlers/mention_reply.py` 文件并定义 `MentionReplyHandler` 类。考虑继承自 `BaseHandler` 或一个新的基类。
2.  `[x]` **[Dependencies]** 在 `MentionReplyHandler.__init__` 中接收依赖项：`client`, `db`, `UserBotStateService` 实例, `my_id`。
3.  `[x]` **[Handler Method]** 定义一个核心的异步方法，例如 `async def handle_event(self, event: events.NewMessage.Event):`。此方法将由事件分发器调用（在阶段 7 中注册）。
4.  `[x]` **[Filtering]** 在 `handle_event` 方法内部实现过滤逻辑：
    *   `[x]` 使用注入的 `self.state_service` 实例。
    *   `[x]` 检查 `self.state_service.is_enabled()` 是否为 `True`。
    *   `[x]` 检查 `event.chat_id` 是否在 `self.state_service.get_target_group_ids()` 中。
    *   `[x]` 使用注入的 `self.my_id`。检查 `event.sender_id == self.my_id` (忽略自己发的消息)。
    *   `[x]` 检查是否满足触发条件：
        *   `[x]` `event.mentioned` (是否 @ 了自己)
        *   `[x]` 或者 (`self.state_service.is_reply_trigger_enabled()` 且 `event.is_reply` 且 `event.reply_to_msg_id` 对应的消息是自己发的 - 可能需要 `reply_msg = await event.get_reply_message()` 然后检查 `reply_msg.sender_id == self.my_id`)。
    *   `[x]` 如果同时满足 @ 和回复，确保只处理一次。
5.  `[x]` **[Rate Limit]** 调用 `self.state_service.check_rate_limit(event.chat_id)`。如果受限，则 `return` 停止处理。
6.  `[x]` **[Get Role]** 获取当前角色详情 `role_details = await self.state_service.resolve_role_details(self.state_service.get_current_role_alias())`。如果角色为空或获取失败，则 `return` 停止处理。
7.  `[x]` **[Generate Reply]**
    *   `[x]` **If `role_details['role_type'] == 'static'`:** 直接使用 `reply_text = role_details.get('static_content', '')`。 (已实现)
    *   `[x]` **If `role_details['role_type'] == 'ai'`:**
        *   `[x]` 获取当前模型 ID `model_id = await self.state_service.resolve_model_id(...)`。 (已实现)
        *   `[x]` **准备 AI 请求上下文:**
            *   `[x]` 获取系统提示 `system_prompt = role_details.get('system_prompt')`。 (已实现)
            *   `[x]` 获取并解析预设消息 `preset_messages_json = role_details.get('preset_messages')`。如果存在且有效，解析为列表。 (已实现)
            *   `[x]` 获取配置的历史数量: `history_count = self.state_service.get_ai_history_length()`。 (已实现)
            *   `[x]` **If `history_count > 0`:**
                *   `[x]` 从数据库获取历史消息: `history_messages = await self.db.get_messages_before(...)`。 (已实现)
                *   `[x]` 将获取的消息按时间正序排列: `history_context_messages = reversed(past_messages)`。(注意：`get_messages_before` 返回的是正序列表，无需反转) (已实现，并修正了注释)
            *   `[x]` 获取当前触发消息 `event.message.text`。 (已实现)
        *   `[x]` **构建消息列表:** 按照 AI 服务要求的格式，组合系统提示、预设消息、历史消息和当前用户消息。 (已实现)
        *   `[x]` 调用 AI 服务接口，传入模型 ID 和构建好的消息列表，获取生成的 `reply_text`。 (已实现)
        *   `[x]` 处理 AI 服务可能发生的错误 (例如，记录日志并设置错误回复)。 (已实现)
8.  `[x]` **[Send Reply]** 调用 `await event.reply(reply_text)` 发送回复。 (已实现)
9.  `[x]` **[Update Limit]** 如果发送成功，调用 `self.state_service.update_rate_limit(event.chat_id)`。 (已实现)
10. `[x]` **[Registration]** 事件注册将在阶段 7 中通过 `client.add_event_handler` 显式完成，而不是在此处使用装饰器。 (已确认，无代码实现)

**阶段 5: AI 集成 (OpenAI) (`telegram_logger/services` 或 `telegram_logger/utils`)**

1.  `[x]` **[Dependency]** 在 `pyproject.toml` 中添加 `openai` 依赖。 (已由用户确认完成)
2.  `[x]` **[Config]** 在 `.env.example` 和 `.env` 中添加 OpenAI 配置： (已更新 `.env.example`)
    *   `[x]` `OPENAI_API_KEY`: 必需，用于 API 认证。
    *   `[x]` `OPENAI_BASE_URL`: 可选，用于指定自定义的 OpenAI API 端点（例如代理或兼容服务）。
3.  `[x]` **[Interface/Implementation]** 创建一个 AI 服务类或模块，例如 `AIService` 或 `ai_service.py`。 (已创建 `AIService` 类和文件)
4.  `[x]` **[Implementation]** 在该服务中实现一个核心的异步函数，例如 `async def get_openai_completion(model_id: str, messages: List[Dict[str, str]]) -> Optional[str]:`。
    *   `[x]` 此函数接收 OpenAI 兼容的模型 ID 和一个消息列表（格式如 `[{"role": "system", "content": "..."}, {"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]`）。 (已实现)
    *   `[x]` 内部使用 `openai` 库与 OpenAI API 进行交互。 (已实现)
    *   `[x]` 从环境变量加载 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL` (如果设置了)。 (已实现，通过惰性初始化)
    *   `[x]` 处理 API 调用可能出现的异常（例如 `openai.APIError`, `openai.AuthenticationError`, `openai.RateLimitError`, `openai.BadRequestError` 等），记录错误日志并返回 `None`。 (已实现)
    *   `[x]` 解析 API 响应，提取生成的文本内容并返回。 (已实现)
5.  `[x]` **[Integration]** 在阶段 4 的 `handle_mention_or_reply` 函数中，当角色类型为 `ai` 时：
    *   `[x]` 导入并（可能需要实例化）`AIService`。 (已实现，通过 __init__ 注入)
    *   `[x]` **构建消息列表:** 按照 OpenAI 格式，正确组合系统提示 (`system_prompt`)、预设消息 (`preset_messages`)、历史对话消息 (`history_context_messages`) 和当前用户消息 (`event.message.text`)。确保角色 (`system`, `user`, `assistant`) 分配正确。 (已实现)
    *   `[x]` 调用 `await ai_service.get_openai_completion(model_id=model_id, messages=constructed_messages)` 获取回复。 (已实现)
    *   `[x]` **(补充) 转换历史消息:** 需要明确如何将从数据库获取的 `Message` 对象列表 (`history_context_messages`) 转换为 OpenAI 需要的 `{"role": "...", "content": "..."}` 格式列表，根据 `message.from_id == self.my_id` 判断 `role` 是 `assistant` 还是 `user`。 (已实现)

**阶段 6: 错误处理与日志**

*   **目标:** 确保系统在遇到预期和意外错误时能够健壮地运行，提供有用的日志信息，并向用户提供适当的反馈（仅在私聊指令中）。
*   **通用原则:**
    *   **日志记录:** 在所有关键操作（数据库交互、API 调用、状态变更、消息发送/接收）前后及异常处理块中使用 `logging` 模块记录信息。区分日志级别 (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`)。
    *   **用户反馈:** 仅在处理用户私聊指令 (`UserBotCommandHandler`) 时，将操作成功或失败（及原因）反馈给用户。自动回复 (`MentionReplyHandler`) 中的内部错误**绝不**应在群组中发送错误消息，只记录日志。

*   **具体实现步骤:**

    *   **`DatabaseManager`:**
        *   `[x]` 在执行 SQL 查询和修改的内部同步方法（例如 `_sync_create`, `_sync_set`, `_sync_remove`, `_sync_get`, `_sync_save`, `_sync_add` 等的 `def _sync_...():` 块内）添加 `try...except sqlite3.Error` 块。
        *   `[x]` 在 `except sqlite3.Error` 块中，使用 `logger.error(...)` 记录详细错误信息（包括操作类型、涉及的表、错误消息）。
        *   `[x]` 在 `except` 块中，根据方法约定返回适当的错误指示值（例如 `None`, `False`, 空列表 `[]`, 空字典 `{}`）。

    *   **`UserBotStateService`:**
        *   `[x]` 在 `load_state` 方法中，为每个数据库调用（如 `self.db.get_user_bot_settings`, `self.db.get_target_groups` 等）添加错误处理逻辑（检查返回是否为 `None` 或捕获异常）。
        *   `[x]` 在 `load_state` 中，如果加载关键设置（如 `user_bot_settings`）失败，记录 `CRITICAL` 错误，并考虑是否应引发异常阻止服务启动或以安全的默认状态运行。 (已实现：记录 CRITICAL，使用默认值继续)
        *   `[x]` 在 `load_state` 中，如果加载非关键列表（如别名、群组）失败，记录 `ERROR` 并使用空列表/字典继续初始化内存状态。
        *   `[x]` 在所有修改状态的异步方法（如 `set_model_alias`, `remove_group`, `set_ai_history_length` 等）中，检查调用的 `DatabaseManager` 方法是否返回了错误指示（例如 `None`, `False`）。
        *   `[x]` 如果数据库更新操作失败（根据 `DatabaseManager` 返回值判断），记录 `ERROR`，**不**更新内存中的状态，并向调用者返回失败指示（例如 `return False`）。
        *   `[x]` 在 `resolve_model_id` 和 `resolve_role_details` 方法中，处理数据库查询返回 `None` 的情况（表示别名不存在或查询失败），记录适当的日志（`WARNING` 或 `DEBUG`），并确保返回 `None`。
        *   `[x]` 在 `set_role_preset_messages` 方法中，在调用数据库方法之前，添加 `try...except json.JSONDecodeError` 来验证 `presets_json` 字符串。如果解析失败，记录 `WARNING` 并返回失败指示（例如 `return False`）。 (已实现：记录 WARNING，返回 False)

    *   **`AIService`:**
        *   `[x]` 在 `get_openai_completion` 方法中，使用 `try...except` 块捕获 `openai` 库的特定异常 (`openai.APIError`, `openai.AuthenticationError`, `openai.RateLimitError`, `openai.BadRequestError` 等) 以及通用的网络异常 (如 `httpx.RequestError`)。
        *   `[x]` 在 `except` 块中，使用 `logger.error(...)` 记录错误信息，包含错误类型和上下文（如模型 ID）。
        *   `[x]` 确保在任何捕获到的异常情况下，方法返回 `None`。

    *   **`UserBotCommandHandler`:**
        *   `[x]` 在 `handle_command` 方法的指令解析部分，使用 `try...except (ValueError, IndexError)` 块包裹 `shlex.split` 和参数访问，以处理格式错误的命令。 (已实现 `shlex` 的 `ValueError` 和通用的 `IndexError` 捕获)
        *   `[x]` 对每个指令的参数实现严格验证逻辑（检查类型、范围、格式等，例如 `.sethistory` 的数字范围，`.setrolepreset` 的 JSON 格式）。 (已为已实现的指令添加验证)
        *   `[x]` 在调用 `UserBotStateService` 的修改状态方法后，检查其返回值（通常是 `bool`）以判断操作是否成功。 (已为已实现的指令添加检查)
        *   `[x]` 如果命令解析、参数验证或状态更新失败，记录 `WARNING` 或 `INFO` 日志，并使用 `await event.respond(...)` 向用户发送清晰、具体的错误消息。 (已实现)
        *   `[x]` 使用 `try...except telethon.errors.FloodWaitError` 等 `telethon` 相关异常包裹 `await event.respond(...)` 调用，并在捕获异常时记录 `ERROR`。 (已通过 `_safe_respond` 实现)

    *   **`MentionReplyHandler`:**
        *   `[x]` 在 `handle_event` 方法的开头，添加一个顶层的 `try...except Exception as e:` 块包裹整个处理逻辑。 (已实现)
        *   `[x]` 在顶层 `except` 块中，使用 `logger.critical("Unhandled exception in MentionReplyHandler: %s", e, exc_info=True)` 记录未预料的错误，然后 `return` 以确保处理流程安全终止。 (已实现)
        *   `[x]` 在调用 `UserBotStateService` 的方法（如 `is_enabled`, `resolve_role_details`, `check_rate_limit`）后，检查其返回值是否表示错误或无效状态（例如 `None`）。如果是，记录 `ERROR` 并 `return` 提前终止处理。 (已实现)
        *   `[x]` 使用 `try...except sqlite3.Error` 包裹对 `self.db.get_messages_before(...)` 的调用。在 `except` 块中记录 `ERROR` 并 `return`。 (已实现)
        *   `[x]` 在调用 `self.ai_service.get_openai_completion(...)` 后，检查返回值是否为 `None`。如果是，表示 AI 调用失败，记录 `ERROR` 并 `return`。 (已实现)
        *   `[x]` 使用 `try...except (telethon.errors.rpcerrorlist.ChatWriteForbiddenError, Exception) as e:` 包裹对 `await event.reply(...)` 的调用。 (已实现)
        *   `[x]` 在 `event.reply` 的 `except` 块中，记录 `ERROR`，**不要**尝试在群组中发送任何错误信息。 (已实现)
        *   `[x]` 确保 `self.state_service.update_rate_limit(event.chat_id)` 只在 `await event.reply(...)` 调用**成功后**（即没有抛出异常）才被执行。 (已实现)

    *   **`main.py` / `TelegramClientService`:**
        *   `[x]` 在 `main.py` 的 `main` 函数中，使用 `try...except Exception` 包裹对 `user_bot_state_service.load_state()` 的调用。在 `except` 块中记录 `CRITICAL` 错误，并考虑是否需要 `sys.exit(1)` 退出程序。 (已在阶段 7 实现)
        *   `[x]` 在 `TelegramClientService.initialize` 方法中，使用 `try...except (telethon.errors.AuthKeyError, telethon.errors.PhoneNumberInvalidError, Exception) as e:` 包裹对 `self.client.start()` 的调用。在 `except` 块中记录 `CRITICAL` 错误，并确保方法返回或引发异常，以阻止程序在客户端未成功连接的情况下继续运行。 (已实现)

**阶段 7: 应用初始化与依赖注入 (`telegram_logger/main.py`)**

1.  `[x]` **[Init]** 在 `main()` 函数中，获取 `TelegramClientService` 实例 (`client_service`)。 (已实现)
2.  `[x]` **[Init]** 调用 `user_id = await client_service.initialize()` 并存储返回的用户 ID。 (已实现)
3.  `[x]` **[Init]** 创建 `UserBotStateService` 实例，将 `DatabaseManager` 实例 (`db`) 和获取到的 `user_id` 传递给其构造函数。 (已实现)
    ```python
    # 示例
    from telegram_logger.services.user_bot_state import UserBotStateService # 需要创建这个文件和类
    user_bot_state_service = UserBotStateService(db=db, my_id=user_id)
    ```
4.  `[x]` **[Init]** 调用 `await user_bot_state_service.load_state()` 来加载 UserBot 的初始状态。 (已实现，包含错误处理)
5.  `[x]` **[Init]** 导入新的 Handler 类。 (已实现)
    ```python
    from telegram_logger.handlers.user_bot_command import UserBotCommandHandler # 需要创建
    from telegram_logger.handlers.mention_reply import MentionReplyHandler # 需要创建
    # 假设 AIService 在 telegram_logger.services.ai_service
    from telegram_logger.services.ai_service import AIService # 需要创建
    ```
6.  `[x]` **[Init]** (可选) 创建 AI 服务实例。 (已实现)
    ```python
    ai_service = AIService() # 如果需要实例化
    ```
7.  `[x]` **[Init]** 创建新的 Handler 实例，并注入所有必要的依赖。 (已实现)
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
8.  `[x]` **[Registration]** 使用 `client_service.client.add_event_handler` 显式注册 Handler 的方法。
    ```python
    # 注册处理用户命令的方法
    client_service.client.add_event_handler(
        user_bot_command_handler.handle_command, # Handler 实例的方法
        events.NewMessage(from_users=user_id, chats='me') # 事件过滤器
    )
    # 注册处理提及/回复的方法
    client_service.client.add_event_handler(
        mention_reply_handler.handle_event, # Handler 实例的方法
        events.NewMessage(incoming=True) # 更精细的过滤在 handle_event 方法内部完成
    )
    ```
9.  `[x]` **[Management]** (可选) 如果需要统一管理所有 Handler，可以将新创建的 Handler 实例添加到 `client_service` 的 `handlers` 列表中（如果 `TelegramClientService` 设计支持）。 (已确认：当前 `TelegramClientService._register_handlers` 设计不适用于需要特定过滤器/方法的 Handler，因此不添加。特定注册已在步骤 8 完成。)
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
