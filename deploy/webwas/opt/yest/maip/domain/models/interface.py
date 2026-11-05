from django.db import models

from .system import AbstractAuditModel

# 외부 인터페이스 수신 테이블(`if_*`) — 받은 것을 해석하지 않고 원본 열 그대로 담는다(DECISIONS 사용자 결정 2026-10-19).
# 값은 모두 글자다. 형 변환·검증은 마스터(품목·BOM·입고예정)로 옮기는 반영 단계가 맡는다.
# 칼럼의 verbose_name 은 원본 엑셀 머리글이다 — 파일 경로 어댑터(domain/services/interface.py)가 이것으로 열을 찾는다.
# 수신건(IfBatch)은 경로(파일·API·DB 연동)와 상관없이 같다. 실패한 수신도 행 없이 남긴다.
# 조직 구분이 없는 MES 계열 테이블이다(RLS 대상 아님).


class IfBatch(AbstractAuditModel):
    class Kinds(models.TextChoices):
        PLM_PART_BOM = 'PLM_PART_BOM', 'PLM 품목·BOM'
        ERP_PURCHASE_REQ = 'ERP_PURCHASE_REQ', 'ERP 구매요청 현황'

    class Channels(models.TextChoices):
        FILE = 'FILE', '파일'
        API = 'API', 'API'
        DB = 'DB', 'DB 연동'

    class Statuses(models.TextChoices):
        RECEIVE_FAILED = 'RECEIVE_FAILED', '수신 실패'
        RECEIVED = 'RECEIVED', '반영 대기'
        APPLIED = 'APPLIED', '반영 완료'
        APPLY_FAILED = 'APPLY_FAILED', '반영 실패'

    id = models.AutoField(primary_key=True)
    Kind = models.CharField('인터페이스구분', max_length=30, choices=Kinds.choices)
    Channel = models.CharField('수신경로', max_length=10, choices=Channels.choices, default='FILE', db_default='FILE')
    SourceRef = models.CharField('출처', max_length=255, null=True)  # 파일명·요청 id·조회 범위
    RowCount = models.IntegerField('행수')
    Status = models.CharField('상태', max_length=20, choices=Statuses.choices, default='RECEIVED', db_default='RECEIVED')
    Message = models.TextField('메시지', null=True)  # 수신·반영 실패 사유
    AppliedAt = models.DateTimeField('반영일시', null=True)  # 마지막 반영
    ApplyResult = models.JSONField('반영결과', null=True)  # 마지막 반영 건수

    class Meta():
        db_table = 'if_batch'
        verbose_name = '인터페이스-수신건'


class IfPlmPartBom(AbstractAuditModel):
    id = models.AutoField(primary_key=True)
    Batch = models.ForeignKey(IfBatch, on_delete=models.CASCADE, related_name='plm_rows')
    RowNo = models.IntegerField('파일행순서')
    No = models.TextField('No.', null=True)
    Depth = models.TextField('Depth', null=True)
    LineNo = models.TextField('Line No ( 7 Depth )', null=True)
    PartType = models.TextField('Part Type', null=True)
    PartErp = models.TextField('Part(ERP)', null=True)
    PartNo = models.TextField('Part No', null=True)
    PartName = models.TextField('Part Name', null=True)
    PartVer = models.TextField('Part Ver', null=True)
    Qty = models.TextField('Qty', null=True)
    Sub = models.TextField('Sub', null=True)
    SubTotal = models.TextField('Sub Total', null=True)
    SubMultiply = models.TextField('Sub Multiply', null=True)
    PartState = models.TextField('Part State', null=True)
    PartCheckout = models.TextField('Part Checkout', null=True)
    PostProcess = models.TextField('후처리', null=True)
    PartCreated = models.TextField('최초생성일(P)', null=True)
    PartVerCreated = models.TextField('현버전생성일(P)', null=True)
    Spec = models.TextField('Spec(P)', null=True)
    MaterialGroup = models.TextField('Material Group(P)', null=True)
    Material = models.TextField('Material(P)', null=True)
    Model3dType = models.TextField('3D Type', null=True)
    Model3dNo = models.TextField('3D No', null=True)
    Model3dName = models.TextField('3D Name', null=True)
    Model3dVer = models.TextField('3D Ver', null=True)
    Model3dState = models.TextField('3D State', null=True)
    Model3dCheckout = models.TextField('3D Checkout', null=True)
    Model3dNonOwnerRel = models.TextField('비소유자연관(M)', null=True)
    Model3dCreated = models.TextField('최초생성일(M)', null=True)
    Model3dVerCreated = models.TextField('현버전생성일(M)', null=True)
    Model3dModified = models.TextField('마지막수정일(M)', null=True)
    Drawing2dNo = models.TextField('2D No', null=True)
    Drawing2dName = models.TextField('2D Name', null=True)
    Drawing2dVer = models.TextField('2D Ver', null=True)
    Drawing2dState = models.TextField('2D State', null=True)
    Drawing2dCheckout = models.TextField('2D Checkout', null=True)
    Drawing2dRel = models.TextField('연관관계(D)', null=True)
    Drawing2dCreated = models.TextField('최초생성일(D)', null=True)
    Drawing2dVerCreated = models.TextField('현버전생성일(D)', null=True)
    Drawing2dModified = models.TextField('마지막수정일(D)', null=True)

    class Meta():
        db_table = 'if_plm_part_bom'
        verbose_name = '인터페이스-PLM품목BOM'


