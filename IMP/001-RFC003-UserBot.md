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
-   **指令处理器 (`CommandHandler`):** 一个新的处理器，专门负责监听用户在私聊中发送的控制指令，并执行相应的操作。
-   **事件监听器 (`MentionReplyHandler`):** 一个新的处理器或逻辑单元，负责监听目标群组中的新消息事件，判断是否满足触发条件，并执行自动回复。
-   **AI 服务接口 (可选):** 如果需要与外部 AI 服务（如 OpenAI, Claude 等）交互，需要定义清晰的接口。

## 3. 数据存储设计

我们将扩展现有的 SQLite 数据库 (`db/messages.db`) 来存储用户机器人的配置。需要新增以下表：

**3.1. `user_bot_settings` 表 (单行表，存储全局设置)**

| 列名                  | 类型    | 描述                                     | 默认值             |
| :-------------------- | :------ | :--------------------------------------- | :----------------- |
| `user_id`             | INTEGER | 用户自己的 ID (主键)                     | N/A                |
| `enabled`             | BOOLEAN | 功能是否启用                             | `False`            |
| `reply_trigger_enabled` | BOOLEAN | 是否启用回复触发                         | `False`            |
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
| `preset_messages`| TEXT    | AI 预设消息 (JSON 字符串列表，仅用于 `ai` 类型, 可选)        |

**3.5. 频率限制状态存储 (内存实现)**

*   **注意:** 频率限制状态（最后回复时间戳）通常更适合存储在内存中（例如 Python 字典），以获得更好的性能。如果需要跨重启保持状态，可以考虑持久化，但这会增加 I/O 开销。**初步实现将使用内存缓存。**
    *   内存结构: `Dict[int, float]`  ( `chat_id` -> `last_reply_timestamp`)

## 4. 详细实现步骤

**阶段 1: 数据模型与存储层 (`telegram_logger/data`)**

1.  **[DB]** 在 `DatabaseManager._create_tables` 中添加创建上述 `user_bot_settings`, `user_bot_target_groups`, `user_bot_model_aliases`, `user_bot_role_aliases` 四个表的 SQL 语句。
2.  **[DB]** 实现 `DatabaseManager` 中的方法来管理这些表：
    *   `get_user_bot_settings(user_id: int) -> Optional[Dict]`
    *   `save_user_bot_settings(user_id: int, settings: Dict)` (使用 `INSERT OR REPLACE`)
    *   `add_target_group(chat_id: int)`
    *   `remove_target_group(chat_id: int)`
    *   `get_target_groups() -> List[int]`
    *   `set_model_alias(alias: str, model_id: str)`
    *   `remove_model_alias(alias: str)`
    *   `get_model_aliases() -> Dict[str, str]`
    *   `get_model_id_by_alias(alias: str) -> Optional[str]`
    *   `create_role_alias(alias: str, role_type: str, static_content: Optional[str] = None)` (创建别名，如果是 static 则同时设置内容)
    *   `set_role_description(alias: str, description: str)` (设置通用描述)
    *   `set_role_static_content(alias: str, content: str)` (仅用于 static 类型，更新内容)
    *   `set_role_system_prompt(alias: str, prompt: str)` (仅用于 ai 类型)
    *   `set_role_preset_messages(alias: str, presets_json: str)` (仅用于 ai 类型, 需验证 JSON 格式)
    *   `remove_role_alias(alias: str)` (删除别名及其所有相关数据)
    *   `get_role_aliases() -> Dict[str, Dict[str, Any]]` (返回包含所有字段的字典)
    *   `get_role_details_by_alias(alias: str) -> Optional[Dict[str, Any]]` (获取指定别名的所有详情)
3.  **[Model]** (推荐) 创建 Dataclass `RoleDetails` 来表示角色配置，包含 `alias`, `role_type`, `description`, `static_content`, `system_prompt`, `preset_messages` (解析后的列表或原始 JSON 字符串) 字段。

**阶段 2: 状态管理 (`telegram_logger/services`)**

