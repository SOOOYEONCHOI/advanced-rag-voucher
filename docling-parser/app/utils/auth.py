"""
API Key 인증 모듈
"""
import os
from typing import Optional


def get_api_key() -> Optional[str]:
    """환경 변수에서 API Key 가져오기"""
    return os.getenv("API_KEY")


def verify_api_key(provided_key: str) -> bool:
    """
    API Key 검증
    
    Args:
        provided_key: 제공된 API Key
        
    Returns:
        검증 성공 여부
    """
    expected_key = get_api_key()
    if not expected_key:
        # API Key가 설정되지 않은 경우 개발 환경에서는 허용
        return True
    
    return provided_key == expected_key

