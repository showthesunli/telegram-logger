import logging
import pickle
import os # 导入 os 模块以备将来可能的清理操作
import re # 导入 re 模块用于链接转换
from datetime import datetime
from typing import Optional, Union, List, Dict, Any
from telethon import events, errors
from telethon.tl.types import Message as TelethonMessage, DocumentAttributeSticker
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
            logger.debug("消息不是来自目标用户或群组，跳过")
            return None

        try:
            # 创建提及链接
            # create_mention should ideally return a formatted string like "[Name](link)" or "[ID](link)"
            mention_sender = await create_mention(self.client, from_id)
            mention_chat = await create_mention(self.client, event.chat_id, event.message.id)

            # 获取时间戳
            timestamp = event.message.date.strftime('%Y-%m-%d %H:%M:%S UTC') # 使用UTC以保持一致

            # --- 第一部分: 消息来源信息 ---
            text = f"{mention_sender} 在 {mention_chat} 中，于 {timestamp}，发言：\n\n"
            
            # --- 第二部分: 消息内容 ---
            if event.message.text:
                text += f"```markdown\n{event.message.text}\n```" # 使用markdown格式包裹内容
            else:
                # 尝试获取媒体标题
                caption = getattr(event.message, 'caption', None)
                if caption:
                    text += f"```markdown\n{caption}\n```" # 使用markdown格式包裹媒体标题
                else:
                    text += "[No text content or caption]"

            # 处理媒体指示 (纯文本)
            media_section = ""
            if event.message.media:
                media_section += "\n--------------------\n"
                media_section += "MEDIA:\n"
                # 检查是否是贴纸
                is_sticker = False
                if hasattr(event.message.media, 'attributes'):
                    is_sticker = any(isinstance(attr, DocumentAttributeSticker) for attr in event.message.media.attributes)

                if is_sticker:
                    media_type = "Sticker"
                    media_filename = None # 贴纸通常没有用户可见的文件名
                else:
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

            # --- 如果 use_markdown_format 为 True，转换链接格式 ---
            original_text_for_markdown = text # 保留一份原始文本用于可能的 Markdown 包裹
            if self.use_markdown_format:
                try:
                    # 正则表达式查找 Markdown 链接 [text](url) 并替换为 text (url)
                    # 应用于将要被包裹在 ```markdown ... ``` 中的文本
                    original_text_for_markdown = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1 (\2)', original_text_for_markdown)
                    logger.debug("已将 Markdown 链接转换为纯文本格式，用于 Markdown 代码块")
                except Exception as re_err:
                    logger.warning(f"转换 Markdown 链接时出错: {re_err}")
            # --- 链接转换结束 ---


            # 处理发送逻辑
            if event.message.media:
                # 对于有媒体的消息，调用 _handle_media_message
                # 它将根据 use_markdown_format 决定是否包裹文本
                # 传递转换过链接格式的文本（如果 use_markdown_format 为 True）
                text_to_send_with_media = original_text_for_markdown if self.use_markdown_format else text
                await self._handle_media_message(event.message, text_to_send_with_media)
            else:
                # 对于纯文本消息
                final_text_to_send = text # 默认使用原始文本
                if self.use_markdown_format:
                    # 仅当标记为 True 时，包裹转换过链接格式的文本
                    final_text_to_send = f"```markdown\n{original_text_for_markdown}\n```"
                
                # 始终使用 Markdown 解析模式，以便 Telegram 能识别 ```markdown ... ``` 块
                await self.client.send_message(self.log_chat_id, final_text_to_send, parse_mode='md')
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

    async def _handle_media_message(self, message: TelethonMessage, text_content: str):
        """
        处理包含媒体的消息。
        接收已经根据 use_markdown_format 可能转换过链接的 text_content。
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

        # text_content 已经是转换过链接（如果需要）的文本
        final_text_to_send = text_content # 从传入的文本开始

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
                                final_text_to_send = f"```markdown\n{text_content}\n```" # 包裹传入的（可能已转换链接的）文本

                            # 始终使用 Markdown 解析模式
                            await self.client.send_message(self.log_chat_id, final_text_to_send, file=media_file, parse_mode='md')
                            logger.info(f"成功发送带受限媒体的消息到日志频道. Markdown包裹: {self.use_markdown_format}")
                        else:
                            logger.warning(f"无法检索或解密媒体文件: {file_path}")
                            error_note = "\n  Error: Failed to retrieve/decrypt media file.\n"
                            # 在原始（可能已转换链接的）文本末尾追加错误
                            final_text_to_send = text_content + error_note + "\n===================="

                            if self.use_markdown_format:
                                final_text_to_send = f"```markdown\n{final_text_to_send}\n```" # 包裹含错误的文本

                            # 始终使用 Markdown 解析模式
                            await self.client.send_message(self.log_chat_id, final_text_to_send, parse_mode='md')
                else:
                    logger.warning("save_media_as_file 未能成功保存受限文件，仅发送文本")
                    error_note = "\n  Error: Failed to save restricted media file.\n"
                    final_text_to_send = text_content + error_note + "\n===================="

                    if self.use_markdown_format:
                        final_text_to_send = f"```markdown\n{final_text_to_send}\n```"

                    # 始终使用 Markdown 解析模式
                    await self.client.send_message(self.log_chat_id, final_text_to_send, parse_mode='md')

            except Exception as e:
                logger.error(f"处理受保护媒体时出错: {e}", exc_info=True)
                error_note = f"\n  Error: Exception during restricted media handling - {type(e).__name__}: {e}\n"
                final_text_to_send = text_content + error_note + "\n===================="

                if self.use_markdown_format:
                    final_text_to_send = f"```markdown\n{final_text_to_send}\n```"

                # 始终使用 Markdown 解析模式
                await self.client.send_message(self.log_chat_id, final_text_to_send, parse_mode='md')
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
                # 检查是否是贴纸
                is_sticker = False
                doc_attributes_for_log = None # 用于记录实际检查的属性
                media_obj_for_log = message.media # 用于记录原始媒体对象

                # 导入 MessageMediaDocument (如果尚未导入)
                from telethon.tl.types import MessageMediaDocument

                if isinstance(message.media, MessageMediaDocument):
                    doc = getattr(message.media, 'document', None)
                    if doc and hasattr(doc, 'attributes'):
                        doc_attributes_for_log = doc.attributes # 获取文档的属性列表
                        is_sticker = any(isinstance(attr, DocumentAttributeSticker) for attr in doc.attributes)

                # 添加详细日志
                logger.debug(f"媒体类型检查: is_sticker = {is_sticker}")
                logger.debug(f"媒体对象: {media_obj_for_log}")
                logger.debug(f"检查的文档属性: {doc_attributes_for_log}") # 记录实际检查的属性

                if is_sticker:
                    # 对于贴纸，先发送文本信息，再单独发送贴纸
                    logger.debug(f"处理贴纸消息. use_markdown_format: {self.use_markdown_format}")
                    logger.debug(f"传入的 text_content (可能已转换链接): {text_content[:200]}...") # Log beginning of text

                    # 1. 发送文本信息
                    text_sent_successfully = False # 标记文本是否成功发送
                    try:
                        # 根据 use_markdown_format 决定是否包裹文本
                        text_for_sticker_info = text_content # Start with the original content
                        if self.use_markdown_format:
                            text_for_sticker_info = f"```markdown\n{text_content}\n```"
                        
                        logger.debug(f"准备发送的贴纸文本信息 (text_for_sticker_info): {text_for_sticker_info[:200]}...")

                        # 始终使用 Markdown 解析模式发送文本
                        logger.info("尝试发送贴纸的文本信息...")
                        await self.client.send_message(self.log_chat_id, text_for_sticker_info, parse_mode='md')
                        logger.info(f"成功发送贴纸的文本信息到日志频道. Markdown包裹: {self.use_markdown_format}")
                        text_sent_successfully = True # 标记成功
                    except errors.MessageTooLongError:
                        logger.warning("贴纸的文本信息过长，尝试发送截断版本。")
                        try:
                            # 尝试发送截断后的文本
                            # 注意：需要重新应用 markdown 包裹（如果需要）
                            truncated_original_text = f"{text_content[:4000]}...\n[Original message too long]"
                            truncated_text_to_send = truncated_original_text
                            if self.use_markdown_format:
                                truncated_text_to_send = f"```markdown\n{truncated_original_text}\n```"
                            
                            logger.info("尝试发送截断的贴纸文本信息...")
                            await self.client.send_message(self.log_chat_id, truncated_text_to_send, parse_mode='md')
                            logger.info("成功发送截断的贴纸文本信息。")
                            text_sent_successfully = True # 标记成功（即使是截断的）
                        except Exception as e_trunc:
                            logger.error(f"发送截断的贴纸文本信息失败: {e_trunc}")
                            # 发送一个简单的错误提示
                            await self.client.send_message(self.log_chat_id, "⚠️ Error: Text content for sticker was too long and could not be sent.", parse_mode='md')
                    except Exception as e_text:
                        logger.error(f"发送贴纸的文本信息时出错: {e_text}", exc_info=True)
                        # 发送错误通知
                        await self.client.send_message(self.log_chat_id, f"⚠️ Error sending text part for sticker: {type(e_text).__name__}", parse_mode='md')

                    # 2. 单独发送贴纸文件 (无标题)
                    # 仅在文本信息发送成功（或尝试发送但失败有记录）后发送贴纸，确保不会只有贴纸
                    if text_sent_successfully:
                        try:
                            logger.info("尝试发送贴纸文件...")
                            await self.client.send_file(self.log_chat_id, message.media)
                            logger.info("成功发送贴纸文件到日志频道.")
                        except Exception as e_sticker:
                            logger.error(f"发送贴纸文件时出错: {e_sticker}", exc_info=True)
                            # 发送错误通知
                            await self.client.send_message(self.log_chat_id, f"⚠️ Error sending sticker file: {type(e_sticker).__name__}", parse_mode='md')
                    else:
                         logger.warning("由于贴纸的文本信息未能成功发送，跳过发送贴纸文件，以避免孤立的贴纸。")


                else:
                    # 对于非贴纸的普通媒体，保持原有逻辑：文本和媒体一起发送
                    if self.use_markdown_format:
                        final_text_to_send = f"```markdown\n{text_content}\n```" # 包裹传入的（可能已转换链接的）文本
                    else:
                        final_text_to_send = text_content # 使用原始（可能已转换链接的）文本

                    # 始终使用 Markdown 解析模式
                    await self.client.send_message(self.log_chat_id, final_text_to_send, file=message.media, parse_mode='md')
                    logger.info(f"成功发送带非受保护媒体的消息到日志频道. Markdown包裹: {self.use_markdown_format}")
            except errors.MediaCaptionTooLongError:
                 logger.warning(f"媒体标题过长，尝试不带标题发送媒体.")
                 try:
                     # 如果是贴纸，这里不应该发生，因为我们是分开处理的
                     # 但为了健壮性，如果真的在这里捕获到，只记录错误，因为贴纸已发送
                     # 非贴纸的回退逻辑保持不变
                     await self.client.send_message(self.log_chat_id, file=message.media)
                     # 单独发送文本（可能截断或修改）
                     caption_warning = "\n  Warning: Original caption was too long and might be truncated or omitted.\n"
                     final_text_to_send = text_content + caption_warning + "\n===================="
                     if self.use_markdown_format:
                         final_text_to_send = f"```markdown\n{final_text_to_send}\n```"
                     # 始终使用 Markdown 解析模式
                     await self.client.send_message(self.log_chat_id, final_text_to_send, parse_mode='md')

                 except Exception as e_fallback:
                     logger.error(f"发送非受保护媒体（无标题回退）时出错: {e_fallback}", exc_info=True)
                     error_note = f"\n  Error: Exception during non-restricted media fallback - {type(e_fallback).__name__}: {e_fallback}\n"
                     final_text_to_send = text_content + error_note + "\n===================="
                     if self.use_markdown_format:
                         final_text_to_send = f"```markdown\n{final_text_to_send}\n```"
                     # 始终使用 Markdown 解析模式
                     await self.client.send_message(self.log_chat_id, final_text_to_send, parse_mode='md')

            except Exception as e:
                logger.error(f"发送非受保护媒体时出错: {e}", exc_info=True)
                error_note = f"\n  Error: Exception during non-restricted media handling - {type(e).__name__}: {e}\n"
                # 如果是贴纸且发送文本时出错
                final_text_to_send = text_content + error_note + "\n===================="

                if self.use_markdown_format:
                    final_text_to_send = f"```markdown\n{final_text_to_send}\n```"

                # 始终使用 Markdown 解析模式
                await self.client.send_message(self.log_chat_id, final_text_to_send, parse_mode='md')


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
