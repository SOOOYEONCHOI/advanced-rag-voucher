from django.core.exceptions import ValidationError
from model_utils import Choices
#from django.utils.translation import ugettext_lazy

from django.db import models
from django.dispatch import receiver

from django.contrib.auth.models import User
from ..services.date import DateUtil

def space_check(value):
    if ' ' in value:
        raise ValidationError('Do not allow spaces.', params={'value': value})
    return


class AbstractAuditModel(models.Model):
    _status = models.CharField('_status', max_length=10, null=True)
    _created    = models.DateTimeField('_created', auto_now_add=True)
    _modified   = models.DateTimeField('_modfied', auto_now=True, null=True)
    _creater_id = models.IntegerField('_creater_id', null=True)
    _modifier_id = models.IntegerField('_modifier_id', null=True)
    
    class Meta:
        abstract = True

    def set_audit(self, user):
        if self._creater_id is None:
            self._creater_id = user.id
        self._modifier_id = user.id
        self._modified = DateUtil.get_current_datetime()
        return


class SystemLog(models.Model):
    id = models.BigAutoField(primary_key=True)
    Type= models.CharField('로그유형', max_length=20, null=True)
    Source= models.CharField('소스', max_length=100, null=True)
    Message = models.TextField('메시지', null=True)
    _created    = models.DateTimeField('_created', auto_now_add=True)

    class Meta():
        db_table = 'sys_log'
        verbose_name = '시스템로그'
        indexes = [
            models.Index(fields=['_created'], name='sys_log_created_idx'),
            models.Index(fields=['Type', '_created'], name='sys_log_type_created_idx'),
            models.Index(fields=['Source', '_created'], name='sys_log_source_created_idx'),
        ]

    @classmethod
    def add_log(cls, logtype, source, message=None):
        message = str(message)
        syslog = cls.objects.create(Type=logtype, Source=source, Message=message)
        return syslog


class LoginLog(models.Model):
    """로그인·로그아웃 기록. 실패도 남긴다.

    실패는 존재하지 않는 계정일 수 있어 `User` 가 null이다. 그때 어떤 아이디로
    시도했는지 알아야 하므로 `Username` 을 따로 둔다.
    """

    id = models.BigAutoField(primary_key=True)
    Type = models.CharField('구분', max_length=50)          # login / logout / fail
    User = models.ForeignKey(User, on_delete=models.DO_NOTHING, null=True)
    Username = models.CharField('시도한 아이디', max_length=150, null=True)
    IPAddress = models.GenericIPAddressField('IP주소', null=True)
    UserAgent = models.CharField('User-Agent', max_length=300, null=True)
    FailReason = models.CharField('실패 사유', max_length=100, null=True)
    _created    = models.DateTimeField('_created', auto_now_add=True)
    class Meta():
        db_table = 'login_log'
        verbose_name = '로그인로그'
        indexes = [
            models.Index(fields=['_created'], name='login_log_created_idx'),
            models.Index(fields=['User', '_created'], name='login_log_user_created_idx'),
            models.Index(fields=['IPAddress', '_created'], name='login_log_ip_created_idx'),
        ]


class SystemCode(AbstractAuditModel):
    id = models.AutoField(primary_key=True)
    CodeType = models.CharField('코드유형', max_length=30)
    Code = models.CharField('코드', max_length=30)
    Value = models.CharField('디코드값', max_length=30)
    Description	= models.CharField('설명', max_length=500, null=True)
    _ordering   = models.IntegerField('_순서',default=0, null=True)

    class Meta():
        db_table = 'sys_code'
        verbose_name = '시스템코드'
        unique_together = [
            ['CodeType', 'Code'],
        ]
        indexes = [
            models.Index(fields=['CodeType', 'Code', 'Value'], name='sys_code_type_code_value_idx'),
        ]


class UserCode(AbstractAuditModel):
    id  = models.AutoField(primary_key=True)
    Code = models.CharField('코드', max_length=30)
    Value = models.CharField('디코드값', max_length=100)
    Description	= models.CharField('설명', max_length=500, null=True)
    Parent = models.ForeignKey('self', verbose_name='Parent', related_name='Children', on_delete=models.PROTECT, null=True)
    _order   = models.IntegerField('순서',default=0, null=True)
    Type = models.CharField('구분', max_length=100, null=True)
    Type2 = models.CharField('구분2', max_length=100, null=True)
    StartDate = models.DateField('적용시작일', null=True)
    EndDate = models.DateField('적용종료일', null=True)

    class Meta():
        db_table = 'user_code'
        verbose_name = '사용자코드'
        unique_together = [
            ['Code', 'Parent'],
        ]
        indexes = [
            models.Index(fields=['Parent', 'Code', 'Value'], name='user_code_parent_code_val_idx'),
        ]


