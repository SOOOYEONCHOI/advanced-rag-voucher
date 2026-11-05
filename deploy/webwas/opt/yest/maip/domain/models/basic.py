"""통합 플랫폼이 유지하는 MES 기준정보 모델.

원본 MES `domain/models/mes.py`(96개 업무 모델)에서 범위 내 3개만 남겼다.
`Depart`는 `system.py`에 있다. 품목·BOM 은 PLM 인터페이스 수신건을 반영해 만든다(domain/services/plm_bom.py).
입고는 ERP 구매요청 현황(= 입고의뢰) 수신건을 반영해 만든다(domain/services/receipt.py).
"""
from django.db import models

from .interface import IfBatch
from .system import AbstractAuditModel


class Unit(AbstractAuditModel):
    id  = models.AutoField(primary_key=True)
    Name = models.CharField('단위명', max_length=30)
    Description	= models.CharField('설명', max_length=200, null=True)
    PieceYN	= models.CharField('낱개단위YN', max_length=1, null=True)
    class Meta():
        db_table = 'unit'
        verbose_name = '단위'
        unique_together = [
            ['Name'],
        ]


class Factory(AbstractAuditModel):
    id  = models.AutoField(primary_key=True)
    Code = models.CharField('공장코드', max_length=50)
    Name = models.CharField('공장명', max_length=100, null=True)
    
    class Meta():
        db_table = 'factory'
        verbose_name = '공장'
        unique_together = [
            ['Code'],
            ['Name'],
        ]


class Company(AbstractAuditModel):
    id = models.AutoField(primary_key=True)
    Name = models.CharField('업체명', max_length=50)
    EngName = models.CharField('영문업체명', max_length=100, null=True)
    Code = models.CharField('업체코드', max_length=50, null=True)
    Code2 = models.CharField('업체코드2', max_length=50, null=True)
    Country = models.CharField('국가', max_length=50, null=True)
    CompanyType = models.CharField('업체유형', max_length=30, null=True)
    GroupName =  models.CharField('업체그룹', max_length=100, null=True)  #그룹명
    BusinessNumber= models.CharField('사업자번호', max_length=50, null=True)
    CEOName = models.CharField('대표이사', max_length=50, null=True)
    ZipCode = models.CharField('우편번호', max_length=50, null=True)
    Address = models.CharField('주소', max_length=100, null=True)
    TelNumber = models.CharField('전화번호', max_length=100, null=True)
    FaxNumber = models.CharField('팩스번호', max_length=100, null=True)
    BusinessType = models.CharField('업태', max_length=50, null=True)
    BusinessItem = models.CharField('종목', max_length=50, null=True)
    Email = models.EmailField('이메일', null=True)
    Homepage = models.CharField('홈페이지', max_length=100, null=True)  #홈페이지
    ShippingLocation = models.CharField('출하장소', max_length=100, null=True)  #홈페이지
    Description = models.CharField('비고', max_length=500, null=True)    #비고

    PurchaseSalesDeadline= models.CharField('매입매출마감일', max_length=50, null=True)
    TradingGrade= models.CharField('거래등급', max_length=30, null=True)
    FirstTradingDay = models.DateField('거래개시일', null=True)    #거래개시일
    LastTradingDay = models.DateField('최종거래일', null=True)
    OurManager = models.CharField('자사담당자', max_length=50, null=True)
    SalesManager = models.CharField('영업담당자', max_length=50, null=True)
    SalesManagerPhone = models.CharField('영업담당자전번', max_length=50, null=True)
    AccountManager = models.CharField('경리담당자', max_length=50, null=True)
    AccountManagerPhone = models.CharField('경리담당자전번', max_length=50, null=True)
    ReceivableAmount = models.DecimalField('미수금액', null=True, max_digits=18, decimal_places=3)      #미수금액
    UnpaidAmount = models.DecimalField('미지급금액', null=True, max_digits=18, decimal_places=3)   #미지급금액

    #CreditSalesLimitAmount = models.FloatField('CreditSalesLimitAmount', null=True)
    TrandingBank = models.CharField('거래은행', max_length=50, null=True)
    AccountHolder = models.CharField('예금주', max_length=50, null=True)
    AccountNumber = models.CharField('계좌번호', max_length=50, null=True)
    CreditLimitAmount = models.DecimalField('여신한도금액', null=True, max_digits=18, decimal_places=3)
    PaymentCondition = models.CharField('대금결제조건', max_length=50, null=True)
    ManageRemark = models.CharField('관리비고', max_length=500, null=True)  #관리비고
    
    # 결재방법
    PaymentMethod = models.CharField('결재방법', max_length=200)

    CompanyTelNumber = models.CharField('전화번호2', max_length=50, null=True)
    
    class Meta():
        db_table = 'company'
        verbose_name = '업체'
        unique_together = [
            ['Name'],
            ['Code'],
            ['BusinessNumber'],
        ]

        #index_together = [
        #    (),
        #]