1.  **[Service]** 创建 `UserBotStateService` 类。
2.  **[Service]** 在 `UserBotStateService.__init__` 中接收 `DatabaseManager` 实例。
3.  **[Service]** 实现 `load_state()` 方法，在服务启动时从数据库加载所有设置、目标群组和别名到内存属性中。
4.  **[Service]** 提供访问当前状态的属性或方法，例如 `is_enabled()`, `get_current_model_id()`, `get_current_role() -> Optional[Dict]`, `get_target_group_ids() -> Set[int]`, `get_rate_limit() -> int` 等。
5.  **[Service]** 实现更新状态的方法，这些方法应同时更新内存状态和调用 `DatabaseManager` 保存到数据库。例如 `enable()`, `disable()`, `set_current_model(model_ref: str)`, `set_current_role(role_ref: str)`, `add_group(chat_id: int)` 等。
6.  **[Service]** 实现别名解析逻辑：`resolve_model_id(ref: str) -> Optional[str]` 和 `resolve_role_details(ref: str) -> Optional[Dict]`，它们能接受 ID/别名/描述，并返回最终的模型 ID 或角色详情。
7.  **[Service]** 实现频率限制状态管理（内存字典）：`check_rate_limit(chat_id: int) -> bool` 和 `update_rate_limit(chat_id: int)`。

**阶段 3: 指令处理器 (`telegram_logger/handlers`)**

1.  **[Handler]** 创建 `UserBotCommandHandler` 类，继承自 `BaseHandler` 或直接实现事件处理。
2.  **[Registration]** 在 `telegram_logger/main.py` 或 `TelegramClientService` 中，注册 `UserBotCommandHandler` 来处理来自用户自己私聊 (`event.is_private and event.sender_id == self.my_id`) 的 `events.NewMessage`。
3.  **[Parsing]** 在 `UserBotCommandHandler.process` (或类似方法) 中，检查消息文本是否以 `.` 开头，并解析指令和参数。可以使用 `shlex.split` 处理带引号的参数。
4.  **[Implementation]** 为 RFC 003 中定义的每个指令 (`.on`, `.off`, `.status`, `.replyon`, `.replyoff`, `.setmodel`, `.listmodels`, `.aliasmodel`, `.unaliasmodel`, `.setrole`, `.listroles`, `.aliasrole`, `.unaliasrole`, `.addgroup`, `.delgroup`, `.listgroups`, `.setlimit`, `.help`) 实现对应的处理逻辑。
    *   调用 `UserBotStateService` 的方法来读取或更新状态。
    *   实现输入验证（例如，`.addgroup` 验证群组，`.setlimit` 验证数字，`.setrolepreset` 验证 JSON 格式，确保别名存在等）。
    *   调用 `client.send_message` (或通过 `LogSender`) 将操作反馈发送回用户的私聊。
    *   `.listmodels`, `.listroles`, `.listgroups`, `.status`, `.help` 需要格式化输出信息，特别是 `.listroles` 需要显示所有新字段。

**阶段 4: 自动回复逻辑 (`telegram_logger/handlers`)**

1.  **[Handler]** 创建 `MentionReplyHandler` 类，或在现有合适的 Handler (如果重构后有) 中添加逻辑。
2.  **[Registration]** 在 `telegram_logger/main.py` 或 `TelegramClientService` 中，注册 `MentionReplyHandler` 来处理 `events.NewMessage`。
3.  **[Filtering]** 在 `MentionReplyHandler.process` 中实现过滤逻辑：
    *   检查 `UserBotStateService.is_enabled()` 是否为 `True`。
    *   检查 `event.chat_id` 是否在 `UserBotStateService.get_target_group_ids()` 中。
    *   检查 `event.sender_id == self.my_id` (忽略自己发的消息)。
    *   检查是否满足触发条件：
        *   `event.mentioned` (是否 @ 了自己)
        *   或者 (`UserBotStateService.is_reply_trigger_enabled()` 且 `event.is_reply` 且 `event.reply_to_msg_id` 对应的消息是自己发的 - 可能需要 `client.get_messages` 确认)。
    *   如果同时满足 @ 和回复，确保只处理一次。
