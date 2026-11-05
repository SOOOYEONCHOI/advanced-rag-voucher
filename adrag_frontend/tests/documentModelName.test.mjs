// 2026.10.19(sooyeon.choi) 추가 - UI-12 파일별 모델명: 기본값·행별 수정·검증·요청별 전송·접수 거절 후 재전송
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { reactive } from 'vue';
import { createServer } from 'vite';

const file = (name) => new File(['fixture'], name, { lastModified: name.length });

test('each upload row keeps its own model name from default to request', async () => {
  const server = await createServer({ server: { middlewareMode: true }, logLevel: 'silent' });
  try {
    const mod = await server.ssrLoadModule('/src/composables/useDocumentUpload.js');
    assert.equal(mod.defaultModelName('C2.assembly.rev2.pdf'), 'C2.assembly.rev2');
    assert.equal(mod.modelNameError('  '), '모델명을 입력하세요.');
    assert.equal(mod.modelNameError('가'.repeat(100)), '');
    assert.match(mod.modelNameError('가'.repeat(101)), /100자/);

    const sent = [];
    let rejectNext = false;
    const api = {
      async uploadDocument(data) {
        sent.push({ filename: data.get('file').name, productModel: data.get('product_model') });
        if (rejectNext) {
          rejectNext = false;
          throw { response: { status: 422, data: { detail: '모델명은 앞뒤 공백을 제외하고 1~100자로 입력하세요.' } } };
        }
        return { data: { job_id: `job-${sent.length}` } };
      },
      async getIngestJob(jobId) { return { data: { status: 'queued', current_step: 'queued', job_id: jobId } }; },
    };
    const form = reactive({ collectionName: 'documents', parserType: 'docling', documentType: 'auto' });
    const upload = mod.useDocumentUpload({ form, api, onCompleted: async () => {} });
    upload.addFiles([file('C2.assembly.rev2.pdf'), file('NEOCON C3.xlsx')]);
    const [first, second] = upload.uploadItems.value;
    assert.equal(first.productModel, 'C2.assembly.rev2');
    assert.equal(second.productModel, 'NEOCON C3');

    // 한 행 수정은 다른 행에 영향 없음, 빈 값이면 전송 차단
    first.productModel = '   ';
    assert.equal(upload.modelError(first), '모델명을 입력하세요.');
    assert.equal(upload.modelError(second), '');
    assert.equal(upload.hasModelError.value, true);
    assert.equal(upload.canUpload.value, false);

    first.productModel = '  NEOCON C2 제조 관리 문서 대장 ';
    assert.equal(upload.canUpload.value, true);
    await upload.uploadDocument();
    upload.stopMonitoring();
    assert.deepEqual(sent, [
      { filename: 'C2.assembly.rev2.pdf', productModel: 'NEOCON C2 제조 관리 문서 대장' },
      { filename: 'NEOCON C3.xlsx', productModel: 'NEOCON C3' },
    ]);
    // 접수 후에는 입력 잠금
    assert.equal(upload.canEditModel(first), false);

    // 접수 거절 행은 수정한 값으로 재전송
    upload.addFiles([file('reject.pdf')]);
    const third = upload.uploadItems.value[2];
    rejectNext = true;
    await upload.uploadDocument();
    assert.equal(third.status, 'rejected');
    assert.equal(upload.canEditModel(third), true);
    third.productModel = '재전송 모델명';
    await upload.uploadDocument();
    upload.stopMonitoring();
    assert.deepEqual(sent.slice(2), [
      { filename: 'reject.pdf', productModel: 'reject' },
      { filename: 'reject.pdf', productModel: '재전송 모델명' },
    ]);
  } finally {
    await server.close();
  }
});
