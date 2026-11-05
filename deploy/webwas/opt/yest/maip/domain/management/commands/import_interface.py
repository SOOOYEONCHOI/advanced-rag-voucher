"""외부 인터페이스 엑셀(xlsx)을 수신 테이블(`if_*`)에 넣는다 — 파일 경로(Channel FILE)다.

    python manage.py import_interface plm_part_bom tmp/interface/Part_Vertical_BOM.xlsx
    python manage.py import_interface erp_purchase_req tmp/interface/PUOPRQ00400_X10148_1000_8100_grid.xlsx

- 받을 때마다 수신건(`if_batch`) 하나가 생긴다. 이전 수신건은 지우지 않는다
- 원본 값을 글자로 담는다. 마스터 반영은 `apply_interface` 다
- 머리글이 양식과 다르거나 읽지 못하면 한 행도 넣지 않고 수신건을 수신 실패로 남긴다
"""
from django.core.management.base import BaseCommand, CommandError

from domain.models.interface import IfBatch
from domain.services.interface import receive_xlsx

KINDS = {'plm_part_bom': IfBatch.Kinds.PLM_PART_BOM, 'erp_purchase_req': IfBatch.Kinds.ERP_PURCHASE_REQ}


class Command(BaseCommand):
    help = '외부 인터페이스 엑셀(xlsx)을 수신 테이블(if_*)에 넣는다'

    def add_arguments(self, parser):
        parser.add_argument('kind', choices=sorted(KINDS))
        parser.add_argument('file')

    def handle(self, *args, **options):
        try:
            batch = receive_xlsx(KINDS[options['kind']], options['file'])
        except OSError as exc:
            raise CommandError(str(exc))
        except ValueError as exc:
            raise CommandError(f'{exc} (수신 실패로 남겼습니다)')
        self.stdout.write(f'수신건 {batch.id}: {batch.get_Kind_display()} {batch.RowCount}행 ({batch.SourceRef})')
