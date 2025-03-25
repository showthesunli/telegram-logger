# Telegram 删除消息记录器模块化重构计划

## 当前问题

当前的 `tg_delete_logger.py` 文件存在以下问题：

1. 文件过大，包含了太多功能
2. 缺乏模块化结构，难以维护和扩展
3. 混合了多种职责（数据库操作、Telegram API 交互、媒体文件处理等）
4. 全局变量使用过多
5. 缺少适当的错误处理和日志记录策略

## 重构目标

1. 将代码拆分为多个功能明确的模块
2. 减少全局变量的使用，改用依赖注入
3. 提高代码的可测试性
4. 改进错误处理和日志记录
5. 使代码结构更清晰，便于未来扩展

## 模块化拆分计划

### 1. 项目结构

```
telegram_logger/
├── __init__.py
├── main.py                  # 主入口点
├── config.py                # 配置文件（从现有的 config.py 导入）
├── data/
│   ├── __init__.py
│   ├── models.py            # 数据库模型
│   └── database.py          # 数据库操作
├── handlers/
│   ├── __init__.py
│   ├── message_handler.py   # 消息处理
│   ├── delete_handler.py    # 删除消息处理
│   ├── edit_handler.py      # 编辑消息处理
│   └── forward_handler.py   # 转发消息处理
├── utils/
│   ├── __init__.py
│   ├── media.py             # 媒体文件处理
│   ├── mentions.py          # 创建提及链接
│   └── logging.py           # 日志工具
└── services/
    ├── __init__.py
    ├── client.py            # Telegram 客户端服务
    └── cleanup.py           # 清理过期消息服务
```

### 2. 模块职责划分

#### 2.1 主模块 (main.py)

- 初始化 Telegram 客户端
- 注册事件处理器
- 启动应用程序

#### 2.2 数据库模块 (data/)

- **models.py**: 定义消息数据模型
- **database.py**: 提供数据库连接和操作函数
  - 初始化数据库
  - 保存消息
  - 查询消息
  - 删除过期消息

#### 2.3 处理器模块 (handlers/)

- **message_handler.py**: 处理新消息
- **delete_handler.py**: 处理删除的消息
- **edit_handler.py**: 处理编辑的消息
- **forward_handler.py**: 处理需要转发的消息

#### 2.4 工具模块 (utils/)

- **media.py**: 媒体文件处理
  - 保存媒体文件
  - 检索媒体文件
  - 获取文件名
- **mentions.py**: 创建提及链接
- **logging.py**: 日志配置和工具

#### 2.5 服务模块 (services/)

- **client.py**: Telegram 客户端服务
  - 客户端初始化
  - 会话管理
- **cleanup.py**: 清理服务
  - 删除过期消息
  - 删除过期媒体文件

### 3. 重构步骤

✅ 1. **创建项目结构**

- 创建所有必要的目录和空文件

✅ 2. **配置模块**

- 从现有的 config.py 导入配置
- 创建配置验证函数

✅ 3. **数据库模块**

- 将数据库初始化和操作从主文件移至 data/database.py
- 创建消息模型在 data/models.py 中

✅ 4. **工具模块**

- 提取媒体处理函数到 media.py
- 提取提及创建函数到 mentions.py
- 设置日志配置在 logging.py

[当前进度]
- 处理器模块部分完成(ForwardHandler已实现)
- 主文件中仍包含NewMessageHandler和EditDeleteHandler待迁移
- 下一步应完成剩余处理器迁移和服务模块实现

5. **处理器模块**
   - ✅ ForwardHandler 已完成
   - ✅ NewMessageHandler 已完成
   - ✅ EditDeleteHandler 已完成
   - ✅ 重构处理器以使用依赖注入而非全局变量

6. **服务模块**
   - ✅ ClientService 实现
   - ✅ CleanupService 实现
   - ✅ 服务健康检查实现

7. **主模块**
   - ✅ 应用程序入口点
   - ✅ 模块连接
   - ✅ 错误处理增强

### 4. 改进点

1. **依赖注入**

   - 使用类和对象替代全局变量
   - 通过构造函数传递依赖

2. **异步处理**

   - 保持异步函数的一致性
   - 使用 asyncio 进行并发操作

3. **错误处理**

   - 添加更详细的异常处理
   - 实现重试机制

4. **日志记录**

   - 为每个模块设置专门的日志记录器
   - 添加更详细的日志信息

5. **类型提示**
   - 为所有函数添加类型提示
   - 使用 mypy 进行类型检查

### 5. 测试策略

1. 为每个模块创建单元测试
2. 使用模拟对象测试 Telegram API 交互
3. 创建集成测试验证模块间交互

## 当前模块状态

