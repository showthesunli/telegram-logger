import time
from telethon import TelegramClient, events, errors as telethon_errors
import sys # 确保 sys 已导入，因为后面用到了 sys.exit
from typing import List
import logging
from telegram_logger.handlers.base_handler import BaseHandler

logger = logging.getLogger(__name__)

class TelegramClientService:
    def __init__(
        self,
        session_name: str,
        api_id: int,
        api_hash: str,
        handlers: List[BaseHandler],
        log_chat_id: int
    ):
        self.client = TelegramClient(session_name, api_id, api_hash)
        self.handlers = handlers
        self.log_chat_id = log_chat_id
        self._is_initialized = False
        self._start_time = time.time()
        self._last_error = None

    async def initialize(self) -> int:
        """初始化客户端，连接到 Telegram 并返回用户 ID。"""
        logger.info("正在初始化 Telegram 客户端...")
        try:
            # 尝试连接和登录
            # 注意：如果需要输入验证码或密码，Telethon 会在控制台提示
            await self.client.connect()
            if not await self.client.is_user_authorized():
                logger.info("用户未授权，可能需要登录。")
                # 根据 Telethon 的行为，start() 会处理登录流程
                # 如果需要电话号码，它会要求输入
                # 如果需要验证码或密码，它也会要求输入
                # 这里假设必要的交互在控制台进行
                await self.client.start() # start() 包含了登录逻辑

            # 再次检查连接状态，因为 start() 可能失败但未抛出特定异常
            if not self.client.is_connected():
                 logger.critical("客户端未能成功连接。")
                 sys.exit(1)

            me = await self.client.get_me()
            if me is None:
                 logger.critical("无法获取用户信息 (get_me 返回 None)，请检查网络或会话文件。")
                 # 抛出异常或返回特定错误代码可能更好，但这里先记录并退出
                 sys.exit(1)

            my_id = me.id
            logger.info(f"客户端初始化成功。用户 ID: {my_id}")

            # 注册事件处理器 (移动到获取 my_id 之后，确保 client 正常)
            self._register_handlers()
            logger.info("事件处理器已注册。")

            return my_id

        except telethon_errors.AuthKeyError:
            logger.critical("授权密钥无效或已过期。请删除 session 文件并重新运行以登录。", exc_info=True)
            sys.exit(1) # 认证失败，无法继续
        except telethon_errors.PhoneNumberInvalidError:
            logger.critical("提供的电话号码无效。", exc_info=True)
            sys.exit(1) # 配置错误，无法继续
        except ConnectionError as e:
             logger.critical(f"连接 Telegram 时发生网络错误: {e}", exc_info=True)
             sys.exit(1) # 网络问题，无法继续
        except Exception as e:
            # 捕获其他可能的 Telethon 启动错误或意外异常
            logger.critical(f"初始化 Telegram 客户端时发生未处理的异常: {e}", exc_info=True)
            sys.exit(1) # 未知严重错误，无法继续

    def _register_handlers(self):
        """根据新的统一接口方案注册事件处理器。"""
        if not self.client or not self.client.is_connected():
            logger.error("客户端尚未初始化或未连接，无法注册处理器。")
            return

        logger.info("开始注册事件处理器 (统一接口方案)...")

        # 遍历所有注入的处理器实例
        for handler in self.handlers:
            # 检查处理器是否是 BaseHandler 的实例
            if isinstance(handler, BaseHandler):
                handler_name = type(handler).__name__
                logger.info(f"为处理器 '{handler_name}' 注册通用事件监听器...")

                # 注册 NewMessage 事件，不带过滤器，指向 handler.process
                try:
                    self.client.add_event_handler(
                        handler.process,
                        events.NewMessage() # 通用事件，无过滤器
                    )
                    logger.debug(f"  - 已为 '{handler_name}' 注册 NewMessage 事件 -> process()")
                except Exception as e:
                    logger.error(f"为 '{handler_name}' 注册 NewMessage 事件失败: {e}", exc_info=True)

                # 注册 MessageEdited 事件，不带过滤器，指向 handler.process
                try:
                    self.client.add_event_handler(
                        handler.process,
                        events.MessageEdited() # 通用事件，无过滤器
                    )
                    logger.debug(f"  - 已为 '{handler_name}' 注册 MessageEdited 事件 -> process()")
                except Exception as e:
                    logger.error(f"为 '{handler_name}' 注册 MessageEdited 事件失败: {e}", exc_info=True)

                # 注册 MessageDeleted 事件，不带过滤器，指向 handler.process
                try:
                    self.client.add_event_handler(
                        handler.process,
                        events.MessageDeleted() # 通用事件，无过滤器
                    )
                    logger.debug(f"  - 已为 '{handler_name}' 注册 MessageDeleted 事件 -> process()")
                except Exception as e:
                    logger.error(f"为 '{handler_name}' 注册 MessageDeleted 事件失败: {e}", exc_info=True)

            else:
                # 如果处理器不是 BaseHandler 的子类，则记录警告
                logger.warning(
                    f"处理器 {type(handler).__name__} 不是 BaseHandler 的实例，"
                    f"无法按统一接口方案注册事件。"
                )

        logger.info("所有处理器事件注册完成。")

    async def health_check(self) -> dict:
        """检查服务健康状态
        
        返回:
            dict: 包含以下健康指标:
                - connected (bool): 是否连接服务器
                - handlers (int): 注册的事件处理器数量
                - logged_in (bool): 是否完成登录
                - uptime (float): 运行时间(秒)
                - last_error (str): 最后错误信息(如果有)
        """
        try:
            me = await self.client.get_me() if self._is_initialized else None
            return {
                'connected': self.client.is_connected(),
                'handlers': len(self.client.list_event_handlers()),
                'logged_in': self._is_initialized,
                'user_id': me.id if me else None,
                'uptime': (time.time() - self._start_time) if hasattr(self, '_start_time') else 0,
                'last_error': getattr(self, '_last_error', None)
            }
        except Exception as e:
            self._last_error = str(e)
            return {
                'connected': False,
                'handlers': 0,
                'logged_in': False,
                'user_id': None,
                'uptime': 0,
                'last_error': str(e)
            }

    async def run(self):
        """Run client until disconnected"""
        await self.client.run_until_disconnected()
