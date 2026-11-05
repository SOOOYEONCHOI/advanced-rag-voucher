"""제조AI플랫폼 스키마 전체(2026-10-23 에 옛 0001~0021 을 하나로 다시 정리했다. 그 전 정리는 2026-10-12 의 옛 0001~0015).

모델이 만드는 테이블 다음에, 모델로 표현되지 않는 PostgreSQL 객체를 만든다(SQLite 테스트에서는 건너뛴다).

- 시퀀스 `dig_form_code_seq` — 디지털 양식코드 순번
- SQL 함수 `fn_code_name`·`fn_class_data_text` — raw SQL 서비스가 부른다(원본 MES DB 에만 있던 것)
- 뷰 `v_menu_folder` — 좌측 메뉴 트리. `menu_folder` 를 재귀로 펼쳐 계층·정렬 경로를 계산한다
  (`path` 는 폴더 5자리, 메뉴는 호출부에서 `-9` + 3자리를 덧붙여 같은 계층에서 하위폴더보다 뒤에 온다.
  `folder_order` 는 최상위 폴더 순서를 하위까지 물려준다)
- 테넌트 테이블 14개 Row Level Security(`TENANT_TABLES`)와 단일 조직 제약

옛 0018·0021 의 데이터 단계(기존 행의 촬영 방식·등록 경로 보정)는 빈 DB 에 할 일이 없어 옮기지 않았다.
이미 옛 0001~0021 을 모두 적용한 DB 는 `0001_initial` 기록이 있어 이 파일을 다시 돌리지 않는다 — 파일 없는 옛 기록 줄은
`python manage.py migrate domain --prune` 으로 지운다. 정리할 때 옛 마이그레이션으로 만든 스키마와 이 파일로 만든 스키마가
같은지 빈 PostgreSQL 두 개로 비교했다.
"""
import django.db.models.deletion
import domain.models.system
import domain.models.vision
import domain.storage
import uuid
from django.conf import settings
from django.db import migrations, models

from ._pgsql import run_sql

# 양식 편집이 새 양식코드(DF + 4자리)를 nextval('dig_form_code_seq') 로 매긴다. 모델이 아니라 직접 만든다.
DIG_FORM_CODE_SEQ = "CREATE SEQUENCE IF NOT EXISTS dig_form_code_seq START 1"

FN_CODE_NAME = """
CREATE OR REPLACE FUNCTION fn_code_name(p_code_type text, p_code text)
RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT c."Value" FROM sys_code c
    WHERE c."CodeType" = p_code_type AND c."Code" = p_code
    LIMIT 1
$$;
"""

FN_CLASS_DATA_TEXT = """
CREATE OR REPLACE FUNCTION fn_class_data_text(p_table_name text, p_class_name text, p_data_pk integer)
RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT string_agg(COALESCE(fn_code_name(p_class_name, d."Tag"), d."Tag"), ', ' ORDER BY d."Tag")
    FROM class_data d
    WHERE d."TableName" = p_table_name
      AND d."ClassName" = p_class_name
      AND d."DataPk" = p_data_pk
$$;
"""

V_MENU_FOLDER = """
CREATE OR REPLACE VIEW v_menu_folder AS
WITH RECURSIVE f AS (
    SELECT mf.id                                        AS folder_id,
           mf."FolderName"                              AS folder_name,
           mf."Parent_id"                               AS p_folder_id,
           1                                            AS _level,
           LPAD(COALESCE(mf._order, 0)::text, 5, '0')   AS path,
           COALESCE(mf._order, 0)                       AS folder_order,
           mf."IconCSS"                                 AS icon
      FROM menu_folder mf
     WHERE mf."Parent_id" IS NULL
    UNION ALL
    SELECT c.id,
           c."FolderName",
           c."Parent_id",
           f._level + 1,
           f.path || '-' || LPAD(COALESCE(c._order, 0)::text, 5, '0'),
           f.folder_order,
           c."IconCSS"
      FROM menu_folder c
      JOIN f ON c."Parent_id" = f.folder_id
)
SELECT folder_id, folder_name, p_folder_id, _level, path, folder_order, icon FROM f;
"""

# 테넌트 테이블 Row Level Security. 조직이 하나뿐이어도 정책을 남긴다 —
# 조직이 늘면 제약만 풀면 되고, 애플리케이션이 `tenant` 필터를 빠뜨려도 DB 가 막는다.
# `FORCE ROW LEVEL SECURITY` 라 테이블 소유자에게도 적용된다. `SET LOCAL app.tenant_id` 없이 읽으면
# 0행이다 — `domain.tenancy.tenant_atomic()` 안에서만 데이터를 다루는 이유다.
TENANT_TABLES = [
    'vision_data_activitylog',
    'vision_data_annotation',
    'vision_data_backgroundjob',
    'vision_data_category',
    'vision_data_dataset',
    'vision_data_datasetversion',
    'vision_data_exportjob',
    'vision_data_imageasset',
    'vision_data_item',
    'vision_data_itemdeletionrequest',
    'vision_data_labelclass',
    'vision_data_labelingtask',
    'vision_data_measurementpoint',
    'vision_data_tenantmembership',
]
TENANT_SCOPE = "tenant_id::text = current_setting('app.tenant_id', true)"

