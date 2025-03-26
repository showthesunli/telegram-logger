# Telegram 消息日志系统

一个用于记录和管理 Telegram 消息的 Python 工具，支持消息存储、编辑删除跟踪、媒体处理和自动清理功能。

## 主要功能

- 📝 记录新消息、编辑和删除的消息
- 🔄 自动转发指定消息
- 🖼️ 支持媒体文件下载和加密存储
- 🗑️ 基于时间自动清理过期消息
- 🔒 数据库和文件加密存储
- ⚙️ 高度可配置的消息处理规则

## 前期准备

### 获取 Telegram API 凭证

1. 访问 [Telegram API 开发工具](https://my.telegram.org/apps)
2. 登录你的 Telegram 账号
3. 填写表单信息：
   - App title：随意填写，如 `My Logger`
   - Short name：随意填写，如 `mylogger`
   - Platform：选择 `Desktop`
   - Description：简单描述用途
4. 提交后，你将获得：
   - `api_id`：一串数字
   - `api_hash`：一串字母数字组合
5. 将这些值保存好，后续配置需要用到

> **⚠️ 注意：** API 凭证关系账号安全，请勿分享给他人

### 如何获取 ID

用户、channel、group 的 ID 可以从 @username_to_id_test_bot 这个机器人获取

> **⚠️ 注意：** 该机器人为第三方提供，不保证可用性。

## 快速开始

### 方式一：Docker Compose（推荐）

1. 克隆仓库

```bash
git clone https://github.com/your-repo/telegram-logger.git
cd telegram-logger
```

2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入必要的配置信息（参见[配置文件说明](#配置文件说明)）。

3. 创建必要的目录结构

```bash
mkdir -p files/{db,media,log}
```

4. 启动服务

```bash
# 拉取最新镜像并启动
docker compose pull
docker compose up -d

# 查看日志
docker compose logs -f

# 停止服务
docker compose down
```

### 方式二：本地安装

#### 环境要求

- Python 3.13+
- Telegram API 凭证 ([申请地址](https://my.telegram.org/))
- uv 包管理器 (`pip install uv`)

### 安装步骤

1. 克隆仓库

```bash
git clone https://github.com/your-repo/telegram-logger.git
cd telegram-logger
```

2. 安装依赖

```bash
# 使用 uv 同步依赖
uv pip sync

# 如果需要开发环境依赖，使用
uv pip sync --all
```

注意：项目使用 `uv.lock` 文件锁定依赖版本。如果需要更新依赖：

```bash
# 更新所有依赖到最新版本
uv pip compile pyproject.toml -o uv.lock

# 更新特定依赖
uv pip compile pyproject.toml -o uv.lock --upgrade-package telethon
```

3. 配置环境变量
   复制 `.env.example` 为 `.env` 并修改：

```bash
cp .env.example .env
```

### 配置文件说明

编辑 `.env` 文件：

```ini
API_ID=你的API_ID
API_HASH=你的API_HASH
LOG_CHAT_ID=日志频道ID

FILE_PASSWORD=文件加密密码
IGNORED_IDS=-10000  # 忽略的聊天ID，逗号分隔
FORWARD_USER_IDS=    # 要转发的用户ID，channelID(俗称皮套)，逗号分隔
FORWARD_GROUP_IDS=   # 要转发的群组ID，逗号分隔

# 消息持久化时间（天）
PERSIST_TIME_IN_DAYS_USER=1
PERSIST_TIME_IN_DAYS_GROUP=1
PERSIST_TIME_IN_DAYS_CHANNEL=1
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

## 开发指南

项目结构:

```
telegram_logger/
├── data/          # 数据库相关
├── handlers/      # 消息处理器
├── services/      # 核心服务
└── utils/         # 工具类
```

## Docker 部署说明

### 目录结构

```
files/
├── db/          # 数据库文件
├── media/       # 媒体文件存储
└── log/         # 日志文件
```

### 数据持久化

Docker 配置中已设置以下目录映射：

- `files/db`: 存储数据库文件
- `files/media`: 存储下载的媒体文件
- `files/log`: 存储日志文件

### Docker Compose 配置示例

```yaml
version: "3.8"

services:
  telegram-logger:
    image: ghcr.io/showthesunli/telegram-logger:latest
    container_name: telegram-logger
    restart: unless-stopped
    env_file:
      - .env
    environment:
      - TZ=Asia/Shanghai
    volumes:
      - ./files/db:/app/db:rw
      - ./files/media:/app/media:rw
      - ./files/log:/app/log:rw
    networks:
      - telegram-net

networks:
  telegram-net:
    driver: bridge
```

## 许可证

MIT License

