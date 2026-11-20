"""0011_user_pwd_changed_at (2026.11.13 사용자 비밀번호 변경).

근거: adrag_frontend/docs/chat_UI-비밀번호변경_20261113.html
- tb_users.pwd_changed_at: 사용자가 비밀번호를 마지막으로 변경한 시각(NULL=변경 이력 없음).
  이 시각보다 먼저 발급된 일반 사용자 토큰(JWT iat)은 거부한다(app/utils/security.py).
  → 비밀번호를 바꾸면 모든 기기에서 로그아웃된다.

downgrade: 컬럼 삭제(변경 시각이 사라져 이전 토큰이 만료 전까지 다시 유효해진다).

Revision ID: 0011_user_pwd_changed_at
Revises: 0010_drawing_ingest_steps
Create Date: 2026-11-13
"""
from alembic import op

revision = "0011_user_pwd_changed_at"
down_revision = "0010_drawing_ingest_steps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tb_users ADD COLUMN IF NOT EXISTS pwd_changed_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE tb_users DROP COLUMN IF EXISTS pwd_changed_at")