# 조직이 하나뿐임을 DB 가 보장한다. 두 번째 행이 들어가면 RLS 컨텍스트를 고정한
# current_tenant() 가 조용히 틀린 데이터를 보게 된다.
SINGLE_TENANT = """
ALTER TABLE vision_data_tenant
  ADD CONSTRAINT ck_single_tenant
  CHECK (id = '00000000-0000-4000-8000-000000000001'::uuid);
"""


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for table in TENANT_TABLES:
        schema_editor.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;')
        schema_editor.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY;')
        schema_editor.execute(
            f'CREATE POLICY {table}_tenant_scope ON {table} '
            f'USING ({TENANT_SCOPE}) WITH CHECK ({TENANT_SCOPE});')
    schema_editor.execute(SINGLE_TENANT)


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute(
        'ALTER TABLE vision_data_tenant DROP CONSTRAINT IF EXISTS ck_single_tenant;')
    for table in TENANT_TABLES:
        schema_editor.execute(f'DROP POLICY IF EXISTS {table}_tenant_scope ON {table};')
        schema_editor.execute(f'ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;')
        schema_editor.execute(f'ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;')


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Dataset",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=160)),
                ("version", models.CharField(default="v0.1", max_length=32)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("RAW", "RAW · 수집됨"),
                            ("VALIDATED", "VALIDATED · 점검됨"),
                            ("LABELED", "LABELED · 라벨링됨"),
                            ("CURATED", "CURATED · 검수됨"),
                            ("EXPORTED", "EXPORTED · 내보냄"),
                        ],
                        default="RAW",
                        max_length=16,
                    ),
                ),
                (
                    "source_type",
                    models.CharField(default="DIGITAL_UPLOAD", max_length=32),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "데이터셋",
                "db_table": "vision_data_dataset",
                "ordering": ["-updated_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="DigFormWorkClass",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                (
                    "Class1Name",
                    models.CharField(max_length=100, verbose_name="대분류명"),
                ),
                (
                    "Class2Name",
                    models.CharField(
                        max_length=100, null=True, verbose_name="중분류명"
                    ),
                ),
                (
                    "Class3Name",
                    models.CharField(
                        max_length=100, null=True, verbose_name="소분류명"
                    ),
                ),
                (
                    "Description",
                    models.CharField(max_length=500, null=True, verbose_name="비고"),
                ),
            ],
            options={
                "verbose_name": "디지털양식-항목별작업마스터",
                "db_table": "dig_form_work_class",
            },
        ),
        migrations.CreateModel(
            name="IfBatch",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                (
                    "Kind",
                    models.CharField(
                        choices=[
                            ("PLM_PART_BOM", "PLM 품목·BOM"),
                            ("ERP_PURCHASE_REQ", "ERP 구매요청 현황"),
                        ],
                        max_length=30,
                        verbose_name="인터페이스구분",
                    ),
                ),
                (
                    "Channel",
                    models.CharField(
                        choices=[("FILE", "파일"), ("API", "API"), ("DB", "DB 연동")],
                        db_default="FILE",
                        default="FILE",
                        max_length=10,
                        verbose_name="수신경로",
                    ),
                ),
                (
                    "SourceRef",
                    models.CharField(max_length=255, null=True, verbose_name="출처"),
                ),
                ("RowCount", models.IntegerField(verbose_name="행수")),
                (
                    "Status",
                    models.CharField(
                        choices=[
                            ("RECEIVE_FAILED", "수신 실패"),
                            ("RECEIVED", "반영 대기"),
                            ("APPLIED", "반영 완료"),
                            ("APPLY_FAILED", "반영 실패"),
                        ],
                        db_default="RECEIVED",
                        default="RECEIVED",
                        max_length=20,
                        verbose_name="상태",
                    ),
                ),
                ("Message", models.TextField(null=True, verbose_name="메시지")),
                ("AppliedAt", models.DateTimeField(null=True, verbose_name="반영일시")),
                ("ApplyResult", models.JSONField(null=True, verbose_name="반영결과")),
            ],
            options={
                "verbose_name": "인터페이스-수신건",
                "db_table": "if_batch",
            },
        ),
        migrations.CreateModel(
            name="IntegrationClient",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "client_id",
                    models.CharField(
                        max_length=50, unique=True, verbose_name="Client ID"
                    ),
                ),
                ("name", models.CharField(max_length=100, verbose_name="연동 이름")),
                (
                    "api_key_hash",
                    models.CharField(
                        max_length=64, unique=True, verbose_name="API Key 해시"
                    ),
                ),
                ("active", models.BooleanField(default=True, verbose_name="사용")),
                (
                    "last_seen_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="최근 접속"
                    ),
                ),
            ],
            options={
                "verbose_name": "외부 연동 키",
                "db_table": "integration_client",
                "ordering": ["client_id"],
            },
        ),
        migrations.CreateModel(
            name="Tenant",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=140, verbose_name="조직명")),
                ("description", models.TextField(blank=True, verbose_name="설명")),
                (
                    "status",
                    models.CharField(
                        choices=[("ACTIVE", "활성"), ("SUSPENDED", "일시 중지")],
                        default="ACTIVE",
                        max_length=16,
                        verbose_name="상태",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "조직",
                "db_table": "vision_data_tenant",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="AttachFile",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("TableName", models.CharField(max_length=50, verbose_name="테이블명")),
                ("DataPk", models.IntegerField(verbose_name="데이터pk")),
                ("AttachName", models.CharField(max_length=50, verbose_name="첨부명")),
                ("FileIndex", models.IntegerField(verbose_name="파일인덱스")),
                ("FileName", models.CharField(max_length=100, verbose_name="파일명")),
                (
                    "PhysicFileName",
                    models.CharField(max_length=100, verbose_name="물리파일명"),
                ),
                (
                    "ExtName",
                    models.CharField(max_length=10, null=True, verbose_name="확장자"),
                ),
                (
                    "FilePath",
                    models.CharField(
                        max_length=500, null=True, verbose_name="파일경로"
                    ),
                ),
                ("FileSize", models.IntegerField(null=True, verbose_name="파일사이즈")),
            ],
            options={
                "verbose_name": "첨부파일",
                "db_table": "attach_file",
                "indexes": [
                    models.Index(
                        fields=["DataPk", "TableName"], name="attach_file_pk_table_idx"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="AttachMaster",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("TableName", models.CharField(max_length=50, verbose_name="테이블명")),
                ("AttachName", models.CharField(max_length=50, verbose_name="첨부명")),
                (
                    "Description",
                    models.CharField(max_length=500, null=True, verbose_name="설명"),
                ),
                (
                    "FilePath",
                    models.CharField(
                        max_length=500, null=True, verbose_name="파일경로"
                    ),
                ),
            ],
            options={
                "verbose_name": "첨부파일정의",
                "db_table": "attach_master",
                "indexes": [
                    models.Index(fields=["TableName"], name="attach_master_table_idx")
                ],
            },
        ),
        migrations.CreateModel(
            name="ClassData",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("DataPk", models.IntegerField(verbose_name="데이터pk")),
                ("TableName", models.CharField(max_length=50, verbose_name="테이블명")),
                (
                    "ClassName",
                    models.CharField(
                        default="Basic", max_length=50, verbose_name="분류명"
                    ),
                ),
                ("Tag", models.CharField(max_length=100, verbose_name="분류코드")),
            ],
            options={
                "verbose_name": "분류데이터",
                "db_table": "class_data",
                "indexes": [
                    models.Index(
                        fields=["TableName", "ClassName", "Tag", "DataPk"],
                        name="class_data_tbl_cls_tag_pk_idx",
                    )
                ],
                "unique_together": {("DataPk", "TableName", "ClassName", "Tag")},
            },
        ),
        migrations.CreateModel(
            name="ClassMaster",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("TableName", models.CharField(max_length=50, verbose_name="테이블명")),
                (
                    "ClassName",
                    models.CharField(
                        default="Basic", max_length=50, verbose_name="분류명"
                    ),
                ),
                ("Tag", models.CharField(max_length=100, verbose_name="분류코드")),
            ],
            options={
                "verbose_name": "분류마스터",
                "db_table": "class_master",
                "unique_together": {("TableName", "Tag", "ClassName")},
            },
        ),
        migrations.CreateModel(
            name="Company",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("Name", models.CharField(max_length=50, verbose_name="업체명")),
                (
                    "EngName",
                    models.CharField(
                        max_length=100, null=True, verbose_name="영문업체명"
                    ),
                ),
                (
                    "Code",
                    models.CharField(max_length=50, null=True, verbose_name="업체코드"),
                ),
                (
                    "Code2",
                    models.CharField(
                        max_length=50, null=True, verbose_name="업체코드2"
                    ),
                ),
                (
                    "Country",
                    models.CharField(max_length=50, null=True, verbose_name="국가"),
                ),
                (
                    "CompanyType",
                    models.CharField(max_length=30, null=True, verbose_name="업체유형"),
                ),
                (
                    "GroupName",
                    models.CharField(
                        max_length=100, null=True, verbose_name="업체그룹"
                    ),
                ),
                (
                    "BusinessNumber",
                    models.CharField(
                        max_length=50, null=True, verbose_name="사업자번호"
                    ),
                ),
                (
                    "CEOName",
                    models.CharField(max_length=50, null=True, verbose_name="대표이사"),
                ),
                (
                    "ZipCode",
                    models.CharField(max_length=50, null=True, verbose_name="우편번호"),
                ),
                (
                    "Address",
                    models.CharField(max_length=100, null=True, verbose_name="주소"),
                ),
                (
                    "TelNumber",
                    models.CharField(
                        max_length=100, null=True, verbose_name="전화번호"
                    ),
                ),
                (
                    "FaxNumber",
                    models.CharField(
                        max_length=100, null=True, verbose_name="팩스번호"
                    ),
                ),
                (
                    "BusinessType",
                    models.CharField(max_length=50, null=True, verbose_name="업태"),
                ),
                (
                    "BusinessItem",
                    models.CharField(max_length=50, null=True, verbose_name="종목"),
                ),
                (
                    "Email",
                    models.EmailField(max_length=254, null=True, verbose_name="이메일"),
                ),
                (
                    "Homepage",
                    models.CharField(
                        max_length=100, null=True, verbose_name="홈페이지"
                    ),
                ),
                (
                    "ShippingLocation",
                    models.CharField(
                        max_length=100, null=True, verbose_name="출하장소"
                    ),
                ),
                (
                    "Description",
                    models.CharField(max_length=500, null=True, verbose_name="비고"),
                ),
                (
                    "PurchaseSalesDeadline",
                    models.CharField(
                        max_length=50, null=True, verbose_name="매입매출마감일"
                    ),
                ),
                (
                    "TradingGrade",
                    models.CharField(max_length=30, null=True, verbose_name="거래등급"),
                ),
                (
                    "FirstTradingDay",
                    models.DateField(null=True, verbose_name="거래개시일"),
                ),
                (
                    "LastTradingDay",
                    models.DateField(null=True, verbose_name="최종거래일"),
                ),
                (
                    "OurManager",
                    models.CharField(
                        max_length=50, null=True, verbose_name="자사담당자"
                    ),
                ),
                (
                    "SalesManager",
                    models.CharField(
                        max_length=50, null=True, verbose_name="영업담당자"
                    ),
                ),
                (
                    "SalesManagerPhone",
                    models.CharField(
                        max_length=50, null=True, verbose_name="영업담당자전번"
                    ),
                ),
                (
                    "AccountManager",
                    models.CharField(
                        max_length=50, null=True, verbose_name="경리담당자"
                    ),
                ),
                (
                    "AccountManagerPhone",
                    models.CharField(
                        max_length=50, null=True, verbose_name="경리담당자전번"
                    ),
                ),
                (
                    "ReceivableAmount",
                    models.DecimalField(
                        decimal_places=3,
                        max_digits=18,
                        null=True,
                        verbose_name="미수금액",
                    ),
                ),
                (
                    "UnpaidAmount",
                    models.DecimalField(
                        decimal_places=3,
                        max_digits=18,
                        null=True,
                        verbose_name="미지급금액",
                    ),
                ),
                (
                    "TrandingBank",
                    models.CharField(max_length=50, null=True, verbose_name="거래은행"),
                ),
                (
                    "AccountHolder",
                    models.CharField(max_length=50, null=True, verbose_name="예금주"),
                ),
                (
                    "AccountNumber",
                    models.CharField(max_length=50, null=True, verbose_name="계좌번호"),
                ),
                (
                    "CreditLimitAmount",
                    models.DecimalField(
                        decimal_places=3,
                        max_digits=18,
                        null=True,
                        verbose_name="여신한도금액",
                    ),
                ),
                (
                    "PaymentCondition",
                    models.CharField(
                        max_length=50, null=True, verbose_name="대금결제조건"
                    ),
                ),
                (
                    "ManageRemark",
                    models.CharField(
                        max_length=500, null=True, verbose_name="관리비고"
                    ),
                ),
                (
                    "PaymentMethod",
                    models.CharField(max_length=200, verbose_name="결재방법"),
                ),
                (
                    "CompanyTelNumber",
                    models.CharField(
                        max_length=50, null=True, verbose_name="전화번호2"
                    ),
                ),
            ],
            options={
                "verbose_name": "업체",
                "db_table": "company",
                "unique_together": {("BusinessNumber",), ("Code",), ("Name",)},
            },
        ),
        migrations.CreateModel(
            name="DatasetVersion",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("version_tag", models.CharField(max_length=32)),
                ("manifest", models.JSONField(default=dict)),
                ("is_immutable", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "dataset",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="versions",
                        to="domain.dataset",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(class)s_records",
                        to="domain.tenant",
                    ),
                ),
            ],
            options={
                "verbose_name": "스냅샷",
                "db_table": "vision_data_datasetversion",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="Depart",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("Name", models.CharField(max_length=200, verbose_name="부서명")),
                (
                    "Code",
                    models.CharField(
                        max_length=50,
                        null=True,
                        validators=[domain.models.system.space_check],
                        verbose_name="부서코드",
                    ),
                ),
                (
                    "Type",
                    models.CharField(max_length=20, null=True, verbose_name="부서유형"),
                ),
                (
                    "Description",
                    models.CharField(max_length=1000, null=True, verbose_name="비고"),
                ),
            ],
            options={
                "verbose_name": "부서",
                "db_table": "depart",
                "unique_together": {("Code",), ("Name",)},
            },
        ),
        migrations.CreateModel(
            name="DigForm",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("Code", models.CharField(max_length=20, verbose_name="양식코드")),
                ("Version", models.IntegerField(default=1, verbose_name="버전")),
                ("Title", models.CharField(max_length=200, verbose_name="제목")),
                ("Content", models.TextField(null=True, verbose_name="내용")),
                (
                    "TotalColumnWidth",
                    models.IntegerField(null=True, verbose_name="총컬럼넓이"),
                ),
                (
                    "HeaderHeight",
                    models.IntegerField(null=True, verbose_name="헤더높이"),
                ),
                (
                    "FixedTopContent",
                    models.TextField(null=True, verbose_name="상단고정내용"),
                ),
                ("EstablishDate", models.DateField(null=True, verbose_name="제정일")),
                (
                    "ApplyModel",
                    models.CharField(
                        max_length=100, null=True, verbose_name="적용모델"
                    ),
                ),
                (
                    "UseYN",
                    models.CharField(
                        default="Y", max_length=1, verbose_name="사용여부"
                    ),
                ),
                ("StartDate", models.DateField(null=True, verbose_name="적용시작일")),
                ("EndDate", models.DateField(null=True, verbose_name="적용종료일")),
                (
                    "Description",
                    models.CharField(max_length=500, null=True, verbose_name="비고"),
                ),
                (
                    "LayoutType",
                    models.CharField(
                        default="GRID", max_length=10, verbose_name="레이아웃구분"
                    ),
                ),
                (
                    "FormType",
                    models.CharField(
                        db_default="OUTGOING",
                        default="OUTGOING",
                        max_length=10,
                        verbose_name="양식구분",
                    ),
                ),
            ],
            options={
                "verbose_name": "디지털양식-문서헤더",
                "db_table": "dig_form",
                "unique_together": {("Code", "Version")},
            },
        ),
        migrations.CreateModel(
            name="DigFormResult",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("WriteDate", models.DateField(verbose_name="작성일")),
                (
                    "WorkOrderNumber",
                    models.CharField(max_length=50, null=True, verbose_name="작지번호"),
                ),
                (
                    "State",
                    models.CharField(
                        default="working", max_length=20, verbose_name="작성상태"
                    ),
                ),
                ("Round", models.IntegerField(default=1, verbose_name="차수")),
                (
                    "Description",
                    models.CharField(max_length=500, null=True, verbose_name="비고"),
                ),
                (
                    "HeaderValues",
                    models.TextField(null=True, verbose_name="머리글입력값"),
                ),
                (
                    "DigForm",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="domain.digform"
                    ),
                ),
            ],
            options={
                "verbose_name": "디지털양식-문서헤더결과",
                "db_table": "dig_form_result",
            },
        ),
        migrations.CreateModel(
            name="DigFormSection",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                (
                    "SectionType",
                    models.CharField(max_length=20, verbose_name="섹션구분"),
                ),
                (
                    "Title",
                    models.CharField(max_length=200, null=True, verbose_name="제목"),
                ),
                ("Content", models.TextField(null=True, verbose_name="내용")),
                ("SortOrder", models.IntegerField(default=0, verbose_name="순서")),
                ("Width", models.IntegerField(null=True, verbose_name="너비")),
                ("Height", models.IntegerField(null=True, verbose_name="높이")),
                (
                    "ColumnCount",
                    models.IntegerField(null=True, verbose_name="컬럼개수"),
                ),
                (
                    "HeaderRowCount",
                    models.IntegerField(default=1, verbose_name="머리줄행수"),
                ),
                (
                    "WorkerColumnYN",
                    models.CharField(
                        default="Y", max_length=1, verbose_name="작업자표시여부"
                    ),
                ),
                (
                    "DigForm",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="domain.digform"
                    ),
                ),
            ],
            options={
                "verbose_name": "디지털양식-섹션마스터",
                "db_table": "dig_form_section",
            },
        ),
        migrations.CreateModel(
            name="DocumentForm",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("FormType", models.CharField(max_length=20, verbose_name="문서유형")),
                ("FormGroup", models.CharField(max_length=20, verbose_name="양식종류")),
                ("FormName", models.CharField(max_length=200, verbose_name="양식명")),
                ("Content", models.TextField(null=True, verbose_name="내용")),
                (
                    "Description",
                    models.CharField(max_length=500, null=True, verbose_name="설명"),
                ),
                (
                    "State",
                    models.CharField(max_length=20, null=True, verbose_name="상태"),
                ),
                (
                    "StartDate",
                    models.DateTimeField(null=True, verbose_name="적용시작일"),
                ),
                ("EndDate", models.DateTimeField(null=True, verbose_name="적용종료일")),
            ],
            options={
                "verbose_name": "문서양식",
                "db_table": "doc_form",
                "indexes": [
                    models.Index(fields=["FormType"], name="doc_form_type_idx")
                ],
            },
        ),
        migrations.CreateModel(
            name="Factory",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("Code", models.CharField(max_length=50, verbose_name="공장코드")),
                (
                    "Name",
                    models.CharField(max_length=100, null=True, verbose_name="공장명"),
                ),
            ],
            options={
                "verbose_name": "공장",
                "db_table": "factory",
                "unique_together": {("Code",), ("Name",)},
            },
        ),
        migrations.CreateModel(
            name="GridColumn",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("ModuleName", models.CharField(max_length=100, verbose_name="화면명")),
                (
                    "TemplateKey",
                    models.CharField(max_length=50, verbose_name="템플릿명"),
                ),
                ("GridName", models.CharField(max_length=50, verbose_name="그리드명")),
                ("Key", models.CharField(max_length=50, verbose_name="컬럼키")),
                ("Index", models.IntegerField(verbose_name="순서")),
                (
                    "Label",
                    models.CharField(max_length=50, null=True, verbose_name="라벨"),
                ),
                ("Width", models.IntegerField(null=True, verbose_name="너비")),
                (
                    "Hidden",
                    models.CharField(max_length=1, null=True, verbose_name="감춤"),
                ),
                (
                    "DataField",
                    models.CharField(
                        max_length=50, null=True, verbose_name="데이터필드"
                    ),
                ),
                (
                    "HeaderText",
                    models.CharField(max_length=50, null=True, verbose_name="헤더명"),
                ),
                (
                    "Visible",
                    models.BooleanField(
                        default=True, null=True, verbose_name="표시여부"
                    ),
                ),
            ],
            options={
                "verbose_name": "그리드컬럼설정",
                "db_table": "grid_col",
                "unique_together": {("ModuleName", "TemplateKey", "GridName", "Key")},
            },
        ),
        migrations.CreateModel(
            name="IfErpPurchaseReq",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("RowNo", models.IntegerField(verbose_name="파일행순서")),
                ("No", models.TextField(null=True, verbose_name="No")),
                ("Plant", models.TextField(null=True, verbose_name="공장")),
                ("ReqNo", models.TextField(null=True, verbose_name="요청번호")),
                ("ReqSeq", models.TextField(null=True, verbose_name="요청순번")),
                (
                    "ReqAcctSeq",
                    models.TextField(null=True, verbose_name="요청계정순번"),
                ),
                (
                    "ReqApprovalDate",
                    models.TextField(null=True, verbose_name="요청결재일"),
                ),
                ("InputDate", models.TextField(null=True, verbose_name="입력일")),
                ("WbsElement", models.TextField(null=True, verbose_name="WBS요소")),
                ("ProjectNo", models.TextField(null=True, verbose_name="프로젝트번호")),
                ("ProjectName", models.TextField(null=True, verbose_name="프로젝트명")),
                ("RequesterName", models.TextField(null=True, verbose_name="요청자명")),
                ("UpgvcNo", models.TextField(null=True, verbose_name="UPGVC번호")),
                ("Item", models.TextField(null=True, verbose_name="품목")),
                ("ItemName", models.TextField(null=True, verbose_name="품목명")),
                ("Spec", models.TextField(null=True, verbose_name="규격")),
                ("Category", models.TextField(null=True, verbose_name="대분류")),
                ("ReqDueDate", models.TextField(null=True, verbose_name="요청납기일")),
                (
                    "PlanReceiptDateAppr",
                    models.TextField(null=True, verbose_name="입고예정일(품의)"),
                ),
                (
                    "PlanReceiptDatePo",
                    models.TextField(null=True, verbose_name="입고예정일(발주)"),
                ),
                ("Unit", models.TextField(null=True, verbose_name="단위")),
                ("ReqQty", models.TextField(null=True, verbose_name="요청수량")),
                ("ApprQty", models.TextField(null=True, verbose_name="품의수량")),
                (
                    "VendorAppr",
                    models.TextField(null=True, verbose_name="거래처(품의)"),
                ),
                ("PoQty", models.TextField(null=True, verbose_name="발주수량")),
                ("ReceiptQty", models.TextField(null=True, verbose_name="입고수량")),
                ("ReceiptDate", models.TextField(null=True, verbose_name="입고일자")),
                ("PoNo", models.TextField(null=True, verbose_name="발주번호")),
                ("PoDate", models.TextField(null=True, verbose_name="발주일자")),
                ("VendorPo", models.TextField(null=True, verbose_name="거래처(발주)")),
                ("PoStatus", models.TextField(null=True, verbose_name="발주상태")),
                ("PoManager", models.TextField(null=True, verbose_name="발주담당자")),
                (
                    "Drawing2dDownload",
                    models.TextField(null=True, verbose_name="2D다운로드"),
                ),
                ("EoNo", models.TextField(null=True, verbose_name="EO번호")),
                ("EoReason", models.TextField(null=True, verbose_name="EO발행사유")),
                (
                    "ReqCancelYN",
                    models.TextField(null=True, verbose_name="구매요청취소여부"),
                ),
                (
                    "PurchaseOpinion",
                    models.TextField(null=True, verbose_name="구매의견"),
                ),
                (
                    "PurchaseOpinionDetail",
                    models.TextField(null=True, verbose_name="구매의견상세"),
                ),
                ("ReqOpinion", models.TextField(null=True, verbose_name="요청의견")),
                (
                    "ReqOpinionDetail",
                    models.TextField(null=True, verbose_name="요청의견상세"),
                ),
                (
                    "Batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="erp_rows",
                        to="domain.ifbatch",
                    ),
                ),
            ],
            options={
                "verbose_name": "인터페이스-ERP구매요청",
                "db_table": "if_erp_purchase_req",
            },
        ),
        migrations.CreateModel(
            name="IfPlmPartBom",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("RowNo", models.IntegerField(verbose_name="파일행순서")),
                ("No", models.TextField(null=True, verbose_name="No.")),
                ("Depth", models.TextField(null=True, verbose_name="Depth")),
                (
                    "LineNo",
                    models.TextField(null=True, verbose_name="Line No ( 7 Depth )"),
                ),
                ("PartType", models.TextField(null=True, verbose_name="Part Type")),
                ("PartErp", models.TextField(null=True, verbose_name="Part(ERP)")),
                ("PartNo", models.TextField(null=True, verbose_name="Part No")),
                ("PartName", models.TextField(null=True, verbose_name="Part Name")),
                ("PartVer", models.TextField(null=True, verbose_name="Part Ver")),
                ("Qty", models.TextField(null=True, verbose_name="Qty")),
                ("Sub", models.TextField(null=True, verbose_name="Sub")),
                ("SubTotal", models.TextField(null=True, verbose_name="Sub Total")),
                (
                    "SubMultiply",
                    models.TextField(null=True, verbose_name="Sub Multiply"),
                ),
                ("PartState", models.TextField(null=True, verbose_name="Part State")),
                (
                    "PartCheckout",
                    models.TextField(null=True, verbose_name="Part Checkout"),
                ),
                ("PostProcess", models.TextField(null=True, verbose_name="후처리")),
                (
                    "PartCreated",
                    models.TextField(null=True, verbose_name="최초생성일(P)"),
                ),
                (
                    "PartVerCreated",
                    models.TextField(null=True, verbose_name="현버전생성일(P)"),
                ),
                ("Spec", models.TextField(null=True, verbose_name="Spec(P)")),
                (
                    "MaterialGroup",
                    models.TextField(null=True, verbose_name="Material Group(P)"),
                ),
                ("Material", models.TextField(null=True, verbose_name="Material(P)")),
                ("Model3dType", models.TextField(null=True, verbose_name="3D Type")),
                ("Model3dNo", models.TextField(null=True, verbose_name="3D No")),
                ("Model3dName", models.TextField(null=True, verbose_name="3D Name")),
                ("Model3dVer", models.TextField(null=True, verbose_name="3D Ver")),
                ("Model3dState", models.TextField(null=True, verbose_name="3D State")),
                (
                    "Model3dCheckout",
                    models.TextField(null=True, verbose_name="3D Checkout"),
                ),
                (
                    "Model3dNonOwnerRel",
                    models.TextField(null=True, verbose_name="비소유자연관(M)"),
                ),
                (
                    "Model3dCreated",
                    models.TextField(null=True, verbose_name="최초생성일(M)"),
                ),
                (
                    "Model3dVerCreated",
                    models.TextField(null=True, verbose_name="현버전생성일(M)"),
                ),
                (
                    "Model3dModified",
                    models.TextField(null=True, verbose_name="마지막수정일(M)"),
                ),
                ("Drawing2dNo", models.TextField(null=True, verbose_name="2D No")),
                ("Drawing2dName", models.TextField(null=True, verbose_name="2D Name")),
                ("Drawing2dVer", models.TextField(null=True, verbose_name="2D Ver")),
                (
                    "Drawing2dState",
                    models.TextField(null=True, verbose_name="2D State"),
                ),
                (
                    "Drawing2dCheckout",
                    models.TextField(null=True, verbose_name="2D Checkout"),
                ),
                (
                    "Drawing2dRel",
                    models.TextField(null=True, verbose_name="연관관계(D)"),
                ),
                (
                    "Drawing2dCreated",
                    models.TextField(null=True, verbose_name="최초생성일(D)"),
                ),
                (
                    "Drawing2dVerCreated",
                    models.TextField(null=True, verbose_name="현버전생성일(D)"),
                ),
                (
                    "Drawing2dModified",
                    models.TextField(null=True, verbose_name="마지막수정일(D)"),
                ),
                (
                    "Batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="plm_rows",
                        to="domain.ifbatch",
                    ),
                ),
            ],
            options={
                "verbose_name": "인터페이스-PLM품목BOM",
                "db_table": "if_plm_part_bom",
            },
        ),
        migrations.CreateModel(
            name="ImageAsset",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "storage_key",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                (
                    "file",
                    models.ImageField(upload_to=domain.storage.item_image_upload_path),
                ),
                (
                    "thumbnail",
                    models.ImageField(
                        blank=True,
                        editable=False,
                        null=True,
                        upload_to=domain.storage.item_image_thumbnail_upload_path,
                    ),
                ),
                (
                    "original_file",
                    models.ImageField(
                        blank=True,
                        editable=False,
                        null=True,
                        upload_to=domain.storage.item_image_upload_path,
                    ),
                ),
                ("preprocess", models.JSONField(blank=True, default=list)),
                ("original_name", models.CharField(max_length=255)),
                ("mime_type", models.CharField(max_length=80)),
                ("width", models.PositiveIntegerField()),
                ("height", models.PositiveIntegerField()),
                ("file_size", models.PositiveBigIntegerField()),
                ("sha256", models.CharField(max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[("UPLOADED", "업로드됨"), ("LABELED", "라벨 저장됨")],
                        default="UPLOADED",
                        max_length=16,
                    ),
                ),
                (
                    "ingestion_status",
                    models.CharField(
                        choices=[
                            ("UPLOADING", "업로드 중"),
                            ("VALIDATING", "검증 중"),
                            ("READY", "준비됨"),
                            ("REJECTED", "거부됨"),
                        ],
                        default="READY",
                        max_length=16,
                    ),
                ),
                (
                    "label_status",
                    models.CharField(
                        choices=[
                            ("UNLABELED", "미작업"),
                            ("IN_PROGRESS", "작업중"),
                            ("SUBMITTED", "제출됨"),
                            ("REWORK", "재작업 필요"),
                            ("APPROVED", "작업완료"),
                        ],
                        default="UNLABELED",
                        max_length=16,
                    ),
                ),
                ("rework_reason", models.TextField(blank=True, default="")),
                (
                    "source_inspection_id",
                    models.CharField(
                        blank=True, max_length=36, null=True, verbose_name="원 검사 ID"
                    ),
                ),
                (
                    "channel",
                    models.CharField(
                        choices=[
                            ("CLIENT", "클라이언트"),
                            ("FILE", "파일 업로드"),
                            ("CAMERA", "카메라 촬영"),
                            ("FORM", "양식 사진 넣기"),
                        ],
                        db_default="FILE",
                        default="FILE",
                        max_length=16,
                        verbose_name="등록 경로",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "dataset",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="images",
                        to="domain.dataset",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="uploaded_images",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="등록자",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(class)s_records",
                        to="domain.tenant",
                    ),
                ),
            ],
            options={
                "verbose_name": "이미지",
                "db_table": "vision_data_imageasset",
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="InspectionCategory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=100, verbose_name="분류 이름")),
                (
                    "form_type",
                    models.CharField(
                        blank=True,
                        choices=[("INCOMING", "수입"), ("OUTGOING", "품질")],
                        default="",
                        max_length=10,
                        verbose_name="양식 구분",
                    ),
                ),
                (
                    "form_code",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=20,
                        verbose_name="매핑 양식 코드",
                    ),
                ),
                ("sort_order", models.IntegerField(default=0, verbose_name="순서")),
                ("description", models.TextField(blank=True, verbose_name="설명")),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="children",
                        to="domain.inspectioncategory",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(class)s_records",
                        to="domain.tenant",
                    ),
                ),
            ],
            options={
                "verbose_name": "검사 분류",
                "db_table": "vision_data_category",
                "ordering": ["sort_order", "name"],
            },
        ),
        migrations.CreateModel(
            name="InspectionItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "code",
                    models.CharField(
                        max_length=50, unique=True, verbose_name="비전검사항목코드"
                    ),
                ),
                (
                    "name",
                    models.CharField(max_length=140, verbose_name="비전검사항목명"),
                ),
                (
                    "task_type",
                    models.CharField(
                        choices=[
                            ("OBJECT_DETECTION", "객체 탐지"),
                            ("CLASSIFICATION", "분류"),
                            ("ANOMALY_DETECTION", "이상 탐지"),
                            ("MEASUREMENT", "치수 측정"),
                        ],
                        default="OBJECT_DETECTION",
                        max_length=32,
                        verbose_name="유형",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("ACTIVE", "사용"),
                            ("PAUSED", "중지"),
                            ("DELETION_PENDING", "삭제 승인 대기"),
                        ],
                        default="ACTIVE",
                        max_length=16,
                        verbose_name="상태",
                    ),
                ),
                (
                    "capture_method",
                    models.CharField(
                        choices=[("RIG", "고정 거치대"), ("TABLET", "태블릿")],
                        db_default="RIG",
                        default="RIG",
                        max_length=16,
                        verbose_name="촬영 방식",
                    ),
                ),
                ("description", models.TextField(blank=True, verbose_name="설명")),
                (
                    "cover_image",
                    models.ImageField(
                        blank=True,
                        null=True,
                        upload_to=domain.storage.item_cover_upload_path,
                        verbose_name="대표 이미지",
                    ),
                ),
                (
                    "display_order",
                    models.IntegerField(default=0, verbose_name="표시 순서"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "category",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="items",
                        to="domain.inspectioncategory",
                        verbose_name="검사 분류",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_items",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(class)s_records",
                        to="domain.tenant",
                    ),
                ),
            ],
            options={
                "verbose_name": "비전검사항목",
                "db_table": "vision_data_item",
                "ordering": ["display_order", "name"],
            },
        ),
        migrations.CreateModel(
            name="DigFormItem",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("RowType", models.CharField(max_length=10, verbose_name="구분")),
                ("RowIndex", models.IntegerField(verbose_name="행순번")),
                ("ColumnIndex", models.IntegerField(verbose_name="컬럼순번")),
                ("RowSpan", models.IntegerField(default=1, verbose_name="rowspan")),
                ("ColSpan", models.IntegerField(default=1, verbose_name="colspan")),
                (
                    "Content",
                    models.CharField(max_length=1000, null=True, verbose_name="내용"),
                ),
                (
                    "ResultType",
                    models.CharField(max_length=10, null=True, verbose_name="판정타입"),
                ),
                (
                    "CodeGroup",
                    models.CharField(max_length=30, null=True, verbose_name="코드그룹"),
                ),
                (
                    "MinColumnWidth",
                    models.IntegerField(null=True, verbose_name="최소컬럼넓이"),
                ),
                (
                    "InputYN",
                    models.CharField(
                        default="N", max_length=1, verbose_name="입력컬럼여부"
                    ),
                ),
                (
                    "UpperLimit",
                    models.DecimalField(
                        decimal_places=3,
                        max_digits=18,
                        null=True,
                        verbose_name="상한값",
                    ),
                ),
                (
                    "LowerLimit",
                    models.DecimalField(
                        decimal_places=3,
                        max_digits=18,
                        null=True,
                        verbose_name="하한값",
                    ),
                ),
                (
                    "DigFormSection",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="domain.digformsection",
                    ),
                ),
                (
                    "DigFormWorkClass",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="domain.digformworkclass",
                    ),
                ),
                (
                    "VisionItem",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="domain.inspectionitem",
                    ),
                ),
            ],
            options={
                "verbose_name": "디지털양식-문서항목",
                "db_table": "dig_form_item",
            },
        ),
        migrations.AddField(
            model_name="dataset",
            name="item",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="datasets",
                to="domain.inspectionitem",
            ),
        ),
        migrations.CreateModel(
            name="LabelClass",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=64, verbose_name="클래스명")),
                (
                    "display_name_ko",
                    models.CharField(max_length=64, verbose_name="표시명"),
                ),
                (
                    "color",
                    models.CharField(
                        default="#16A5A3", max_length=7, verbose_name="색상"
                    ),
                ),
                (
                    "is_defect",
                    models.BooleanField(default=True, verbose_name="불량 여부"),
                ),
                (
                    "sort_order",
                    models.PositiveSmallIntegerField(default=0, verbose_name="순서"),
                ),
                (
                    "annotation_shape",
                    models.CharField(
                        choices=[("BBOX", "Bounding box"), ("POLYGON", "Polygon mask")],
                        default="BBOX",
                        max_length=16,
                        verbose_name="도형",
                    ),
                ),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="label_classes",
                        to="domain.inspectionitem",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(class)s_records",
                        to="domain.tenant",
                    ),
                ),
            ],
            options={
                "verbose_name": "라벨 클래스",
                "db_table": "vision_data_labelclass",
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.CreateModel(
            name="LabelCode",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("ModuleName", models.CharField(max_length=100, verbose_name="화면명")),
                (
                    "TemplateKey",
                    models.CharField(max_length=100, verbose_name="템플릿명"),
                ),
                (
                    "LabelCode",
                    models.CharField(max_length=200, verbose_name="라벨코드"),
                ),
                (
                    "Description",
                    models.CharField(max_length=200, null=True, verbose_name="설명"),
                ),
            ],
            options={
                "verbose_name": "라벨코드",
                "db_table": "label_code",
                "unique_together": {("ModuleName", "TemplateKey", "LabelCode")},
            },
        ),
        migrations.CreateModel(
            name="LabelCodeLanguage",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("LangCode", models.CharField(max_length=30, verbose_name="언어코드")),
                ("DispText", models.CharField(max_length=500, verbose_name="표시문자")),
                (
                    "LabelCode",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="domain.labelcode",
                    ),
                ),
            ],
            options={
                "verbose_name": "라벨다국어설정",
                "db_table": "label_code_lang",
            },
        ),
        migrations.CreateModel(
            name="LoginLog",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("Type", models.CharField(max_length=50, verbose_name="구분")),
                (
                    "Username",
                    models.CharField(
                        max_length=150, null=True, verbose_name="시도한 아이디"
                    ),
                ),
                (
                    "IPAddress",
                    models.GenericIPAddressField(null=True, verbose_name="IP주소"),
                ),
                (
                    "UserAgent",
                    models.CharField(
                        max_length=300, null=True, verbose_name="User-Agent"
                    ),
                ),
                (
                    "FailReason",
                    models.CharField(
                        max_length=100, null=True, verbose_name="실패 사유"
                    ),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "User",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "로그인로그",
                "db_table": "login_log",
            },
        ),
        migrations.CreateModel(
            name="MenuFolder",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("FolderName", models.CharField(max_length=50, verbose_name="폴더명")),
                (
                    "IconCSS",
                    models.CharField(
                        max_length=50, null=True, verbose_name="아이콘스타일"
                    ),
                ),
                (
                    "_order",
                    models.IntegerField(default=0, null=True, verbose_name="순서"),
                ),
                (
                    "Parent",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="Children",
                        to="domain.menufolder",
                        verbose_name="부모폴더",
                    ),
                ),
            ],
            options={
                "verbose_name": "메뉴폴더",
                "db_table": "menu_folder",
            },
        ),
        migrations.CreateModel(
            name="MenuItem",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                (
                    "MenuCode",
                    models.CharField(
                        max_length=50,
                        primary_key=True,
                        serialize=False,
                        verbose_name="메뉴코드",
                    ),
                ),
                ("MenuName", models.CharField(max_length=50, verbose_name="메뉴명")),
                (
                    "IconCSS",
                    models.CharField(
                        max_length=50, null=True, verbose_name="아이콘스타일"
                    ),
                ),
                (
                    "Url",
                    models.CharField(max_length=100, null=True, verbose_name="Url"),
                ),
                (
                    "_order",
                    models.IntegerField(default=0, null=True, verbose_name="순서"),
                ),
                (
                    "MenuFolder",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        to="domain.menufolder",
                    ),
                ),
            ],
            options={
                "verbose_name": "메뉴항목",
                "db_table": "menu_item",
            },
        ),
        migrations.CreateModel(
            name="Bookmark",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "User",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "MenuItem",
                    models.ForeignKey(
                        db_column="MenuCode",
                        on_delete=django.db.models.deletion.CASCADE,
                        to="domain.menuitem",
                    ),
                ),
            ],
            options={
                "verbose_name": "바로가기메뉴",
                "db_table": "bookmark",
            },
        ),
        migrations.CreateModel(
            name="MenuUseLog",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("MenuCode", models.CharField(max_length=50, verbose_name="메뉴코드")),
                (
                    "User",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "메뉴사용로그",
                "db_table": "menu_use_log",
            },
        ),
        migrations.CreateModel(
            name="Product",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("Code", models.CharField(max_length=50, verbose_name="품목코드")),
                ("PartNo", models.CharField(max_length=50, verbose_name="품번")),
                ("Revision", models.CharField(max_length=10, verbose_name="리비전")),
                (
                    "Version",
                    models.CharField(max_length=20, null=True, verbose_name="버전"),
                ),
                ("Name", models.CharField(max_length=200, verbose_name="품목명")),
                (
                    "PartType",
                    models.CharField(max_length=30, null=True, verbose_name="품목유형"),
                ),
                (
                    "Spec",
                    models.CharField(max_length=200, null=True, verbose_name="규격"),
                ),
                (
                    "MaterialGroup",
                    models.CharField(
                        max_length=100, null=True, verbose_name="자재그룹"
                    ),
                ),
                (
                    "Material",
                    models.CharField(max_length=100, null=True, verbose_name="재질"),
                ),
                (
                    "PostProcess",
                    models.CharField(max_length=200, null=True, verbose_name="후처리"),
                ),
                (
                    "PartState",
                    models.CharField(max_length=20, null=True, verbose_name="PLM상태"),
                ),
                (
                    "PlmCreatedDate",
                    models.DateField(null=True, verbose_name="최초생성일"),
                ),
                (
                    "PlmVersionDate",
                    models.DateField(null=True, verbose_name="현버전생성일"),
                ),
                (
                    "Model3dType",
                    models.CharField(max_length=10, null=True, verbose_name="3D유형"),
                ),
                (
                    "Model3dNo",
                    models.CharField(max_length=100, null=True, verbose_name="3D번호"),
                ),
                (
                    "Model3dVersion",
                    models.CharField(max_length=20, null=True, verbose_name="3D버전"),
                ),
                (
                    "Model3dState",
                    models.CharField(max_length=20, null=True, verbose_name="3D상태"),
                ),
                (
                    "Model3dModified",
                    models.DateTimeField(null=True, verbose_name="3D마지막수정일"),
                ),
                (
                    "Drawing2dNo",
                    models.CharField(max_length=100, null=True, verbose_name="2D번호"),
                ),
                (
                    "Drawing2dVersion",
                    models.CharField(max_length=20, null=True, verbose_name="2D버전"),
                ),
                (
                    "Drawing2dState",
                    models.CharField(max_length=20, null=True, verbose_name="2D상태"),
                ),
                (
                    "Drawing2dModified",
                    models.DateTimeField(null=True, verbose_name="2D마지막수정일"),
                ),
            ],
            options={
                "verbose_name": "품목",
                "db_table": "mst_product",
                "unique_together": {("Code",)},
            },
        ),
        migrations.CreateModel(
            name="Bom",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                (
                    "Qty",
                    models.DecimalField(
                        decimal_places=3, max_digits=18, verbose_name="수량"
                    ),
                ),
                ("Seq", models.IntegerField(verbose_name="순서")),
                (
                    "Child",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="bom_parents",
                        to="domain.product",
                    ),
                ),
                (
                    "Parent",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="bom_children",
                        to="domain.product",
                    ),
                ),
            ],
            options={
                "verbose_name": "BOM",
                "db_table": "mst_bom",
            },
        ),
        migrations.CreateModel(
            name="ProductForm",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("PartNo", models.CharField(max_length=50, verbose_name="품번")),
                ("FormCode", models.CharField(max_length=20, verbose_name="양식코드")),
            ],
            options={
                "verbose_name": "품목검사양식",
                "db_table": "mst_product_form",
                "unique_together": {("PartNo", "FormCode")},
            },
        ),
        migrations.CreateModel(
            name="PropertyData",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("DataPk", models.IntegerField(verbose_name="데이터pk")),
                ("TableName", models.CharField(max_length=50, verbose_name="테이블명")),
                ("Code", models.CharField(max_length=50, verbose_name="속성코드")),
                (
                    "Type",
                    models.CharField(max_length=50, null=True, verbose_name="속성유형"),
                ),
                (
                    "Char1",
                    models.CharField(max_length=200, null=True, verbose_name="문자값1"),
                ),
                (
                    "Number1",
                    models.DecimalField(
                        decimal_places=3,
                        max_digits=18,
                        null=True,
                        verbose_name="수치값1",
                    ),
                ),
                ("Date1", models.DateTimeField(null=True, verbose_name="일시값1")),
                ("Text1", models.TextField(null=True, verbose_name="텍스트값1")),
                (
                    "Number2",
                    models.DecimalField(
                        decimal_places=3,
                        max_digits=18,
                        null=True,
                        verbose_name="수치값2",
                    ),
                ),
            ],
            options={
                "verbose_name": "속성데이터",
                "db_table": "prop_data",
                "unique_together": {("DataPk", "TableName", "Code")},
            },
        ),
        migrations.CreateModel(
            name="PropertyMaster",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("TableName", models.CharField(max_length=50, verbose_name="테이블명")),
                ("Code", models.CharField(max_length=50, verbose_name="속성코드")),
                (
                    "Type",
                    models.CharField(max_length=50, null=True, verbose_name="속성유형"),
                ),
                (
                    "Description",
                    models.CharField(
                        max_length=500, null=True, verbose_name="속성설명"
                    ),
                ),
            ],
            options={
                "verbose_name": "속성정의",
                "db_table": "prop_master",
                "unique_together": {("TableName", "Code")},
            },
        ),
        migrations.CreateModel(
            name="Receipt",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("ReceiptNo", models.CharField(max_length=50, verbose_name="입고번호")),
                ("ReqNo", models.CharField(max_length=30, verbose_name="요청번호")),
                ("ReqSeq", models.IntegerField(verbose_name="요청순번")),
                ("ItemCode", models.CharField(max_length=50, verbose_name="품목코드")),
                ("ItemName", models.CharField(max_length=200, verbose_name="품목명")),
                (
                    "Spec",
                    models.CharField(max_length=200, null=True, verbose_name="규격"),
                ),
                (
                    "Category",
                    models.CharField(max_length=50, null=True, verbose_name="대분류"),
                ),
                (
                    "Unit",
                    models.CharField(max_length=20, null=True, verbose_name="단위"),
                ),
                (
                    "Qty",
                    models.DecimalField(
                        decimal_places=3, max_digits=18, verbose_name="수량"
                    ),
                ),
                ("ReceiptDate", models.DateField(null=True, verbose_name="입고일")),
                (
                    "VendorName",
                    models.CharField(
                        max_length=100, null=True, verbose_name="거래처명"
                    ),
                ),
                (
                    "ProjectNo",
                    models.CharField(
                        max_length=50, null=True, verbose_name="프로젝트번호"
                    ),
                ),
                (
                    "ProjectName",
                    models.CharField(
                        max_length=200, null=True, verbose_name="프로젝트명"
                    ),
                ),
                (
                    "RequesterName",
                    models.CharField(max_length=50, null=True, verbose_name="요청자명"),
                ),
                (
                    "EoNo",
                    models.CharField(max_length=50, null=True, verbose_name="EO번호"),
                ),
                (
                    "Batch",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="receipts",
                        to="domain.ifbatch",
                    ),
                ),
                (
                    "Product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="receipts",
                        to="domain.product",
                    ),
                ),
            ],
            options={
                "verbose_name": "입고",
                "db_table": "mst_receipt",
            },
        ),
        migrations.CreateModel(
            name="SequenceMaker",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("Code", models.CharField(max_length=50, verbose_name="코드")),
                (
                    "Code2",
                    models.CharField(
                        default="", max_length=50, null=True, verbose_name="코드2"
                    ),
                ),
                ("BaseDate", models.CharField(max_length=10, verbose_name="기준일자")),
                ("CurrVal", models.IntegerField(default=0, verbose_name="현재값")),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
            ],
            options={
                "verbose_name": "채번마스터",
                "db_table": "seq_maker",
                "unique_together": {("BaseDate", "Code", "Code2")},
            },
        ),
        migrations.CreateModel(
            name="SystemCode",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("CodeType", models.CharField(max_length=30, verbose_name="코드유형")),
                ("Code", models.CharField(max_length=30, verbose_name="코드")),
                ("Value", models.CharField(max_length=30, verbose_name="디코드값")),
                (
                    "Description",
                    models.CharField(max_length=500, null=True, verbose_name="설명"),
                ),
                (
                    "_ordering",
                    models.IntegerField(default=0, null=True, verbose_name="_순서"),
                ),
            ],
            options={
                "verbose_name": "시스템코드",
                "db_table": "sys_code",
                "indexes": [
                    models.Index(
                        fields=["CodeType", "Code", "Value"],
                        name="sys_code_type_code_value_idx",
                    )
                ],
                "unique_together": {("CodeType", "Code")},
            },
        ),
        migrations.CreateModel(
            name="SystemLog",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "Type",
                    models.CharField(max_length=20, null=True, verbose_name="로그유형"),
                ),
                (
                    "Source",
                    models.CharField(max_length=100, null=True, verbose_name="소스"),
                ),
                ("Message", models.TextField(null=True, verbose_name="메시지")),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
            ],
            options={
                "verbose_name": "시스템로그",
                "db_table": "sys_log",
                "indexes": [
                    models.Index(fields=["_created"], name="sys_log_created_idx"),
                    models.Index(
                        fields=["Type", "_created"], name="sys_log_type_created_idx"
                    ),
                    models.Index(
                        fields=["Source", "_created"], name="sys_log_source_created_idx"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="SystemOption",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("Code", models.CharField(max_length=50, verbose_name="코드")),
                (
                    "Value",
                    models.CharField(max_length=500, null=True, verbose_name="값"),
                ),
                (
                    "Description",
                    models.CharField(max_length=500, null=True, verbose_name="설명"),
                ),
            ],
            options={
                "verbose_name": "시스템옵션",
                "db_table": "sys_option",
                "unique_together": {("Code",)},
            },
        ),
        migrations.CreateModel(
            name="MeasurementPoint",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("code", models.CharField(max_length=20, verbose_name="측정점 코드")),
                ("name", models.CharField(max_length=100, verbose_name="측정점 이름")),
                (
                    "nominal",
                    models.DecimalField(
                        decimal_places=3, max_digits=18, verbose_name="기준값"
                    ),
                ),
                (
                    "lower",
                    models.DecimalField(
                        decimal_places=3, max_digits=18, verbose_name="하한"
                    ),
                ),
                (
                    "upper",
                    models.DecimalField(
                        decimal_places=3, max_digits=18, verbose_name="상한"
                    ),
                ),
                (
                    "unit",
                    models.CharField(default="mm", max_length=10, verbose_name="단위"),
                ),
                ("description", models.TextField(blank=True, verbose_name="측정 방법")),
                (
                    "sort_order",
                    models.PositiveSmallIntegerField(default=0, verbose_name="순서"),
                ),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="measurement_points",
                        to="domain.inspectionitem",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(class)s_records",
                        to="domain.tenant",
                    ),
                ),
            ],
            options={
                "verbose_name": "측정점",
                "db_table": "vision_data_measurementpoint",
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.CreateModel(
            name="LabelingTask",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("READY", "대기"),
                            ("CLAIMED", "할당됨"),
                            ("IN_PROGRESS", "작업중"),
                            ("SUBMITTED", "제출됨"),
                        ],
                        default="READY",
                        max_length=16,
                    ),
                ),
                (
                    "lease_token",
                    models.UUIDField(blank=True, editable=False, null=True),
                ),
                ("lease_expires_at", models.DateTimeField(blank=True, null=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("last_saved_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "assignee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="labeling_tasks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "image",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="labeling_tasks",
                        to="domain.imageasset",
                    ),
                ),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="labeling_tasks",
                        to="domain.inspectionitem",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(class)s_records",
                        to="domain.tenant",
                    ),
                ),
            ],
            options={
                "verbose_name": "라벨링 작업",
                "db_table": "vision_data_labelingtask",
                "ordering": ["created_at", "id"],
            },
        ),
        migrations.CreateModel(
            name="ItemDeletionRequest",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("REQUESTED", "승인 대기"),
                            ("APPROVED", "승인됨"),
                            ("REJECTED", "반려됨"),
                            ("CANCELED", "취소됨"),
                        ],
                        default="REQUESTED",
                        max_length=16,
                    ),
                ),
                (
                    "item_code",
                    models.CharField(
                        blank=True,
                        db_default="",
                        default="",
                        max_length=50,
                        verbose_name="비전검사항목 코드",
                    ),
                ),
                (
                    "item_name",
                    models.CharField(
                        blank=True,
                        db_default="",
                        default="",
                        max_length=140,
                        verbose_name="비전검사항목명",
                    ),
                ),
                ("reason", models.TextField(blank=True, verbose_name="사유")),
                ("review_note", models.TextField(blank=True, verbose_name="검토 의견")),
                ("requested_at", models.DateTimeField(auto_now_add=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="deletion_requests",
                        to="domain.inspectionitem",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="item_deletion_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reviewed_item_deletions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(class)s_records",
                        to="domain.tenant",
                    ),
                ),
            ],
            options={
                "verbose_name": "비전검사항목 삭제 요청",
                "db_table": "vision_data_itemdeletionrequest",
                "ordering": ["-requested_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="ExportJob",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "storage_key",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                (
                    "format",
                    models.CharField(
                        choices=[
                            ("COCO", "COCO Detection"),
                            ("YOLO", "YOLO Detection"),
                            ("IMAGEFOLDER", "ImageFolder"),
                            ("CSV", "Classification CSV"),
                            ("CLASSIFICATION_JSON", "Classification JSON"),
                            ("MVTEC", "MVTec AD"),
                            ("IMAGE_MASK", "Image + Mask"),
                            ("ANOMALY_JSON", "Anomaly JSON"),
                            ("WEZARD", "Wezard 학습 데이터셋"),
                        ],
                        default="COCO",
                        max_length=24,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("QUEUED", "대기 중"),
                            ("RUNNING", "생성 중"),
                            ("COMPLETED", "완료"),
                            ("FAILED", "실패"),
                        ],
                        default="QUEUED",
                        max_length=16,
                    ),
                ),
                (
                    "file",
                    models.FileField(
                        blank=True,
                        max_length=512,
                        null=True,
                        upload_to=domain.storage.export_upload_path,
                    ),
                ),
                ("file_size", models.BigIntegerField(blank=True, null=True)),
                ("file_sha256", models.CharField(blank=True, max_length=64)),
                ("error_message", models.TextField(blank=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "dataset_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="exports",
                        to="domain.datasetversion",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(class)s_records",
                        to="domain.tenant",
                    ),
                ),
            ],
            options={
                "verbose_name": "Export",
                "db_table": "vision_data_exportjob",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddField(
            model_name="dataset",
            name="tenant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="%(class)s_records",
                to="domain.tenant",
            ),
        ),
        migrations.CreateModel(
            name="BackgroundJob",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "job_type",
                    models.CharField(
                        choices=[("EXPORT", "Export 생성")], max_length=16
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("QUEUED", "대기 중"),
                            ("RUNNING", "실행 중"),
                            ("COMPLETED", "완료"),
                            ("FAILED", "실패"),
                        ],
                        default="QUEUED",
                        max_length=16,
                    ),
                ),
                ("payload", models.JSONField(default=dict)),
                ("result", models.JSONField(default=dict)),
                ("error_message", models.TextField(blank=True)),
                (
                    "attempt_count",
                    models.PositiveSmallIntegerField(
                        default=0, verbose_name="시도 횟수"
                    ),
                ),
                (
                    "next_retry_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="다음 재시도"
                    ),
                ),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "requested_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(class)s_records",
                        to="domain.tenant",
                    ),
                ),
            ],
            options={
                "verbose_name": "백그라운드 작업",
                "db_table": "vision_data_backgroundjob",
                "ordering": ["created_at"],
            },
        ),
        migrations.CreateModel(
            name="Annotation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "geometry_type",
                    models.CharField(
                        choices=[
                            ("NONE", "없음"),
                            ("BBOX", "Bounding box"),
                            ("POLYGON", "Polygon"),
                        ],
                        default="NONE",
                        max_length=16,
                    ),
                ),
                ("geometry", models.JSONField(blank=True, null=True)),
                ("attributes", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "image",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="annotations",
                        to="domain.imageasset",
                    ),
                ),
                (
                    "label_class",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="annotations",
                        to="domain.labelclass",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(class)s_records",
                        to="domain.tenant",
                    ),
                ),
            ],
            options={
                "verbose_name": "어노테이션",
                "db_table": "vision_data_annotation",
                "ordering": ["id"],
            },
        ),
        migrations.CreateModel(
            name="ActivityLog",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("event_type", models.CharField(max_length=48)),
                ("actor_name", models.CharField(default="일반 사용자", max_length=80)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="audit_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="activities",
                        to="domain.inspectionitem",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(class)s_records",
                        to="domain.tenant",
                    ),
                ),
            ],
            options={
                "verbose_name": "활동 이력",
                "db_table": "vision_data_activitylog",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="TenantMembership",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("joined_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(class)s_records",
                        to="domain.tenant",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tenant_memberships",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "조직 소속",
                "db_table": "vision_data_tenantmembership",
            },
        ),
        migrations.CreateModel(
            name="Unit",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("Name", models.CharField(max_length=30, verbose_name="단위명")),
                (
                    "Description",
                    models.CharField(max_length=200, null=True, verbose_name="설명"),
                ),
                (
                    "PieceYN",
                    models.CharField(
                        max_length=1, null=True, verbose_name="낱개단위YN"
                    ),
                ),
            ],
            options={
                "verbose_name": "단위",
                "db_table": "unit",
                "unique_together": {("Name",)},
            },
        ),
        migrations.CreateModel(
            name="UserCode",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("Code", models.CharField(max_length=30, verbose_name="코드")),
                ("Value", models.CharField(max_length=100, verbose_name="디코드값")),
                (
                    "Description",
                    models.CharField(max_length=500, null=True, verbose_name="설명"),
                ),
                (
                    "_order",
                    models.IntegerField(default=0, null=True, verbose_name="순서"),
                ),
                (
                    "Type",
                    models.CharField(max_length=100, null=True, verbose_name="구분"),
                ),
                (
                    "Type2",
                    models.CharField(max_length=100, null=True, verbose_name="구분2"),
                ),
                ("StartDate", models.DateField(null=True, verbose_name="적용시작일")),
                ("EndDate", models.DateField(null=True, verbose_name="적용종료일")),
                (
                    "Parent",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="Children",
                        to="domain.usercode",
                        verbose_name="Parent",
                    ),
                ),
            ],
            options={
                "verbose_name": "사용자코드",
                "db_table": "user_code",
            },
        ),
        migrations.CreateModel(
            name="UserGroup",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                (
                    "id",
                    models.AutoField(editable=False, primary_key=True, serialize=False),
                ),
                ("Code", models.CharField(max_length=50, verbose_name="코드")),
                (
                    "Name",
                    models.CharField(
                        default="None", max_length=100, verbose_name="사용자그룹명"
                    ),
                ),
                (
                    "Disabled",
                    models.BooleanField(
                        default=False, null=True, verbose_name="사용안함"
                    ),
                ),
                (
                    "Description",
                    models.CharField(max_length=500, null=True, verbose_name="비고"),
                ),
            ],
            options={
                "verbose_name": "사용자그룹",
                "verbose_name_plural": "User Groups",
                "db_table": "user_group",
                "default_related_name": "UserGroup",
                "unique_together": {("Code",)},
            },
        ),
        migrations.CreateModel(
            name="UserGroupMenu",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                (
                    "id",
                    models.AutoField(editable=False, primary_key=True, serialize=False),
                ),
                ("MenuCode", models.CharField(max_length=50, verbose_name="메뉴코드")),
                ("AuthCode", models.CharField(max_length=10, verbose_name="권한코드")),
                (
                    "UserGroup",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="domain.usergroup",
                    ),
                ),
            ],
            options={
                "verbose_name": "사용자그룹메뉴",
                "db_table": "user_group_menu",
            },
        ),
        migrations.CreateModel(
            name="UserProfile",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                (
                    "User",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        serialize=False,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "password_changed",
                    models.DateTimeField(null=True, verbose_name="패스워드변경일"),
                ),
                (
                    "lang_code",
                    models.CharField(
                        default="ko-KR", max_length=30, verbose_name="사용언어코드"
                    ),
                ),
                (
                    "Name",
                    models.CharField(
                        max_length=100, null=True, verbose_name="사용자명"
                    ),
                ),
                (
                    "Company",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        to="domain.company",
                    ),
                ),
                (
                    "Depart",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        to="domain.depart",
                    ),
                ),
                (
                    "Factory",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        to="domain.factory",
                    ),
                ),
                (
                    "UserGroup",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        to="domain.usergroup",
                    ),
                ),
            ],
            options={
                "verbose_name": "사용자프로필",
                "db_table": "user_profile",
            },
        ),
        migrations.CreateModel(
            name="VisionClient",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "client_id",
                    models.CharField(
                        max_length=50, unique=True, verbose_name="Client ID"
                    ),
                ),
                (
                    "name",
                    models.CharField(max_length=100, verbose_name="클라이언트 명"),
                ),
                (
                    "api_key_hash",
                    models.CharField(max_length=64, verbose_name="API Key 해시"),
                ),
                ("active", models.BooleanField(default=True, verbose_name="사용")),
                (
                    "last_seen_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="최근 접속"
                    ),
                ),
                (
                    "service_account",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="vision_client",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "비전검사 클라이언트",
                "db_table": "vision_client",
                "ordering": ["client_id"],
            },
        ),
        migrations.CreateModel(
            name="VisionInspection",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.CharField(max_length=36, primary_key=True, serialize=False),
                ),
                (
                    "request_id",
                    models.CharField(
                        max_length=36, unique=True, verbose_name="요청 ID"
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("RECEIVED", "접수됨"),
                            ("SUCCESS", "판정 완료"),
                            ("FAILED", "실패"),
                        ],
                        default="RECEIVED",
                        max_length=20,
                        verbose_name="상태",
                    ),
                ),
                (
                    "capture_timestamp",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="촬영 시각"
                    ),
                ),
                (
                    "client_version",
                    models.CharField(
                        blank=True,
                        max_length=50,
                        null=True,
                        verbose_name="클라이언트 버전",
                    ),
                ),
                (
                    "camera_vendor",
                    models.CharField(
                        blank=True,
                        max_length=100,
                        null=True,
                        verbose_name="카메라 제조사",
                    ),
                ),
                (
                    "camera_serial",
                    models.CharField(
                        blank=True,
                        max_length=100,
                        null=True,
                        verbose_name="카메라 일련번호",
                    ),
                ),
                (
                    "abnormal",
                    models.BooleanField(
                        blank=True, null=True, verbose_name="이상 판정"
                    ),
                ),
                (
                    "model_name",
                    models.CharField(
                        blank=True, max_length=255, null=True, verbose_name="사용 모델"
                    ),
                ),
                (
                    "model_version",
                    models.CharField(
                        blank=True, max_length=50, null=True, verbose_name="모델 버전"
                    ),
                ),
                (
                    "defects",
                    models.JSONField(blank=True, null=True, verbose_name="탐지 결과"),
                ),
                (
                    "anomaly_score",
                    models.FloatField(blank=True, null=True, verbose_name="이상 점수"),
                ),
                (
                    "classification",
                    models.JSONField(blank=True, null=True, verbose_name="분류 결과"),
                ),
                (
                    "threshold",
                    models.FloatField(
                        blank=True, null=True, verbose_name="적용 임계값"
                    ),
                ),
                (
                    "measurements",
                    models.JSONField(blank=True, null=True, verbose_name="측정 결과"),
                ),
                (
                    "calibration",
                    models.JSONField(blank=True, null=True, verbose_name="배율 정보"),
                ),
                (
                    "inference_ms",
                    models.FloatField(
                        blank=True, null=True, verbose_name="추론 시간(ms)"
                    ),
                ),
                (
                    "heatmap",
                    models.FileField(
                        blank=True,
                        null=True,
                        upload_to=domain.models.vision.heatmap_upload_path,
                        verbose_name="Heatmap",
                    ),
                ),
                (
                    "error_message",
                    models.TextField(blank=True, null=True, verbose_name="오류"),
                ),
                (
                    "client",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="inspections",
                        to="domain.visionclient",
                    ),
                ),
                (
                    "image_asset",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="inspections",
                        to="domain.imageasset",
                    ),
                ),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="inspections",
                        to="domain.inspectionitem",
                    ),
                ),
            ],
            options={
                "verbose_name": "검사 결과",
                "db_table": "vision_inspection",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="VisionModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=100, verbose_name="모델명")),
                (
                    "inspection_type",
                    models.CharField(
                        choices=[
                            ("CLASSIFICATION", "분류"),
                            ("DETECTION", "객체 탐지"),
                            ("ANOMALY", "이상 탐지"),
                        ],
                        max_length=16,
                        verbose_name="검사 유형",
                    ),
                ),
                ("version", models.CharField(max_length=50, verbose_name="버전")),
                (
                    "artifact_path",
                    models.CharField(max_length=255, verbose_name="아티팩트 경로"),
                ),
                ("runtime", models.CharField(max_length=50, verbose_name="런타임")),
                (
                    "threshold",
                    models.FloatField(blank=True, null=True, verbose_name="임계값"),
                ),
                ("active", models.BooleanField(default=True, verbose_name="사용")),
            ],
            options={
                "verbose_name": "AI 모델",
                "db_table": "vision_model",
                "ordering": ["name", "-version"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("name", "version"), name="uq_vision_model_name_version"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="VisionItemModelMapping",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "model_code",
                    models.CharField(max_length=100, verbose_name="모델 식별자"),
                ),
                (
                    "model_version",
                    models.CharField(max_length=50, verbose_name="모델 버전"),
                ),
                (
                    "threshold_override",
                    models.FloatField(
                        blank=True, null=True, verbose_name="임계값 재지정"
                    ),
                ),
                ("active", models.BooleanField(default=True, verbose_name="사용")),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="model_mappings",
                        to="domain.inspectionitem",
                    ),
                ),
                (
                    "model",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="mappings",
                        to="domain.visionmodel",
                    ),
                ),
            ],
            options={
                "verbose_name": "비전검사항목 모델 매핑",
                "db_table": "vision_item_model_mapping",
                "ordering": ["-active", "-updated_at"],
            },
        ),
        migrations.CreateModel(
            name="VisionOverlay",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("version", models.IntegerField(default=1, verbose_name="버전")),
                ("visible", models.BooleanField(default=True, verbose_name="표시")),
                ("opacity", models.FloatField(default=0.7, verbose_name="불투명도")),
                (
                    "image",
                    models.ImageField(
                        upload_to=domain.models.vision.overlay_upload_path,
                        verbose_name="Overlay 이미지",
                    ),
                ),
                (
                    "item",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="overlay",
                        to="domain.inspectionitem",
                    ),
                ),
            ],
            options={
                "verbose_name": "Overlay",
                "db_table": "vision_overlay",
            },
        ),
        migrations.CreateModel(
            name="DigFormItemResult",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                (
                    "TextResult",
                    models.CharField(
                        max_length=500, null=True, verbose_name="문자결과"
                    ),
                ),
                (
                    "NumberResult",
                    models.DecimalField(
                        decimal_places=3,
                        max_digits=18,
                        null=True,
                        verbose_name="숫자결과",
                    ),
                ),
                (
                    "ComboResult",
                    models.CharField(max_length=30, null=True, verbose_name="콤보결과"),
                ),
                (
                    "CheckResultYN",
                    models.CharField(max_length=1, null=True, verbose_name="체크결과"),
                ),
                (
                    "DigFormItem",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="domain.digformitem",
                    ),
                ),
                (
                    "DigFormResult",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="domain.digformresult",
                    ),
                ),
            ],
            options={
                "verbose_name": "디지털양식-항목결과",
                "db_table": "dig_form_item_result",
                "unique_together": {("DigFormResult", "DigFormItem")},
            },
        ),
        migrations.CreateModel(
            name="DocumentResult",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("DocumentDate", models.DateField(verbose_name="일자")),
                (
                    "DocumentName",
                    models.CharField(max_length=200, verbose_name="문서명"),
                ),
                ("Content", models.TextField(null=True, verbose_name="내용")),
                (
                    "Description",
                    models.CharField(max_length=500, null=True, verbose_name="설명"),
                ),
                (
                    "Number1",
                    models.DecimalField(
                        decimal_places=3,
                        max_digits=18,
                        null=True,
                        verbose_name="수치값1",
                    ),
                ),
                (
                    "Number2",
                    models.DecimalField(
                        decimal_places=3,
                        max_digits=18,
                        null=True,
                        verbose_name="수치값2",
                    ),
                ),
                (
                    "Number3",
                    models.DecimalField(
                        decimal_places=3,
                        max_digits=18,
                        null=True,
                        verbose_name="수치값3",
                    ),
                ),
                (
                    "Text1",
                    models.CharField(max_length=100, null=True, verbose_name="문자값1"),
                ),
                (
                    "Text2",
                    models.CharField(max_length=100, null=True, verbose_name="문자값2"),
                ),
                (
                    "Text3",
                    models.CharField(max_length=100, null=True, verbose_name="문자값3"),
                ),
                (
                    "DocumentForm",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="domain.documentform",
                    ),
                ),
            ],
            options={
                "verbose_name": "문서결과",
                "db_table": "doc_result",
                "indexes": [
                    models.Index(
                        fields=["DocumentForm", "DocumentDate"],
                        name="doc_result_form_date_idx",
                    ),
                    models.Index(fields=["DocumentDate"], name="doc_result_date_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="GridColumnLanguage",
            fields=[
                (
                    "_status",
                    models.CharField(max_length=10, null=True, verbose_name="_status"),
                ),
                (
                    "_created",
                    models.DateTimeField(auto_now_add=True, verbose_name="_created"),
                ),
                (
                    "_modified",
                    models.DateTimeField(
                        auto_now=True, null=True, verbose_name="_modfied"
                    ),
                ),
                (
                    "_creater_id",
                    models.IntegerField(null=True, verbose_name="_creater_id"),
                ),
                (
                    "_modifier_id",
                    models.IntegerField(null=True, verbose_name="_modifier_id"),
                ),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("LangCode", models.CharField(max_length=30, verbose_name="언어")),
                ("DispText", models.CharField(max_length=500, verbose_name="표시문자")),
                (
                    "GridColumn",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="domain.gridcolumn",
                    ),
                ),
            ],
            options={
                "verbose_name": "그리드컬럼언어",
                "db_table": "grid_col_lang",
                "unique_together": {("GridColumn", "LangCode")},
            },
        ),
        migrations.AddConstraint(
            model_name="digformitem",
            constraint=models.UniqueConstraint(
                fields=("DigFormSection", "RowIndex", "ColumnIndex"),
                name="dig_form_item_pos_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="digformitem",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("InputYN", "N"), ("ResultType__isnull", False), _connector="OR"
                ),
                name="dig_form_item_input_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="digformitem",
            constraint=models.CheckConstraint(
                condition=models.Q(("ColSpan__gte", 1), ("RowSpan__gte", 1)),
                name="dig_form_item_span_ck",
            ),
        ),
        migrations.AddIndex(
            model_name="labelcodelanguage",
            index=models.Index(
                fields=["LabelCode", "LangCode", "DispText"],
                name="label_lang_code_lang_text_idx",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="labelcodelanguage",
            unique_together={("LabelCode", "LangCode")},
        ),
        migrations.AddIndex(
            model_name="loginlog",
            index=models.Index(fields=["_created"], name="login_log_created_idx"),
        ),
        migrations.AddIndex(
            model_name="loginlog",
            index=models.Index(
                fields=["User", "_created"], name="login_log_user_created_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="loginlog",
            index=models.Index(
                fields=["IPAddress", "_created"], name="login_log_ip_created_idx"
            ),
        ),
        migrations.AlterUniqueTogether(
            name="bookmark",
            unique_together={("User", "MenuItem")},
        ),
        migrations.AddIndex(
            model_name="menuuselog",
            index=models.Index(fields=["_created"], name="menu_log_created_idx"),
        ),
        migrations.AddIndex(
            model_name="menuuselog",
            index=models.Index(
                fields=["User", "_created"], name="menu_log_user_created_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="menuuselog",
            index=models.Index(
                fields=["MenuCode", "_created"], name="menu_log_menu_created_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="menuuselog",
            index=models.Index(
                fields=["User", "MenuCode", "_created"],
                name="menu_log_user_menu_crt_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="bom",
            constraint=models.CheckConstraint(
                condition=models.Q(("Qty__gt", 0)), name="ck_mst_bom_qty_positive"
            ),
        ),
        migrations.AddConstraint(
            model_name="bom",
            constraint=models.CheckConstraint(
                condition=models.Q(("Parent", models.F("Child")), _negated=True),
                name="ck_mst_bom_not_self",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="bom",
            unique_together={("Parent", "Child")},
        ),
        migrations.AlterUniqueTogether(
            name="receipt",
            unique_together={("ReceiptNo",)},
        ),
        migrations.AddConstraint(
            model_name="measurementpoint",
            constraint=models.UniqueConstraint(
                fields=("tenant", "item", "code"), name="uq_measurement_point_code"
            ),
        ),
        migrations.AddConstraint(
            model_name="measurementpoint",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("lower__lte", models.F("nominal")),
                    ("nominal__lte", models.F("upper")),
                ),
                name="ck_measurement_point_range",
            ),
        ),
        migrations.AddIndex(
            model_name="labelingtask",
            index=models.Index(
                fields=["tenant", "item", "status"],
                name="vision_data_tenant__35999f_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="labelingtask",
            index=models.Index(
                fields=["tenant", "assignee", "status"],
                name="vision_data_tenant__a1a826_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="labelingtask",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status__in", ["CLAIMED", "IN_PROGRESS"])),
                fields=("tenant", "image"),
                name="unique_active_labeling_task_per_image",
            ),
        ),
        migrations.AddIndex(
            model_name="labelclass",
            index=models.Index(
                fields=["tenant", "item", "sort_order"],
                name="vision_data_tenant__b8e60f_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="labelclass",
            constraint=models.UniqueConstraint(
                fields=("tenant", "item", "name"),
                name="unique_label_class_in_tenant_item",
            ),
        ),
        migrations.AddIndex(
            model_name="itemdeletionrequest",
            index=models.Index(
                fields=["tenant", "status"], name="vision_data_tenant__b4ae6a_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="itemdeletionrequest",
            index=models.Index(
                fields=["tenant", "item", "status"],
                name="vision_data_tenant__53c4a7_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="inspectionitem",
            index=models.Index(
                fields=["tenant", "-updated_at"], name="vision_data_tenant__9ff5df_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="inspectionitem",
            index=models.Index(
                fields=["tenant", "status", "display_order"],
                name="vision_data_tenant__bf3d2c_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="inspectioncategory",
            constraint=models.UniqueConstraint(
                condition=models.Q(("parent__isnull", True)),
                fields=("tenant", "name"),
                name="uq_category_major_name",
            ),
        ),
        migrations.AddConstraint(
            model_name="inspectioncategory",
            constraint=models.UniqueConstraint(
                condition=models.Q(("parent__isnull", False)),
                fields=("tenant", "parent", "name"),
                name="uq_category_minor_name",
            ),
        ),
        migrations.AddConstraint(
            model_name="inspectioncategory",
            constraint=models.UniqueConstraint(
                condition=models.Q(("form_code", ""), _negated=True),
                fields=("tenant", "form_code"),
                name="uq_category_form_code",
            ),
        ),
        migrations.AddConstraint(
            model_name="inspectioncategory",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("parent__isnull", True), ("form_code", "")),
                    models.Q(("parent__isnull", False), ("form_type", "")),
                    _connector="OR",
                ),
                name="ck_category_level_fields",
            ),
        ),
        migrations.AddIndex(
            model_name="imageasset",
            index=models.Index(
                fields=["tenant", "dataset", "label_status", "-updated_at", "-id"],
                name="image_list_dataset_label_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="imageasset",
            index=models.Index(
                fields=[
                    "tenant",
                    "ingestion_status",
                    "label_status",
                    "-updated_at",
                    "-id",
                ],
                name="image_queue_status_label_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="imageasset",
            index=models.Index(
                fields=["tenant", "dataset", "sha256"], name="image_sha256_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="imageasset",
            index=models.Index(
                fields=["source_inspection_id"], name="image_source_inspection_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="exportjob",
            index=models.Index(
                fields=["tenant", "status", "-created_at"],
                name="vision_data_tenant__3516d0_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="datasetversion",
            index=models.Index(
                fields=["tenant", "dataset", "-created_at"],
                name="vision_data_tenant__566a92_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="datasetversion",
            constraint=models.UniqueConstraint(
                fields=("tenant", "dataset", "version_tag"),
                name="unique_dataset_version_per_tenant",
            ),
        ),
        migrations.AddIndex(
            model_name="dataset",
            index=models.Index(
                fields=["tenant", "item", "-updated_at"],
                name="vision_data_tenant__d5efab_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="dataset",
            constraint=models.UniqueConstraint(
                fields=("tenant", "item", "version"),
                name="unique_dataset_version_in_tenant_item",
            ),
        ),
        migrations.AddIndex(
            model_name="backgroundjob",
            index=models.Index(
                fields=["tenant", "status", "created_at"],
                name="vision_data_tenant__120c26_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="backgroundjob",
            index=models.Index(
                fields=["status", "next_retry_at"], name="vision_data_status_a89f39_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="annotation",
            index=models.Index(
                fields=["tenant", "image", "label_class"],
                name="vision_data_tenant__9b0011_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="activitylog",
            index=models.Index(
                fields=["tenant", "-created_at"], name="vision_data_tenant__65e689_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="activitylog",
            index=models.Index(
                fields=["tenant", "event_type"], name="vision_data_tenant__2e64aa_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="activitylog",
            index=models.Index(
                fields=["tenant", "item", "-created_at"],
                name="vision_data_tenant__3be78b_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="tenantmembership",
            index=models.Index(
                fields=["tenant", "is_active", "user"],
                name="vision_data_tenant__f5c2b9_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="tenantmembership",
            index=models.Index(
                fields=["user", "is_active", "tenant"],
                name="vision_data_user_id_4c9390_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="tenantmembership",
            constraint=models.UniqueConstraint(
                fields=("tenant", "user"), name="unique_tenant_membership"
            ),
        ),
        migrations.AddIndex(
            model_name="usercode",
            index=models.Index(
                fields=["Parent", "Code", "Value"], name="user_code_parent_code_val_idx"
            ),
        ),
        migrations.AlterUniqueTogether(
            name="usercode",
            unique_together={("Code", "Parent")},
        ),
        migrations.AlterUniqueTogether(
            name="usergroupmenu",
            unique_together={("MenuCode", "UserGroup")},
        ),
        migrations.AddIndex(
            model_name="visioninspection",
            index=models.Index(
                fields=["item", "-created_at"], name="vision_insp_item_id_4ca28c_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="visioninspection",
            index=models.Index(
                fields=["client", "-created_at"], name="vision_insp_client__e33295_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="visioninspection",
            index=models.Index(
                fields=["status", "-created_at"], name="vision_insp_status_a0dcd5_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="visioninspection",
            index=models.Index(
                fields=["-created_at"], name="vision_insp_created_a27e1d_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="visionitemmodelmapping",
            constraint=models.UniqueConstraint(
                condition=models.Q(("active", True)),
                fields=("item",),
                name="uq_vision_active_mapping_per_item",
            ),
        ),
        # 모델로 표현되지 않는 PostgreSQL 객체(파일 위 설명)
        run_sql(DIG_FORM_CODE_SEQ, 'DROP SEQUENCE IF EXISTS dig_form_code_seq'),
        run_sql(FN_CODE_NAME, 'DROP FUNCTION IF EXISTS fn_code_name(text, text)'),
        run_sql(FN_CLASS_DATA_TEXT, 'DROP FUNCTION IF EXISTS fn_class_data_text(text, text, integer)'),
        run_sql(V_MENU_FOLDER, 'DROP VIEW IF EXISTS v_menu_folder'),
        migrations.RunPython(enable_rls, disable_rls),
    ]
