"""수신건(`if_batch`)을 마스터에 반영한다. 반영 규칙은 종류 등록부(`domain/services/interface.py` `INTERFACES`)에 있다.

    python manage.py apply_interface <수신건 id>

- 같은 수신건을 다시 반영해도 결과가 같다. 마지막 반영 결과(상태·일시·건수 또는 사유)가 수신건에 남는다
- 검증이 하나라도 틀리면 아무것도 반영하지 않고 수신건에 반영 실패와 사유를 남긴다
- ERP 구매요청 수신건은 입고예정 설계 뒤에 반영한다
"""
from django.core.management.base import BaseCommand, CommandError

from domain.models.interface import IfBatch
from domain.services.interface import INTERFACES, apply


class Command(BaseCommand):
    help = '수신건(if_batch)을 마스터에 반영한다'

    def add_arguments(self, parser):
        parser.add_argument('batch_id', type=int)

    def handle(self, *args, **options):
        batch = IfBatch.objects.filter(id=options['batch_id']).first()
        if batch is None:
            raise CommandError(f"수신건 {options['batch_id']} 이 없습니다.")
        try:
            result = apply(batch)
        except ValueError as exc:
            raise CommandError(str(exc))
        labels = INTERFACES[IfBatch.Kinds(batch.Kind)].result_labels
        self.stdout.write(f'수신건 {batch.id} 반영: ' + ', '.join(f'{labels.get(k, k)} {v}' for k, v in result.items()))
