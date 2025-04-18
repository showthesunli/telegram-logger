# Handlers 模块重构计划 (Migration Plan)

## 1. 背景

当前的 `handlers` 模块包含 `NewMessageHandler`, `EditDeleteHandler`, 和 `ForwardHandler`。这些处理器存在职责重叠和逻辑耦合的问题：

-   多个处理器监听相同的事件（如 `NewMessage`, `MessageEdited`, `MessageDeleted`）。
-   消息的持久化、日志记录（编辑/删除通知）和条件转发逻辑分散在不同的类中。
-   `ForwardHandler` 承担了过多的职责，包括事件过滤、格式化、媒体处理、速率限制和发送。
-   配置项（如 `FORWARD_USER_IDS`, `IGNORED_IDS`）在多个处理器中使用，增加了维护难度。

这种混乱的结构使得代码难以理解、维护和扩展。

## 2. 重构目标

-   **清晰职责分离**: 每个处理器应具有单一、明确的职责。
-   **减少冗余**: 消除重复的事件监听和逻辑处理。
-   **提高可维护性**: 使代码结构更清晰，易于理解和修改。
-   **增强可扩展性**: 为未来可能增加的新处理逻辑（如不同类型的通知、过滤规则）打下基础。

## 3. 目标架构

我们将重构 `handlers` 模块，采用以下结构：

-   **`PersistenceHandler`**:
    -   **职责**: 负责将消息数据持久化到数据库。
    -   **监听事件**: `NewMessage`, `MessageEdited`。
    -   **核心逻辑**:
        -   接收原始事件。
        -   创建或更新 `Message` 数据模型对象。
        -   调用 `DatabaseManager` 将 `Message` 对象保存到数据库。
        -   不处理任何过滤、格式化或发送逻辑。
-   **`OutputHandler`**:
    -   **职责**: 负责根据配置和事件类型，格式化消息并将其发送到日志频道。合并了原 `EditDeleteHandler` 的日志记录功能和 `ForwardHandler` 的转发功能。
    -   **监听事件**: `NewMessage`, `MessageEdited`, `MessageDeleted`。
    -   **核心逻辑**:
        -   接收原始事件。
        -   **事件过滤**:
            -   对于 `NewMessage` 和 `MessageEdited` 事件，检查消息是否来自 `FORWARD_USER_IDS` 或 `FORWARD_GROUP_IDS`。如果不是，则忽略。
            -   对于 `MessageDeleted` 事件，检查事件是否发生在 `FORWARD_GROUP_IDS` 中的群组。如果不是，则忽略。
            -   检查发送者或聊天是否在 `IGNORED_IDS` 中（如果适用）。
        -   **数据检索**: 对于 `MessageDeleted` 事件，从数据库 (`DatabaseManager`) 检索原始消息内容。
        -   **格式化**: 使用 `MessageFormatter` 格式化要发送到日志频道的消息文本（包括新消息、编辑标记、删除标记）。
        -   **媒体处理**:
            -   处理普通媒体的发送。
            -   使用 `RestrictedMediaHandler` 处理受限媒体的下载、解密和发送（主要用于转发场景）。
            -   处理贴纸的特殊发送逻辑。
        -   **速率限制**: 应用原 `ForwardHandler` 中的删除事件速率限制逻辑，以防止删除通知刷屏。
        -   **发送**: 使用 `LogSender` 将最终格式化的文本和/或媒体文件发送到 `LOG_CHAT_ID`。
-   **`BaseHandler`**:
    -   保持不变，提供基础功能，如客户端/数据库注入、`my_id` 获取等。
-   **辅助类**:
    -   `MessageFormatter`, `LogSender`, `RestrictedMediaHandler` 基本保持不变，由 `OutputHandler` 调用。

### 事件处理流程

1.  Telethon 触发事件 (e.g., `NewMessage`)。
2.  `TelegramClientService` 将事件分发给注册的处理器。
3.  `PersistenceHandler` 接收事件，创建/更新 `Message` 对象并存入数据库。
4.  `OutputHandler` 接收事件：
    a.  检查事件是否满足过滤条件（转发规则、忽略列表等）。
    b.  如果满足条件，根据事件类型（New/Edited/Deleted）执行相应操作：
        i.  (Deleted) 从数据库获取原始消息。
        ii. 格式化消息文本。
        iii. 处理媒体（包括受限媒体）。
        iv. (Deleted) 应用速率限制。
        v.  通过 `LogSender` 发送到日志频道。

## 4. 重构步骤

