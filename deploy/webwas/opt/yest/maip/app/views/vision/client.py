"""비전검사 클라이언트 관리 (`wm_vis_client`).

MES 규약: 단일 함수 + `action` 분기, 조회는 행 목록, 변경은 `{'success', 'message'}`.
"""
import hashlib
import secrets

from django.contrib.auth.models import User
from django.db import transaction

from domain.models.data import TenantMembership
from domain.models.user import UserGroup, UserProfile
from domain.models.vision import VisionClient, VisionInspection
from domain.services.logging import LogWriter
from domain.tenancy import current_tenant, tenant_atomic


def client(context):
    """api/vision/client"""
    gparam = context.gparam
    posparam = context.posparam
    action = gparam.get('action', 'list')

    try:
        if action == 'list':
            keyword = (gparam.get('keyword') or '').strip()
            queryset = VisionClient.objects.all()
            if keyword:
                queryset = queryset.filter(client_id__icontains=keyword)
            return [{
                'id': row.id,
                'client_id': row.client_id,
                'name': row.name,
                'active': row.active,
                'last_seen_at': row.last_seen_at.strftime('%Y-%m-%d %H:%M:%S')
                if row.last_seen_at else '',
                'created_at': row.created_at.strftime('%Y-%m-%d %H:%M'),
            } for row in queryset.order_by('client_id')]

        if action == 'detail':
            row = VisionClient.objects.filter(id=gparam.get('id')).first()
            if row is None:
                return {'success': False, 'message': '클라이언트를 찾을 수 없습니다.'}
            return {'id': row.id, 'client_id': row.client_id, 'name': row.name,
                    'active': row.active}

        if action == 'save':
            return _save(context, posparam)

        if action == 'reissue_key':
            return _reissue_key(posparam.get('id'))

        if action == 'delete':
            return _delete(posparam.get('id'))

        raise ValueError('action: ' + str(action))

    except Exception as ex:
        LogWriter.add_dblog('error', 'vision/client : action-{}'.format(action), ex)
        return {'success': False, 'message': '처리 중 오류가 발생했습니다.'}


@transaction.atomic
def _save(context, posparam):
    client_id = (posparam.get('client_id') or '').strip()
    name = (posparam.get('name') or '').strip()
    if not client_id or not name:
        return {'success': False, 'message': 'Client ID 와 이름을 입력해 주세요.'}

    # 상세 영역의 "사용" 필드. 보내지 않으면 사용이다(등록 기본값).
    active = posparam.get('active') not in ('0', 'false', 'False')

    row_id = posparam.get('id')
    if row_id:
        row = VisionClient.objects.filter(id=row_id).first()
        if row is None:
            return {'success': False, 'message': '클라이언트를 찾을 수 없습니다.'}
        row.name = name
        row.active = active
        row.save(update_fields=['name', 'active', 'updated_at'])
        return {'success': True, 'id': row.id}

    if VisionClient.objects.filter(client_id=client_id).exists():
        return {'success': False, 'message': '이미 등록된 Client ID 입니다.'}

    api_key = secrets.token_urlsafe(32)
    row = VisionClient.objects.create(
        client_id=client_id, name=name, active=active,
        api_key_hash=hashlib.sha256(api_key.encode('utf-8')).hexdigest(),
        service_account=_create_service_account(client_id, name))

    # API Key 는 해시만 저장한다. 이 응답이 원문을 볼 수 있는 유일한 기회다.
    return {'success': True, 'id': row.id, 'api_key': api_key,
            'message': 'API Key 는 지금만 확인할 수 있습니다. 안전한 곳에 보관해 주세요.'}


def _delete(row_id):
    """검사 기록이 없을 때만 지운다(검사는 클라이언트를 PROTECT 로 가리킨다). 서비스 계정도 함께 지운다.

    서비스 계정을 가리키는 업로더 등은 SET_NULL 이고 그 테이블이 RLS 라 테넌트 컨텍스트 안에서 지운다.
    """
    with tenant_atomic():
        row = VisionClient.objects.filter(id=row_id).select_related('service_account').first()
        if row is None:
            return {'success': False, 'message': '클라이언트를 찾을 수 없습니다.'}
        if VisionInspection.objects.filter(client=row).exists():
            return {'success': False, 'message': '검사 기록이 있어 삭제할 수 없습니다. 사용을 해제해 주세요.'}
        account = row.service_account
        row.delete()
        if account is not None:
            account.delete()
    return {'success': True, 'message': '삭제되었습니다.'}


def _reissue_key(row_id):
    row = VisionClient.objects.filter(id=row_id).first()
    if row is None:
        return {'success': False, 'message': '클라이언트를 찾을 수 없습니다.'}
    api_key = secrets.token_urlsafe(32)
    row.api_key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()
    row.save(update_fields=['api_key_hash', 'updated_at'])
    return {'success': True, 'api_key': api_key,
            'message': '기존 키는 즉시 무효가 됩니다. 현장 클라이언트 설정을 바꿔야 합니다.'}


def _create_service_account(client_id, name):
    """클라이언트가 보낸 이미지의 업로더로 기록할 계정.

    웹 로그인은 불가능하다. 활동 이력에 "누가 올렸는가"를 남기기 위한 것이다.
    """
    username = 'svc-{}'.format(client_id.lower())
    account, _ = User.objects.get_or_create(username=username, defaults={'is_active': True})
    account.set_unusable_password()
    account.save()

    user_group = UserGroup.objects.filter(Code='user').first()
    UserProfile.objects.filter(User=account).update(Name=name, UserGroup=user_group)
    with tenant_atomic() as tenant:
        TenantMembership.objects.get_or_create(tenant=tenant, user=account)
    return account
