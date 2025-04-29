import logging
import os
import asyncio
from typing import List, Dict, Optional

# 导入更具体的错误类型
from openai import (
    AsyncOpenAI,
    OpenAIError,
    APIError,
    AuthenticationError,
    RateLimitError,
    BadRequestError,
)

# 导入 httpx 错误类型
from httpx import RequestError

logger = logging.getLogger(__name__)


class AIService:
    """
    封装与 AI 模型（当前为 OpenAI）交互的服务。
    内部使用流式请求，但对外返回完整响应。
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
        self._base_url = os.getenv("OPENAI_BASE_URL") or None  # None 会使用默认 URL

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
                self._client = AsyncOpenAI(
                    api_key=self._api_key, base_url=self._base_url
                )
                logger.info("AsyncOpenAI 客户端已惰性初始化。")
            except Exception as e:
                logger.error(f"惰性初始化 AsyncOpenAI 客户端失败: {e}", exc_info=True)
                return None  # 初始化失败则返回 None
        return self._client

    async def get_openai_completion(
        self, model_id: str, messages: List[Dict[str, str]]
    ) -> Optional[str]:
        """
        使用 OpenAI API 获取聊天补全。
        内部实现使用流式请求，但将结果拼接后一次性返回。

        Args:
            model_id: 要使用的 OpenAI 模型 ID。
            messages: OpenAI API 所需格式的消息列表。

        Returns:
            生成的完整回复文本，如果发生错误则返回 None。
        """
        logger.debug(
            f"请求 OpenAI 补全 (内部流式): 模型={model_id}, 消息数={len(messages)}"
        )

        client = self._get_client()  # 获取 (或初始化) 客户端
        if not client:
            logger.error("无法获取 OpenAI 客户端实例，取消补全请求。")
            return None  # 如果客户端无法初始化，则直接返回

        full_response = ""  # 用于拼接所有接收到的块
        stream = True  # 初始化 stream 变量
        try:
            # 调用 OpenAI API，启用流式传输
            stream = await client.chat.completions.create(
                model=model_id,
                messages=messages,
                stream=True,  # 内部启用流式响应
                # 可以根据需要添加其他参数，如 temperature, max_tokens 等
                temperature=0.7,
                # max_tokens=1500, # 示例：如果需要限制最大 token
            )

            finish_reason = None
            # 异步迭代处理流式响应，并将内容块拼接到 full_response
            async for chunk in stream:
                # 提取内容块
                content = (
                    chunk.choices[0].delta.content
                    if chunk.choices and chunk.choices[0].delta
                    else None
                )
                if content:
                    full_response += content  # 拼接内容块

                # 记录流结束原因 (通常在最后一个 chunk 中)
                if chunk.choices and chunk.choices[0].finish_reason:
                    finish_reason = chunk.choices[0].finish_reason
                    logger.debug(f"OpenAI 内部流结束。Finish reason: {finish_reason}")

            # 注意：流式响应通常不直接提供最终的 token usage 信息。
            logger.debug("内部流式响应处理完成，已拼接完整内容。")
            # 返回拼接后的完整字符串，去除可能的首尾空白
            return full_response.strip() if full_response else None

        # --- 错误处理 ---
        # 这些异常可能在请求开始时或在流处理期间发生
        except AuthenticationError as e:
            logger.error(f"OpenAI API 认证失败: {e}. 请检查 OPENAI_API_KEY 是否正确。")
            return None
        except RateLimitError as e:
            logger.error(f"OpenAI API 速率限制: {e}. 请检查您的账户配额或稍后重试。")
            return None
        except BadRequestError as e:
            logger.error(
                f"OpenAI API 请求无效 (BadRequestError): {e}. 可能模型不支持或输入格式错误。 Model: {model_id}"
            )
            return None
        except APIError as e:  # 捕获更通用的 OpenAI API 错误
            logger.error(
                f"OpenAI API 返回错误: Status={e.status_code}, Error={e.body}. Model: {model_id}"
            )
            return None
        except RequestError as e:  # 捕获 httpx 网络错误
            logger.error(
                f"连接 OpenAI API 时发生网络错误: {e}. Model: {model_id}", exc_info=True
            )
            return None
        except OpenAIError as e:  # 捕获其他 OpenAI 库错误
            logger.error(f"发生 OpenAI 库错误: {e}. Model: {model_id}", exc_info=True)
            return None
        # 捕获其他所有意外错误
        except Exception as e:
            logger.error(
                f"处理 OpenAI 内部流式响应时发生未知错误: {e}. Model: {model_id}",
                exc_info=True,
            )
            return None
        finally:
            # 根据 openai v1.x+ 的文档，使用 async for 会自动处理流的关闭
            # 无需手动关闭 stream
            logger.debug("内部流式请求处理流程结束（包括正常结束或异常）。")

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
