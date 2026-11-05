import { computed, onBeforeUnmount, ref } from 'vue';
// 2026.10.16(sooyeon.choi) 추가
import { voiceApi } from '../api/voiceApi';

// 2026.10.14(woojin.jung) 추가 - 브라우저 MediaRecorder 기반 음성 녹음 및 녹음 파일 생성
const MAX_DURATION_MS = 60_000;
const SILENCE_NOTICE_MS = 3_000;
const SILENCE_THRESHOLD = 0.018;

const MIME_TYPE_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/mp4',
  'audio/ogg;codecs=opus',
  'audio/webm',
];

const extensionForMimeType = (mimeType = '') => {
  if (mimeType.includes('mp4')) return 'm4a';
  if (mimeType.includes('ogg')) return 'ogg';
  return 'webm';
};

const createRecordingFileName = (extension) => {
  const now = new Date();
  const pad = (value) => String(value).padStart(2, '0');
  return `voice_question_${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}.${extension}`;
};

// 2026.10.14(woojin.jung) 추가 - 마이크 권한 및 장치 오류별 사용자 안내 문구 처리
const messageForMediaError = (error) => {
  if (error?.name === 'NotAllowedError' || error?.name === 'SecurityError') {
    return '마이크 권한이 차단되어 있습니다. 마이크 권한을 허용해 주세요.';
  }
  if (error?.name === 'NotFoundError' || error?.name === 'OverconstrainedError') {
    return '연결된 마이크를 찾을 수 없습니다.';
  }
  if (error?.name === 'NotReadableError' || error?.name === 'AbortError') {
    return '다른 프로그램이 마이크를 사용 중입니다. 사용 중인 앱을 닫고 다시 시도해 주세요.';
  }
  return '마이크를 시작할 수 없습니다. 브라우저의 마이크 설정을 확인해 주세요.';
};

