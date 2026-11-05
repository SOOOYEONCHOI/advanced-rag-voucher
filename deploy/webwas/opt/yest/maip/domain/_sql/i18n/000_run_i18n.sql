-- MES 다국어 기준 데이터 전체 실행 스크립트
-- 반드시 이 파일을 psql로 실행하며, 010/020/030 파일은 직접 실행하지 않는다.
\set ON_ERROR_STOP on

BEGIN;

\ir 010_template_data_labelcd.sql
\ir 020_template_grid_columns.sql
\ir 030_side_menu_translations.sql

COMMIT;