class Product(AbstractAuditModel):
    """품목 마스터. PLM `Part(ERP)` 가 코드다 — 리비전이 오르면 새 품목이 된다. 지우지 않는다."""
    id = models.AutoField(primary_key=True)
    Code = models.CharField('품목코드', max_length=50)
    PartNo = models.CharField('품번', max_length=50)
    Revision = models.CharField('리비전', max_length=10)
    Version = models.CharField('버전', max_length=20, null=True)
    Name = models.CharField('품목명', max_length=200)
    PartType = models.CharField('품목유형', max_length=30, null=True)
    Spec = models.CharField('규격', max_length=200, null=True)
    MaterialGroup = models.CharField('자재그룹', max_length=100, null=True)
    Material = models.CharField('재질', max_length=100, null=True)
    PostProcess = models.CharField('후처리', max_length=200, null=True)
    PartState = models.CharField('PLM상태', max_length=20, null=True)
    PlmCreatedDate = models.DateField('최초생성일', null=True)
    PlmVersionDate = models.DateField('현버전생성일', null=True)
    Model3dType = models.CharField('3D유형', max_length=10, null=True)
    Model3dNo = models.CharField('3D번호', max_length=100, null=True)
    Model3dVersion = models.CharField('3D버전', max_length=20, null=True)
    Model3dState = models.CharField('3D상태', max_length=20, null=True)
    Model3dModified = models.DateTimeField('3D마지막수정일', null=True)
    Drawing2dNo = models.CharField('2D번호', max_length=100, null=True)
    Drawing2dVersion = models.CharField('2D버전', max_length=20, null=True)
    Drawing2dState = models.CharField('2D상태', max_length=20, null=True)
    Drawing2dModified = models.DateTimeField('2D마지막수정일', null=True)

    class Meta():
        db_table = 'mst_product'
        verbose_name = '품목'
        unique_together = [
            ['Code'],
        ]


class Bom(AbstractAuditModel):
    """BOM 마스터 — 부모-자식 한 쌍이 한 행이다. 장비 트리는 Parent 에서 재귀로 펼친다."""
    id = models.AutoField(primary_key=True)
    Parent = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='bom_children')
    Child = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='bom_parents')
    Qty = models.DecimalField('수량', max_digits=18, decimal_places=3)
    Seq = models.IntegerField('순서')

    class Meta():
        db_table = 'mst_bom'
        verbose_name = 'BOM'
        unique_together = [
            ['Parent', 'Child'],
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(Qty__gt=0), name='ck_mst_bom_qty_positive'),
            models.CheckConstraint(condition=~models.Q(Parent=models.F('Child')), name='ck_mst_bom_not_self'),
        ]


class Receipt(AbstractAuditModel):
    """입고 — ERP 구매요청 현황(= 입고의뢰) 한 줄이 입고 한 줄이다. 구매요청 수신건 반영으로만 만든다.

    입고번호(`ReceiptNo` = 요청번호-요청순번)가 수입검사 작성건의 `WorkOrderNumber` 다. 검사 상태는 저장하지 않고 그 작성건으로 센다.
    """
    id = models.AutoField(primary_key=True)
    ReceiptNo = models.CharField('입고번호', max_length=50)
    ReqNo = models.CharField('요청번호', max_length=30)
    ReqSeq = models.IntegerField('요청순번')
    Product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='receipts')
    ItemCode = models.CharField('품목코드', max_length=50)
    ItemName = models.CharField('품목명', max_length=200)
    Spec = models.CharField('규격', max_length=200, null=True)
    Category = models.CharField('대분류', max_length=50, null=True)
    Unit = models.CharField('단위', max_length=20, null=True)
    Qty = models.DecimalField('수량', max_digits=18, decimal_places=3)
    ReceiptDate = models.DateField('입고일', null=True)
    VendorName = models.CharField('거래처명', max_length=100, null=True)
    ProjectNo = models.CharField('프로젝트번호', max_length=50, null=True)
    ProjectName = models.CharField('프로젝트명', max_length=200, null=True)
    RequesterName = models.CharField('요청자명', max_length=50, null=True)
    EoNo = models.CharField('EO번호', max_length=50, null=True)
    Batch = models.ForeignKey(IfBatch, on_delete=models.SET_NULL, null=True, related_name='receipts')  # 마지막으로 바꾼 수신건

    class Meta():
        db_table = 'mst_receipt'
        verbose_name = '입고'
        unique_together = [
            ['ReceiptNo'],
        ]


class ProductForm(AbstractAuditModel):
    """품목별 수입검사 양식 — 품번(리비전 무관)과 양식코드 N:M. 검사할 때 그 코드의 사용 중인 최신 버전을 연다."""
    id = models.AutoField(primary_key=True)
    PartNo = models.CharField('품번', max_length=50)
    FormCode = models.CharField('양식코드', max_length=20)

    class Meta():
        db_table = 'mst_product_form'
        verbose_name = '품목검사양식'
        unique_together = [
            ['PartNo', 'FormCode'],
        ]

