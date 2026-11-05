"""
Database initialization script (개발 환경).

2026.10.16 Phase 1.5 수정 - SQLite schema.sql 적용 대신 PostgreSQL에 ``alembic upgrade head``를 실행한다.
dev 이미지 CMD(``python init_database.py && uvicorn …``)가 기동 시 호출한다.
운영 이미지는 이 스크립트를 실행하지 않고, 앱 기동 시 스키마 버전만 확인한다(N-10).
관리자 계정은 ``python scripts/create_admin.py``로 만든다(고정 관리자 시드 없음).
2026.10.20 추가 - DEV_BOOTSTRAP_ADMIN=true(dev compose만)이면 upgrade 후 활성 관리자가 없을 때
``ADMIN_PASSWORD``로 관리자를 자동 생성한다(D-19). 실패해도 기동은 계속한다.
"""

import os
import sys
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.utils.log.log import LoggingLogger
from app.repositories.database import alembic_head, close_database_manager, initialize_database

# 로거 초기화
logger_instance = LoggingLogger()
logger = logger_instance.getLogger()

if __name__ == "__main__":
    logger.info("Initializing database (alembic upgrade head)...")
    manager = initialize_database()
    logger.info(f"✓ Database ready: {manager.url.render_as_string(hide_password=True)} @ {alembic_head()}")
    # 2026.10.20(sooyeon.choi) 수정 - dev 관리자 자동 생성. 기본값 꺼짐 = 기존 동작
    if os.environ.get("DEV_BOOTSTRAP_ADMIN", "").strip().lower() in ("1", "true", "yes"):
        from app.services.admin_bootstrap import ensure_dev_admin

        try:
            result, message = ensure_dev_admin(
                manager,
                os.environ.get("DEV_BOOTSTRAP_ADMIN_ID", "").strip() or "admin",
                "관리자",
                os.environ.get("ADMIN_PASSWORD"),
            )
            if result in ("created", "skipped_admin_exists"):
                logger.info(f"[dev 관리자] {message}")
            else:
                logger.warning(f"[dev 관리자] {message}")
        except Exception as exc:
            logger.warning(f"[dev 관리자] 자동 생성 실패(기동은 계속): {exc}")
    close_database_manager()
