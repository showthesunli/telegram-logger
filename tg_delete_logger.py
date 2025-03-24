#!/usr/bin/env python3

import logging
import pickle
import sqlite3
import asyncio
from datetime import datetime, timedelta
from typing import List, Union
import os
import re
from asyncio.locks import Event
from contextlib import contextmanager

from telethon import events

from telethon.events import NewMessage, MessageDeleted, MessageEdited
from telethon import TelegramClient
from telethon.hints import Entity
from telethon.tl.functions.messages import SaveGifRequest, SaveRecentStickerRequest
from telethon.tl.types import (
    DocumentAttributeFilename,
    Message,
    PeerUser,
    PeerChat,
    PeerChannel,
    Channel,
    Chat,
    DocumentAttributeSticker,
    DocumentAttributeVideo,
    MessageMediaDice,
    MessageMediaWebPage,
    MessageMediaGame,
    Document,
    InputDocument,
    DocumentAttributeAnimated,
    MessageMediaPhoto,
    MessageMediaContact,
    MessageMediaGeo,
    MessageMediaPoll,
    Photo,
    Contact,
    UpdateReadMessagesContents,
)
import config
import file_encrypt

logging.basicConfig(
    level=logging.INFO,  # 设置日志级别为 INFO
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

TYPE_USER = 1
TYPE_CHANNEL = 2
TYPE_GROUP = 3
TYPE_BOT = 4
TYPE_UNKNOWN = 0

client = TelegramClient("db/user", config.API_ID, config.API_HASH)
my_id = -1
sqlite_cursor: sqlite3.Cursor = None
sqlite_connection: sqlite3.Connection = None


def init_db():
    if not os.path.exists("db"):
        os.mkdir("db")
    if not os.path.exists("media"):
        os.mkdir("media")

    connection = sqlite3.connect("db/messages.db")
    cursor = connection.cursor()
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER, from_id INTEGER, chat_id INTEGER,
                  type INTEGER, msg_text TEXT, media BLOB, noforwards INTEGER DEFAULT 0, self_destructing INTEGER DEFAULT 0, created_time TIMESTAMP, edited_time TIMESTAMP,
                  PRIMARY KEY (chat_id, id, edited_time))"""
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS messages_created_index ON messages (created_time DESC)"
    )

    connection.commit()

    return cursor, connection


async def get_chat_type(event: Event) -> int:
    chat_type = TYPE_UNKNOWN
    if event.is_group:  # chats and megagroups
        chat_type = TYPE_GROUP
    elif event.is_channel:  # megagroups and channels
        chat_type = TYPE_CHANNEL
    elif event.is_private:
        if (await event.get_sender()).bot:
            chat_type = TYPE_BOT
        else:
            chat_type = TYPE_USER
    return chat_type


async def new_message_handler(event: Union[NewMessage.Event, MessageEdited.Event]):
    chat_id = event.chat_id
    from_id = get_sender_id(event.message)
    msg_id = event.message.id

    if (
        chat_id == config.LOG_CHAT_ID
        and from_id == my_id
        and event.message.text
        and (
            re.match(r"^(https:\/\/)?t\.me\/(?:c\/)?[\d\w]+\/[\d]+", event.message.text)
            or re.match(
                r"^tg:\/\/openmessage\?user_id=\d+&message_id=\d+", event.message.text
            )
        )
    ):
        msg_links = re.findall(
            r"(?:https:\/\/)?t\.me\/(?:c\/)?[\d\w]+\/[\d]+", event.message.text
        )
        if not msg_links:
            msg_links = re.findall(
                r"tg:\/\/openmessage\?user_id=\d+&message_id=\d+", event.message.text
            )
        if msg_links:
            for msg_link in msg_links:
                await save_restricted_msg(msg_link)
            return

    if from_id in config.IGNORED_IDS or chat_id in config.IGNORED_IDS:
        return

    edited_time = 0
    noforwards = False
    self_destructing = False

    try:
        noforwards = event.chat.noforwards is True
    except (
        AttributeError
    ):  # AttributeError: 'User' object has no attribute 'noforwards'
        noforwards = event.message.noforwards is True

    # noforwards = False  # wtf why does it work now?

    try:
        if event.message.media.ttl_seconds:
            self_destructing = True
    except AttributeError:
        pass

    if event.message.media or (noforwards or self_destructing):
        await save_media_as_file(event.message)

    async with asyncio.Lock():
        if isinstance(event, MessageEdited.Event):
            edited_time = datetime.now()  # event.message.edit_date
            await edited_deleted_handler(event)

        sqlite_cursor.execute(
            "INSERT INTO messages (id, from_id, chat_id, edited_time, type, msg_text, media, noforwards, self_destructing, created_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                msg_id,
                from_id,
                chat_id,
                edited_time,
                await get_chat_type(event),
                event.message.message,
                sqlite3.Binary(pickle.dumps(event.message.media)),
                int(noforwards),
                int(self_destructing),
                datetime.now(),
            ),
        )
        sqlite_connection.commit()


def get_sender_id(message) -> int:
    from_id = 0
    if isinstance(message.peer_id, PeerUser):
        from_id = my_id if message.out else message.peer_id.user_id
    elif isinstance(message.peer_id, PeerChannel):
        if isinstance(message.from_id, PeerUser):
            from_id = message.from_id.user_id
        if isinstance(message.from_id, PeerChannel):
            from_id = message.from_id.channel_id
    elif isinstance(message.peer_id, PeerChat):
        if isinstance(message.from_id, PeerUser):
            from_id = message.from_id.user_id
        if isinstance(message.from_id, PeerChannel):
            from_id = message.from_id.channel_id

    return from_id


def load_messages_from_event(
    event: Union[MessageDeleted.Event, MessageEdited.Event, UpdateReadMessagesContents],
) -> List[Message]:
    if isinstance(event, MessageDeleted.Event):
        ids = event.deleted_ids[: config.RATE_LIMIT_NUM_MESSAGES]
    if isinstance(event, UpdateReadMessagesContents):
        ids = event.messages[: config.RATE_LIMIT_NUM_MESSAGES]
    elif isinstance(event, MessageEdited.Event):
        ids = [event.message.id]

    sql_message_ids = ",".join(str(deleted_id) for deleted_id in ids)
    if hasattr(event, "chat_id") and event.chat_id:
        where_clause = f"WHERE chat_id = {event.chat_id} and id IN ({sql_message_ids})"
    else:
        where_clause = f'WHERE chat_id not like "-100%" and id IN ({sql_message_ids})'
    query = f"""SELECT * FROM (SELECT id, from_id, chat_id, msg_text, media, noforwards, self_destructing,
            created_time, type FROM messages {where_clause} ORDER BY edited_time DESC)
            GROUP BY chat_id, id ORDER BY created_time ASC"""

    db_results = sqlite_cursor.execute(query).fetchall()

    messages = []
    for db_result in db_results:
        # skip read messages which are not self-destructing
        if isinstance(event, UpdateReadMessagesContents) and not db_result[6]:
            continue

        messages.append(
            {
                "id": db_result[0],
                "from_id": db_result[1],
                "chat_id": db_result[2],
                "msg_text": db_result[3],
                "media": pickle.loads(db_result[4]),
                "noforwards": db_result[5],
                "self_destructing": db_result[6],
                "type": db_result[8],  # 添加类型信息
            }
        )

    return messages


async def create_mention(entity_id, chat_msg_id: int = None) -> str:
    if chat_msg_id is None:
        msg_id = 1
    else:
        msg_id = chat_msg_id

    if entity_id == 0:
        return "Unknown"

    try:
        entity: Entity = await client.get_entity(entity_id)

        if isinstance(entity, (Channel, Chat)):
            name = entity.title
            chat_id = str(entity_id).replace("-100", "")
            mention = f"[{name}](t.me/c/{chat_id}/{msg_id})"
        else:
            if entity.first_name:
                is_pm = chat_msg_id is not None
                name = (entity.first_name + " " if entity.first_name else "") + (
                    entity.last_name if entity.last_name else ""
                )

                mention = f"[{name}](tg://user?id={entity.id})" + (
                    " #pm" if is_pm else ""
                )
            elif entity.username:
                mention = f"[@{entity.username}](t.me/{entity.username})"
            elif entity.phone:
                mention = entity.phone
            else:
                mention = entity.id
    except Exception as e:
        logging.warning(e)
        mention = str(entity_id)

    return mention


async def edited_deleted_handler(
    event: Union[MessageDeleted.Event, MessageEdited.Event, UpdateReadMessagesContents],
):
    if (
        not isinstance(event, MessageDeleted.Event)
        and not isinstance(event, MessageEdited.Event)
        and not isinstance(event, UpdateReadMessagesContents)
    ):
        return

    if isinstance(event, MessageEdited.Event) and not config.SAVE_EDITED_MESSAGES:
        return

    messages = load_messages_from_event(event)
    log_deleted_sender_ids = []

    for message in messages:
        if (
            message["from_id"] in config.IGNORED_IDS
            or message["chat_id"] in config.IGNORED_IDS
        ):
            return

        # 检查消息类型，如果是机器人消息则跳过
        chat_type = message.get("type", TYPE_UNKNOWN)  # 从数据库记录中获取类型
        if chat_type == TYPE_BOT:
            logging.info(f"跳过机器人消息 - 发送者ID: {message['from_id']}")
            continue

        mention_sender = await create_mention(message["from_id"])
        mention_chat = await create_mention(message["chat_id"], message["id"])

        log_deleted_sender_ids.append(message["from_id"])

        if isinstance(event, MessageDeleted.Event) or isinstance(
            event, UpdateReadMessagesContents
        ):
            if isinstance(event, MessageDeleted.Event):
                text = f"**Deleted message from: **{mention_sender}\n"
            if isinstance(event, UpdateReadMessagesContents):
                text = f"**Deleted #selfdestructing message from: **{mention_sender}\n"

            text += f"in {mention_chat}\n"

            if message["msg_text"]:
                text += "**Message:** \n" + message["msg_text"]
        elif isinstance(event, MessageEdited.Event):
            text = f"**✏Edited message from: **{mention_sender}\n"

            text += f"in {mention_chat}\n"

            if message["msg_text"]:
                text += f"**Original message:**\n{message['msg_text']}\n\n"
            if event.message.text:
                text += f"**Edited message:**\n{event.message.text}"

        is_sticker = (
            hasattr(message["media"], "document")
            and message["media"].document.attributes
            and any(
                isinstance(attr, DocumentAttributeSticker)
                for attr in message["media"].document.attributes
            )
        )
        is_gif = (
            hasattr(message["media"], "document")
            and message["media"].document.attributes
            and any(
                isinstance(attr, DocumentAttributeAnimated)
                for attr in message["media"].document.attributes
            )
        )
        is_round_video = (
            hasattr(message["media"], "document")
            and message["media"].document.attributes
            and any(
                (
                    isinstance(attr, DocumentAttributeVideo)
                    and attr.round_message is True
                )
                for attr in message["media"].document.attributes
            )
        )
        is_dice = isinstance(message["media"], MessageMediaDice)
        is_instant_view = isinstance(message["media"], MessageMediaWebPage)
        is_game = isinstance(message["media"], MessageMediaGame)
        is_geo = isinstance(message["media"], MessageMediaGeo)
        is_poll = isinstance(message["media"], MessageMediaPoll)
        is_contact = isinstance(message["media"], (MessageMediaContact, Contact))

        with retrieve_media_as_file(
            message["id"],
            message["chat_id"],
            message["media"],
            message["noforwards"] or message["self_destructing"],
        ) as media_file:

            if (
                is_sticker
                or is_round_video
                or is_dice
                or is_game
                or is_contact
                or is_geo
                or is_poll
            ):
                sent_msg = await client.send_message(
                    config.LOG_CHAT_ID, file=media_file
                )
                await sent_msg.reply(text)
            elif is_instant_view:
                await client.send_message(config.LOG_CHAT_ID, text)
            else:
                await client.send_message(config.LOG_CHAT_ID, text, file=media_file)

        if is_gif and config.DELETE_SENT_GIFS_FROM_SAVED:
            await delete_from_saved_gifs(message["media"].document)

        if is_sticker and config.DELETE_SENT_STICKERS_FROM_SAVED:
            await delete_from_saved_stickers(message["media"].document)

    if isinstance(event, MessageDeleted.Event):
        ids = event.deleted_ids
        event_verb = "deleted"
    elif isinstance(event, UpdateReadMessagesContents):
        ids = event.messages
        event_verb = "self destructed"
    elif isinstance(event, MessageEdited.Event):
        ids = [event.message.id]
        event_verb = "edited"

    if len(ids) > config.RATE_LIMIT_NUM_MESSAGES and log_deleted_sender_ids:
        await client.send_message(
            config.LOG_CHAT_ID,
            f"{len(ids)} messages {event_verb}. Logged {config.RATE_LIMIT_NUM_MESSAGES}.",
        )

    logging.info(
        f"Got 1 {event_verb} message. DB has {len(messages)}. Users: {', '.join(str(_id) for _id in log_deleted_sender_ids)}"
    )


def get_file_name(media) -> str:
    if media:
        try:
            file_name = [
                attr
                for attr in media.document.attributes
                if isinstance(attr, DocumentAttributeFilename)
            ][0].file_name
        except Exception as e:
            try:
                mime_type = media.document.mime_type
            except (NameError, AttributeError) as e:
                mime_type = None

            if mime_type == "audio/ogg":
                file_name = "voicenote.ogg"
            elif mime_type == "video/mp4":
                file_name = "video.mp4"
            elif isinstance(media, (MessageMediaPhoto, Photo)):
                file_name = "photo.jpg"
            elif isinstance(media, (MessageMediaContact, Contact)):
                file_name = "contact.vcf"
            else:
                file_name = "file.unknown"

        return file_name
    else:
        return None


async def save_restricted_msg(link: str):
    if link.startswith("tg://"):
        parts = re.findall(r"\d+", link)
        if len(parts) == 2:
            chat_id = int(parts[0])
            msg_id = int(parts[1])
        else:
            await client.send_message(
                config.LOG_CHAT_ID, f"Could not parse link: {link}"
            )
            return
    else:
        parts = link.split("/")
        msg_id = int(parts[-1])
        chat_id = int(parts[-2]) if parts[-2].isdigit() else parts[-2]

    msg = await client.get_messages(chat_id, ids=msg_id)
    chat_id = msg.chat_id
    from_id = get_sender_id(msg)

    mention_sender = await create_mention(from_id)
    mention_chat = await create_mention(chat_id, msg_id)

    text = f"**↗️Saved message from: **{mention_sender}\n"

    text += f"in {mention_chat}\n"

    if msg.text:
        text += "**Message:** \n" + msg.text

    try:
        if msg.media:
            await save_media_as_file(msg)
            with retrieve_media_as_file(msg_id, chat_id, msg.media, True) as f:
                await client.send_message("me", text, file=f)
        else:
            await client.send_message("me", text)
    except Exception as e:
        await client.send_message(config.LOG_CHAT_ID, str(e))


async def save_media_as_file(msg: Message):
    msg_id = msg.id
    chat_id = msg.chat_id

    logging.info(f"开始保存媒体文件 - 消息ID: {msg_id}, 聊天ID: {chat_id}")

    if msg.media:
        # 记录媒体类型
        logging.info(f"媒体类型: {type(msg.media).__name__}")

        if msg.file:
            logging.info(f"文件大小: {msg.file.size} bytes")

        if msg.file and msg.file.size > config.MAX_IN_MEMORY_FILE_SIZE:
            logging.warning(
                f"文件太大无法保存 ({msg.file.size} bytes), 最大限制: {config.MAX_IN_MEMORY_FILE_SIZE} bytes"
            )
            raise Exception(f"File too large to save ({msg.file.size} bytes)")

        file_path = f"media/{msg_id}_{chat_id}"
        logging.info(f"保存文件路径: {file_path}")

        try:
            with file_encrypt.encrypted(file_path) as f:
                await client.download_media(msg.media, f)
            logging.info("媒体文件保存成功")
        except Exception as e:
            logging.error(f"保存媒体文件失败: {str(e)}")
            raise
    else:
        logging.info("消息不包含媒体内容")


@contextmanager
def retrieve_media_as_file(msg_id: int, chat_id: int, media, noforwards: bool):
    file_name = get_file_name(media)
    file_path = f"media/{msg_id}_{chat_id}"

    logging.info(f"尝试获取媒体文件 - 路径: {file_path}, 文件名: {file_name}")
    logging.info(f"媒体类型: {type(media).__name__}")
    logging.info(f"noforwards: {noforwards}")

    try:
        if (
            noforwards
            and not isinstance(media, MessageMediaGeo)
            and not isinstance(media, MessageMediaPoll)
        ):
            if not os.path.exists(file_path):
                logging.error(f"媒体文件不存在: {file_path}")
                # 如果文件不存在，直接返回原始media
                yield media
                return

            logging.info(f"解密并读取媒体文件: {file_path}")
            with file_encrypt.decrypted(file_path) as f:
                f.name = file_name
                yield f
        else:
            logging.info("直接使用原始媒体对象")
            yield media
    except Exception as e:
        logging.error(f"获取媒体文件时发生错误: {str(e)}")
        # 发生错误时也返回原始media
        yield media


async def delete_from_saved_gifs(gif: Document):
    await client(
        SaveGifRequest(
            id=InputDocument(
                id=gif.id,
                access_hash=gif.access_hash,
                file_reference=gif.file_reference,
            ),
            unsave=True,
        )
    )


async def delete_from_saved_stickers(sticker: Document):
    await client(
        SaveRecentStickerRequest(
            id=InputDocument(
                id=sticker.id,
                access_hash=sticker.access_hash,
                file_reference=sticker.file_reference,
            ),
            unsave=True,
        )
    )


async def delete_expired_messages():
    while True:
        now = datetime.now()
        time_user = now - timedelta(days=config.PERSIST_TIME_IN_DAYS_USER)
        time_channel = now - timedelta(days=config.PERSIST_TIME_IN_DAYS_CHANNEL)
        time_group = now - timedelta(days=config.PERSIST_TIME_IN_DAYS_GROUP)
        time_bot = now - timedelta(days=config.PERSIST_TIME_IN_DAYS_BOT)
        time_unknown = now - timedelta(days=config.PERSIST_TIME_IN_DAYS_GROUP)

        sqlite_cursor.execute(
            """DELETE FROM messages WHERE (type = ? and created_time < ?) OR
            (type = ? and created_time < ?) OR
            (type = ? and created_time < ?) OR
            (type = ? and created_time < ?) OR
            (type = ? and created_time < ?)""",
            (
                TYPE_USER,
                time_user,
                TYPE_CHANNEL,
                time_channel,
                TYPE_GROUP,
                time_group,
                TYPE_BOT,
                time_bot,
                TYPE_UNKNOWN,
                time_unknown,
            ),
        )

        if sqlite_cursor.rowcount > 0:
            logging.info(f"Deleted {sqlite_cursor.rowcount} expired messages from DB")

        # todo: save group/channel label in file name

        num_files_deleted = 0
        file_persist_days = max(
            config.PERSIST_TIME_IN_DAYS_GROUP, config.PERSIST_TIME_IN_DAYS_CHANNEL
        )
        for dirpath, dirnames, filenames in os.walk("media"):
            for filename in filenames:
                file_path = os.path.join(dirpath, filename)
                modified_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                expiry_time = now - timedelta(days=file_persist_days)
                if modified_time < expiry_time:
                    os.unlink(file_path)
                    num_files_deleted += 1

        if num_files_deleted > 0:
            logging.info(f"Deleted {num_files_deleted} expired files")

        await asyncio.sleep(300)


async def forward_user_messages_handler(event: NewMessage.Event):
    """处理特定用户的消息转发"""
    # 添加调试日志
    from_id = get_sender_id(event.message)
    logging.info(f"收到消息 - 来自: {from_id}, 目标用户列表: {config.FORWARD_USER_IDS}")

    try:
        # 检查消息是否来自目标用户
        if from_id not in config.FORWARD_USER_IDS:
            logging.debug(f"消息不是来自目标用户，忽略 - 来自: {from_id}")
            return

        logging.info(
            f"开始处理目标用户消息 - 用户ID: {from_id}, 消息ID: {event.message.id}"
        )

        # 创建消息文本
        mention_sender = await create_mention(from_id)
        mention_chat = await create_mention(event.chat_id, event.message.id)

        text = f"**📨转发消息来自: **{mention_sender}\n"
        text += f"在 {mention_chat}\n"

        if event.message.text:
            text += "**消息内容:** \n" + event.message.text

        # 处理媒体内容
        if event.message.media:
            # 如果是禁止转发的内容，先保存媒体
            noforwards = False
            try:
                noforwards = event.chat.noforwards is True
            except AttributeError:
                noforwards = event.message.noforwards is True

            if noforwards:
                await save_media_as_file(event.message)
                with retrieve_media_as_file(
                    event.message.id, event.chat_id, event.message.media, noforwards
                ) as media_file:
                    await client.send_message(config.LOG_CHAT_ID, text, file=media_file)
            else:
                # 直接转发消息
                await client.send_message(
                    config.LOG_CHAT_ID, text, file=event.message.media
                )
        else:
            # 纯文本消息直接发送
            await client.send_message(config.LOG_CHAT_ID, text)

        logging.info(f"消息转发成功 - 用户ID: {from_id}, 消息ID: {event.message.id}")

    except Exception as e:
        logging.error(f"转发消息失败: {str(e)}")


async def init():
    global my_id
    me = await client.get_me()
    my_id = me.id

    # 添加转发用户消息的事件处理器
    if hasattr(config, "FORWARD_USER_IDS") and config.FORWARD_USER_IDS:
        # 为每个目标用户ID单独添加事件处理器
        for user_id in config.FORWARD_USER_IDS:
            client.add_event_handler(
                forward_user_messages_handler, events.NewMessage(from_users=user_id)
            )
            logging.info(f"已添加用户消息转发处理器 - 用户ID: {user_id}")

    # 注册其他事件处理器
    client.add_event_handler(new_message_handler, events.NewMessage())
    client.add_event_handler(new_message_handler, events.MessageEdited())
    # client.add_event_handler(edited_deleted_handler, events.MessageEdited())
    # client.add_event_handler(edited_deleted_handler, events.MessageDeleted())

    await delete_expired_messages()


if __name__ == "__main__":
    sqlite_cursor, sqlite_connection = init_db()

    with client:
        client.loop.run_until_complete(init())
