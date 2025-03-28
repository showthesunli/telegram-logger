import logging
import pickle
import os # 导入 os 模块以备将来可能的清理操作
from datetime import datetime
from typing import Optional, Union, List, Dict, Any
from telethon import events, errors
from telethon.tl.types import Message as TelethonMessage
from telegram_logger.handlers.base_handler import BaseHandler
from telegram_logger.utils.mentions import create_mention
from telegram_logger.data.models import Message
# 从 media 模块导入 _get_filename 函数
from telegram_logger.utils.media import save_media_as_file, retrieve_media_as_file, _get_filename

logger = logging.getLogger(__name__)

class ForwardHandler(BaseHandler):
    def __init__(self, client, db, log_chat_id, ignored_ids, forward_user_ids=None, forward_group_ids=None, use_markdown_format: bool = False):
        super().__init__(client, db, log_chat_id, ignored_ids)
        self.forward_user_ids = forward_user_ids or []
        self.forward_group_ids = forward_group_ids or []
        self.use_markdown_format = use_markdown_format
        logger.info(f"ForwardHandler initialized with forward_user_ids: {self.forward_user_ids}")
        logger.info(f"ForwardHandler initialized with forward_group_ids: {self.forward_group_ids}")
        logger.info(f"ForwardHandler Markdown format enabled: {self.use_markdown_format}")

    async def handle_new_message(self, event):
        """处理新消息事件，这个方法名与client.py中的注册方法匹配"""
        # 确保handler已初始化
        if not self.client:
            logger.error("Handler not initialized, client is None")
            return None

        from_id = self._get_sender_id(event.message)
        chat_id = event.chat_id
        logger.info(f"ForwardHandler received message from user {from_id} in chat {chat_id}")
        return await self.process(event)

    async def process(self, event: events.NewMessage.Event) -> Optional[Message]:
        """处理转发消息"""
        from_id = self._get_sender_id(event.message)
        chat_id = event.chat_id

        # 检查是否来自目标用户或目标群组
        is_target_user = from_id in self.forward_user_ids
        is_target_group = chat_id in self.forward_group_ids

        logger.info(f"处理消息 - 用户ID: {from_id}, 聊天ID: {chat_id}, 是目标用户: {is_target_user}, 是目标群组: {is_target_group}")

        if not (is_target_user or is_target_group):
            logger.debug(f"消息不是来自目标用户或群组，跳过")
            return None

        try:
            # 获取发送者实体信息
            sender_entity = None
            sender_name = ""
            try:
                sender_entity = await self.client.get_entity(from_id)
                if sender_entity:
                    sender_name = f"{sender_entity.first_name or ''}"
                    if sender_entity.last_name:
                        sender_name += f" {sender_entity.last_name}"
                    sender_name = sender_name.strip()
            except (errors.UsernameInvalidError, errors.ChannelPrivateError, ValueError, TypeError) as e:
                logger.warning(f"获取发送者实体信息失败 (ID: {from_id}): {e}")
            except Exception as e:
                logger.error(f"获取发送者实体信息时发生意外错误 (ID: {from_id}): {e}", exc_info=True)


            # 创建提及链接 (即使获取实体失败，也尝试创建基于 ID 的链接)
            mention_sender = await create_mention(self.client, from_id)
            mention_chat = await create_mention(self.client, event.chat_id, event.message.id)

            # 组合显示姓名和用户名
            sender_display = f"{sender_name} ({mention_sender})" if sender_name else mention_sender

            # 获取时间戳
            timestamp = event.message.date.strftime('%Y-%m-%d %H:%M:%S UTC') # 使用UTC以保持一致

            # --- 构建结构化纯文本 ---
            text = "FORWARDED MESSAGE\n"
            text += "====================\n\n"

            source_label = "USER" if is_target_user else "GROUP/CHANNEL"
            text += f"TYPE: {source_label}\n"
            text += f"FROM: {sender_display}\n"
            text += f"CHAT: {mention_chat}\n"
            text += f"TIME: {timestamp}\n\n"
            text += "--------------------\n"
            text += "CONTENT:\n\n"

            if event.message.text:
                text += f"{event.message.text}\n" # 保留原始文本换行
            else:
                # 尝试获取媒体标题
                caption = getattr(event.message, 'caption', None)
                if caption:
                    text += f"{caption}\n" # 保留原始标题换行
                else:
                    text += "[No text content or caption]\n"

            # 处理媒体指示 (纯文本)
            media_section = ""
            if event.message.media:
                media_section += "\n--------------------\n"
                media_section += "MEDIA:\n"
                media_type = type(event.message.media).__name__.replace("MessageMedia", "")
                media_filename = _get_filename(event.message.media)
                media_section += f"  Type: {media_type}\n"
                if media_filename:
                    media_section += f"  Filename: {media_filename}\n"

                # 添加关于限制或特性的注释
                noforwards = False
                try:
                    noforwards = getattr(event.chat, 'noforwards', False) or \
                                 getattr(event.message, 'noforwards', False)
                except AttributeError:
                    pass

                if noforwards:
                    media_section += "  Note: Restricted content. Media file will be handled separately.\n"

                ttl_seconds = getattr(getattr(event.message, 'media', None), 'ttl_seconds', None)
                if ttl_seconds:
                    media_section += f"  Note: Self-destructing media (TTL: {ttl_seconds}s).\n"

            text += media_section
            text += "\n===================="
            # --- 结构化纯文本构建结束 ---


            # 处理发送逻辑
            if event.message.media:
                # 对于有媒体的消息，调用 _handle_media_message
                # 它将根据 use_markdown_format 决定是否包裹文本
                await self._handle_media_message(event.message, text)
            else:
                # 对于纯文本消息
                final_text_to_send = text
                if self.use_markdown_format:
                    # 仅当标记为 True 时，包裹纯文本消息
                    final_text_to_send = f"```markdown\n{text}\n```"
                
                await self.client.send_message(self.log_chat_id, final_text_to_send, parse_mode='md' if not self.use_markdown_format else None)
                logger.info(f"成功发送纯文本转发消息到日志频道. Markdown包裹: {self.use_markdown_format}")


            # 创建并保存数据库消息对象
            message = await self._create_message_object(event)
            if message: # 确保对象创建成功
                await self.save_message(message)
            return message

        except Exception as e:
            logger.error(f"处理或转发消息时发生严重错误: {str(e)}", exc_info=True)
            # 尝试发送错误通知到日志频道
            try:
                error_message = f"⚠️ **错误:** 处理消息 {event.message.id} (来自 chat {event.chat_id}) 时出错。\n\n`{type(e).__name__}: {str(e)}`"
                await self.client.send_message(self.log_chat_id, error_message, parse_mode='md')
            except Exception as send_err:
                logger.error(f"发送错误通知到日志频道失败: {send_err}")
            return None

    async def _handle_media_message(self, message: TelethonMessage, text: str):
        """
        处理包含媒体的消息。
        根据 self.use_markdown_format 决定是否包裹文本。
        """
        noforwards = False
        file_path = None
        error_note = "" # 用于在文本中记录媒体处理错误

        try:
            noforwards = getattr(message.chat, 'noforwards', False) or \
                         getattr(message, 'noforwards', False)
        except AttributeError:
            pass # noforwards 保持 False

        final_text_to_send = text # 从传入的结构化文本开始

        if noforwards:
            try:
                # 尝试保存媒体文件
                file_path = await save_media_as_file(self.client, message)
                if file_path:
                    original_filename = _get_filename(message.media)
                    logger.info(f"受限媒体已保存: {file_path}. 原始文件名: {original_filename}")

                    # 使用上下文管理器检索并解密文件
                    with retrieve_media_as_file(file_path, True) as media_file:
                        if media_file:
                            media_file.name = original_filename # 设置正确的文件名
                            logger.info(f"准备发送解密后的文件: {media_file.name}")

                            # 根据 use_markdown_format 决定是否包裹文本
                            if self.use_markdown_format:
                                final_text_to_send = f"```markdown\n{text}\n```"

                            await self.client.send_message(self.log_chat_id, final_text_to_send, file=media_file, parse_mode='md' if not self.use_markdown_format else None)
                            logger.info(f"成功发送带受限媒体的消息到日志频道. Markdown包裹: {self.use_markdown_format}")
                        else:
                            logger.warning(f"无法检索或解密媒体文件: {file_path}")
                            error_note = "\n  Error: Failed to retrieve/decrypt media file.\n"
                            final_text_to_send = text + error_note + "\n====================" # 在原始文本末尾追加错误

                            if self.use_markdown_format:
                                final_text_to_send = f"```markdown\n{final_text_to_send}\n```" # 包裹含错误的文本

                            await self.client.send_message(self.log_chat_id, final_text_to_send, parse_mode='md' if not self.use_markdown_format else None)
                else:
                    logger.warning("save_media_as_file 未能成功保存受限文件，仅发送文本")
                    error_note = "\n  Error: Failed to save restricted media file.\n"
                    final_text_to_send = text + error_note + "\n===================="

                    if self.use_markdown_format:
                        final_text_to_send = f"```markdown\n{final_text_to_send}\n```"

                    await self.client.send_message(self.log_chat_id, final_text_to_send, parse_mode='md' if not self.use_markdown_format else None)

            except Exception as e:
                logger.error(f"处理受保护媒体时出错: {e}", exc_info=True)
                error_note = f"\n  Error: Exception during restricted media handling - {type(e).__name__}: {e}\n"
                final_text_to_send = text + error_note + "\n===================="

                if self.use_markdown_format:
                    final_text_to_send = f"```markdown\n{final_text_to_send}\n```"

                await self.client.send_message(self.log_chat_id, final_text_to_send, parse_mode='md' if not self.use_markdown_format else None)
            finally:
                # 可以在这里添加清理逻辑，例如删除临时的 file_path
                # if file_path and os.path.exists(file_path):
                #     try:
                #         os.remove(file_path)
                #         logger.info(f"已清理临时媒体文件: {file_path}")
                #     except OSError as e:
                #         logger.error(f"清理临时媒体文件失败: {file_path}, Error: {e}")
                pass # 暂时不加删除逻辑

        else: # 非受保护内容 (noforwards is False)
            try:
                # 根据 use_markdown_format 决定是否包裹文本
                if self.use_markdown_format:
                    final_text_to_send = f"```markdown\n{text}\n```"

                await self.client.send_message(self.log_chat_id, final_text_to_send, file=message.media, parse_mode='md' if not self.use_markdown_format else None)
                logger.info(f"成功发送带非受保护媒体的消息到日志频道. Markdown包裹: {self.use_markdown_format}")
            except errors.MediaCaptionTooLongError:
                 logger.warning(f"媒体标题过长，尝试不带标题发送媒体.")
                 try:
                     # 尝试只发送文件
                     await self.client.send_message(self.log_chat_id, file=message.media)
                     # 单独发送文本（可能截断或修改）
                     caption_warning = "\n  Warning: Original caption was too long and might be truncated or omitted.\n"
                     final_text_to_send = text + caption_warning + "\n===================="
                     if self.use_markdown_format:
                         final_text_to_send = f"```markdown\n{final_text_to_send}\n```"
                     await self.client.send_message(self.log_chat_id, final_text_to_send, parse_mode='md' if not self.use_markdown_format else None)

                 except Exception as e_fallback:
                     logger.error(f"发送非受保护媒体（无标题回退）时出错: {e_fallback}", exc_info=True)
                     error_note = f"\n  Error: Exception during non-restricted media fallback - {type(e_fallback).__name__}: {e_fallback}\n"
                     final_text_to_send = text + error_note + "\n===================="
                     if self.use_markdown_format:
                         final_text_to_send = f"```markdown\n{final_text_to_send}\n```"
                     await self.client.send_message(self.log_chat_id, final_text_to_send, parse_mode='md' if not self.use_markdown_format else None)

            except Exception as e:
                logger.error(f"发送非受保护媒体时出错: {e}", exc_info=True)
                error_note = f"\n  Error: Exception during non-restricted media handling - {type(e).__name__}: {e}\n"
                final_text_to_send = text + error_note + "\n===================="

                if self.use_markdown_format:
                    final_text_to_send = f"```markdown\n{final_text_to_send}\n```"

                await self.client.send_message(self.log_chat_id, final_text_to_send, parse_mode='md' if not self.use_markdown_format else None)


    async def _create_message_object(self, event: events.NewMessage.Event) -> Optional[Message]:
        """创建用于数据库存储的消息对象"""
        from_id = self._get_sender_id(event.message)
        noforwards = False
        try:
            noforwards = getattr(event.chat, 'noforwards', False) or \
                         getattr(event.message, 'noforwards', False)
        except AttributeError:
            pass

        self_destructing = False
        ttl_seconds = None
        try:
            ttl_seconds = getattr(getattr(event.message, 'media', None), 'ttl_seconds', None)
            if ttl_seconds:
                self_destructing = True
        except AttributeError:
            pass

        media_content = None
        media_path = None # 用于存储媒体文件的路径（如果保存了）

        if event.message.media:
            try:
                # 尝试保存媒体文件，即使是受保护的，也可能需要记录路径或元数据
                # 注意：save_media_as_file 现在主要用于受限媒体下载，
                # 对于数据库记录，我们可能只需要序列化基本信息或存储路径。
                # 这里我们仍然调用它，如果成功，可以记录路径。
                # 如果失败或非受限，media_path 将为 None 或不被使用。
                if noforwards or self_destructing: # 仅为受限或阅后即焚媒体尝试保存文件以记录
                     media_path = await save_media_as_file(self.client, event.message)
                     logger.info(f"媒体文件尝试保存于: {media_path} (用于数据库记录)")


                # 序列化媒体对象以存入数据库。这可能包含敏感信息或过大。
                # 考虑只存储媒体类型、文件名、大小等元数据，而不是整个对象。
                # 为了简化，暂时保持序列化，但要注意潜在问题。
                try:
                    media_content = pickle.dumps(event.message.media)
                except (pickle.PicklingError, TypeError) as pe:
                     logger.warning(f"序列化媒体对象失败: {pe}. 将存储 None.")
                     media_content = None # 无法序列化则存 None

            except Exception as e:
                logger.error(f"为数据库记录处理媒体时出错: {str(e)}")
                media_content = None # 出错则存 None

        # 获取聊天类型
        chat_type_code = await self.get_chat_type(event)

        try:
            return Message(
                id=event.message.id,
                from_id=from_id,
                chat_id=event.chat_id,
                msg_type=chat_type_code,
                media=media_content, # 存储序列化后的媒体对象或 None
                # media_path=media_path, # 可以考虑增加这个字段存储文件路径
                noforwards=noforwards,
                self_destructing=self_destructing,
                # ttl_seconds=ttl_seconds, # 可以考虑增加这个字段
                created_time=event.message.date, # 使用消息的原始时间
                edited_time=event.message.edit_date, # 使用消息的编辑时间
                msg_text=event.message.message # 存储原始文本
            )
        except Exception as e:
            logger.error(f"创建 Message 对象失败: {e}", exc_info=True)
            return None


    async def get_chat_type(self, event) -> int:
        """获取聊天类型代码 (1: user, 2: group, 3: channel, 4: bot, 0: unknown)"""
        if event.is_private:
            try:
                sender = await event.get_sender()
                if sender and sender.bot:
                    return 4  # bot
                return 1  # user
            except Exception as e:
                 logger.warning(f"获取私聊发送者信息失败: {e}. 默认为 user.")
                 return 1 # 无法确定是否是 bot 时，默认为 user
        elif event.is_group:
             # Telethon 的 is_group 包含 megagroups 和 legacy groups
             # 通常我们想区分 channel (megagroup/broadcast) 和 group (legacy)
             # 但这里简单处理，都归为 group
             # 如果需要更细致区分，需要检查 event.chat.megagroup
             return 2 # group or megagroup
        elif event.is_channel:
             # is_channel 通常指 megagroups 或 broadcast channels
             # 如果 event.is_group 已经是 2，这里可能不会执行到
             # 但为了覆盖所有情况，如果能到这里，认为是 channel
             # 注意：Telethon 的定义可能随版本变化，需要验证
             # 假设 event.is_channel 且 not event.is_group 是 broadcast channel
             if hasattr(event.chat, 'broadcast') and event.chat.broadcast:
                 return 3 # broadcast channel
             elif hasattr(event.chat, 'megagroup') and event.chat.megagroup:
                 return 2 # megagroup (也算 group 类型)
             else:
                 return 3 # 默认为 channel
        return 0  # unknown type