1.  **创建 `PersistenceHandler`**:
    -   创建 `telegram_logger/handlers/persistence_handler.py` 文件。
    -   定义 `PersistenceHandler` 类，继承自 `BaseHandler`。
    -   实现 `handle_new_message` 和 `handle_message_edited` 方法（或一个统一的 `process` 方法）。
    -   将原 `NewMessageHandler` 中的 `_create_message_object` 和 `db.save_message` 逻辑移入此处理器。
    -   确保该处理器仅负责数据持久化。
2.  **创建 `OutputHandler`**:
    -   创建 `telegram_logger/handlers/output_handler.py` 文件。
    -   定义 `OutputHandler` 类，继承自 `BaseHandler`。
    -   实现 `handle_new_message`, `handle_message_edited`, `handle_message_deleted` 方法（或一个统一的 `process` 方法）。
    -   **合并逻辑**:
        -   将 `ForwardHandler` 的核心逻辑（事件过滤、格式化、媒体处理、速率限制、发送）移入 `OutputHandler`。
        -   将 `EditDeleteHandler` 的核心逻辑（编辑/删除事件的格式化、数据库检索、发送）移入 `OutputHandler`，并与 `ForwardHandler` 的逻辑整合（例如，编辑/删除事件现在也受转发规则约束）。
    -   **依赖注入**: 确保 `OutputHandler` 能接收并使用 `client`, `db`, `log_chat_id`, `ignored_ids`, `forward_user_ids`, `forward_group_ids`, 以及速率限制相关的配置参数。
    -   **实例化辅助类**: 在 `__init__` 中实例化 `MessageFormatter`, `LogSender`, `RestrictedMediaHandler`。
3.  **更新 `TelegramClientService`**:
    -   **(可选但推荐)** 在 `handlers` 模块中定义抽象基类（接口），如 `IPersistenceEventHandler` 和 `IOutputEventHandler`，让 `PersistenceHandler` 和 `OutputHandler` 分别继承它们。这些接口表明处理器关心哪些类型的事件。
    -   修改 `_register_handlers` 方法：
        -   移除所有旧的基于 `hasattr` 或 `isinstance(handler, ForwardHandler)` 的注册逻辑。
        -   移除所有为 `NewMessageHandler`, `EditDeleteHandler`, `ForwardHandler` 添加事件处理器的代码。
        -   遍历 `handlers` 列表。
        -   对于每个 `handler`：
            -   使用 `isinstance(handler, IPersistenceEventHandler)` (或直接检查类型 `isinstance(handler, PersistenceHandler)`) 判断是否需要注册持久化相关事件。如果是，则调用 `self.client.add_event_handler()` 注册**通用**的 `events.NewMessage()` 和 `events.MessageEdited()`，指向 `handler.process` 或相应的处理方法。
            -   使用 `isinstance(handler, IOutputEventHandler)` (或直接检查类型 `isinstance(handler, OutputHandler)`) 判断是否需要注册输出相关事件。如果是，则调用 `self.client.add_event_handler()` 注册**通用**的 `events.NewMessage()`, `events.MessageEdited()`, 和 `events.MessageDeleted()`，指向 `handler.process` 或相应的处理方法。
        -   **关键**: 确保所有 `add_event_handler` 调用都使用**不带 `from_users` 或 `chats` 过滤器**的通用事件构造器。过滤逻辑完全移交给 `OutputHandler` 内部处理。
4.  **清理旧处理器**:
    -   删除 `telegram_logger/handlers/new_message_handler.py` 文件。
    -   删除 `telegram_logger/handlers/edit_delete_handler.py` 文件。
    -   删除 `telegram_logger/handlers/forward_handler.py` 文件。
    -   (可选) 可以先将旧文件重命名或移动到备份目录，待重构稳定后再删除。
5.  **更新 `__init__.py`**:
    -   修改 `telegram_logger/handlers/__init__.py`，导出新的处理器：`PersistenceHandler`, `OutputHandler`。移除旧的导出。
6.  **更新 `main.py`**:
    -   修改 `main` 函数中的 `handlers` 列表。
    -   移除 `NewMessageHandler`, `EditDeleteHandler`, `ForwardHandler` 的实例化。
    -   实例化 `PersistenceHandler` 和 `OutputHandler`，并将所需的配置（DB, client (稍后注入), log_chat_id, ignored_ids, forward_ids, rate limits 等）传递给它们。
    -   确保 `client_service.initialize()` 后的客户端注入逻辑对新处理器仍然有效。
7.  **审查和测试**:
    -   仔细审查所有修改的代码。
    -   进行全面的测试，覆盖新消息、编辑消息、删除消息、转发规则、忽略规则、受限媒体、贴纸、速率限制等场景。
