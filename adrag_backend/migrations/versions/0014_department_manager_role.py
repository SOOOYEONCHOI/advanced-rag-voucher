"""0014_department_manager_role (2026.11.23 부서 운영관리자 역할 추가).

- tb_users.role / tb_login_history.user_role 에 'manager'를 추가한다.
- 부서별 manager는 한 명만 허용한다.

Revision ID: 0014_department_manager_role
Revises: 0013_eval_qa_single_source
Create Date: 2026-11-23
"""

from alembic import op


revision = "0014_department_manager_role"
down_revision = "0013_eval_qa_single_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tb_users DROP CONSTRAINT IF EXISTS tb_users_role_check")
    op.execute(
        "ALTER TABLE tb_users ADD CONSTRAINT tb_users_role_check "
        "CHECK (role IN ('admin', 'manager', 'user'))"
    )
    op.execute("ALTER TABLE tb_login_history DROP CONSTRAINT IF EXISTS tb_login_history_user_role_check")
    op.execute(
        "ALTER TABLE tb_login_history ADD CONSTRAINT tb_login_history_user_role_check "
        "CHECK (user_role IN ('admin', 'manager', 'user'))"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_department_manager "
        "ON tb_users(department_id) WHERE role = 'manager'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_users_department_manager")
    op.execute("UPDATE tb_users SET role = 'user' WHERE role = 'manager'")
    op.execute("UPDATE tb_login_history SET user_role = 'user' WHERE user_role = 'manager'")
    op.execute("ALTER TABLE tb_users DROP CONSTRAINT IF EXISTS tb_users_role_check")
    op.execute("ALTER TABLE tb_users ADD CONSTRAINT tb_users_role_check CHECK (role IN ('admin', 'user'))")
    op.execute("ALTER TABLE tb_login_history DROP CONSTRAINT IF EXISTS tb_login_history_user_role_check")
    op.execute(
        "ALTER TABLE tb_login_history ADD CONSTRAINT tb_login_history_user_role_check "
        "CHECK (user_role IN ('admin', 'user'))"
    )
