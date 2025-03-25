import pytest
from unittest.mock import AsyncMock, patch
from telegram_logger.main import main

@pytest.mark.asyncio
async def test_main_success():
    """测试主流程正常启动"""
    mock_client = AsyncMock()
    mock_client.initialize.return_value = 12345
    mock_cleanup = AsyncMock()
    
    with patch('telegram_logger.main.TelegramClientService', return_value=mock_client), \
         patch('telegram_logger.main.CleanupService', return_value=mock_cleanup), \
         patch('telegram_logger.main.DatabaseManager'), \
         patch('telegram_logger.main.configure_logging'):
        
        await main()
        
        # 验证服务初始化
        mock_client.initialize.assert_called_once()
        mock_cleanup.start.assert_called_once()
        
        # 验证服务关闭
        mock_cleanup.stop.assert_called_once()
