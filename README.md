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

编辑 `.env` 文件，填入必要的配置信息（参见[配置文件说明](#配置文件说明)）。**确保 `SESSION_NAME` 指向 `db/` 目录下的某个文件，例如 `db/user`**，这样会话文件会保存在挂载的卷中。

3. 创建必要的目录结构

```bash
mkdir -p files/{db,media,log}
```

4. **首次启动与交互式登录**

   **重要提示:** 首次运行或会话文件 (`.session`) 失效时，需要进行**交互式登录**以授权 Telegram 客户端。`docker compose up` 命令**不适用于**此交互过程。你需要使用 `docker compose run` 来完成首次登录。

   a. **拉取最新镜像:**
      ```bash
      docker compose pull
      ```

   b. **(可选) 清理旧会话:** 如果你不确定之前的会话状态，可以先删除旧的 `.session` 文件 (例如 `files/db/user.session`)，以确保进行全新的登录流程。
      ```bash
      # 示例：删除名为 user 的会话文件
      rm ./files/db/user.session
      ```

   c. **执行交互式登录:** 使用 `docker compose run` 启动一个临时容器，并将你的终端连接到它，以便输入登录信息。
      ```bash
      docker compose run --rm telegram-logger
      ```
      *   `--rm` 参数表示容器在退出后会自动删除。
      *   执行此命令后，终端会显示 Telethon 的登录提示。按照指示输入你的 **手机号码** (国际格式，例如 `+8612345678900`)、Telegram 发送给你的 **验证码**，以及可能的**两步验证密码**。

   d. **验证会话文件:** 登录成功后，检查你的本地 `./files/db/` 目录下是否已生成或更新了 `.session` 文件 (文件名基于你的 `SESSION_NAME` 配置，例如 `user.session`)。

5. **正常启动服务 (非首次)**

   完成首次交互式登录并生成 `.session` 文件后，你可以使用标准的 `docker compose up` 命令来启动服务。服务将使用已保存的会话文件自动登录。

   ```bash
   # 在后台启动服务
   docker compose up -d
   ```
   或者
   ```bash
   # 在前台启动服务并查看日志
   docker compose up
   ```

6. **其他常用命令**

   ```bash
   # 查看日志
   docker compose logs -f

   # 停止服务
   docker compose down

   # 更新镜像并重启
   docker compose pull
   docker compose up -d --force-recreate
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
SESSION_NAME=db/user # 会话文件路径，确保在 db 目录下

FILE_PASSWORD=文件加密密码
IGNORED_IDS=-10000  # 忽略的聊天ID，逗号分隔
FORWARD_USER_IDS=    # 要转发的用户ID，channelID(俗称皮套)，逗号分隔
FORWARD_GROUP_IDS=   # 要转发的群组ID，逗号分隔
FORWARDER_USE_MARKDOWN=False # 是否对转发的消息使用 Markdown 代码块格式 (True/False)

# 消息持久化时间（天）
PERSIST_TIME_IN_DAYS_USER=1
PERSIST_TIME_IN_DAYS_GROUP=1
PERSIST_TIME_IN_DAYS_CHANNEL=1
```

### 运行程序

```bash
python main.py
```

首次运行时，程序会在终端提示输入手机号和验证码。

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
├── db/          # 数据库文件和 session 文件
├── media/       # 媒体文件存储
└── log/         # 日志文件
```

### 数据持久化

Docker 配置中已设置以下目录映射：

- `files/db`: 存储数据库文件 (`messages.db`) 和 Telegram 会话文件 (例如 `user.session`)
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
    stdin_open: true # 允许交互式登录
    tty: true        # 分配伪终端
    env_file:
      - .env # 从 .env 文件加载环境变量
    environment:
      - TZ=Asia/Shanghai # 设置容器时区
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

