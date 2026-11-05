// 2026.10.16(sooyeon.choi) 추가
import { authConfig, http } from './http';

// 녹음 미리듣기 후 사용자 요청으로만 STT 실행.
export const voiceApi = {
  transcribe(formData, signal) {
    return http.post('/voice/transcriptions', formData, authConfig({ timeout: 35000, signal }));
  },
};
