import os
import re
import logging
from dotenv import load_dotenv
from telethon import TelegramClient, events, errors
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

# --- 配置 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
SESSION_NAME = os.getenv("SESSION_NAME", "media_forwarder")
TARGET_CHANNEL_ID = os.getenv("TARGET_CHANNEL_ID") # 可以是 ID (int) 或 username (str)

if not all([API_ID, API_HASH, TARGET_CHANNEL_ID]):
    logging.error("请确保 .env 文件中设置了 API_ID, API_HASH, 和 TARGET_CHANNEL_ID")
    exit(1)

try:
    # 尝试将 TARGET_CHANNEL_ID 转换为整数，如果失败则保持为字符串 (username)
    TARGET_CHANNEL_ID = int(TARGET_CHANNEL_ID)
except ValueError:
    logging.info(f"目标频道 ID '{TARGET_CHANNEL_ID}' 不是数字，将作为 username 处理。")

# 正则表达式匹配 Telegram 消息链接
# 支持 t.me/username/123 和 t.me/c/123456789/123 格式
link_pattern = re.compile(r'https://t\.me/(\w+|c/\d+)/(\d+)')

# --- Telethon 客户端 ---
client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)

@client.on(events.NewMessage(incoming=True))
async def handle_link(event):
    message_text = event.message.message
    match = link_pattern.search(message_text)

    if not match:
        # 如果消息不包含链接，则忽略
        return

    identifier = match.group(1)
    message_id = int(match.group(2))
    sender_chat_id = event.chat_id # 记录是谁发送了链接

    logging.info(f"检测到链接: identifier={identifier}, message_id={message_id}")

    try:
        # 1. 获取源 Chat Entity
        logging.info(f"尝试获取源实体: {identifier}")
        source_entity = await client.get_entity(identifier)
        logging.info(f"成功获取源实体: {getattr(source_entity, 'title', identifier)}")

        # 2. 获取源消息
        logging.info(f"尝试获取消息 ID: {message_id} 从 {getattr(source_entity, 'title', identifier)}")
        # 使用 get_messages 比 GetMessagesRequest 更常用且简单
        source_message = await client.get_messages(source_entity, ids=message_id)

        if not source_message:
            logging.warning(f"找不到消息 ID {message_id} 在 {getattr(source_entity, 'title', identifier)}")
            await client.send_message(sender_chat_id, f"错误：在源频道/群组中找不到消息 ID {message_id}。")
            return

        if not source_message.media:
            logging.info(f"消息 {message_id} 不包含媒体文件。")
            await client.send_message(sender_chat_id, f"提示：链接指向的消息 {message_id} 不包含媒体文件。")
            return

        logging.info(f"消息 {message_id} 包含媒体，类型: {type(source_message.media)}")

        # 3. 获取目标 Chat Entity
        logging.info(f"尝试获取目标实体: {TARGET_CHANNEL_ID}")
        target_entity = await client.get_entity(TARGET_CHANNEL_ID)
        logging.info(f"成功获取目标实体: {getattr(target_entity, 'title', TARGET_CHANNEL_ID)}")

        # 4. 发送媒体到目标频道
        logging.info(f"尝试将媒体从消息 {message_id} 发送到 {getattr(target_entity, 'title', TARGET_CHANNEL_ID)}")

        # 尝试直接使用 source_message.media 发送
        # Telethon 会处理文件引用或必要的后台传输
        await client.send_file(
            target_entity,
            source_message.media,
            caption=f"媒体来自: {getattr(source_entity, 'title', identifier)}/{message_id}" # 可选：添加说明
        )

        logging.info(f"成功将媒体从消息 {message_id} 发送到 {getattr(target_entity, 'title', TARGET_CHANNEL_ID)}")
        await client.send_message(sender_chat_id, f"成功将链接指向的媒体发送到目标频道。")

    except errors.FloodWaitError as e:
         logging.error(f"触发 Telegram Flood Wait: 需等待 {e.seconds} 秒")
         await client.send_message(sender_chat_id, f"错误：操作过于频繁，请等待 {e.seconds} 秒后再试。")
    except errors.ChannelPrivateError:
         logging.error(f"无法访问源频道/群组 '{identifier}'，可能是私有的或需要邀请。")
         await client.send_message(sender_chat_id, f"错误：无法访问源频道/群组 '{identifier}'，它可能是私有的，或者我没有加入。")
    except errors.ChatAdminRequiredError:
         logging.error(f"没有权限向目标频道 '{TARGET_CHANNEL_ID}' 发送消息。")
         await client.send_message(sender_chat_id, f"错误：我没有权限向目标频道发送消息。请检查我是不是成员并且有发送媒体的权限。")
    except errors.UserNotParticipantError:
         logging.error(f"运行脚本的账户不是源频道/群组 '{identifier}' 的成员。")
         await client.send_message(sender_chat_id, f"错误：我需要先加入源频道/群组 '{identifier}' 才能访问其消息。")
    except errors.MediaUnavailableError:
         logging.error(f"无法访问或发送来自消息 {message_id} 的媒体。可能是源频道开启了严格的内容保护。")
         await client.send_message(sender_chat_id, f"错误：无法获取或发送该媒体。源频道可能开启了严格的内容保护，禁止了媒体的保存和转发。")
    except ValueError as e:
        # 通常是 get_entity 失败
        logging.error(f"无法解析标识符 '{identifier}' 或 '{TARGET_CHANNEL_ID}': {e}")
        await client.send_message(sender_chat_id, f"错误：无法找到源或目标频道/群组。请检查链接和 TARGET_CHANNEL_ID 是否正确。({e})")
    except Exception as e:
        logging.exception(f"处理链接时发生未知错误: {e}") # 使用 exception 记录堆栈跟踪
        await client.send_message(sender_chat_id, f"处理链接时发生未知错误: {e}")


async def main():
    logging.info("脚本启动...")
    logging.info(f"将尝试把链接中的媒体转发到: {TARGET_CHANNEL_ID}")
    await client.start()
    logging.info("客户端已连接并登录。")
    logging.info("等待包含 Telegram 消息链接的新消息...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    client.loop.run_until_complete(main())
