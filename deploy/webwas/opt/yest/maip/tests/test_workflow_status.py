"""화면의 업무 단계 — `label_status`·`ingestion_status` → 다섯 단계."""
from types import SimpleNamespace

from django.test import SimpleTestCase

from domain.services.data.workflow import WorkflowStatus, workflow_status, workflow_status_label


def image(label_status='UNLABELED', ingestion_status='READY'):
    return SimpleNamespace(label_status=label_status, ingestion_status=ingestion_status)


class WorkflowStatusTest(SimpleTestCase):
    def test_라벨_상태를_업무_단계로_바꾼다(self):
        self.assertEqual({status: workflow_status(image(status)) for status in
                          ('UNLABELED', 'REWORK', 'IN_PROGRESS', 'SUBMITTED', 'APPROVED')}, {
            'UNLABELED': WorkflowStatus.WAITING, 'REWORK': WorkflowStatus.WAITING,
            'IN_PROGRESS': WorkflowStatus.IN_PROGRESS, 'SUBMITTED': WorkflowStatus.COMPLETED,
            'APPROVED': WorkflowStatus.REVIEWED})

    def test_업로드_중이면_업로드_단계이고_거절은_단계가_없다(self):
        for ingestion in ('UPLOADING', 'VALIDATING'):
            self.assertEqual(workflow_status(image('APPROVED', ingestion)), WorkflowStatus.UPLOAD)
        self.assertIsNone(workflow_status(image('APPROVED', 'REJECTED')))

    def test_단계_이름(self):
        self.assertEqual([workflow_status_label(s) for s in (WorkflowStatus.UPLOAD, WorkflowStatus.WAITING,
                                                             WorkflowStatus.IN_PROGRESS, WorkflowStatus.COMPLETED,
                                                             WorkflowStatus.REVIEWED, None)],
                         ['데이터 업로드', '작업 대기', '작업 중', '작업 완료', '검수 완료', '상태 확인 필요'])
