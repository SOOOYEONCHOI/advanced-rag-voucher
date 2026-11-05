"""DB 접속 전용 설정 (2026.09.29 추가 - Phase 1.5).

DB 계층·Alembic·이관 스크립트·테스트가 사용한다. 전체 Settings(app.core.config)와 분리해
다른 필수 설정값이나 테스트의 config 모듈 대체와 무관하게 접속 정보를 읽는다.
우선순위: 환경변수 > ../.env(프로젝트 루트) > .env
"""

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """DB 접속 설정만 읽는 경량 설정 (2026.09.29 추가).

    DB 계층·Alembic·이관 스크립트가 사용한다. 전체 Settings의 다른 필수값과 무관하게 로드되고,
    테스트가 get_settings를 대체해도 DB 접속 정보는 유지된다.
    """

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    # 2026.10.16 수정 - DB 이름 규칙: 개발 rag_chatbot_dev / 테스트 rag_chatbot_test / 운영 rag_chatbot_prod (설계 3.7)
    postgres_db: str = "rag_chatbot_dev"
    postgres_user: str = "rag_chatbot"
    postgres_password: str = ""
    database_url: Optional[str] = None
    db_pool_size: int = Field(default=10, gt=0)
    db_max_overflow: int = Field(default=20, ge=0)
    # 2026.10.16 추가 - N-9(MES 공용 서버 보호): 쿼리 시간 제한(0 = 미적용), DBA가 세션을 구분할 이름
    db_statement_timeout_ms: int = Field(default=0, ge=0)
    db_application_name: str = "adrag-backend"

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache()
def get_database_settings() -> DatabaseSettings:
    return DatabaseSettings()
