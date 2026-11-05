"""외부 인터페이스 — 경로 어댑터 → 공통 수신 → 종류별 반영.

- 경로 어댑터는 받은 것을 [{칼럼: 글자}] 로 바꾸기만 한다. 지금은 xlsx 파일 하나다(`xlsx_rows`).
  API·DB 연동은 받는 방법을 정할 때 어댑터를 더하고 `receive` 를 부른다
- 공통 수신(`receive`)은 경로와 상관없이 수신건(`if_batch`) 하나와 원본 행을 넣는다. 실패해도 수신건(수신 실패, 행 0)을 남긴다
- 반영(`apply`)은 종류 등록부(`INTERFACES`)의 반영 함수를 부르고 마지막 결과를 수신건에 남긴다
- 새 인터페이스는 원본 행 모델(`domain/models/interface.py`) + 등록부 한 줄 + 반영 함수다
(DECISIONS 사용자 결정 2026-10-19, DATA_MODEL §2)
"""
import datetime
from pathlib import Path
from typing import Callable, NamedTuple, Optional

import openpyxl
from django.db import transaction
from django.db.models import TextField
from django.utils import timezone

from domain.models.interface import IfBatch, IfErpPurchaseReq, IfPlmPartBom
from domain.services import plm_bom, receipt
from domain.services.logging import LogWriter


class Interface(NamedTuple):
    row_model: type
    apply: Optional[Callable]       # 수신건 → 건수 dict. 없으면 아직 반영 규칙이 없다
    result_labels: dict             # 건수 키 → 화면 이름


INTERFACES = {
    IfBatch.Kinds.PLM_PART_BOM: Interface(IfPlmPartBom, plm_bom.apply_plm_part_bom, plm_bom.RESULT_LABELS),
    IfBatch.Kinds.ERP_PURCHASE_REQ: Interface(IfErpPurchaseReq, receipt.apply_purchase_req, receipt.RESULT_LABELS),  # 구매요청 = 입고의뢰
}
# 파일 머리글을 찾는 범위. PLM 파일은 제목 줄·PM 분류 줄 아래(3행)에 있다
HEADER_SCAN_ROWS = 5


def columns(kind):
    """원본 칼럼 [(칼럼, 원본 머리글)] — 순서는 원본 열 순서다."""
    return [(f.name, f.verbose_name) for f in INTERFACES[kind].row_model._meta.fields if isinstance(f, TextField)]


def _key(header):
    return ''.join(str(header or '').split())


def _text(value):
    if value is None or value == '':
        return None
    if isinstance(value, datetime.datetime):
        return value.strftime('%Y-%m-%d' if value.time() == datetime.time() else '%Y-%m-%d %H:%M:%S')
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def xlsx_rows(kind, path):
    """파일 경로 어댑터 — 엑셀 첫 시트를 [{칼럼: 글자}] 로 읽는다. 머리글이 다르거나 읽지 못하면 ValueError."""
    by_header = {_key(header): name for name, header in columns(kind)}
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except OSError:
        raise
    except Exception:
        raise ValueError('xlsx 파일을 읽지 못했습니다.')
    try:
        rows = list(wb.worksheets[0].iter_rows(values_only=True))
    finally:
        wb.close()

    best = None  # 머리글 후보 중 모델 칼럼과 가장 많이 겹치는 줄
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        keys = [_key(h) for h in row]
        hits = len(set(keys) & by_header.keys())
        if best is None or hits > best[2]:
            best = (index, keys, hits)
    index, keys, _ = best or (0, [], 0)
    named = [k for k in keys if k]
    missing = [k for k in by_header if k not in named]
    extra = [k for k in named if k not in by_header]
    if missing or extra or len(named) != len(set(named)):
        raise ValueError('머리글이 {} 양식과 다릅니다. 없는 열: {} / 모르는 열: {}'.format(
            kind.label, ', '.join(missing) or '-', ', '.join(extra) or '-'))

    out = []
    for row in rows[index + 1:]:
        values = {by_header[k]: _text(v) for k, v in zip(keys, row) if k}
        if any(v is not None for v in values.values()):
            out.append(values)
    return out


def _new_batch(kind, channel, source_ref, user, **values):
    batch = IfBatch(Kind=kind, Channel=channel, SourceRef=source_ref, **values)
    if user is not None:
        batch.set_audit(user)
    batch.save()
    return batch


def receive(kind, rows, channel, source_ref, user=None):
    """공통 수신 — 원본 행 [{칼럼: 글자}] 을 수신건 하나로 넣고 IfBatch 를 돌려준다. 모르는 칼럼이면 수신 실패로 남기고 ValueError."""
    kind = IfBatch.Kinds(kind)
    known = {name for name, _header in columns(kind)}
    unknown = sorted({key for row in rows for key in row} - known)
    if unknown:
        message = '{} 에 없는 칼럼입니다: {}'.format(kind.label, ', '.join(unknown))
        _new_batch(kind, channel, source_ref, user, RowCount=0, Status=IfBatch.Statuses.RECEIVE_FAILED, Message=message)
        raise ValueError(message)
    with transaction.atomic():
        batch = _new_batch(kind, channel, source_ref, user, RowCount=len(rows))
        model = INTERFACES[kind].row_model
        model.objects.bulk_create([model(Batch=batch, RowNo=no, **values) for no, values in enumerate(rows, 1)])
    return batch


def receive_xlsx(kind, path, user=None):
    """xlsx 파일 하나를 받는다. 읽지 못하거나 머리글이 다르면 수신 실패로 남기고 ValueError. 파일이 없으면 OSError 다(남기지 않는다)."""
    kind = IfBatch.Kinds(kind)
    try:
        rows = xlsx_rows(kind, path)
    except ValueError as exc:
        _new_batch(kind, IfBatch.Channels.FILE, Path(path).name, user,
                   RowCount=0, Status=IfBatch.Statuses.RECEIVE_FAILED, Message=str(exc))
        raise
    return receive(kind, rows, IfBatch.Channels.FILE, Path(path).name, user)


def apply(batch):
    """수신건을 마스터에 반영하고 건수 dict 를 돌려준다. 마지막 결과(상태·일시·건수 또는 사유)를 수신건에 남긴다.

    반영 함수는 자기 트랜잭션 안에서 돈다 — 실패하면 마스터는 그대로고 수신건에 반영 실패만 남는다.
    """
    kind = IfBatch.Kinds(batch.Kind)
    spec = INTERFACES[kind]
    if spec.apply is None:
        raise ValueError(f'{kind.label} 수신건은 아직 반영 규칙이 없습니다.')
    if batch.Status == IfBatch.Statuses.RECEIVE_FAILED:
        raise ValueError('수신에 실패한 건은 반영할 수 없습니다.')
    now = timezone.now()
    record = IfBatch.objects.filter(id=batch.id)
    try:
        result = spec.apply(batch)
    except Exception as exc:
        if isinstance(exc, ValueError):
            message = str(exc)
        else:
            message = '반영 중 오류가 발생했습니다. 시스템 로그를 확인해 주세요.'
            LogWriter.add_dblog('error', 'interface/apply : batch-{}'.format(batch.id), exc)
        record.update(Status=IfBatch.Statuses.APPLY_FAILED, Message=message, AppliedAt=now, ApplyResult=None, _modified=now)
        raise
    record.update(Status=IfBatch.Statuses.APPLIED, Message=None, AppliedAt=now, ApplyResult=result, _modified=now)
    return result