class IfErpPurchaseReq(AbstractAuditModel):
    id = models.AutoField(primary_key=True)
    Batch = models.ForeignKey(IfBatch, on_delete=models.CASCADE, related_name='erp_rows')
    RowNo = models.IntegerField('파일행순서')
    No = models.TextField('No', null=True)
    Plant = models.TextField('공장', null=True)
    ReqNo = models.TextField('요청번호', null=True)
    ReqSeq = models.TextField('요청순번', null=True)
    ReqAcctSeq = models.TextField('요청계정순번', null=True)
    ReqApprovalDate = models.TextField('요청결재일', null=True)
    InputDate = models.TextField('입력일', null=True)
    WbsElement = models.TextField('WBS요소', null=True)
    ProjectNo = models.TextField('프로젝트번호', null=True)
    ProjectName = models.TextField('프로젝트명', null=True)
    RequesterName = models.TextField('요청자명', null=True)
    UpgvcNo = models.TextField('UPGVC번호', null=True)
    Item = models.TextField('품목', null=True)
    ItemName = models.TextField('품목명', null=True)
    Spec = models.TextField('규격', null=True)
    Category = models.TextField('대분류', null=True)
    ReqDueDate = models.TextField('요청납기일', null=True)
    PlanReceiptDateAppr = models.TextField('입고예정일(품의)', null=True)
    PlanReceiptDatePo = models.TextField('입고예정일(발주)', null=True)
    Unit = models.TextField('단위', null=True)
    ReqQty = models.TextField('요청수량', null=True)
    ApprQty = models.TextField('품의수량', null=True)
    VendorAppr = models.TextField('거래처(품의)', null=True)
    PoQty = models.TextField('발주수량', null=True)
    ReceiptQty = models.TextField('입고수량', null=True)
    ReceiptDate = models.TextField('입고일자', null=True)
    PoNo = models.TextField('발주번호', null=True)
    PoDate = models.TextField('발주일자', null=True)
    VendorPo = models.TextField('거래처(발주)', null=True)
    PoStatus = models.TextField('발주상태', null=True)
    PoManager = models.TextField('발주담당자', null=True)
    Drawing2dDownload = models.TextField('2D다운로드', null=True)
    EoNo = models.TextField('EO번호', null=True)
    EoReason = models.TextField('EO발행사유', null=True)
    ReqCancelYN = models.TextField('구매요청취소여부', null=True)
    PurchaseOpinion = models.TextField('구매의견', null=True)
    PurchaseOpinionDetail = models.TextField('구매의견상세', null=True)
    ReqOpinion = models.TextField('요청의견', null=True)
    ReqOpinionDetail = models.TextField('요청의견상세', null=True)

    class Meta():
        db_table = 'if_erp_purchase_req'
        verbose_name = '인터페이스-ERP구매요청'