✅ 已完成模块:
- 项目结构创建
- 配置模块
- 数据库模块
- 工具模块(media.py, mentions.py, logging.py)
- ForwardHandler处理器
- NewMessageHandler处理器
- EditDeleteHandler处理器
- ClientService实现 (包含健康检查)
- CleanupService实现
- 主模块整合

✅ 已完成测试:
- 消息处理流程测试
- 媒体文件加密/解密测试
- 数据库操作测试
- 服务健康检查测试

## 文档完善

### 新增配置项说明

1. **`MAX_IN_MEMORY_FILE_SIZE`**  
   - 类型: int (bytes)
   - 默认: 5 * 1024 * 1024 (5MB)
   - 描述: 内存中处理的最大文件大小，超过此大小的文件将被拒绝

2. **`FILE_PASSWORD`**  
   - 类型: str
   - 必填: 是
   - 描述: 用于加密/解密媒体文件的密码，修改后旧文件将无法解密

3. **`SESSION_NAME`**  
   - 类型: str (文件路径)
   - 默认: "db/user"
   - 描述: Telegram会话文件存储路径，包含登录状态等信息

4. **`PERSIST_TIME_IN_DAYS_*`**  
   - 类型: int (天数)
   - 描述: 控制各类消息的保留时长，包括:
     - `PERSIST_TIME_IN_DAYS_USER`: 用户消息
     - `PERSIST_TIME_IN_DAYS_CHANNEL`: 频道消息
     - `PERSIST_TIME_IN_DAYS_GROUP`: 群组消息
     - `PERSIST_TIME_IN_DAYS_BOT`: 机器人消息

### 已知问题

1. **大文件处理**  
   - 当前全内存处理方式对大文件不友好
   - 临时解决方案: 通过`MAX_IN_MEMORY_FILE_SIZE`限制文件大小
   - 计划优化: 实现流式处理减少内存占用

2. **媒体文件清理**  
   - 当前仅根据修改时间判断过期
   - 可能导致关联消息已删除但媒体文件仍保留
   - 计划优化: 结合数据库记录精确清理

3. **错误恢复**  
   - 转发处理器遇到错误后会跳过当前消息
   - 缺乏重试机制和错误队列
   - 计划优化: 实现指数退避重试和死信队列

4. **数据库性能**  
   - 高频消息场景下可能出现写入延迟
   - 计划优化: 实现批量写入和WAL模式

## 后续优化计划

### 配置说明

1. 必须配置项:
   - `API_ID` 和 `API_HASH`: Telegram API凭证
   - `SESSION_NAME`: 会话文件路径
   - `FILE_PASSWORD`: 媒体文件加密密码

2. 可选配置项:
   ```python
   # 消息保存期限(天)
   PERSIST_TIME_IN_DAYS_USER = 30  
   PERSIST_TIME_IN_DAYS_CHANNEL = 365
   
   # 功能开关
   SAVE_EDITED_MESSAGES = False
   DELETE_SENT_GIFS_FROM_SAVED = True
   ```

### 部署指南

1. 安装依赖:
   ```bash
   pip install -r requirements.txt
   ```

2. 复制配置文件:
   ```bash
   cp config.py.example config.py
   ```

3. 运行:
   ```bash
   python -m telegram_logger.main
   ```

4. 系统服务配置示例:
   ```ini
   [Unit]
   Description=Telegram Logger Service
   
   [Service]
   ExecStart=/usr/bin/python3 -m telegram_logger.main
   Restart=always
   ```

### 测试建议

1. 单元测试:
   ```bash
   pytest tests/ -v
   ```

2. 集成测试:
   - 验证消息处理全流程
   - 测试媒体文件加解密
   - 验证定时清理任务

### 后续优化计划

1. **性能优化**:
   - 实现媒体文件处理的内存优化
   - 添加数据库批量操作支持
   - 优化消息处理流水线

2. **稳定性增强**:
   - 完善错误处理和自动恢复机制
   - 添加服务健康检查API
   - 实现消息处理重试队列

3. **监控与运维**:
   - 添加Prometheus指标监控
   - 实现日志轮转和归档
   - 添加系统资源使用告警

4. **功能扩展**:
   - 支持消息内容搜索
   - 添加REST API接口
   - 实现Web管理界面

## 迁移注意事项

1. 主模块整合需要验证:
   - 所有handler是否正确注册
   - 服务是否正常启动
   - 依赖注入是否工作正常

2. 测试重点:
   - 消息处理全流程(接收、存储、转发)
   - 媒体文件加解密
   - 定时清理任务
   - 错误处理与恢复

3. 性能优化:
   - 数据库批量操作
   - 媒体文件处理并发控制
   - 内存使用监控

4. 文档更新:
   - 新API文档
   - 配置说明
   - 部署指南