class LabelCode(AbstractAuditModel):
    id = models.AutoField(primary_key=True)
    ModuleName = models.CharField('화면명', max_length=100)
    TemplateKey = models.CharField('템플릿명', max_length=100)
    LabelCode = models.CharField('라벨코드', max_length=200)
    Description	= models.CharField('설명', max_length=200, null=True)
    
    class Meta():
        db_table = 'label_code'
        verbose_name = '라벨코드'
        unique_together = [
            ['ModuleName', 'TemplateKey', 'LabelCode'],
        ]


class LabelCodeLanguage(AbstractAuditModel):
    id = models.AutoField(primary_key=True)
    LabelCode = models.ForeignKey(LabelCode, on_delete=models.CASCADE)
    LangCode = models.CharField('언어코드', max_length=30)
    DispText = models.CharField('표시문자', max_length=500)

    class Meta():
        db_table = 'label_code_lang'
        verbose_name = '라벨다국어설정'
        unique_together = [
            ['LabelCode', 'LangCode'],
        ]
        indexes = [
            models.Index(fields=['LabelCode', 'LangCode', 'DispText'], name='label_lang_code_lang_text_idx'),
        ]


class MenuFolder(AbstractAuditModel):
    id = models.AutoField(primary_key=True)
    FolderName = models.CharField('폴더명', max_length=50)
    IconCSS = models.CharField('아이콘스타일', max_length=50, null=True)
    Parent = models.ForeignKey('self', verbose_name='부모폴더', related_name='Children', on_delete=models.CASCADE, null=True)
    _order = models.IntegerField('순서',default=0, null=True)

    class Meta():
        db_table = 'menu_folder'
        verbose_name = '메뉴폴더'
        # index_together(Parent) 는 외래키 인덱스와 중복이라 지웠다(0015, Django 5.1 에서 index_together 제거)


class MenuItem(AbstractAuditModel):
    MenuCode = models.CharField('메뉴코드', primary_key=True, max_length=50)
    MenuName = models.CharField('메뉴명', max_length=50)
    MenuFolder = models.ForeignKey(MenuFolder, on_delete=models.DO_NOTHING, null=True)    
    IconCSS = models.CharField('아이콘스타일', max_length=50, null=True)
    Url = models.CharField('Url', max_length=100, null=True)
    _order = models.IntegerField('순서', default=0, null=True)

    class Meta():
        db_table = 'menu_item'
        verbose_name = '메뉴항목'
        #index_together = [
        #    ['MenuFolder'],
        #]


class Bookmark(models.Model):
    id = models.AutoField(primary_key=True)
    User = models.ForeignKey(User, on_delete=models.CASCADE)    
    MenuItem = models.ForeignKey(MenuItem, on_delete=models.CASCADE, db_column='MenuCode')
    _created    = models.DateTimeField('_created', auto_now_add=True)

    class Meta():
        db_table = 'bookmark'
        verbose_name = '바로가기메뉴'
        unique_together = [
            ['User', 'MenuItem'],
        ]


class DocumentForm(AbstractAuditModel):
    id = models.AutoField(primary_key=True)
    FormType = models.CharField('문서유형', max_length=20,)
    FormGroup = models.CharField('양식종류', max_length=20,)
    FormName = models.CharField('양식명', max_length=200,)
    Content = models.TextField('내용', null=True, )
    Description	= models.CharField('설명', max_length=500, null=True)
    State = models.CharField('상태', max_length=20, null=True)
    StartDate = models.DateTimeField('적용시작일', null=True)
    EndDate = models.DateTimeField('적용종료일', null=True)
    
    class Meta():
        db_table = 'doc_form'
        verbose_name = '문서양식'
        indexes = [
            models.Index(fields=['FormType'], name='doc_form_type_idx'),
        ]


class DocumentResult(AbstractAuditModel):
    id  = models.AutoField(primary_key=True)
    DocumentForm = models.ForeignKey(DocumentForm, on_delete=models.PROTECT)
    DocumentDate = models.DateField('일자')
    DocumentName = models.CharField('문서명', max_length=200)
    Content	= models.TextField('내용', null=True)
    Description	= models.CharField('설명', max_length=500, null=True)
    Number1 = models.DecimalField('수치값1', null=True, max_digits=18, decimal_places=3)
    Number2 = models.DecimalField('수치값2', null=True, max_digits=18, decimal_places=3)
    Number3 = models.DecimalField('수치값3', null=True, max_digits=18, decimal_places=3)
    Text1 = models.CharField('문자값1', max_length=100, null=True)
    Text2 = models.CharField('문자값2', max_length=100, null=True)
    Text3 = models.CharField('문자값3', max_length=100, null=True)

    class Meta():
        db_table = 'doc_result'
        verbose_name = '문서결과'
        indexes = [
            models.Index(fields=['DocumentForm', 'DocumentDate'], name='doc_result_form_date_idx'),
            models.Index(fields=['DocumentDate'], name='doc_result_date_idx'),
        ]