export const useVoiceRecorder = () => {
  const state = ref('idle');
  const elapsedMs = ref(0);
  const audioLevels = ref(Array(7).fill(0.12));
  const silenceDetected = ref(false);
  const errorMessage = ref('');
  const recordedFile = ref(null);
  const audioUrl = ref('');
  const autoStopped = ref(false);
  // 2026.10.16(sooyeon.choi) 추가
  const transcript = ref('');
  const originalTranscript = ref('');
  const transcriptionId = ref(null);
  const hasTranscription = ref(false);
  const isTranscribing = ref(false);
  const transcriptionError = ref('');
  let transcriptionController = null;

  let mediaRecorder = null;
  let mediaStream = null;
  let audioContext = null;
  let analyser = null;
  let animationFrame = null;
  let timer = null;
  let startedAt = 0;
  let lastSoundAt = 0;
  let chunks = [];
  let discardCurrentRecording = false;
  let recordingRequestId = 0;

  const isSupported = computed(
    () => typeof navigator !== 'undefined' && Boolean(navigator.mediaDevices?.getUserMedia) && typeof MediaRecorder !== 'undefined'
  );
  const isRecording = computed(() => state.value === 'recording');
  const isRequesting = computed(() => state.value === 'requesting');
  const hasRecording = computed(() => state.value === 'ready' && Boolean(recordedFile.value));

  const revokeAudioUrl = () => {
    if (!audioUrl.value) return;
    URL.revokeObjectURL(audioUrl.value);
    audioUrl.value = '';
  };

  const stopTracks = () => {
    mediaStream?.getTracks().forEach((track) => track.stop());
    mediaStream = null;
  };

  const stopMeter = () => {
    if (animationFrame !== null) cancelAnimationFrame(animationFrame);
    animationFrame = null;
    if (timer !== null) window.clearInterval(timer);
    timer = null;
    analyser?.disconnect();
    analyser = null;
    if (audioContext && audioContext.state !== 'closed') audioContext.close().catch(() => {});
    audioContext = null;
    stopTracks();
  };

  const clearRecording = () => {
    // 2026.10.16(sooyeon.choi) 추가
    transcriptionController?.abort();
    transcriptionController = null;
    isTranscribing.value = false;
    transcript.value = '';
    originalTranscript.value = '';
    transcriptionId.value = null;
    hasTranscription.value = false;
    transcriptionError.value = '';
    revokeAudioUrl();
    recordedFile.value = null;
    elapsedMs.value = 0;
    autoStopped.value = false;
  };

  const chooseMimeType = () => MIME_TYPE_CANDIDATES.find((type) => MediaRecorder.isTypeSupported?.(type)) || '';

  // 2026.10.14(woojin.jung) 추가 - 실시간 마이크 입력 레벨 및 3초 무음 상태 감지
  const updateMeter = () => {
    if (!analyser || state.value !== 'recording') return;

    const samples = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(samples);
    let squareSum = 0;
    for (const sample of samples) {
      const normalized = (sample - 128) / 128;
      squareSum += normalized * normalized;
    }
    const rms = Math.sqrt(squareSum / samples.length);
    const strength = Math.min(1, Math.max(0.08, rms * 6));
    audioLevels.value = audioLevels.value.map((_, index) => Math.min(1, Math.max(0.08, strength * (0.72 + ((index * 37) % 5) * 0.11))));

    if (rms >= SILENCE_THRESHOLD) lastSoundAt = performance.now();
    silenceDetected.value = performance.now() - lastSoundAt >= SILENCE_NOTICE_MS;
    animationFrame = requestAnimationFrame(updateMeter);
  };

  const prepareMeter = () => {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass || !mediaStream) return;
    audioContext = new AudioContextClass();
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 512;
    analyser.smoothingTimeConstant = 0.72;
    audioContext.createMediaStreamSource(mediaStream).connect(analyser);
    updateMeter();
  };

  const finishRecording = () => {
    stopMeter();
    const shouldDiscard = discardCurrentRecording;
    discardCurrentRecording = false;

    if (shouldDiscard) {
      chunks = [];
      state.value = 'idle';
      return;
    }

    const mimeType = mediaRecorder?.mimeType || chunks[0]?.type || 'audio/webm';
    const blob = new Blob(chunks, { type: mimeType });
    chunks = [];
    mediaRecorder = null;

    if (!blob.size) {
      state.value = 'error';
      errorMessage.value = '녹음된 음성이 없습니다. 다시 녹음해 주세요.';
      return;
    }

    const extension = extensionForMimeType(mimeType);
    recordedFile.value = new File([blob], createRecordingFileName(extension), {
      type: mimeType,
      lastModified: Date.now(),
    });
    audioUrl.value = URL.createObjectURL(blob);
    state.value = 'ready';
  };

  const stopRecording = ({ reachedLimit = false } = {}) => {
    if (!mediaRecorder || mediaRecorder.state === 'inactive') return;
    autoStopped.value = reachedLimit;
    elapsedMs.value = Math.min(MAX_DURATION_MS, Date.now() - startedAt);
    mediaRecorder.stop();
  };

  const startTimer = () => {
    timer = window.setInterval(() => {
      elapsedMs.value = Math.min(MAX_DURATION_MS, Date.now() - startedAt);
      if (elapsedMs.value >= MAX_DURATION_MS) stopRecording({ reachedLimit: true });
    }, 200);
  };

  // 2026.10.21(woojin.jung) 수정 - 마이크 준비 상태를 먼저 표시하고 장치 연결 완료 후 실제 녹음 시작
  const startRecording = async () => {
    if (state.value === 'recording' || state.value === 'requesting') return;
    errorMessage.value = '';
    silenceDetected.value = false;
    clearRecording();

    if (!isSupported.value) {
      state.value = 'error';
      errorMessage.value = '이 브라우저에서는 음성 녹음을 지원하지 않습니다.';
      return;
    }

    const requestId = ++recordingRequestId;
    state.value = 'requesting';

    try {
      const requestedStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      });

      if (requestId !== recordingRequestId || state.value !== 'requesting') {
        requestedStream.getTracks().forEach((track) => track.stop());
        return;
      }

      mediaStream = requestedStream;
      const mimeType = chooseMimeType();
      mediaRecorder = mimeType ? new MediaRecorder(mediaStream, { mimeType }) : new MediaRecorder(mediaStream);
      chunks = [];
      discardCurrentRecording = false;
      mediaRecorder.addEventListener('dataavailable', (event) => {
        if (event.data?.size) chunks.push(event.data);
      });
      mediaRecorder.addEventListener('stop', finishRecording, { once: true });
      mediaRecorder.addEventListener('error', (event) => {
        stopMeter();
        state.value = 'error';
        errorMessage.value = messageForMediaError(event.error);
      });

      mediaRecorder.start(250);
      startedAt = Date.now();
      lastSoundAt = performance.now();
      elapsedMs.value = 0;
      state.value = 'recording';
      prepareMeter();
      startTimer();
    } catch (error) {
      if (requestId !== recordingRequestId) return;
      stopMeter();
      state.value = 'error';
      errorMessage.value = messageForMediaError(error);
    }
  };

  const cancelRecording = async () => {
    recordingRequestId += 1;
    discardCurrentRecording = true;
    let waitForStop = null;
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      waitForStop = new Promise((resolve) => mediaRecorder.addEventListener('stop', resolve, { once: true }));
      mediaRecorder.stop();
      stopMeter();
    } else {
      stopMeter();
      state.value = 'idle';
    }
    if (waitForStop) await waitForStop;
    mediaRecorder = null;
    chunks = [];
    errorMessage.value = '';
    silenceDetected.value = false;
    clearRecording();
  };

  const retryRecording = async () => {
    await cancelRecording();
    await startRecording();
  };

  // 2026.10.14(woojin.jung) 추가 - 백엔드 STT API 연동 전 녹음 파일 FormData 생성
  const buildUploadFormData = () => {
    if (!recordedFile.value) throw new Error('전송할 녹음 파일이 없습니다.');
    const formData = new FormData();
    formData.append('audio', recordedFile.value, recordedFile.value.name);
    formData.append('language', 'ko');
    formData.append('duration_ms', String(elapsedMs.value));
    return formData;
  };

  const dismiss = () => cancelRecording();

  // 2026.10.21(woojin.jung) 수정 - 인식 결과 원문과 transcription ID를 보관하여 음성 질문 전송에 사용
  const transcribeRecording = async () => {
    if (!hasRecording.value || isTranscribing.value) return;
    const controller = new AbortController();
    transcriptionController = controller;
    isTranscribing.value = true;
    transcriptionError.value = '';
    try {
      const { data } = await voiceApi.transcribe(buildUploadFormData(), controller.signal);
      if (controller.signal.aborted) return;
      const text = typeof data?.text === 'string' ? data.text.trim() : '';
      if (!text) throw new Error('empty transcription');
      transcript.value = text;
      originalTranscript.value = text;
      transcriptionId.value = data?.transcription_id ?? data?.transcriptionId ?? null;
      hasTranscription.value = true;
    } catch (error) {
      if (controller.signal.aborted) return;
      const status = error.response?.status;
      transcriptionError.value = status === 503
        ? '음성 인식 서버가 설정되지 않았거나 사용할 수 없습니다.'
        : status === 401
          ? '로그인이 필요합니다. 다시 로그인해 주세요.'
          : status === 413
            ? '녹음 파일이 너무 큽니다. 짧게 다시 녹음해 주세요.'
            : error.code === 'ECONNABORTED' || status === 504
              ? '음성 인식 시간이 초과되었습니다. 다시 시도해 주세요.'
              : '음성을 인식하지 못했습니다. 다시 변환하거나 다시 녹음해 주세요.';
    } finally {
      if (transcriptionController === controller) {
        transcriptionController = null;
        isTranscribing.value = false;
      }
    }
  };

  onBeforeUnmount(cancelRecording);

  return {
    state,
    elapsedMs,
    audioLevels,
    silenceDetected,
    errorMessage,
    recordedFile,
    audioUrl,
    autoStopped,
    // 2026.10.16(sooyeon.choi) 추가
    transcript,
    originalTranscript,
    transcriptionId,
    hasTranscription,
    isTranscribing,
    transcriptionError,
    transcribeRecording,
    isSupported,
    isRecording,
    isRequesting,
    hasRecording,
    maxDurationMs: MAX_DURATION_MS,
    startRecording,
    stopRecording,
    cancelRecording,
    retryRecording,
    buildUploadFormData,
    dismiss,
  };
};
