# Handlers 模块重构计划 (Migration Plan)

## 1. 背景

当前的 `handlers` 模块包含 `NewMessageHandler`, `EditDeleteHandler`, 和 `ForwardHandler`。这些处理器存在职责重叠和逻辑耦合的问题：

- 多个处理器监听相同的事件（如 `NewMessage`, `MessageEdited`, `MessageDeleted`）。
- 消息的持久化、日志记录（编辑/删除通知）和条件转发逻辑分散在不同的类中。
- `ForwardHandler` 承担了过多的职责，包括事件过滤、格式化、媒体处理、速率限制和发送。
- 配置项（如 `FORWARD_USER_IDS`, `IGNORED_IDS`）在多个处理器中使用，增加了维护难度。

这种混乱的结构使得代码难以理解、维护和扩展。

## 2. 重构目标

- **清晰职责分离**: 每个处理器应具有单一、明确的职责。
- **减少冗余**: 消除重复的事件监听和逻辑处理。
- **提高可维护性**: 使代码结构更清晰，易于理解和修改。
- **增强可扩展性**: 为未来可能增加的新处理逻辑（如不同类型的通知、过滤规则）打下基础。

## 3. 目标架构

我们将重构 `handlers` 模块，采用以下结构：

- **`PersistenceHandler`**:
  - **职责**: 负责将消息数据持久化到数据库。
  - **监听事件**: (通过 `TelegramClientService` 注册) `NewMessage`, `MessageEdited`, `MessageDeleted` (但内部只处理需要的)。
  - **核心逻辑 (在 `process` 方法中实现)**:
    - 接收 `TelegramClientService` 传递的所有事件。
    - 使用 `isinstance(event, (events.NewMessage, events.MessageEdited))` 判断是否为需要处理的事件类型。
    - 如果是 `NewMessage` 或 `MessageEdited`：
      - 创建或更新 `Message` 数据模型对象。
      - 调用 `DatabaseManager` 将 `Message` 对象保存到数据库。
    - 忽略其他类型的事件 (如 `MessageDeleted`)。
    - 不处理任何过滤、格式化或发送逻辑。
- **`OutputHandler`**:
  - **职责**: 负责根据配置和事件类型，过滤、格式化消息并将其发送到日志频道。合并了原 `EditDeleteHandler` 的日志记录功能和 `ForwardHandler` 的转发功能。
  - **监听事件**: (通过 `TelegramClientService` 注册) `NewMessage`, `MessageEdited`, `MessageDeleted`。
  - **核心逻辑 (在 `process` 方法中实现)**:
    - 接收 `TelegramClientService` 传递的所有事件。
    - 使用 `isinstance(event, ...)` 判断事件类型 (`NewMessage`, `MessageEdited`, `MessageDeleted`)。
    - **事件过滤 (内部处理)**:
      - 根据事件类型和内容，应用过滤规则：
        - 对于 `NewMessage` 和 `MessageEdited` 事件，检查消息是否来自 `FORWARD_USER_IDS` 或 `FORWARD_GROUP_IDS`。如果不是，则忽略。
        - 对于 `MessageDeleted` 事件，检查事件是否发生在 `FORWARD_GROUP_IDS` 中的群组。如果不是，则忽略。
        - 检查发送者或聊天是否在 `IGNORED_IDS` 中（如果适用）。
      - 如果事件被过滤掉，则提前返回。
    - **数据检索 (含竞态处理)**:
      - 对于 `MessageDeleted` 事件，从数据库 (`DatabaseManager`) 检索原始消息内容。
      - **注意**: 由于 `PersistenceHandler` 保存消息和 `OutputHandler` 处理删除事件是并发的，可能存在竞态条件，即处理删除事件时消息尚未写入数据库。
      - **解决方案 (方案三：简单重试)**: 在 `OutputHandler` 的 `process` 方法中处理 `MessageDeleted` 事件时，如果首次通过 `DatabaseManager` 查询未能获取到已删除消息的数据，并且该删除事件相对较新（例如，发生在过去几秒内），则应进行短暂延迟（如 `await asyncio.sleep(0.5)`) 后重试查询一次。如果重试后仍失败，则记录一条包含消息 ID 但缺少原始内容的简化删除日志到日志频道。
    - **格式化**: 依赖 `MessageFormatter` (在 `OutputHandler` 内部实例化和调用) 来格式化要发送到日志频道的消息文本（包括新消息、编辑标记、删除标记）。
    - **媒体处理**:
      - 依赖 `LogSender` (在 `OutputHandler` 内部实例化和调用) 发送普通媒体。
      - 依赖 `RestrictedMediaHandler` (在 `OutputHandler` 内部实例化和调用) 处理受限媒体的下载、解密和发送（通过 `LogSender` 发送）。确认 `telegram_logger/utils/media.py` 和 `telegram_logger/utils/file_encrypt.py` 提供了必要的功能支持。
      - 包含处理贴纸的特殊发送逻辑。
    - **速率限制**: 应用原 `ForwardHandler` 中的删除事件速率限制逻辑，以防止删除通知刷屏。
    - **发送**: 最终使用 `LogSender` 将格式化的文本和/或媒体文件发送到 `LOG_CHAT_ID`。
