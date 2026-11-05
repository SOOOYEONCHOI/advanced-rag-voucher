"""seed_vision_items: NEOCON C2 비전검사항목·설명·라벨 클래스를 만들고(없는 것만), 화면에서 고친 값은 덮지 않는다."""
import io

from django.core.management import call_command
from django.test import TestCase

from domain.models.data import ActivityLog, Dataset, InspectionCategory, InspectionItem, LabelClass, MeasurementPoint
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic

T = InspectionItem.TaskType
EXPECTED = {'VIS-CLN': T.CLASSIFICATION, 'VIS-ROT-SF': T.ANOMALY_DETECTION, 'TAB-IMK': T.OBJECT_DETECTION,
            'TAB-LBL': T.OBJECT_DETECTION, 'TAB-ROT': T.ANOMALY_DETECTION, 'TAB-TRM': T.OBJECT_DETECTION,
            'VIS-ROT-DIM': T.MEASUREMENT,
            # 검사 분류와 함께 더한 9개(설계 2026-10-21 §8)
            'TAB-PRT': T.OBJECT_DETECTION, 'TAB-EPD': T.OBJECT_DETECTION, 'TAB-FAN': T.OBJECT_DETECTION,
            'TAB-HTR': T.ANOMALY_DETECTION, 'TAB-SNS': T.OBJECT_DETECTION, 'TAB-BLT': T.OBJECT_DETECTION,
            'TAB-CFN': T.CLASSIFICATION, 'TAB-CBL': T.OBJECT_DETECTION, 'TAB-EXT': T.ANOMALY_DETECTION}

# 대분류 › 중분류 › 비전검사항목(설계 2026-10-21 §8 표). 대분류는 수입검사·품질검사·미분류로 고정(사용자 결정 2026-10-21)
MEMBERSHIP = {
    ('수입검사', 'Rotor 수입검사 성적서'): {'VIS-ROT-SF', 'VIS-ROT-DIM'},
    ('수입검사', '수입검사성적서(가공품)'): {'TAB-PRT'},
    ('수입검사', '전장 ASSY Check Sheet'): {'TAB-TRM'},
    ('품질검사', 'Module Check Sheet'): {'TAB-IMK', 'TAB-EPD', 'TAB-FAN', 'TAB-HTR', 'TAB-SNS', 'TAB-BLT', 'TAB-CFN'},
    ('품질검사', '8계통 Check Sheet'): {'TAB-CBL'},
    ('품질검사', '출하검수 Sheet'): {'TAB-LBL', 'VIS-CLN', 'TAB-ROT', 'TAB-EXT'},
}


def seed(*args):
    out = io.StringIO()
    call_command('seed_vision_items', *args, stdout=out)
    return out.getvalue()


# 설명의 머리 — 검사 목적 · 검사 항목(어느 문서의 몇 번) · 검사 기준(원문) · 역할(AI와 사람) · 촬영 · 라벨링(치수 측정은 측정 방법)
SECTIONS = ('■ 검사 목적', '■ 검사 항목', '■ 검사 기준', '■ 역할', '■ 촬영 방법')


