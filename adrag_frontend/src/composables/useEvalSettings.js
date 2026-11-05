// 데이터셋 QA 생성용 OpenAI 키 1회 저장/재사용 (관리자 계정 단위).
//   ChatView처럼 키를 서버에 암호화 저장하고, 조회는 저장 여부(has)만 받는다.
import { ref } from 'vue';
import { evalApi } from '../api/evalApi';

export const useEvalSettings = () => {
  const hasOpenAIKey = ref(false);
  const keyInput = ref('');
  const savingKey = ref(false);
  const keyError = ref('');

  const loadKeyStatus = async () => {
    try {
      const { data } = await evalApi.getOpenAIKeyStatus();
      hasOpenAIKey.value = !!data.has_openai_api_key;
    } catch {
      hasOpenAIKey.value = false;
    }
  };

  const saveKey = async () => {
    if (!keyInput.value) {
      keyError.value = 'OpenAI API 키를 입력하세요.';
      return false;
    }
    savingKey.value = true;
    keyError.value = '';
    try {
      await evalApi.saveOpenAIKey(keyInput.value);
      hasOpenAIKey.value = true;
      keyInput.value = '';
      return true;
    } catch (e) {
      keyError.value = e.response?.data?.detail || 'API 키 저장에 실패했습니다.';
      return false;
    } finally {
      savingKey.value = false;
    }
  };

  const clearKey = async () => {
    try {
      await evalApi.deleteOpenAIKey();
    } catch {
      // 삭제 실패는 조용히 무시 (상태만 유지)
    }
    hasOpenAIKey.value = false;
  };

  return { hasOpenAIKey, keyInput, savingKey, keyError, loadKeyStatus, saveKey, clearKey };
};