- **`BaseHandler` (Abstract Base Class)**:
  - 将修改为抽象基类 (`abc.ABC`)。
  - 提供基础功能（客户端/数据库注入、`my_id` 获取等）。
  - 定义一个抽象方法 `async def process(self, event: events.common.EventCommon)`，强制所有子类实现统一的事件处理入口。
- **辅助类**:
  - `MessageFormatter`, `LogSender`, `RestrictedMediaHandler` 基本保持不变，由 `OutputHandler` 调用。

### TelegramClientService 交互 (方案一：统一接口)

`TelegramClientService` 的事件注册逻辑 (`_register_handlers`) **必须彻底重构**，以采用统一分发策略：

- **完全替换旧逻辑**: **必须删除** `telegram_logger/services/client.py` 中 `_register_handlers` 方法内**所有**现存的事件注册代码。这包括针对 `ForwardHandler` 的特殊处理（如基于 `forward_user_ids` 和 `forward_group_ids` 使用 `from_users` 或 `chats` 过滤器进行的多次注册）以及基于 `hasattr` 的通用注册逻辑。
- **实施统一注册**:
  - 遍历 `self.handlers` 列表中的所有处理器实例。
  - 对于每一个处理器 `handler`：
    - 检查它是否是 `BaseHandler` 的实例 (`isinstance(handler, BaseHandler)`)。
    - 如果是，则为其注册**所有可能相关的基础事件类型** (`events.NewMessage`, `events.MessageEdited`, `events.MessageDeleted`)。
    - 所有事件注册都指向该处理器的**统一入口方法** `handler.process`。
    - **关键**: **必须**使用**不带 `from_users` 或 `chats` 过滤器**的通用事件构造器 (`events.NewMessage()`, `events.MessageEdited()`, `events.MessageDeleted()`) 来注册。
- **解耦与职责委托**:
  - 通过依赖 `BaseHandler` 抽象类和其统一的 `process` 方法，`TelegramClientService` 与具体的处理器实现解耦。它不再需要知道 `PersistenceHandler` 或 `OutputHandler` 的具体细节。
  - 它将“决定是否处理某个特定事件”的职责完全**委托**给了每个处理器自己的 `process` 方法。
- **处理器内部决策**:
  - 当事件发生时，`TelegramClientService` 会调用**所有**已注册处理器的 `process` 方法。
  - 每个处理器的 `process` 方法内部通过检查事件类型 (`isinstance`) 和其他条件（如配置规则）来**自行决定**是否要响应该事件以及如何响应。例如，`PersistenceHandler` 会忽略 `MessageDeleted` 事件，而 `OutputHandler` 会根据其内部逻辑处理所有三种事件类型（包括应用转发规则、忽略规则等）。

### 事件处理流程 (方案一)

1.  Telethon 触发事件 (e.g., `NewMessage`, `MessageEdited`, `MessageDeleted`)。
2.  `TelegramClientService` 将该事件分发给**所有** `BaseHandler` 子类实例的 `process` 方法。
3.  每个处理器的 `process` 方法被调用：
    a. **`PersistenceHandler.process`**: - 检查事件类型是否为 `NewMessage` 或 `MessageEdited`。 - 如果是，则创建/更新 `Message` 对象并存入数据库。 - 否则，忽略该事件。
    b. **`OutputHandler.process`**: - 检查事件类型 (`NewMessage`, `MessageEdited`, `MessageDeleted`)。 - 应用内部过滤规则（转发来源、忽略列表等）。如果被过滤，则忽略该事件。 - 如果事件通过过滤，则根据事件类型执行相应操作：
    i. (Deleted) 从数据库获取原始消息（含重试逻辑）。
    ii. 格式化消息文本。
    iii. 处理媒体（包括受限媒体）。
    iv. (Deleted) 应用速率限制。
    v. 通过 `LogSender` 发送到日志频道。

## 4. 重构步骤

**重要提示**: 每个 `process` 方法的实现都应包含健壮的错误处理 (`try...except`) 和清晰的日志记录 (`logger.info`, `logger.warning`, `logger.error`)。

1.  **修改 `BaseHandler`**: - **状态**: [x] 完成
    - 修改 `telegram_logger/handlers/base_handler.py`。
    - 导入 `abc` 和 `telethon.events`。
    - 让 `BaseHandler` 继承自 `abc.ABC`。
    - 添加抽象方法 `@abc.abstractmethod async def process(self, event: events.common.EventCommon): raise NotImplementedError`。
