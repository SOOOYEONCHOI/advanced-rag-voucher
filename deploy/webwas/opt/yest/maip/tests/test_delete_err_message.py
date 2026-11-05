"""삭제가 외래키에 걸렸을 때 사용자에게 보일 문구.

psycopg 의 IntegrityError 는 인자가 하나라 `ex.args[1]` 에서 IndexError 가 났고,
파서는 한국어 PostgreSQL 메시지('테이블')만 알았다. 그래서 늘 일반 문구로 떨어지면서
오류 로그('LogWriter.delete_message tuple index out of range')가 하나 더 쌓였다.
"""
from unittest.mock import patch

from django.db import IntegrityError
from django.db.models import ProtectedError
from django.test import SimpleTestCase

from domain.services.logging import LogWriter

PG = ('update or delete on table "auth_user" violates foreign key constraint '
      '"login_log_User_id_1986ca11_fk_auth_user_id" on table "login_log"\n'
      'DETAIL:  Key (id)=(17) is still referenced from table "login_log".')


class DeleteErrMessageTest(SimpleTestCase):

    def _message(self, ex):
        with patch.object(LogWriter, 'add_dblog') as log:
            message = LogWriter.delete_err_message(ex)
        self.assertFalse(log.called, '문구를 만들다 오류 로그를 남기면 안 된다')
        return message

    def test_PostgreSQL_외래키_오류는_참조하는_표_이름을_쓴다(self):
        self.assertEqual(self._message(IntegrityError(PG)),
                         '로그인로그에서 사용 중이라 삭제할 수 없습니다.')

    def test_ProtectedError_도_참조하는_표_이름을_쓴다(self):
        ex = ProtectedError("Cannot delete some instances of model 'User' because they are "
                            "referenced through protected foreign keys: 'LoginLog.User'.", set())
        self.assertEqual(self._message(ex), '로그인로그에서 사용 중이라 삭제할 수 없습니다.')

    def test_표를_모르면_일반_문구다(self):
        self.assertEqual(self._message(IntegrityError('on table "unknown_table"')),
                         '다른 곳에서 사용 중인 데이터라 삭제할 수 없습니다.')
