import logging
import pickle
import os # 导入 os 模块以备将来可能的清理操作
from datetime import datetime
from typing import Optional
from telethon import events
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
            # 创建消息内容
            mention_sender = await create_mention(self.client, from_id)
            mention_chat = await create_mention(self.client, event.chat_id, event.message.id)

            # 根据来源构建不同的消息前缀
            if is_target_user:
                text = f"**📨转发用户消息来自: **{mention_sender}\n"
            else:
                text = f"**📨转发群组消息来自: **{mention_sender}\n"

            text += f"在 {mention_chat}\n"

            if event.message.text:
                text += "**消息内容:** \n" + event.message.text

            # 处理媒体消息
            if event.message.media:
                await self._handle_media_message(event.message, text)
            else:
                final_text = text
                if self.use_markdown_format:
                    final_text = f"```markdown\n{text}\n```"
                await self.client.send_message(self.log_chat_id, final_text)

            message = await self._create_message_object(event)
            await self.save_message(message)
            return message

        except Exception as e:
            logger.error(f"转发消息失败: {str(e)}", exc_info=True)
            return None

    async def _handle_media_message(self, message, text):
        """处理包含媒体的消息"""
        noforwards = False
        try:
            noforwards = getattr(message.chat, 'noforwards', False) or \
                        getattr(message, 'noforwards', False)
        except AttributeError:
            pass

        if noforwards:
            file_path = None # 初始化 file_path
            try:
                # 尝试保存媒体文件
                file_path = await save_media_as_file(self.client, message)
                if file_path:
                    # 在调用 retrieve_media_as_file 之前获取原始文件名
                    original_filename = _get_filename(message.media)
                    logger.info(f"从原始媒体获取文件名: {original_filename}")

                    # 使用上下文管理器检索并解密文件
                    with retrieve_media_as_file(file_path, True) as media_file:
                        if media_file: # 确保 media_file 不是 None
                            # 在发送前设置正确的文件名
                            media_file.name = original_filename
                            logger.info(f"准备发送解密后的文件，文件名为: {media_file.name}")
                            await self.client.send_message(self.log_chat_id, text, file=media_file)
                            logger.info(f"成功发送带媒体的消息到日志频道，原始文件名: {original_filename}")
                        else:
                            logger.warning(f"无法检索或解密媒体文件: {file_path}")
                            # 即使文件检索失败，也发送文本消息并附带警告
                            await self.client.send_message(self.log_chat_id, text + "\n\n⚠️ 媒体文件检索失败")
                else:
                    # 如果 save_media_as_file 返回 None 或空字符串
                    logger.warning("save_media_as_file 未能成功保存文件，仅发送文本消息")
                    await self.client.send_message(self.log_chat_id, text)
            except Exception as e:
                # 捕获保存、检索或发送过程中的异常
                logger.error(f"处理受保护媒体时出错: {e}", exc_info=True)
                # 发送带有错误信息的文本消息到日志频道
                await self.client.send_message(self.log_chat_id, text + f"\n\n⚠️ 处理媒体时出错: {e}")
            finally:
                # 可选：如果需要，可以在这里添加清理逻辑，例如删除临时的加密文件
                # if file_path and os.path.exists(file_path):
                #     try:
                #         os.remove(file_path)
                #         logger.info(f"已删除临时加密文件: {file_path}")
                #     except OSError as e:
                #         logger.error(f"删除临时文件失败 {file_path}: {e}")
                pass # 暂时不加删除逻辑

        else:
            # 对于非受保护内容，保持原有逻辑，但也添加错误处理
            try:
                await self.client.send_message(self.log_chat_id, text, file=message.media)
                logger.info("成功发送带非受保护媒体的消息到日志频道")
            except Exception as e:
                logger.error(f"发送非受保护媒体时出错: {e}", exc_info=True)
                # 发送带有错误信息的文本消息到日志频道
                await self.client.send_message(self.log_chat_id, text + f"\n\n⚠️ 发送媒体时出错: {e}")

    async def _create_message_object(self, event):
        """创建消息对象"""
        from_id = self._get_sender_id(event.message)
        noforwards = False
        try:
            noforwards = getattr(event.chat, 'noforwards', False) or \
                        getattr(event.message, 'noforwards', False)
        except AttributeError:
            pass

        self_destructing = False
        try:
            self_destructing = bool(getattr(getattr(event.message, 'media', None), 'ttl_seconds', False))
        except AttributeError:
            pass

        media = None
        if event.message.media:
            try:
                # 注意：这里仍然尝试保存媒体，即使是受保护的，用于数据库记录
                # 如果 save_media_as_file 失败，media 将为 None
                await save_media_as_file(self.client, event.message)
                # 序列化媒体对象以存入数据库，这可能在受保护内容时失败或不完整
                media = pickle.dumps(event.message.media)
            except Exception as e:
                logger.error(f"为数据库记录保存或序列化媒体失败: {str(e)}")
                # 即使保存/序列化失败，也继续创建消息对象，media 为 None

        return Message(
            id=event.message.id,
            from_id=from_id,
            chat_id=event.chat_id,
            msg_type=await self.get_chat_type(event),
            media=media,
            noforwards=noforwards,
            self_destructing=self_destructing,
            created_time=datetime.now(),
            edited_time=None,
            msg_text=event.message.message
        )

    async def get_chat_type(self, event):
        """获取消息类型"""
        if event.is_group:  # chats and megagroups
            return 2  # group
        elif event.is_channel:  # megagroups and channels
            return 3  # channel
        elif event.is_private:
            sender = await event.get_sender()
            if sender and sender.bot: # 检查 sender 是否存在
                return 4  # bot
            return 1  # user
        return 0  # unknown type
