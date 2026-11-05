"""dev 컨테이너 기동 시 관리자 자동 생성

init_database.py가 alembic upgrade head 다음에 호출한다(DEV_BOOTSTRAP_ADMIN=true, dev compose만).
활성 관리자가 한 명도 없을 때만 ADMIN_PASSWORD로 관리자를 만들고, 운영 DB(rag_chatbot_prod)는 거부한다.
운영·수동 생성과 비밀번호 변경은 scripts/create_admin.py(같은 MIN_PASSWORD_LENGTH 사용).
"""
from __future__ import annotations

from app.utils.datetime import now_kst_iso
from app.utils.security import hash_password

MIN_PASSWORD_LENGTH = 10
PROD_DATABASE_NAME = "rag_chatbot_prod"


def ensure_dev_admin(db, user_id: str, name: str, password: str | None) -> tuple[str, str]:
    """활성 관리자가 없을 때만 관리자를 만든다. (결과 코드, 로그 문구)를 돌려준다.

    어떤 경우에도 예외로 기동을 막지 않고, 건너뛴 이유와 다음에 할 일을 문구로 알려 준다.
    비밀번호는 문구에 넣지 않는다.
    """
    if db.url.database == PROD_DATABASE_NAME:
        return "skipped_prod", f"운영 DB({PROD_DATABASE_NAME})에서는 관리자를 자동 생성하지 않습니다. scripts/create_admin.py를 사용하세요."
    if db.execute_query("SELECT 1 FROM tb_users WHERE role = 'admin' AND is_active = TRUE LIMIT 1"):
        return "skipped_admin_exists", "활성 관리자가 이미 있어 자동 생성을 건너뜁니다."
    if not password:
        return "skipped_no_password", (
            "ADMIN_PASSWORD가 .env에 없어 관리자를 만들지 않았습니다. "
            ".env에 추가한 뒤 backend 컨테이너를 재시작하거나 scripts/create_admin.py를 실행하세요."
        )
    if len(password) < MIN_PASSWORD_LENGTH:
        return "skipped_short_password", (
            f"ADMIN_PASSWORD가 {MIN_PASSWORD_LENGTH}자 미만이라 관리자를 만들지 않았습니다. "
            ".env 값을 고친 뒤 backend 컨테이너를 재시작하세요."
        )
    if db.execute_query("SELECT 1 FROM tb_users WHERE user_id = ?", (user_id,)):
        return "skipped_user_exists", (
            f"'{user_id}'는 관리자가 아닌 계정으로 이미 있어 권한을 바꾸지 않았습니다. "
            "DEV_BOOTSTRAP_ADMIN_ID를 다른 아이디로 바꾸세요."
        )
    now = now_kst_iso()
    db.execute_update(
        "INSERT INTO tb_users (user_id, user_pwd, user_name, role, is_active, created_at, updated_at) "
        "VALUES (?, ?, ?, 'admin', TRUE, ?, ?)",
        (user_id, hash_password(password), name, now, now),
    )
    return "created", f"관리자 계정을 만들었습니다: {user_id}"
