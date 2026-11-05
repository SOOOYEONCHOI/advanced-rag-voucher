from django.db import models
from django.db.models import Q

from .system import AbstractAuditModel
from .data import InspectionItem

# 디지털 양식(CheckList) — 팀원 MES `feature/dig-form` 에서 옮겼다. 스키마는 마이그레이션 0006 이 만든다.
# 조직 구분이 없는 MES 계열 테이블이다(RLS 대상 아님). 참고사진은 attach_file(TableName='dig_form_section', AttachName='editor').


class DigForm(AbstractAuditModel):
    id = models.AutoField(primary_key=True)
    Code = models.CharField('양식코드', max_length=20)
    Version = models.IntegerField('버전', default=1)
    Title = models.CharField('제목', max_length=200)
    Content = models.TextField('내용', null=True)
    TotalColumnWidth = models.IntegerField('총컬럼넓이', null=True)
    HeaderHeight = models.IntegerField('헤더높이', null=True)
    FixedTopContent = models.TextField('상단고정내용', null=True)
    EstablishDate = models.DateField('제정일', null=True)
    ApplyModel = models.CharField('적용모델', max_length=100, null=True)
    UseYN = models.CharField('사용여부', max_length=1, default='Y')
    StartDate = models.DateField('적용시작일', null=True)
    EndDate = models.DateField('적용종료일', null=True)
    Description = models.CharField('비고', max_length=500, null=True)
    LayoutType = models.CharField('레이아웃구분', max_length=10, default='GRID')  # GRID(칸 단위)/SECTION(양식 편집)
    FormType = models.CharField('양식구분', max_length=10, default='OUTGOING', db_default='OUTGOING')  # INCOMING(수입검사)/OUTGOING(품질검사)

    class Meta():
        db_table = 'dig_form'
        verbose_name = '디지털양식-문서헤더'
        unique_together = [
            ['Code', 'Version'],
        ]


class DigFormWorkClass(AbstractAuditModel):
    id = models.AutoField(primary_key=True)
    Class1Name = models.CharField('대분류명', max_length=100)
    Class2Name = models.CharField('중분류명', max_length=100, null=True)
    Class3Name = models.CharField('소분류명', max_length=100, null=True)
    Description = models.CharField('비고', max_length=500, null=True)

    class Meta():
        db_table = 'dig_form_work_class'
        verbose_name = '디지털양식-항목별작업마스터'


class DigFormSection(AbstractAuditModel):
    id = models.AutoField(primary_key=True)
    DigForm = models.ForeignKey(DigForm, on_delete=models.PROTECT)
    SectionType = models.CharField('섹션구분', max_length=20)  # PHOTO(참고사진)/INSPECTION(점검항목)
    Title = models.CharField('제목', max_length=200, null=True)
    Content = models.TextField('내용', null=True)  # 참고사진 에디터 HTML
    SortOrder = models.IntegerField('순서', default=0)
    Width = models.IntegerField('너비', null=True)  # 12칸 기준
    Height = models.IntegerField('높이', null=True)  # px, NULL = 자동
    # 점검항목 표 설정 (섹션마다 표 하나)
    ColumnCount = models.IntegerField('컬럼개수', null=True)
    HeaderRowCount = models.IntegerField('머리줄행수', default=1)  # 표 위쪽 머리줄 행 수 (2단 머리줄 등)
    WorkerColumnYN = models.CharField('작업자표시여부', max_length=1, default='Y')  # 본문 행 끝 작업자 열 자동 표시

    class Meta():
        db_table = 'dig_form_section'
        verbose_name = '디지털양식-섹션마스터'


class DigFormItem(AbstractAuditModel):
    id = models.AutoField(primary_key=True)
    DigFormSection = models.ForeignKey(DigFormSection, on_delete=models.PROTECT)  # 양식은 섹션을 거쳐 찾음
    DigFormWorkClass = models.ForeignKey(DigFormWorkClass, on_delete=models.PROTECT, null=True)
    RowType = models.CharField('구분', max_length=10)  # H(헤더)/D(디테일)
    RowIndex = models.IntegerField('행순번')  # 섹션마다 1부터
    ColumnIndex = models.IntegerField('컬럼순번')
    RowSpan = models.IntegerField('rowspan', default=1)
    ColSpan = models.IntegerField('colspan', default=1)
    Content = models.CharField('내용', max_length=1000, null=True)
    ResultType = models.CharField('판정타입', max_length=10, null=True)  # T/N/S/B
    CodeGroup = models.CharField('코드그룹', max_length=30, null=True)
    MinColumnWidth = models.IntegerField('최소컬럼넓이', null=True)
    InputYN = models.CharField('입력컬럼여부', max_length=1, default='N')
    UpperLimit = models.DecimalField('상한값', null=True, max_digits=18, decimal_places=3)
    LowerLimit = models.DecimalField('하한값', null=True, max_digits=18, decimal_places=3)
    # 섹션 양식 이미지 칸(ResultType='I', 본문 행)에 연결한 비전검사항목 — 작성 때 넣은 사진이 그 항목의 비전 데이터가 된다
    # 비전검사항목을 지우면 연결만 풀린다(SET_NULL). 연결을 바꾸면 양식 새 버전(form_edit.item_signature)
    VisionItem = models.ForeignKey(InspectionItem, on_delete=models.SET_NULL, null=True)

    class Meta():
        db_table = 'dig_form_item'
        verbose_name = '디지털양식-문서항목'
        constraints = [
            models.UniqueConstraint(fields=['DigFormSection', 'RowIndex', 'ColumnIndex'], name='dig_form_item_pos_uq'),
            models.CheckConstraint(condition=Q(InputYN='N') | Q(ResultType__isnull=False), name='dig_form_item_input_ck'),
            models.CheckConstraint(condition=Q(RowSpan__gte=1, ColSpan__gte=1), name='dig_form_item_span_ck'),
        ]


class DigFormResult(AbstractAuditModel):
    id = models.AutoField(primary_key=True)
    DigForm = models.ForeignKey(DigForm, on_delete=models.PROTECT)
    WriteDate = models.DateField('작성일')
    WorkOrderNumber = models.CharField('작지번호', max_length=50, null=True)
    State = models.CharField('작성상태', max_length=20, default='working')  # working(작성 중)/done(완료) — 완료는 되돌리지 않는다
    Round = models.IntegerField('차수', default=1)
    Description = models.CharField('비고', max_length=500, null=True)
    HeaderValues = models.TextField('머리글입력값', null=True)  # JSON {"<키>": "값"}

    class Meta():
        db_table = 'dig_form_result'
        verbose_name = '디지털양식-문서헤더결과'


class DigFormItemResult(AbstractAuditModel):
    id = models.AutoField(primary_key=True)
    DigFormResult = models.ForeignKey(DigFormResult, on_delete=models.PROTECT)
    DigFormItem = models.ForeignKey(DigFormItem, on_delete=models.PROTECT)
    TextResult = models.CharField('문자결과', max_length=500, null=True)
    NumberResult = models.DecimalField('숫자결과', null=True, max_digits=18, decimal_places=3)
    ComboResult = models.CharField('콤보결과', max_length=30, null=True)
    CheckResultYN = models.CharField('체크결과', max_length=1, null=True)

    class Meta():
        db_table = 'dig_form_item_result'
        verbose_name = '디지털양식-항목결과'
        unique_together = [
            ['DigFormResult', 'DigFormItem'],
        ]
