"""인터페이스 이력 (`wm_interface_log`) — 조회 전용. 수신건(`if_batch`)과 그 원본 행을 본다.

수신·반영은 명령(`import_interface`·`apply_interface`)이 한다. 원본 행의 열은 종류 등록부(`INTERFACES`)에서 받는다.
"""
from datetime import datetime, timedelta

from django.contrib.auth.models import User

from app.views.item import paged
from domain.models.interface import IfBatch
from domain.models.user import UserProfile
from domain.services.interface import INTERFACES, columns
from domain.services.logging import LogWriter

NO_RULE = '반영 규칙 없음'


def interface_log(context):
    """api/definition/interface_log"""
    gparam = context.gparam
    action = gparam.get('action', 'list')
    try:
        if action == 'list':
            return _list(gparam)
        if action == 'filters':
            return {'kinds': _choices(IfBatch.Kinds), 'channels': _choices(IfBatch.Channels),
                    'statuses': _choices(IfBatch.Statuses)}
        if action == 'detail':
            return _detail(IfBatch.objects.get(id=gparam.get('id')))
        if action == 'rows':
            return _rows(IfBatch.objects.get(id=gparam.get('batch_id')), gparam)
        raise ValueError('action: ' + str(action))
    except Exception as ex:
        LogWriter.add_dblog('error', 'definition/interface_log : action-{}'.format(action), ex)
        return {'success': False, 'message': '인터페이스 이력을 불러오지 못했습니다.'}


def _choices(choices):
    return [{'value': value, 'label': label} for value, label in choices.choices]


def _list(gparam):
    queryset = IfBatch.objects.order_by('-id')
    for param, field in (('kind', 'Kind'), ('channel', 'Channel'), ('status', 'Status')):
        if gparam.get(param):
            queryset = queryset.filter(**{field: gparam[param]})
    if gparam.get('source'):
        queryset = queryset.filter(SourceRef__icontains=gparam['source'].strip())
    if gparam.get('date_from'):
        queryset = queryset.filter(_created__gte=datetime.fromisoformat(gparam['date_from']))
    if gparam.get('date_to'):
        queryset = queryset.filter(_created__lt=datetime.fromisoformat(gparam['date_to']) + timedelta(days=1))
    page = paged(queryset, gparam, lambda batch: batch, default_size=50)
    names = _receivers(page['rows'])
    page['rows'] = [_summary(batch, names) for batch in page['rows']]
    return page


def _receivers(batches):
    """수신자 이름 {user id: 이름}. 사용자 이름이 없으면 아이디다."""
    ids = {b._creater_id for b in batches if b._creater_id}
    names = {u.id: u.username for u in User.objects.filter(id__in=ids)}
    names.update({p.User_id: p.Name for p in UserProfile.objects.filter(User_id__in=ids).exclude(Name=None).exclude(Name='')})
    return names


def _when(value):
    return value.strftime('%Y-%m-%d %H:%M:%S') if value else ''


def _status_label(batch):
    kind = IfBatch.Kinds(batch.Kind)
    if batch.Status == IfBatch.Statuses.RECEIVED and INTERFACES[kind].apply is None:
        return NO_RULE
    return batch.get_Status_display()


def _summary(batch, names):
    # 사람이 받지 않은 건(명령·외부 연동)은 수신자가 없다 — 파일은 명령, 그 밖은 경로 이름이다
    receiver = names.get(batch._creater_id) or ('명령' if batch.Channel == IfBatch.Channels.FILE else batch.get_Channel_display())
    return {
        'id': batch.id, 'kind': batch.Kind, 'kind_label': batch.get_Kind_display(),
        'channel': batch.Channel, 'channel_label': batch.get_Channel_display(), 'source_ref': batch.SourceRef or '',
        'row_count': batch.RowCount, 'status': batch.Status, 'status_label': _status_label(batch),
        'received_at': _when(batch._created), 'receiver': receiver, 'applied_at': _when(batch.AppliedAt),
    }


def _detail(batch):
    kind = IfBatch.Kinds(batch.Kind)
    labels = INTERFACES[kind].result_labels
    # jsonb 는 키 순서를 지키지 않는다 — 등록부의 이름 순서로 보인다
    counts = batch.ApplyResult or {}
    result = [[labels[key], counts[key]] for key in labels if key in counts]
    result += [[key, count] for key, count in counts.items() if key not in labels]
    return dict(_summary(batch, _receivers([batch])), message=batch.Message or '', result=result,
                columns=[{'field': name, 'header': header} for name, header in columns(kind)])


def _rows(batch, gparam):
    kind = IfBatch.Kinds(batch.Kind)
    fields = ['RowNo'] + [name for name, _header in columns(kind)]
    queryset = INTERFACES[kind].row_model.objects.filter(Batch=batch).order_by('RowNo').values(*fields)
    return paged(queryset, gparam, lambda row: row, default_size=100)
