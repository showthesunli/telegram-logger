# Telegram 消息日志系统

一个用于记录和管理 Telegram 消息的 Python 工具，支持消息存储、编辑删除跟踪、媒体处理和自动清理功能。

## 主要功能

- 📝 记录新消息、编辑和删除的消息
- 🔄 自动转发指定消息
- 🖼️ 支持媒体文件下载和加密存储
- 🗑️ 基于时间自动清理过期消息
- 🔒 数据库和文件加密存储
- ⚙️ 高度可配置的消息处理规则

## 快速开始

### 环境要求
- Python 3.8+
- Telegram API 凭证 ([申请地址](https://my.telegram.org/))

### 安装步骤
1. 克隆仓库
```bash
git clone https://github.com/your-repo/telegram-logger.git
cd telegram-logger
```

2. 安装依赖
```bash
pip install -r requirements.txt
```

3. 配置环境变量
复制 `.env.example` 为 `.env` 并修改：
```bash
copy .env.example .env
```

### 配置文件说明
编辑 `.env` 文件：
```ini
# 必填项
API_ID=你的API_ID
API_HASH=你的API_HASH
LOG_CHAT_ID=日志频道ID

# 可选配置
FILE_PASSWORD=文件加密密码
IGNORED_IDS=-10000  # 忽略的聊天ID，逗号分隔
FORWARD_USER_IDS=    # 要转发的用户ID，逗号分隔 
FORWARD_GROUP_IDS=   # 要转发的群组ID，逗号分隔

# 消息保留时间(天)
PERSIST_TIME_IN_DAYS_USER=7
PERSIST_TIME_IN_DAYS_GROUP=30
PERSIST_TIME_IN_DAYS_CHANNEL=30
```

### 运行程序
```bash
python main.py
```

## 高级配置

### 消息转发设置
- `FORWARD_MEDIA=True` 是否转发媒体
- `FORWARD_EDITED=True` 是否转发编辑的消息  
- `ADD_FORWARD_SOURCE=True` 是否添加转发来源

### 文件设置
- `MAX_IN_MEMORY_FILE_SIZE=5242880` 内存中处理的最大文件大小(5MB)
- `FILE_PASSWORD` 用于加密存储的媒体文件

## 常见问题

**Q: 如何获取 LOG_CHAT_ID?**  
A: 转发一条消息到 @username_to_id_bot 获取频道ID

**Q: 为什么收不到转发消息?**  
检查:
1. 机器人是否有发送消息权限
2. 目标频道是否已添加机器人为管理员

## 开发指南

项目结构:
```
telegram_logger/
├── data/          # 数据库相关
├── handlers/      # 消息处理器
├── services/      # 核心服务
└── utils/         # 工具类
```

## 许可证
MIT License