2.  **创建 `PersistenceHandler`**: - **状态**: [x] 完成
    - 创建 `telegram_logger/handlers/persistence_handler.py` 文件。
    - 定义 `PersistenceHandler` 类，继承自 `BaseHandler`。
    - 实现 `async def process(self, event)` 方法。
    - 在 `process` 方法内部，使用 `isinstance` 检查事件类型，仅处理 `NewMessage` 和 `MessageEdited`。
    - 将原 `NewMessageHandler` 中的 `_create_message_object` 和 `db.save_message` 逻辑移入此处理器的 `process` 方法中（在类型检查之后）。
    - 确保该处理器仅负责数据持久化，忽略其他事件类型。
3.  **创建 `OutputHandler`**: - **状态**: [x] 完成
    - 创建 `telegram_logger/handlers/output_handler.py` 文件。
    - 定义 `OutputHandler` 类，继承自 `BaseHandler`。
    - 实现 `async def process(self, event)` 方法。
    - 在 `process` 方法内部，使用 `isinstance` 检查事件类型 (`NewMessage`, `MessageEdited`, `MessageDeleted`)。
    - **合并逻辑 (移入 `process` 方法内部，根据事件类型调用)**:
      - 将 `ForwardHandler` 的核心逻辑（**内部事件过滤**、格式化、媒体处理、速率限制、发送）移入 `OutputHandler` 的 `process` 方法或其调用的私有辅助方法中。
      - 将 `EditDeleteHandler` 的核心逻辑（编辑/删除事件的格式化、数据库检索、发送）移入 `OutputHandler`，并与 `ForwardHandler` 的逻辑整合（例如，编辑/删除事件现在也受转发规则约束）。
    - **依赖注入**: 确保 `OutputHandler` 的 `__init__` 方法能接收并存储所有必要的依赖和配置，包括 `db`, `log_chat_id`, `ignored_ids`, `forward_user_ids`, `forward_group_ids`, 以及速率限制相关的配置参数 (如 `deletion_rate_limit_threshold`, `deletion_rate_limit_window`, `deletion_pause_duration`)。`client` 实例将在稍后通过 `set_client` 方法注入。
    - **实例化辅助类**: 在 `set_client` 方法中实例化 `MessageFormatter`, `LogSender`, `RestrictedMediaHandler` (因为它们需要 client)。确保将 `client` 和其他必要的依赖传递给这些辅助类。
4.  **更新 `TelegramClientService._register_handlers`**: - **状态**: [x] 完成
    - **关键步骤**: 修改 `telegram_logger/services/client.py` 中的 `_register_handlers` 方法。
    - **必须完全移除**现有的事件注册逻辑。
    - **必须严格按照**“目标架构”部分描述的“TelegramClientService 交互 (方案一：统一接口)”策略重新实现事件注册。即：为所有 `BaseHandler` 子类注册 `NewMessage`, `MessageEdited`, `MessageDeleted` 事件，不带过滤器，统一指向 `handler.process`。
5.  **清理旧处理器**: - **状态**: [x] 完成
    - 删除 `telegram_logger/handlers/new_message_handler.py` 文件。
    - 删除 `telegram_logger/handlers/edit_delete_handler.py` 文件。
    - 删除 `telegram_logger/handlers/forward_handler.py` 文件。
6.  **更新 `__init__.py`**: - **状态**: [ ] 未完成
    - 修改 `telegram_logger/handlers/__init__.py`，导出新的处理器：`BaseHandler`, `PersistenceHandler`, `OutputHandler`。移除对旧处理器 (`NewMessageHandler`, `EditDeleteHandler`, `ForwardHandler`) 的导出。
7.  **更新 `main.py`**: - **状态**: [ ] 未完成 (标记为未完成，因为需要实际修改)
    - 修改 `telegram_logger/main.py` 中的 `main` 函数。
    - **移除** `NewMessageHandler`, `EditDeleteHandler`, `ForwardHandler` 的实例化代码。
    - **添加** `PersistenceHandler` 的实例化，确保传递必要的依赖 (`db`, `log_chat_id`, `ignored_ids`)。
    - **添加** `OutputHandler` 的实例化，确保传递所有必要的依赖和配置 (`db`, `log_chat_id`, `ignored_ids`, `forward_user_ids`, `forward_group_ids`, `deletion_rate_limit_threshold`, `deletion_rate_limit_window`, `deletion_pause_duration`)。
    - 确认 `client_service.initialize()` 之后的客户端注入逻辑 (`handler.set_client(client_service.client)`) 保持不变，它将适用于新的 `PersistenceHandler` 和 `OutputHandler` (因为它们都继承自 `BaseHandler` 并应包含 `set_client` 方法)。
8.  **审查和测试**: - **状态**: [ ] 未完成
    - 仔细审查所有修改的代码，特别是 `TelegramClientService._register_handlers` 和 `OutputHandler.process` 的实现。
    - 进行全面的测试，覆盖新消息、编辑消息、删除消息、转发规则、忽略规则、受限媒体、贴纸、速率限制等场景。
