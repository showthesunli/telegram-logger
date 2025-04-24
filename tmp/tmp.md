好的，我们来一起审阅一下 `IMP/001-RFC003-UserBot.md` 这份实现计划文档。

总的来说，这份 IMP 文档相当详尽，结构清晰，并且很好地将 RFC 003 的需求分解为了具体的开发阶段和任务。它涵盖了数据模型、状态管理、指令处理、自动回复逻辑、AI 集成、错误处理和初始化等关键方面。

以下是一些可以考虑**修改或补充**的建议：

1.  **Handler 结构 (阶段 3 & 4 & 7):**
    *   **当前方案:** IMP 建议直接使用 `@client.on` 装饰器来定义指令处理 (`handle_user_commands`) 和提及/回复处理 (`handle_mention_or_reply`) 的异步函数。
    *   **潜在问题:** 这可能导致这些处理函数需要定义在 `main.py` 或其他可以访问 `client` 实例、`my_id`、`UserBotStateService` 实例等核心对象的作用域内，可能会影响代码的模块化和可测试性。
    *   **建议:** 考虑采用更面向对象的方式，创建专门的 Handler 类（例如 `UserBotCommandHandler` 和 `MentionReplyHandler`，可以继承自 `BaseHandler` 或一个新的基类），就像现有的 `PersistenceHandler` 和 `OutputHandler` 一样。
        *   在 `main.py` 中实例化这些 Handler 类，并将所需的依赖（如 `db`, `state_service`, `my_id`, `client`）注入它们的构造函数。
        *   然后，在 `TelegramClientService._register_handlers` 中（或者在 `main.py` 初始化阶段），将这些 Handler 实例的方法注册到 `telethon` 的事件分发器中。例如，`client.add_event_handler(user_bot_command_handler.handle_command, events.NewMessage(from_users=my_id, chats='me'))`。
        *   这样做可以更好地封装逻辑，方便管理依赖，并提高代码的可测试性。IMP 第 7 阶段已经提到了创建这些类的示例，可以进一步强调将事件注册逻辑也移到初始化流程中，而不是直接在类/函数定义处使用装饰器。

2.  **AI 历史消息处理 (阶段 4 & 5):**
    *   **现状:** IMP 提到了从数据库获取历史消息 (`get_messages_before`) 并用于构建 AI 请求上下文。
    *   **补充:** 需要更明确地说明如何将从数据库获取的 `Message` 对象（包含文本、发送者 ID 等）转换为 AI 服务（如 OpenAI）所需的格式，通常是 `List[Dict[str, str]]`，包含 `role` (`user` 或 `assistant`) 和 `content` (`msg_text`)。需要根据 `message.from_id == my_id` 来判断消息的角色。

3.  **默认角色创建 (阶段 2):**
    *   **现状:** IMP 提到 *考虑* 在 `load_state` 时检查并创建默认的 `default_assistant` 角色。
    *   **建议:** 最好明确规定：在 `load_state` 时，如果数据库中不存在别名为 `default_assistant` 的角色，**则应自动创建它**，并使用 RFC 中定义的默认描述和类型（AI）。这样可以确保用户总有一个可用的默认 AI 角色，除非他们手动删除了它。

4.  **JSON 验证 (阶段 2 & 3):**
    *   **现状:** IMP 提到了在 `UserBotStateService` 中调用 DB 方法前验证 JSON (阶段 2)。
    *   **补充:** 应同时在指令处理器 (阶段 3) 解析用户输入的 `.setrolepreset` 命令时，**立即进行 JSON 格式验证**。如果用户输入的不是有效的 JSON 字符串，应直接返回错误提示，而不是等到调用 `StateService` 时才发现。

5.  **`.addgroup` 的群组链接处理 (阶段 3):**
    *   **现状:** IMP 提到要验证群组 ID 或链接。
    *   **补充:** 可以稍微具体说明如何处理链接。例如，使用 `client.get_entity(link)` 来尝试解析链接并获取实体。需要处理可能出现的 `ValueError` (无效链接格式) 或 `telethon.errors` (找不到实体、权限不足等)，并向用户返回相应的错误信息。

6.  **通配符删除 (`.unaliasrole *`, `.unaliasmodel *`) (阶段 3 & 2):**
    *   **现状:** RFC 提到了使用 `*` 作为示例，但 IMP 没有明确说明如何处理。
    *   **补充:** 需要在指令处理器 (阶段 3) 和状态服务 (阶段 2) 中明确如何实现对 `*` 通配符的支持。通常这意味着需要获取所有当前存在的别名列表，然后逐个调用删除方法。

7.  **AI 历史消息数量 (`ai_history_length`) (阶段 1 & 3):**
    *   **现状:** IMP 在 `user_bot_settings` 表中添加了 `ai_history_length` 列 (很好)，默认值为 1。RFC 中没有定义用户修改此值的命令。
    *   **建议:** 需要明确这个值是否允许用户配置。
        *   **如果允许:** 需要在 RFC 和 IMP 中补充定义一个新的用户命令，例如 `.sethistory <数量>`，并在指令处理器 (阶段 3) 和状态服务 (阶段 2) 中实现它。
        *   **如果不允许 (或后续实现):** IMP 中可以加个注释说明当前版本此值固定或由内部逻辑控制，未来可能开放配置。

8.  **数据库方法命名 (阶段 1):**
    *   **建议:** `get_role_aliases()` 返回的是 `Dict[str, Dict[str, Any]]`，包含了所有角色的详细信息。可以考虑将其重命名为 `get_all_role_details()` 或类似名称，以更清晰地反映其返回值内容。而如果真的只需要别名列表，可以再提供一个 `get_role_alias_names() -> List[str]`。同理适用于 `get_model_aliases()`。

9.  **依赖注入的明确性 (阶段 7):**
    *   **现状:** IMP 提到了确保依赖可用。
    *   **建议:** 如果采纳了第 1 点的 Handler 类建议，可以在这里更明确地说明：在 `main.py` 中创建 `UserBotStateService` 实例后，将其连同 `db`, `my_id`, `client` 等一起传递给 `UserBotCommandHandler` 和 `MentionReplyHandler` 的构造函数。

总的来说，这份 IMP 已经非常出色。上述建议主要是为了进一步提高代码结构的健壮性、明确性和用户体验。你可以根据项目的实际情况和偏好来决定是否采纳这些建议。