4.  **[Rate Limit]** 调用 `UserBotStateService.check_rate_limit(event.chat_id)`。如果受限，则停止处理。
5.  **[Get Role]** 获取当前角色详情 `role_details = UserBotStateService.get_current_role()`。如果角色为空，则停止处理。
6.  **[Generate Reply]**
    *   **If `role_details['role_type'] == 'static'`:** 直接使用 `reply_text = role_details.get('static_content', '')`。 (使用 `static_content` 字段)
    *   **If `role_details['role_type'] == 'ai'`:**
        *   获取当前模型 ID `model_id = UserBotStateService.get_current_model_id()`。
        *   **准备 AI 请求上下文:**
            *   获取系统提示 `system_prompt = role_details.get('system_prompt')`。
            *   获取并解析预设消息 `preset_messages_json = role_details.get('preset_messages')`。如果存在且有效，解析为列表。
            *   获取历史消息（例如最近 5-10 条）。
            *   获取当前触发消息 `event.message.text`。
        *   **构建消息列表:** 按照 AI 服务要求的格式，组合系统提示、预设消息、历史消息和当前用户消息。
        *   调用 AI 服务接口 (见阶段 5)，传入模型 ID 和构建好的消息列表，获取生成的 `reply_text`。
        *   处理 AI 服务可能发生的错误。
7.  **[Send Reply]** 调用 `client.send_message(event.chat_id, reply_text, reply_to=event.message.id)` 发送回复。
8.  **[Update Limit]** 如果发送成功，调用 `UserBotStateService.update_rate_limit(event.chat_id)`。

**阶段 5: AI 集成 (如果需要) (`telegram_logger/services` 或 `telegram_logger/utils`)**

1.  **[Interface]** 定义一个通用的 AI 服务调用函数/类，例如 `async def get_ai_completion(model_id: str, system_prompt: str, user_message: str, history: Optional[List] = None) -> str:`。
2.  **[Implementation]** 实现与具体 AI 提供商 (如 OpenAI) 的 API 交互逻辑。处理认证 (API Key)、请求构建、响应解析和错误处理。
3.  **[Config]** 可能需要从 `.env` 文件读取 AI 服务的 API Key 和 Base URL 等配置。

**阶段 6: 错误处理与日志**

1.  在数据库操作、API 调用、消息发送等关键步骤添加 `try...except` 块。
2.  使用 `logging` 模块记录错误信息和关键执行步骤。
3.  确保用户指令处理失败时（如无效输入、权限问题）向用户返回友好的错误提示。
4.  确保自动回复过程中的内部错误（如 AI 服务失败、发送消息失败）只记录日志，不打扰用户或群组。

**阶段 7: 测试 (`tests/`)**

1.  **[Unit Tests]** 为指令解析逻辑、状态服务中的方法（特别是别名解析和状态更新）、频率限制逻辑编写单元测试。
2.  **[Integration Tests]** 编写集成测试：
    *   模拟用户发送指令，验证状态是否正确更新以及反馈消息是否符合预期。
    *   模拟群组中的 @ 提及和回复事件，验证自动回复是否按预期触发（或不触发）、内容是否正确（区分 static/ai）、频率限制是否生效。可能需要 Mock AI 服务接口。

## 5. 依赖项

-   可能需要添加 AI 服务提供商的 Python SDK (例如 `openai`)。
-   其他依赖项应尽量复用项目中已有的库。

## 6. 配置

-   可能需要在 `.env.example` 和 `.env` 中添加新的环境变量：
    -   `AI_PROVIDER_API_KEY` (例如 `OPENAI_API_KEY`)
    -   `AI_PROVIDER_BASE_URL` (可选，用于代理或自托管模型)
-   默认的模型 ID 和角色别名可以在代码中硬编码或作为配置项。

## 7. (已移除) 待讨论/决策点

(本章节原包含的决策点已整合入文档相关部分。)
