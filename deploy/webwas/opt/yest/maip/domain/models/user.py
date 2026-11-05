from model_utils import Choices
#from django.utils.translation import ugettext_lazy
from django.db import models
from django.db.models.signals import post_save

from django.dispatch import receiver
from django.contrib.auth.models import User

#json 필드를 사용시에 postgres 종속성이 생긴다.
from .system import space_check, AbstractAuditModel
from .basic import Factory, Company
from .system import Depart

class UserGroup(AbstractAuditModel):
    id = models.AutoField(primary_key=True, editable=False)
    Code = models.CharField('코드', max_length=50)
    Name = models.CharField('사용자그룹명', max_length=100, default='None')
    Disabled = models.BooleanField('사용안함', null=True, default=False)
    Description	= models.CharField('비고', max_length=500, null=True)

    class Meta():
        db_table = 'user_group'
        verbose_name = '사용자그룹'
        verbose_name_plural = 'User Groups'
        default_related_name = 'UserGroup'

        unique_together = [
            ['Code'],
        ]


class UserProfile(AbstractAuditModel):
    """`auth_user` 확장. Django User 모델은 커스터마이즈하지 않는다.

    PDA용 `access_token`/`refresh_token` 컬럼을 제거했다. 토큰을 DB에 평문으로
    두는 것은 바람직하지 않고, PDA 자체가 이번 범위 밖이다.
    """

    User = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True)
    UserGroup = models.ForeignKey(UserGroup, on_delete=models.DO_NOTHING, null=True)
    Factory = models.ForeignKey(Factory, on_delete=models.DO_NOTHING, null=True)
    password_changed = models.DateTimeField('패스워드변경일', null=True)
    lang_code =  models.CharField('사용언어코드', max_length=30, default='ko-KR')
    Name = models.CharField('사용자명', max_length=100, null=True)
    Company = models.ForeignKey(Company, on_delete=models.DO_NOTHING, null=True)
    Depart = models.ForeignKey(Depart, on_delete=models.DO_NOTHING, null=True)
    #disabled = models.BooleanField(blank=False, null=False, default=True)

    class Meta():
        db_table = 'user_profile'
        verbose_name = '사용자프로필'


@receiver(post_save, sender=User)
def update_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(User=instance)
        _join_single_tenant(instance)
    instance.userprofile.save()


def _join_single_tenant(user):
    """새 사용자를 조직(YEST)에 넣는다.

    데이터 화면의 조직 접근 판정(`TenantAccessService`)이 소속을 본다. 사용자
    화면·시드·`createsuperuser`·클라이언트 서비스 계정이 모두 이 시그널을 지나므로
    여기 한 곳에서 넣는다.
    """
    from domain.models.data import Tenant, TenantMembership
    from domain.tenancy import FIXED_TENANT_ID, FIXED_TENANT_NAME, tenant_atomic

    # current_tenant() 의 캐시를 쓰지 않는다. 테스트가 트랜잭션을 되돌리면 캐시된
    # 행이 DB 에 없어 외래키가 깨진다.
    tenant, _ = Tenant.objects.get_or_create(
        id=FIXED_TENANT_ID, defaults={'name': FIXED_TENANT_NAME})
    with tenant_atomic(tenant):
        TenantMembership.objects.get_or_create(tenant=tenant, user=user)


    return


class UserGroupMenu(AbstractAuditModel):
    id = models.AutoField(primary_key=True, editable=False)
    UserGroup = models.ForeignKey(UserGroup, on_delete=models.CASCADE, null=True)
    MenuCode = models.CharField('메뉴코드', max_length=50, null=False)
    AuthCode = models.CharField('권한코드', max_length=10, null=False)
    class Meta():
        db_table = 'user_group_menu'
        verbose_name = '사용자그룹메뉴'

        unique_together = [
            ['MenuCode', 'UserGroup'],
        ]

