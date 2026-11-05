// 2026.10.19(sooyeon.choi) 추가 - UI-12 최신본 변경·버전 이력: 접수 → 처리 확인 → 완료/실패 안내, 이력 조회, 새로고침 복원
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createServer } from 'vite';

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

test('replace version submits file, polls job and reports result; history lists versions', async () => {
  const server = await createServer({ server: { middlewareMode: true }, logLevel: 'silent' });
  try {
    const { useDocumentVersions } = await server.ssrLoadModule('/src/composables/useDocumentVersions.js');
    const alerts = [];
    let reloads = 0;
    let jobStatus = 'running';
    const sent = [];
    const api = {
      async replaceDocumentVersion(documentId, data) {
        sent.push([documentId, data.get('file').name]);
        if (documentId === 'busy') throw { response: { status: 409, data: { detail: 'JOB_IN_PROGRESS: 처리 중' } } };
        return { data: { job_id: `job-${documentId}`, version_no: 2, document_id: documentId } };
      },
      async getIngestJob(jobId) {
        return { data: { job_id: jobId, status: jobStatus, error: jobStatus === 'failed' ? '파싱 실패' : null } };
      },
      async documentVersions(documentId) {
        return { data: { versions: [{ version_no: 2, status: 'active' }, { version_no: 1, status: 'retired' }] } };
      },
    };
    const versions = useDocumentVersions({
      api, loadDocuments: async () => { reloads += 1; }, showAlert: (msg, type) => alerts.push([type, msg]), pollIntervalMs: 5,
    });

    // 권한 없는 문서는 대화상자를 열지 않는다
    versions.openReplaceDialog({ document_id: 'x', can_edit: false });
    assert.equal(versions.replaceTarget.value, null);

    // 409(처리 중)는 대화상자 안에 오류로 남는다
    versions.openReplaceDialog({ document_id: 'busy', can_edit: true });
    versions.onReplaceFileChange({ target: { files: [new File(['v2'], 'rev2.pdf')] } });
    await versions.submitReplace();
    assert.match(versions.replaceError.value, /JOB_IN_PROGRESS/);
    assert.ok(versions.replaceTarget.value);
    versions.closeReplaceDialog();

    // 접수 성공 → 처리 중 표시 → 완료 시 목록 재조회·성공 안내
    const doc = { document_id: 'doc-1', can_edit: true, version_no: 1 };
    versions.openReplaceDialog(doc);
    versions.onReplaceFileChange({ target: { files: [new File(['v2'], 'rev2.pdf')] } });
    await versions.submitReplace();
    assert.deepEqual(sent.at(-1), ['doc-1', 'rev2.pdf']);
    assert.equal(versions.replaceTarget.value, null);
    assert.equal(versions.isVersionPending(doc), true);
    assert.equal(versions.pendingVersionNo(doc), 2);
    await wait(30);
    assert.equal(reloads, 0);
    jobStatus = 'completed';
    await wait(30);
    assert.equal(reloads, 1);
    assert.equal(versions.versionJobs['doc-1'], undefined);
    assert.ok(alerts.some(([type, msg]) => type === 'success' && msg.includes('v2')));

    // 새로고침 복원: 목록의 pending_job_id로 확인 재개 → 실패 안내(기존 최신본 유지)
    jobStatus = 'failed';
    versions.syncPendingJobs([{ document_id: 'doc-2', can_edit: true, pending_job_id: 'job-2', pending_version_no: 3, filename: 'a.pdf' }]);
    await wait(30);
    assert.ok(alerts.some(([type, msg]) => type === 'error' && msg.includes('기존 최신본')));
    assert.equal(reloads, 2);

    // 버전 이력
    await versions.openVersionHistory(doc);
    assert.deepEqual(versions.historyItems.value.map((v) => v.version_no), [2, 1]);
    assert.equal(versions.versionStatusLabel('active'), '적용 중');
    versions.closeVersionHistory();
    assert.equal(versions.historyTarget.value, null);
  } finally {
    await server.close();
  }
});
