"""관리자 계정 생성 / 비밀번호 재설정 (2026.09.29 Phase 1.5).

기존에는 스키마 초기화 때 고정 비밀번호의 admin 계정이 자동 생성됐다(스키마 진단 F01).
PostgreSQL 기준 스키마에서는 시드를 제거했으므로 최초 관리자는 이 스크립트로 만든다.

사용법 (adrag_backend 폴더에서)
    python scripts/create_admin.py --user-id admin --name 관리자            # 비밀번호는 프롬프트로 입력
    python scripts/create_admin.py --user-id admin --reset-password          # 기존 관리자 비밀번호 변경
비대화형 실행 시 비밀번호는 환경변수 ADMIN_PASSWORD로 전달한다(명령행 인자로 받지 않는다).

2026.10.20 추가 - dev 컨테이너 자동 생성(D-19)은 app/services/admin_bootstrap.py(init_database.py가 호출).
이 스크립트는 운영 최초 생성·비밀번호 변경용 명령행 도구다.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.repositories.database import get_database_manager  # noqa: E402
# 2026.10.20 수정 - 비밀번호 최소 길이는 dev 자동 생성과 같은 값을 쓴다(D-19)
from app.services.admin_bootstrap import MIN_PASSWORD_LENGTH  # noqa: E402
from app.utils.datetime import now_kst_iso  # noqa: E402
from app.utils.security import hash_password  # noqa: E402


def read_password() -> str:
    password = os.environ.get("ADMIN_PASSWORD")
    if password is None:
        password = getpass.getpass("새 비밀번호: ")
        if password != getpass.getpass("비밀번호 확인: "):
            raise SystemExit("비밀번호가 일치하지 않습니다.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"비밀번호는 {MIN_PASSWORD_LENGTH}자 이상이어야 합니다.")
    return password


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--name", default="관리자")
    parser.add_argument("--reset-password", action="store_true", help="기존 관리자 계정의 비밀번호만 변경")
    args = parser.parse_args()

    db = get_database_manager()
    existing = db.execute_query("SELECT role FROM tb_users WHERE user_id = ?", (args.user_id,))
    now = now_kst_iso()
    if args.reset_password:
        if not existing or existing[0]["role"] != "admin":
            print(f"관리자 계정이 없습니다: {args.user_id}", file=sys.stderr)
            return 1
        db.execute_update(
            "UPDATE tb_users SET user_pwd = ?, updated_at = ? WHERE user_id = ? AND role = 'admin'",
            (hash_password(read_password()), now, args.user_id),
        )
        print(f"관리자 비밀번호를 변경했습니다: {args.user_id}")
        return 0

    if existing:
        print(f"이미 존재하는 계정입니다: {args.user_id} (비밀번호 변경은 --reset-password)", file=sys.stderr)
        return 1
    db.execute_update(
        "INSERT INTO tb_users (user_id, user_pwd, user_name, role, is_active, created_at, updated_at) "
        "VALUES (?, ?, ?, 'admin', TRUE, ?, ?)",
        (args.user_id, hash_password(read_password()), args.name, now, now),
    )
    print(f"관리자 계정을 만들었습니다: {args.user_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
