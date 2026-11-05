// 2026.10.16(sooyeon.choi) 추가
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createServer } from 'vite';

// R5-1 / SC-02 / UI-07: 실제 ASR 호출 없이 결과·실패·취소 흐름 검증.
test('STT preserves preview, supports retry, and ignores cancelled results', async () => {
  const server = await createServer({ server: { middlewareMode: true } });
  try {
    const { useVoiceRecorder } = await server.ssrLoadModule('/src/composables/useVoiceRecorder.js');
    const { voiceApi } = await server.ssrLoadModule('/src/api/voiceApi.js');
    const recorder = useVoiceRecorder();
    recorder.state.value = 'ready';
    recorder.recordedFile.value = new Blob(['audio'], { type: 'audio/webm' });
    recorder.audioUrl.value = 'blob:preview';
    recorder.elapsedMs.value = 2500;
    voiceApi.transcribe = async (form) => {
      assert.equal(form.get('language'), 'ko');
      assert.equal(form.get('duration_ms'), '2500');
      assert.equal(form.get('audio').size, 5);
      return { data: { text: ' 조립 순서 ' } };
    };
    await recorder.transcribeRecording();
    assert.equal(recorder.transcript.value, '조립 순서');
    assert.equal(recorder.state.value, 'ready');
    assert.equal(recorder.audioUrl.value, 'blob:preview');
    assert.equal(recorder.isTranscribing.value, false);

    voiceApi.transcribe = async () => { throw { response: { status: 503 } }; };
    await recorder.transcribeRecording();
    assert.match(recorder.transcriptionError.value, /서버/);
    assert.equal(recorder.hasRecording.value, true);

    let complete;
    let signal;
    voiceApi.transcribe = (_, requestSignal) => {
      signal = requestSignal;
      return new Promise((resolve) => { complete = resolve; });
    };
    const pending = recorder.transcribeRecording();
    await recorder.dismiss();
    assert.equal(signal.aborted, true);
    complete({ data: { text: '취소된 결과' } });
    await pending;
    assert.equal(recorder.state.value, 'idle');
    assert.equal(recorder.transcript.value, '');
    assert.equal(recorder.isTranscribing.value, false);
  } finally {
    await server.close();
  }
});
