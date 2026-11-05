"""로그 화면(raw SQL)의 서버 페이징 — `DbUtil.get_page`.

로그 SQL 은 PostgreSQL 함수(`to_char`·`ilike`)를 써서 SQLite 테스트로 돌리지 못한다.
페이지 자르기만 여기서 보고, 실제 SQL 경로는 e2e(`tests/e2e/test_grid_common.py`)가 본다.
"""
from django.contrib.auth.models import User
from django.test import TestCase

from app.views.item import page_params
from domain.services.sql import DbUtil

SQL = 'select username from auth_user where username like %(prefix)s order by username'


class GetPageTest(TestCase):
    def setUp(self):
        for index in range(5):
            User.objects.create(username=f'paging-{index}')

    def test_요청한_페이지만_주고_전체_건수를_함께_준다(self):
        page = DbUtil.get_page(SQL, {'prefix': 'paging-%'}, page=2, size=2)
        self.assertEqual(page['totalRows'], 5)
        self.assertEqual([row['username'] for row in page['rows']], ['paging-2', 'paging-3'])

    def test_크기를_비우면_조건에_맞는_전부를_준다(self):
        page = DbUtil.get_page(SQL, {'prefix': 'paging-%'}, page=1, size=None)
        self.assertEqual((page['totalRows'], len(page['rows'])), (5, 5))


class PageParamsTest(TestCase):
    def test_로그는_200건까지_받는다(self):
        self.assertEqual(page_params({'page': '2', 'page_size': '500'}, 50, max_size=200), (2, 200))
        self.assertEqual(page_params({}, 50, max_size=200), (1, 50))
