"""raw SQL 실행 유틸.

Django ORM 으로 표현하기 어려운 조회(메뉴 트리 재귀 CTE 등)에 쓴다.
대상 DBMS 는 PostgreSQL 하나다 — 원본 MES 의 MSSQL 분기는 제거했다.
"""
from django.db import connection


class DbUtil(object):

    @classmethod
    def get_connection(cls):
        return connection

    @classmethod
    def _dict_fetchall(cls, cursor):
        "Return all rows from a cursor as a dict"
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    @classmethod
    def _dict_fetchone(cls, cursor):
        "Return one row from a cursor as a dict"
        columns = [col[0] for col in cursor.description]
        row = cursor.fetchone()
        if row:
            return dict(zip(columns, row))
        else:
            return None

    @classmethod
    def sql_remove_comment(cls, sql):
        """ sql 문에서 주석 처리된 라인을 제거. 주석 라인에 파라미터 있을 경우 에러를 제거
        """
        strings = sql.split(chr(10))
        ret = []
        for item in strings:
            if not item.strip().startswith('--'):
                ret.append(item)
        new_sql = chr(10).join(ret)
        return new_sql

    @classmethod
    def execute_param(cls, cursor, sql, param):
        """이름 있는 파라미터(%(name)s) 바인딩 실행."""
        try:
            cursor.execute(sql, param)
        except Exception as ex:
            print(ex)
            print(' '.join(sql.split()))
            raise ex

    @classmethod
    def get_rows(cls, sql, param=None):
        """Return query resultset in dictionay
        """
        conn = cls.get_connection()
        cursor = conn.cursor()

        if param:
            cls.execute_param(cursor, sql, param)
        else:
            cursor.execute(sql)

        rows = cls._dict_fetchall(cursor)
        cursor.close()
        return rows

    @classmethod
    def get_row(cls, sql, param=None):
        """Return one result or query in dictionay
        """
        conn = cls.get_connection()
        cursor = conn.cursor()

        if param:
            cls.execute_param(cursor, sql, param)
        else:
            cursor.execute(sql)

        row = cls._dict_fetchone(cursor)
        cursor.close()
        return row

    @classmethod
    def get_page(cls, sql, param, page, size):
        """서버 페이징 목록 `{rows, totalRows}`. sql 은 ORDER BY 까지 갖는다. size 가 None 이면 전부(엑셀)."""
        total = cls.get_row('select count(*) as cnt from (' + sql + ') t', param)['cnt']
        if size is None:
            return {'rows': cls.get_rows(sql, param), 'totalRows': total}
        param = dict(param, _limit=size, _offset=(page - 1) * size)
        return {'rows': cls.get_rows(sql + ' limit %(_limit)s offset %(_offset)s', param), 'totalRows': total}

    @classmethod
    def get_rows_list(cls, sql, param=None):
        """Return query resultset in list
        """
        conn = cls.get_connection()
        cursor = conn.cursor()

        if param:
            cls.execute_param(cursor, sql, param)
        else:
            cursor.execute(sql)

        rows = cursor.fetchall()
        cursor.close()
        return rows

    @classmethod
    def get_row_list(cls, sql, param=None):
        """Return one result or query  in list
        """
        conn = cls.get_connection()
        cursor = conn.cursor()

        if param:
            cls.execute_param(cursor, sql, param)
        else:
            cursor.execute(sql)

        rows = cursor.fetchall()
        cursor.close()

        if rows:
            row = rows[0]
        else:
            row = {}

        return row

    @classmethod
    def execute(cls, sql, param=None):
        """Exectue insert, update, delete query and return success(booleand)
        """
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            if param:
                cls.execute_param(cursor, sql, param)
            else:
                cursor.execute(sql)
            return True
        except Exception as ex:
            raise ex
        finally:
            cursor.close()
