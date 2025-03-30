import os
import re
import logging

# import tempfile  # 不再需要显式下载到临时文件
from dotenv import load_dotenv
from telethon import TelegramClient, events, errors

# --- 配置 ---
# 将基础日志级别设置为 DEBUG，并为 telethon logger 也设置 DEBUG
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s') # 原配置
logging.basicConfig(
    level=logging.INFO,  # 设置为 DEBUG
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)  # 添加 logger 名称

# 可选：如果你只想看 Telethon 的 DEBUG 日志，而保持你自己的代码为 INFO
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# logging.getLogger('telethon').setLevel(logging.DEBUG)

load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
SESSION_NAME = os.getenv("SESSION_NAME", "media_downloader_test")
LOG_CHAT_ID = os.getenv("LOG_CHAT_ID")  # 从 .env 读取目标 LOG_CHAT_ID

if not all([API_ID, API_HASH, LOG_CHAT_ID]):
    logging.error("请确保 .env 文件中设置了 API_ID, API_HASH, 和 LOG_CHAT_ID")
    exit(1)

try:
    # 尝试将 LOG_CHAT_ID 转换为整数，如果失败则保持为字符串 (username)
    LOG_CHAT_ID = int(LOG_CHAT_ID)
    logging.info(f"日志频道 ID '{LOG_CHAT_ID}' 将作为数字 ID 处理。")
except ValueError:
    logging.info(f"日志频道 ID '{LOG_CHAT_ID}' 不是数字，将作为 username 处理。")

# 正则表达式匹配 Telegram 消息链接
# 支持 t.me/username/123 和 t.me/c/123456789/123 格式
link_pattern = re.compile(r"https://t\.me/(\w+|c/\d+)/(\d+)")

# --- Telethon 客户端 ---
# 使用 system_version='4.16.30-vxCUSTOM' 可能有助于处理某些限制，但通常不需要
client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)

# 新增：从 .env 读取测试链接
TEST_MESSAGE_LINK = os.getenv("TEST_MESSAGE_LINK")


