"""치수 측정(MEASUREMENT) 비전검사항목의 측정점 모델."""
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from domain.models.data import InspectionItem, MeasurementPoint
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic


class MeasurementPointModelTest(TestCase):
    def setUp(self):
        reset_tenant_cache()
        self.tenant = current_tenant()
        with tenant_atomic(self.tenant):
            self.item = InspectionItem.objects.create(tenant=self.tenant, code='DIM', name='치수',
                                                      task_type=InspectionItem.TaskType.MEASUREMENT)

    def point(self, code='A', nominal='540', lower='539', upper='541'):
        return MeasurementPoint.objects.create(tenant=self.tenant, item=self.item, code=code, name='치수 ' + code,
                                               nominal=Decimal(nominal), lower=Decimal(lower), upper=Decimal(upper))

    def test_치수_측정은_클라이언트_유형_MEASUREMENT_다(self):
        self.assertEqual(self.item.client_inspection_type, 'MEASUREMENT')

    def test_하한_기준값_상한_순서가_아니면_저장하지_않는다(self):
        with tenant_atomic(self.tenant):
            with self.assertRaises(IntegrityError), transaction.atomic():
                self.point(nominal='538')
            with self.assertRaises(IntegrityError), transaction.atomic():
                self.point(lower='542', upper='541')
            self.assertEqual(self.point(nominal='539', lower='539', upper='539').unit, 'mm')

    def test_같은_항목에_같은_코드는_두_번_없다(self):
        with tenant_atomic(self.tenant):
            self.point()
            with self.assertRaises(IntegrityError), transaction.atomic():
                self.point()


class CaptureMethodModelTest(TestCase):
    def test_촬영_방식은_기본이_고정_거치대다(self):
        reset_tenant_cache()
        with tenant_atomic():
            item = InspectionItem.objects.create(tenant=current_tenant(), code='CAP', name='촬영')
        self.assertEqual((item.capture_method, item.get_capture_method_display()), ('RIG', '고정 거치대'))
        self.assertEqual(InspectionItem.CaptureMethod.TABLET.label, '태블릿')