class SeedVisionItemsTest(TestCase):
    def setUp(self):
        reset_tenant_cache()

    def test_검사항목_유형_설명_업로드_데이터셋을_만든다(self):
        seed()
        with tenant_atomic():
            items = {i.code: i for i in InspectionItem.objects.all()}
            self.assertEqual({code: i.task_type for code, i in items.items()}, EXPECTED)
            for item in items.values():
                self.assertEqual(item.status, InspectionItem.Status.ACTIVE)
                for section in SECTIONS:
                    self.assertIn(section, item.description, f'{item.code} {section}')
                last = '■ 측정 방법' if item.task_type == T.MEASUREMENT else '■ 라벨링 기준'
                self.assertIn(last, item.description, item.code)
                self.assertTrue(Dataset.objects.filter(item=item, version='v0.1').exists())
                self.assertTrue(ActivityLog.objects.filter(item=item, event_type='PROJECT_CREATED').exists())

    def test_TAB_항목은_태블릿이고_나머지는_고정_거치대다(self):
        seed()
        with tenant_atomic():
            methods = dict(InspectionItem.objects.values_list('code', 'capture_method'))
        self.assertEqual({code for code, m in methods.items() if m == 'TABLET'}, {c for c in EXPECTED if c.startswith('TAB-')})
        self.assertEqual({code for code, m in methods.items() if m == 'RIG'}, {'VIS-CLN', 'VIS-ROT-SF', 'VIS-ROT-DIM'})

    def test_Cleaning_은_1_10단계이고_3단계부터_불량이다(self):
        """분류 판정은 1순위 클래스의 불량 여부로 정한다(계약 §6) — 1~2단계 합격, 3~10단계 불합격."""
        seed()
        with tenant_atomic():
            classes = list(LabelClass.objects.filter(item__code='VIS-CLN').values_list('display_name_ko', 'is_defect'))
        self.assertEqual(classes, [(f'{n}단계', n >= 3) for n in range(1, 11)])
        with tenant_atomic():
            description = InspectionItem.objects.get(code='VIS-CLN').description
        for group in ('적합(1~2단계)', '재세정(3~4단계)', '부적합(5~10단계)',
                      '외관검사 - Cleaning 검사', 'No 30'):
            self.assertIn(group, description)

    def test_다시_돌려도_늘지_않고_화면에서_고친_값을_덮지_않는다(self):
        seed()
        with tenant_atomic():
            InspectionItem.objects.filter(code='TAB-IMK').update(name='고친 이름', description='고친 설명')
            LabelClass.objects.filter(item__code='TAB-IMK', name='imark_bad').update(display_name_ko='고친 클래스')
            counts = (InspectionItem.objects.count(), LabelClass.objects.count(), Dataset.objects.count())
        out = seed()
        self.assertIn('새로 0개 / 라벨 클래스 새로 0개 / 측정점 새로 0개', out)
        with tenant_atomic():
            self.assertEqual((InspectionItem.objects.count(), LabelClass.objects.count(), Dataset.objects.count()), counts)
            item = InspectionItem.objects.get(code='TAB-IMK')
            self.assertEqual((item.name, item.description), ('고친 이름', '고친 설명'))
            self.assertTrue(LabelClass.objects.filter(item=item, display_name_ko='고친 클래스').exists())

    def test_지운_라벨_클래스만_다시_만든다(self):
        seed()
        with tenant_atomic():
            LabelClass.objects.filter(item__code='VIS-ROT-SF', name='crack').delete()
        self.assertIn('새로 0개 / 라벨 클래스 새로 1개', seed())

    def test_Rotor_치수는_5번_시트_POINT_A_B_C_를_측정점으로_만든다(self):
        seed()
        with tenant_atomic():
            points = list(MeasurementPoint.objects.filter(item__code='VIS-ROT-DIM')
                          .values_list('code', 'name', 'nominal', 'lower', 'upper', 'unit'))
            self.assertEqual([(c, n, str(a), str(lo), str(hi), u) for c, n, a, lo, hi, u in points], [
                ('A', '치수 A', '540.000', '539.000', '541.000', 'mm'), ('B', '치수 B', '540.000', '539.000', '541.000', 'mm'),
                ('C', '치수 C', '154.000', '153.000', '155.000', 'mm')])
            self.assertFalse(LabelClass.objects.filter(item__code='VIS-ROT-DIM').exists())
            MeasurementPoint.objects.filter(item__code='VIS-ROT-DIM', code='A').update(name='카세트 가로')
            MeasurementPoint.objects.filter(item__code='VIS-ROT-DIM', code='C').delete()
        self.assertIn('측정점 새로 1개', seed())
        with tenant_atomic():
            self.assertTrue(MeasurementPoint.objects.filter(item__code='VIS-ROT-DIM', name='카세트 가로').exists())

    def test_측정점에도_측정_방법을_적는다(self):
        seed()
        with tenant_atomic():
            descriptions = dict(MeasurementPoint.objects.filter(item__code='VIS-ROT-DIM').values_list('code', 'description'))
        self.assertIn('Process Air', descriptions['A'])
        self.assertIn('도면 확인', descriptions['B'])
        self.assertIn('154', descriptions['C'])

    def test_설명_덮어쓰기는_옵션을_줄_때만_설명만_바꾼다(self):
        seed()
        with tenant_atomic():
            InspectionItem.objects.filter(code='TAB-IMK').update(name='고친 이름', description='옛 설명')
            MeasurementPoint.objects.filter(item__code='VIS-ROT-DIM', code='A').update(name='카세트 가로', description='옛')
        seed()
        with tenant_atomic():
            self.assertEqual(InspectionItem.objects.get(code='TAB-IMK').description, '옛 설명')
        out = seed('--update-descriptions')
        self.assertIn('설명을 바꾼 비전검사항목 1개 / 측정점 1개', out)
        with tenant_atomic():
            item = InspectionItem.objects.get(code='TAB-IMK')
            self.assertEqual(item.name, '고친 이름')
            self.assertIn('■ 검사 항목', item.description)
            point = MeasurementPoint.objects.get(item__code='VIS-ROT-DIM', code='A')
            self.assertEqual(point.name, '카세트 가로')
            self.assertIn('Process Air', point.description)
        self.assertIn('설명을 바꾼 비전검사항목 0개 / 측정점 0개', seed('--update-descriptions'))

    def test_검사_분류를_만들고_비전검사항목을_중분류에_넣는다(self):
        seed()
        with tenant_atomic():
            majors = list(InspectionCategory.objects.filter(parent=None).values_list('name', 'form_type'))
            self.assertEqual(majors, [('수입검사', 'INCOMING'), ('품질검사', 'OUTGOING'), ('미분류', '')])
            self.assertEqual(list(InspectionCategory.objects.filter(parent__name='품질검사').values_list('name', flat=True)),
                             ['Module Check Sheet', '8계통 Check Sheet', '출하검수 Sheet'])
            membership = {}
            for item in InspectionItem.objects.select_related('category__parent'):
                membership.setdefault((item.category.parent.name, item.category.name), set()).add(item.code)
            self.assertEqual(membership, MEMBERSHIP)
            self.assertFalse(InspectionCategory.objects.exclude(form_code='').exists())     # 양식 매핑은 seed_dig_form·화면에서
            counts = (InspectionCategory.objects.count(), LabelClass.objects.count())
        seed()
        with tenant_atomic():
            self.assertEqual((InspectionCategory.objects.count(), LabelClass.objects.count()), counts)

    def test_옛_대분류의_중분류는_품질검사로_옮기고_옛_대분류는_지운다(self):
        with tenant_atomic():
            tenant = current_tenant()
            assembly = InspectionCategory.objects.create(tenant=tenant, name='조립검사', form_type='OUTGOING', sort_order=2)
            InspectionCategory.objects.create(tenant=tenant, parent=assembly, name='Module Check Sheet', sort_order=1)
        output = seed()
        self.assertIn('옛 대분류 1개를 지우고 중분류 1개를 옮김', output)
        with tenant_atomic():
            self.assertFalse(InspectionCategory.objects.filter(name='조립검사').exists())
            self.assertEqual(InspectionCategory.objects.get(name='Module Check Sheet').parent.name, '품질검사')

    def test_이미_소속이_있으면_옮기지_않고_비어_있으면_채운다(self):
        seed()
        with tenant_atomic():
            other = InspectionCategory.objects.get(name='8계통 Check Sheet')
            InspectionItem.objects.filter(code='TAB-IMK').update(category=other)
            InspectionItem.objects.filter(code='TAB-LBL').update(category=None)
        seed()
        with tenant_atomic():
            self.assertEqual(InspectionItem.objects.get(code='TAB-IMK').category.name, '8계통 Check Sheet')
            self.assertEqual(InspectionItem.objects.get(code='TAB-LBL').category.name, '출하검수 Sheet')

    def test_기존_항목에_클래스를_더한다(self):
        seed()
        with tenant_atomic():
            names = {code: set(LabelClass.objects.filter(item__code=code).values_list('name', flat=True))
                     for code in ('TAB-TRM', 'TAB-IMK', 'TAB-LBL', 'TAB-CFN')}
        self.assertTrue({'connector_loose', 'numbering_bad', 'terminal_bent', 'lug_wrong', 'ground_bad',
                         'terminal_foreign'} <= names['TAB-TRM'])
        self.assertTrue({'bolt_missing', 'hole_open', 'washer_missing'} <= names['TAB-IMK'])
        self.assertIn('ems_cover_missing', names['TAB-LBL'])
        with tenant_atomic():
            normal = list(LabelClass.objects.filter(item__code='TAB-CFN', is_defect=False).values_list('name', flat=True))
        self.assertEqual(normal, ['fan_ok'])