async def process_message_link(link: str):
    """处理单个 Telegram 消息链接，下载媒体并发送到 LOG_CHAT_ID"""
    match = link_pattern.search(link)

    if not match:
        logging.error(f"提供的链接格式无效: {link}")
        return False  # 表示处理失败

    identifier = match.group(1)  # username or c/channel_id
    message_id = int(match.group(2))

    logging.info(f"开始处理链接: identifier={identifier}, message_id={message_id}")

    # downloaded_file_path = None  # 不再需要
    success = False  # 标记处理是否成功
    try:
        # 1. 获取源 Chat Entity
        logging.info(f"尝试获取源实体: {identifier}")
        source_entity = await client.get_entity(identifier)
        source_entity_title = getattr(
            source_entity, "title", getattr(source_entity, "username", identifier)
        )
        logging.info(f"成功获取源实体: {source_entity_title}")

        # 2. 获取源消息
        logging.info(f"尝试获取消息 ID: {message_id} 从 {source_entity_title}")
        source_messages = await client.get_messages(source_entity, ids=message_id)

        if not source_messages:
            logging.warning(f"找不到消息 ID {message_id} 在 {source_entity_title}")
            # await event.reply(f"错误：在源 '{source_entity_title}' 中找不到消息 ID {message_id}。") # 不再回复事件
            return False

        source_message = (
            source_messages  # get_messages with single ID returns the message itself
        )

        # 3. 检查是否有媒体
        if not source_message.media:
            logging.info(f"消息 {message_id} 不包含媒体文件。")
            # await event.reply(f"提示：链接指向的消息 {message_id} 不包含媒体文件。") # 不再回复事件
            return False  # 可以认为这不是我们想要处理的情况

        media_type = type(source_message.media).__name__
        logging.info(f"消息 {message_id} 包含媒体，类型: {media_type}")

        # 4. 获取目标 Chat Entity (LOG_CHAT_ID)
        logging.info(f"尝试获取目标日志实体: {LOG_CHAT_ID}")
        try:
            target_entity = await client.get_entity(LOG_CHAT_ID)
            target_entity_title = getattr(
                target_entity, "title", getattr(target_entity, "username", LOG_CHAT_ID)
            )
            logging.info(f"成功获取目标日志实体: {target_entity_title}")
        except (ValueError, TypeError) as e:
            logging.error(f"无法解析配置的 LOG_CHAT_ID '{LOG_CHAT_ID}': {e}")
            # await event.reply(f"错误：配置的 LOG_CHAT_ID ('{LOG_CHAT_ID}') 无效或无法访问。请检查 .env 文件。") # 不再回复事件
            return False
        except Exception as e:
            logging.error(f"获取目标日志实体时发生意外错误: {e}")
            # await event.reply(f"错误：无法访问目标日志频道 '{LOG_CHAT_ID}'。") # 不再回复事件
            return False

        # 5. 直接尝试发送媒体对象，而不是下载
        logging.info(f"尝试直接发送消息 {message_id} 的媒体到 {target_entity_title}")
        caption = f"媒体来源: {source_entity_title} / {message_id}\n原始链接: https://t.me/{identifier}/{message_id}"

        # 直接发送媒体文件到目标聊天
        await client.send_file(
            target_entity,
            file=source_message.media,
            caption=f"媒体来源: {source_entity_title} (消息ID: {message_id})\n原始链接: https://t.me/{identifier}/{message_id}"
        )

        logging.info(f"成功将媒体从消息 {message_id} 发送到 {target_entity_title}")
        # await event.reply(f"成功将链接指向的媒体发送到日志频道 '{target_entity_title}'。") # 不再回复
        success = True  # 标记成功

    except errors.FloodWaitError as e:
        logging.error(f"触发 Telegram Flood Wait: 需等待 {e.seconds} 秒")
        # await event.reply(f"错误：操作过于频繁，请等待 {e.seconds} 秒后再试。") # 不再回复
    except (errors.ChannelPrivateError, errors.ChatForbiddenError):
        logging.error(
            f"无法访问源频道/群组 '{identifier}'，可能是私有的、你不在其中或已被禁止访问。"
        )
        # await event.reply(f"错误：无法访问源 '{identifier}'。它可能是私有的，你没有加入，或者我被禁止访问。") # 不再回复
    except errors.ChatAdminRequiredError:
        # 这个错误理论上应该在获取 target_entity 时或发送时捕获
        logging.error(f"没有权限向目标频道 '{LOG_CHAT_ID}' 发送消息。")
        # await event.reply(f"错误：我没有权限向目标日志频道 '{target_entity_title}' 发送消息。请检查我是不是成员并且有发送媒体的权限。") # 不再回复
    except errors.UserNotParticipantError:
        logging.error(f"运行脚本的账户不是源频道/群组 '{identifier}' 的成员。")
        # await event.reply(f"错误：我需要先加入源 '{identifier}' 才能访问其消息。") # 不再回复
    except errors.MediaUnavailableError:
        # 这个错误现在更可能在 send_file 时发生 (如果直接引用失败且无法下载)
        logging.error(
            f"无法访问或发送来自消息 {message_id} 的媒体。可能是源频道开启了严格的内容保护，或媒体已过期/删除。"
        )
        # await event.reply(f"错误：无法获取或发送该媒体。源频道可能开启了严格的内容保护，禁止了媒体的保存和转发，或者媒体本身已不可用。") # 不再回复
    except (ValueError, TypeError) as e:
        # 通常是 get_entity 失败或 ID 格式错误
        logging.error(f"无法解析标识符 '{identifier}' 或 '{LOG_CHAT_ID}': {e}")
        # await event.reply(f"错误：无法找到源或目标。请检查链接和 LOG_CHAT_ID 是否正确。({e})") # 不再回复
    except Exception as e:
        logging.exception(f"处理链接时发生未知错误: {e}")  # 使用 exception 记录堆栈跟踪
        # await event.reply(f"处理链接时发生未知错误: {e}") # 不再回复
    finally:
        # 不再需要清理临时文件
        # if downloaded_file_path and os.path.exists(downloaded_file_path):
        #     try:
        #         os.remove(downloaded_file_path)
        #         logging.info(f"已删除临时文件: {downloaded_file_path}")
        #     except OSError as e:
        #         logging.error(f"删除临时文件 {downloaded_file_path} 时出错: {e}")
        return success  # 返回处理结果


async def main():
    """主函数，启动客户端，处理配置的链接，然后退出"""
    logging.info("媒体下载转发脚本（单次运行模式）启动...")

    if not TEST_MESSAGE_LINK:
        logging.error("错误：未在 .env 文件中配置 TEST_MESSAGE_LINK。")
        return

    logging.info(f"目标处理链接: {TEST_MESSAGE_LINK}")
    logging.info(f"媒体将发送到日志频道: {LOG_CHAT_ID}")

    async with client:  # 使用 async with 确保客户端正确关闭
        logging.info("客户端连接中...")
        # start() 会自动处理登录
        await client.start()
        logging.info("客户端已连接并登录。")

        # 预先检查是否能访问 LOG_CHAT_ID
        try:
            await client.get_entity(LOG_CHAT_ID)
            logging.info(f"成功验证可以访问目标日志频道: {LOG_CHAT_ID}")
        except Exception as e:
            logging.error(f"无法访问配置的目标 LOG_CHAT_ID ('{LOG_CHAT_ID}'): {e}")
            logging.error(
                "请检查 LOG_CHAT_ID 是否正确，以及该账号是否有权访问。脚本将退出。"
            )
            return  # 无法访问目标，直接退出

        # 处理配置的链接
        logging.info(f"开始处理配置的链接: {TEST_MESSAGE_LINK}")
        success = await process_message_link(TEST_MESSAGE_LINK)

        if success:
            logging.info("链接处理成功完成。")
        else:
            logging.error("链接处理失败。请检查日志获取详细信息。")

    logging.info("脚本执行完毕，客户端已断开连接。")


if __name__ == "__main__":
    # 使用 client.loop.run_until_complete 运行 main coroutine
    client.loop.run_until_complete(main())
