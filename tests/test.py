import os
import re
import logging
import tempfile # 用于创建临时文件
from dotenv import load_dotenv
from telethon import TelegramClient, events, errors

# --- 配置 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
SESSION_NAME = os.getenv("SESSION_NAME", "media_downloader_test")
LOG_CHAT_ID = os.getenv("LOG_CHAT_ID") # 从 .env 读取目标 LOG_CHAT_ID

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
link_pattern = re.compile(r'https://t\.me/(\w+|c/\d+)/(\d+)')

# --- Telethon 客户端 ---
# 使用 system_version='4.16.30-vxCUSTOM' 可能有助于处理某些限制，但通常不需要
client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)

@client.on(events.NewMessage(incoming=True))
async def handle_media_link(event):
    """监听新消息，查找 Telegram 链接，下载媒体并发送到 LOG_CHAT_ID"""
    message_text = event.message.text # 使用 .text 获取纯文本
    match = link_pattern.search(message_text)

    if not match:
        # logging.debug("消息不包含 Telegram 链接，已忽略。")
        return

    identifier = match.group(1) # username or c/channel_id
    message_id = int(match.group(2))
    sender_chat_id = event.chat_id # 用于回复处理结果

    logging.info(f"检测到来自 {sender_chat_id} 的链接: identifier={identifier}, message_id={message_id}")

    downloaded_file_path = None # 初始化下载路径变量
    try:
        # 1. 获取源 Chat Entity
        logging.info(f"尝试获取源实体: {identifier}")
        source_entity = await client.get_entity(identifier)
        source_entity_title = getattr(source_entity, 'title', getattr(source_entity, 'username', identifier))
        logging.info(f"成功获取源实体: {source_entity_title}")

        # 2. 获取源消息
        logging.info(f"尝试获取消息 ID: {message_id} 从 {source_entity_title}")
        source_messages = await client.get_messages(source_entity, ids=message_id)

        if not source_messages:
            logging.warning(f"找不到消息 ID {message_id} 在 {source_entity_title}")
            await event.reply(f"错误：在源 '{source_entity_title}' 中找不到消息 ID {message_id}。")
            return

        source_message = source_messages # get_messages with single ID returns the message itself

        # 3. 检查是否有媒体
        if not source_message.media:
            logging.info(f"消息 {message_id} 不包含媒体文件。")
            await event.reply(f"提示：链接指向的消息 {message_id} 不包含媒体文件。")
            return

        media_type = type(source_message.media).__name__
        logging.info(f"消息 {message_id} 包含媒体，类型: {media_type}")

        # 4. 获取目标 Chat Entity (LOG_CHAT_ID)
        logging.info(f"尝试获取目标日志实体: {LOG_CHAT_ID}")
        try:
            target_entity = await client.get_entity(LOG_CHAT_ID)
            target_entity_title = getattr(target_entity, 'title', getattr(target_entity, 'username', LOG_CHAT_ID))
            logging.info(f"成功获取目标日志实体: {target_entity_title}")
        except (ValueError, TypeError) as e:
             logging.error(f"无法解析配置的 LOG_CHAT_ID '{LOG_CHAT_ID}': {e}")
             await event.reply(f"错误：配置的 LOG_CHAT_ID ('{LOG_CHAT_ID}') 无效或无法访问。请检查 .env 文件。")
             return
        except Exception as e:
            logging.error(f"获取目标日志实体时发生意外错误: {e}")
            await event.reply(f"错误：无法访问目标日志频道 '{LOG_CHAT_ID}'。")
            return


        # 5. 下载媒体文件
        logging.info(f"尝试下载消息 {message_id} 的媒体...")
        # 使用 download_media 方法，它能处理受限内容的下载（如果账号有权限查看）
        # 它会返回下载文件的路径
        # 使用 tempfile 确保临时文件被妥善处理
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
             downloaded_file_path = await client.download_media(
                 source_message.media,
                 file=tmp_file.name # 指定下载路径
             )
             # 注意：此时文件可能还未完全写入磁盘，但在 await 后完成

        if not downloaded_file_path or not os.path.exists(downloaded_file_path):
             logging.error(f"下载媒体失败，未找到文件路径或文件不存在。")
             # 尝试给出更具体的错误原因
             if isinstance(source_message.media, (getattr(errors, 'MediaUnavailableError', type(None)), getattr(errors, 'WebpageMediaEmptyError', type(None)))):
                 await event.reply(f"错误：无法下载该媒体。源频道可能开启了严格的内容保护，禁止了媒体的下载，或者媒体本身已不可用。")
             else:
                 await event.reply(f"错误：下载媒体文件失败。")
             return # 停止执行

        logging.info(f"媒体已成功下载到临时文件: {downloaded_file_path}")

        # 6. 发送（上传）媒体到目标频道 (LOG_CHAT_ID)
        logging.info(f"尝试将下载的媒体发送到 {target_entity_title}")
        caption = f"媒体来源: {source_entity_title} / {message_id}\n原始链接: https://t.me/{identifier}/{message_id}"

        await client.send_file(
            target_entity,
            downloaded_file_path,
            caption=caption,
            # 对于视频和动图，尝试保留一些属性
            supports_streaming=getattr(source_message.media, 'supports_streaming', False),
            # duration=getattr(source_message.media, 'duration', None), # 可能需要更复杂的属性提取
            # width=getattr(source_message.media, 'width', None),
            # height=getattr(source_message.media, 'height', None),
        )

        logging.info(f"成功将媒体从消息 {message_id} 发送到 {target_entity_title}")
        await event.reply(f"成功将链接指向的媒体发送到日志频道 '{target_entity_title}'。")

    except errors.FloodWaitError as e:
         logging.error(f"触发 Telegram Flood Wait: 需等待 {e.seconds} 秒")
         await event.reply(f"错误：操作过于频繁，请等待 {e.seconds} 秒后再试。")
    except (errors.ChannelPrivateError, errors.ChatForbiddenError):
         logging.error(f"无法访问源频道/群组 '{identifier}'，可能是私有的、你不在其中或已被禁止访问。")
         await event.reply(f"错误：无法访问源 '{identifier}'。它可能是私有的，你没有加入，或者我被禁止访问。")
    except errors.ChatAdminRequiredError:
         # 这个错误理论上应该在获取 target_entity 时或发送时捕获
         logging.error(f"没有权限向目标频道 '{LOG_CHAT_ID}' 发送消息。")
         await event.reply(f"错误：我没有权限向目标日志频道 '{target_entity_title}' 发送消息。请检查我是不是成员并且有发送媒体的权限。")
    except errors.UserNotParticipantError:
         logging.error(f"运行脚本的账户不是源频道/群组 '{identifier}' 的成员。")
         await event.reply(f"错误：我需要先加入源 '{identifier}' 才能访问其消息。")
    except errors.MediaUnavailableError:
         # 这个错误可能在 get_messages 或 download_media 时发生
         logging.error(f"无法访问或下载来自消息 {message_id} 的媒体。可能是源频道开启了严格的内容保护，或媒体已过期/删除。")
         await event.reply(f"错误：无法获取或下载该媒体。源频道可能开启了严格的内容保护，禁止了媒体的保存和转发，或者媒体本身已不可用。")
    except (ValueError, TypeError) as e:
        # 通常是 get_entity 失败或 ID 格式错误
        logging.error(f"无法解析标识符 '{identifier}' 或 '{LOG_CHAT_ID}': {e}")
        await event.reply(f"错误：无法找到源或目标。请检查链接和 LOG_CHAT_ID 是否正确。({e})")
    except Exception as e:
        logging.exception(f"处理链接时发生未知错误: {e}") # 使用 exception 记录堆栈跟踪
        await event.reply(f"处理链接时发生未知错误: {e}")
    finally:
        # 清理下载的临时文件
        if downloaded_file_path and os.path.exists(downloaded_file_path):
            try:
                os.remove(downloaded_file_path)
                logging.info(f"已删除临时文件: {downloaded_file_path}")
            except OSError as e:
                logging.error(f"删除临时文件 {downloaded_file_path} 时出错: {e}")


async def main():
    """主函数，启动客户端并保持运行"""
    logging.info("媒体下载转发脚本启动...")
    logging.info(f"将尝试把链接中的媒体下载并发送到日志频道: {LOG_CHAT_ID}")

    await client.start()
    logging.info("客户端已连接并登录。")

    # 预先检查是否能访问 LOG_CHAT_ID
    try:
        await client.get_entity(LOG_CHAT_ID)
        logging.info(f"成功验证可以访问目标日志频道: {LOG_CHAT_ID}")
    except Exception as e:
        logging.error(f"无法访问配置的目标 LOG_CHAT_ID ('{LOG_CHAT_ID}'): {e}")
        logging.error("请检查 LOG_CHAT_ID 是否正确，以及该账号是否有权访问。脚本将继续运行，但发送会失败。")

    logging.info("等待包含 Telegram 消息链接的新消息...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    client.loop.run_until_complete(main())