class AttachMaster(AbstractAuditModel):
    id = models.AutoField(primary_key=True)
    TableName = models.CharField('테이블명', max_length=50)
    AttachName = models.CharField('첨부명', max_length=50)
    Description	= models.CharField('설명', max_length=500, null=True)
    FilePath = models.CharField('파일경로', max_length=500, null=True)

    class Meta():
        db_table = 'attach_master'
        verbose_name = '첨부파일정의'
        indexes = [
            models.Index(fields=['TableName'], name='attach_master_table_idx'),
        ]


class AttachFile(AbstractAuditModel):
    id = models.AutoField(primary_key=True)
    TableName = models.CharField('테이블명', max_length=50)
    DataPk = models.IntegerField('데이터pk')
    AttachName = models.CharField('첨부명', max_length=50) # 데이터의 업무 구분
    FileIndex = models.IntegerField('파일인덱스')
    FileName = models.CharField('파일명', max_length=100) # 사용자의 업로드한 파일명
    PhysicFileName = models.CharField('물리파일명', max_length=100) # 물리적인 저장파일명
    ExtName = models.CharField('확장자', max_length=10, null=True)
    FilePath = models.CharField('파일경로', max_length=500, null=True)
    FileSize = models.IntegerField('파일사이즈', null=True)
    class Meta():
        db_table = 'attach_file'
        verbose_name = '첨부파일'
        #unique_together = [
        #    ['DataPk', 'TableName', 'AttachName', 'FileIndex'],
        #]
        indexes = [
            models.Index(fields=['DataPk', 'TableName'], name='attach_file_pk_table_idx'),
        ]


#class BoardGroup(AbstractAuditModel):
#    id  = models.AutoField(primary_key=True)
#    Code = models.CharField('Code', max_length=50)
#    Name = models.CharField('Name', max_length=50)
#    Description	= models.CharField('Description', max_length=500, null=True)
#    class Meta():
#        db_table = 'board_group'


class PropertyMaster(AbstractAuditModel):
    id = models.AutoField(primary_key=True)
    TableName = models.CharField('테이블명', max_length=50)
    Code = models.CharField('속성코드', max_length=50)
    Type = models.CharField('속성유형', max_length=50, null=True)
    Description	= models.CharField('속성설명', max_length=500, null=True)

    class Meta():
        db_table = 'prop_master'
        verbose_name = '속성정의'
        unique_together = [
            ('TableName', 'Code'),
        ]


class PropertyData(AbstractAuditModel):
    ''' 공통속성데이터
    '''
    id = models.AutoField(primary_key=True)
    DataPk = models.IntegerField('데이터pk')
    TableName = models.CharField('테이블명', max_length=50)
    Code = models.CharField('속성코드', max_length=50)
    Type = models.CharField('속성유형', max_length=50, null=True)
    Char1 = models.CharField('문자값1', max_length=200, null=True)
    Number1 =  models.DecimalField('수치값1', null=True, max_digits=18, decimal_places=3)
    Date1 = models.DateTimeField('일시값1', null=True)
    Text1 = models.TextField('텍스트값1', null=True)
 
    Number2 =  models.DecimalField('수치값2', null=True, max_digits=18, decimal_places=3)

    class Meta():
        db_table = 'prop_data'
        verbose_name = '속성데이터'
        unique_together = [
            ('DataPk', 'TableName', 'Code'),
        ]


class SequenceMaker(models.Model):
    """ 채번테이블
    """
    id = models.BigAutoField(primary_key=True)
    Code = models.CharField('코드', max_length=50)
    Code2 = models.CharField('코드2', max_length=50, default='', null=True)
    BaseDate = models.CharField('기준일자', max_length=10)
    CurrVal = models.IntegerField('현재값', default=0)
    _modified   = models.DateTimeField('_modfied', auto_now=True, null=True)

    class Meta():
        db_table = 'seq_maker'
        verbose_name = '채번마스터'
        unique_together = [
            ['BaseDate', 'Code', 'Code2'],
        ]


