# -*- coding: utf-8 -*-
"""
项目启动入口脚本。
加载环境变量并调用核心应用程序逻辑。
"""
import asyncio
import os
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
# 这对于确保 telegram_logger 包在导入时能访问到配置至关重要
load_dotenv()

# 从 telegram_logger 包导入核心的 main 函数
# 使用 'as' 重命名以避免潜在的命名冲突，并提高可读性
from telegram_logger.main import main as run_telegram_logger

if __name__ == "__main__":
    # 运行 telegram_logger 包中定义的异步主函数
    # asyncio.run 会处理事件循环的启动和关闭
    asyncio.run(run_telegram_logger())
