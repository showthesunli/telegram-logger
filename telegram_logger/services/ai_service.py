import logging
import os
import asyncio
from typing import List, Dict, Optional

# 导入更具体的错误类型
from openai import AsyncOpenAI, OpenAIError, APIError, AuthenticationError, RateLimitError, BadRequestError
# 导入 httpx 错误类型
from httpx import RequestError

logger = logging.getLogger(__name__)

class AIService:
    """
    封装与 AI 模型（当前为 OpenAI）交互的服务。
    """

    def __init__(self):
        """
        初始化 AIService。
        实际的客户端初始化将在 get_openai_completion 或单独的 init 方法中进行。
        """
        logger.info("AIService 初始化...")
        # 客户端初始化将在 get_openai_completion 或单独的 init 方法中进行
        self._client: Optional[AsyncOpenAI] = None
        # 可以在这里预先读取环境变量，但不创建客户端
        self._api_key = os.getenv("OPENAI_API_KEY")
        self._base_url = os.getenv("OPENAI_BASE_URL") or None # None 会使用默认 URL

        if not self._api_key:
             logger.warning("OPENAI_API_KEY 环境变量未设置。AI 服务可能无法工作。")

    def _get_client(self) -> Optional[AsyncOpenAI]:
        """惰性初始化并返回 AsyncOpenAI 客户端实例。"""
        if self._client is None:
            if not self._api_key:
                logger.error("无法创建 OpenAI 客户端：OPENAI_API_KEY 未设置。")
                return None
            try:
                # 使用从 __init__ 读取的 key 和 url 初始化客户端
                self._client = AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)
                logger.info("AsyncOpenAI 客户端已惰性初始化。")
            except Exception as e:
                logger.error(f"惰性初始化 AsyncOpenAI 客户端失败: {e}", exc_info=True)
                return None # 初始化失败则返回 None
        return self._client

    async def get_openai_completion(
        self,
        model_id: str,
        messages: List[Dict[str, str]]
    ) -> Optional[str]:
        """
        使用 OpenAI API 获取聊天补全。

        Args:
            model_id: 要使用的 OpenAI 模型 ID。
            messages: OpenAI API 所需格式的消息列表。

        Returns:
            生成的回复文本，如果发生错误则返回 None。
        """
        logger.debug(f"请求 OpenAI 补全: 模型={model_id}, 消息数={len(messages)}")

        client = self._get_client() # 获取 (或初始化) 客户端
        if not client:
            logger.error("无法获取 OpenAI 客户端实例，取消补全请求。")
            return None # 如果客户端无法初始化，则直接返回

        try:
            # 调用 OpenAI API
            response = await client.chat.completions.create(
                model=model_id,
                messages=messages,
                # 可以根据需要添加其他参数，如 temperature, max_tokens 等
                # temperature=0.7,
                # max_tokens=1000,
            )

            # 解析响应
            if response.choices and response.choices[0].message:
                reply_content = response.choices[0].message.content
                finish_reason = response.choices[0].finish_reason
                logger.debug(f"OpenAI 响应成功。Finish reason: {finish_reason}")
                # 记录 token 使用情况 (如果需要)
                if response.usage:
                     logger.debug(f"Token usage: Prompt={response.usage.prompt_tokens}, Completion={response.usage.completion_tokens}, Total={response.usage.total_tokens}")
                # 返回提取的文本内容，去除首尾空白
                return reply_content.strip() if reply_content else None
            else:
                # 如果响应结构不符合预期
                logger.warning(f"OpenAI 响应无效或 choices 为空。Response: {response}")
                return None

        # 处理特定的 OpenAI 错误
        except AuthenticationError as e:
            logger.error(f"OpenAI API 认证失败: {e}. 请检查 OPENAI_API_KEY 是否正确。")
            return None
        except RateLimitError as e:
            logger.error(f"OpenAI API 速率限制: {e}. 请检查您的账户配额或稍后重试。")
            return None
        except BadRequestError as e:
             logger.error(f"OpenAI API 请求无效 (BadRequestError): {e}. 可能模型不支持或输入格式错误。 Model: {model_id}")
             return None
        except APIError as e: # 捕获更通用的 OpenAI API 错误
            logger.error(f"OpenAI API 返回错误: Status={e.status_code}, Error={e.body}. Model: {model_id}")
            return None
        except RequestError as e: # 捕获 httpx 网络错误
            logger.error(f"连接 OpenAI API 时发生网络错误: {e}. Model: {model_id}", exc_info=True)
            return None
        except OpenAIError as e: # 捕获其他 OpenAI 库错误
            logger.error(f"发生 OpenAI 库错误: {e}. Model: {model_id}", exc_info=True)
            return None
        # 捕获其他所有意外错误
        except Exception as e:
            logger.error(f"调用 OpenAI API 时发生未知错误: {e}. Model: {model_id}", exc_info=True)
            return None

    # 可以考虑添加一个异步初始化方法，如果需要在服务启动时就创建客户端并验证
    # async def initialize(self):
    #     """异步初始化 OpenAI 客户端并验证"""
    #     self._get_client() # 尝试初始化
    #     if self._client:
    #         try:
    #             # 尝试进行一次简单的 API 调用来验证连接和密钥
    #             await self._client.models.list(limit=1)
    #             logger.info("OpenAI 客户端连接和密钥验证成功。")
    #         except AuthenticationError:
    #              logger.error("OpenAI API 密钥无效或权限不足。")
    #              self._client = None # 验证失败，重置客户端
    #         except Exception as e:
    #              logger.warning(f"验证 OpenAI 连接时出错 (可能网络问题): {e}")
    #              # 不重置客户端，允许后续重试