class GridColumn(AbstractAuditModel):
    id = models.AutoField(primary_key=True)
    ModuleName = models.CharField('화면명', max_length=100)
    TemplateKey = models.CharField('템플릿명', max_length=50)
    GridName = models.CharField('그리드명', max_length=50)
    Key	= models.CharField('컬럼키', max_length=50)
    Index	= models.IntegerField('순서')
    Label	= models.CharField('라벨', max_length=50, null=True)
    Width	= models.IntegerField('너비', null=True)
    Hidden	= models.CharField('감춤', max_length=1, null=True)

    DataField  = models.CharField('데이터필드', max_length=50, null=True)
    HeaderText = models.CharField('헤더명', max_length=50, null=True)
    Visible    = models.BooleanField('표시여부', default=True, null=True)

    class Meta():
        db_table = 'grid_col'
        verbose_name = '그리드컬럼설정'
        unique_together = [
            ['ModuleName', 'TemplateKey', 'GridName', 'Key'],
            #['ModuleName', 'TemplateKey', 'GridName', 'Index'],
        ]


class GridColumnLanguage(AbstractAuditModel):
    id = models.AutoField(primary_key=True)
    GridColumn = models.ForeignKey(GridColumn, on_delete=models.CASCADE)
    LangCode = models.CharField('언어', max_length=30)
    DispText = models.CharField('표시문자', max_length=500)

    class Meta():
        db_table = 'grid_col_lang'
        verbose_name = '그리드컬럼언어'
        unique_together = [
            ['GridColumn', 'LangCode'],
        ]



class MenuUseLog(AbstractAuditModel):
    id = models.BigAutoField(primary_key=True)
    MenuCode = models.CharField('메뉴코드', max_length = 50)
    User = models.ForeignKey(User, on_delete=models.CASCADE)    
    #ClickTime = models.DateTimeField('ClickTime', auto_now_add=True)
    #UseTime = models.DateTimeField('UseTime', null=True)
    class Meta():
        db_table = 'menu_use_log'
        verbose_name = '메뉴사용로그'
        indexes = [
            models.Index(fields=['_created'], name='menu_log_created_idx'),
            models.Index(fields=['User', '_created'], name='menu_log_user_created_idx'),
            models.Index(fields=['MenuCode', '_created'], name='menu_log_menu_created_idx'),
            models.Index(fields=['User', 'MenuCode', '_created'], name='menu_log_user_menu_crt_idx'),
        ]


class ClassMaster(AbstractAuditModel):
    ''' 공통분류마스터
    '''
    id = models.AutoField(primary_key=True)
    TableName = models.CharField('테이블명', max_length=50)
    ClassName = models.CharField('분류명', max_length=50, default='Basic')
    Tag = models.CharField('분류코드', max_length=100)
 
    class Meta():
        db_table = 'class_master'
        verbose_name = '분류마스터'
        unique_together = [
            ('TableName', 'Tag', 'ClassName'),
        ]


class ClassData(AbstractAuditModel):
    ''' 공통분류데이터
    '''
    id = models.AutoField(primary_key=True)
    DataPk = models.IntegerField('데이터pk')
    TableName = models.CharField('테이블명', max_length=50)
    ClassName = models.CharField('분류명', max_length=50, default='Basic')
    Tag = models.CharField('분류코드', max_length=100)
 
    class Meta():
        db_table = 'class_data'
        verbose_name = '분류데이터'
        unique_together = [
            ('DataPk', 'TableName', 'ClassName', 'Tag'),
        ]
        indexes = [
            models.Index(fields=['TableName', 'ClassName', 'Tag', 'DataPk'], name='class_data_tbl_cls_tag_pk_idx'),
        ]


class SystemOption(AbstractAuditModel):
    id = models.AutoField(primary_key=True)
    Code = models.CharField('코드', max_length=50)
    Value = models.CharField('값', max_length=500, null=True)
    Description = models.CharField('설명', max_length=500, null=True)
    
    class Meta():
        db_table = 'sys_option'
        verbose_name = '시스템옵션'
        unique_together = [
            ['Code'],
        ]


class Depart(AbstractAuditModel):
    id = models.AutoField(primary_key=True)
    Name = models.CharField('부서명', max_length=200)
    Code = models.CharField('부서코드', max_length=50, validators=[space_check], null=True)
    Type	= models.CharField('부서유형', max_length=20, null=True)
    Description	= models.CharField('비고', max_length=1000, null=True)

    class Meta():
        db_table = 'depart'
        verbose_name = '부서'
        unique_together = [
            ['Code'],
            ['Name'],
        ]
