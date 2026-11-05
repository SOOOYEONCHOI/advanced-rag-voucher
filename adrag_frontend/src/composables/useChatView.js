import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { chatApi } from '../api/chatApi';
import { chatStreamApi } from '../api/chatStreamApi';
import { TEMPORARY_ERROR_MESSAGE } from '../constants/userMessages';
import { useAuthStore } from '../stores/authStore';
import { escapeHtml, formatResponse, renderInlineCitations, sortCitations } from '../utils/textFormat';

export const useChatView = ({ router, route }) => {
  const authStore = useAuthStore();

  const showAccessDeniedModal = ref(false);
  const sidebarOpen = ref(false);
  // 2026.11.04(woojin.jung) 추가 - 넓은 화면에서 사이드바 접기(모바일 오버레이는 sidebarOpen)
  const sidebarCollapsed = ref(false);
  const userInput = ref('');
  const messages = ref([]);
  const isLoading = ref(false);
  const isStreaming = ref(false);
  const streamingStage = ref('');
  const isOnline = ref(false);
  const modelName = ref('');
  const chatArea = ref(null);
  const lastError = ref('');

  const chatCollections = ref([]);
  const selectedCollection = ref('');
  const collectionsLoaded = ref(false);

  const sourcesPanelOpen = ref(false);
  const selectedCitationId = ref(null);
  const activeCitations = ref([]);
  const citationPanelRef = ref(null);

  const modelSelectorOpen = ref(false);
  const availableModels = ref([]);
  const selectedModel = ref(null);
  const hasApiKey = ref(false);
  const openaiApiKey = ref('');
  const showApiKeyInput = ref(false);

  let healthCheckTimer = null;

  const authUser = computed(() => authStore.user);
  const currentCollectionName = computed(() => {
    const col = chatCollections.value.find((c) => c.qdrant_name === selectedCollection.value);
    return col ? col.collection_name : '';
  });
  const displayModelName = computed(() => {
    const provider = selectedModel.value?.provider?.toLowerCase();
    if (provider === 'openai' || selectedModel.value?.requires_api_key) {
      return selectedModel.value?.model_name || selectedModel.value?.model_id || '';
    }

    if (!modelName.value) return selectedModel.value?.model_name || '';
    return modelName.value.split(/[\\/]/).filter(Boolean).pop() || modelName.value;
  });
  const streamingStatusText = computed(() => {
    if (streamingStage.value === 'searching') return '문서 검색 중...';
    if (streamingStage.value === 'generating') return '답변 생성 중...';
    return '';
  });

  const isNearBottom = () => {
    const el = chatArea.value;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  const scrollToBottom = async ({ force = true } = {}) => {
    const shouldScroll = force || isNearBottom();
    await nextTick();
    if (shouldScroll && chatArea.value) chatArea.value.scrollTop = chatArea.value.scrollHeight;
  };

  const normalizeCitations = (items = []) =>
    items.map((c) => ({
      ...c,
      document_id: c.document_id || c.doc_id || c.file_id || c.source_document_id || c.metadata?.document_id || c.metadata?.doc_id || null,
    }));

  // 2026.10.22(woojin.jung) 수정 - 스트림·이력의 이미지 응답을 동일한 메시지 표시 형식으로 정규화
  const normalizeImages = (items = []) =>
    items
      .filter((image) => image?.resource_id)
      .map((image) => ({
        ...image,
        resource_id: String(image.resource_id),
        document_id: image.document_id || null,
        title: image.title || image.step_title || '관련 이미지',
      }));

  // 2026.06.24(woojin.jung) 추가 - DB 피드백 값을 화면 표시 값으로 정규화
  const normalizeFeedback = (feedback) => {
    if (feedback === 'like' || feedback === 1 || feedback === true) return 'like';
    if (feedback === 'dislike' || feedback === 0 || feedback === false) return 'dislike';
    return null;
  };

  const checkHealth = async () => {
    try {
      const res = await chatApi.health({ timeout: 5000 });
      isOnline.value = res.status === 200;
    } catch {
      isOnline.value = false;
    }

    try {
      const res = await chatApi.loadedModel({ timeout: 5000 });
      if (res.data?.model) modelName.value = res.data.model;
    } catch {
      /* ignore */
    }
  };

  const loadChatCollections = async () => {
    try {
      const res = await chatApi.queryCollections();
      chatCollections.value = res.data.collections || [];
    } catch {
      chatCollections.value = [];
    } finally {
      collectionsLoaded.value = true;
    }
  };

  const loadChatHistory = async (collectionName) => {
    try {
      const res = await chatApi.history(collectionName);
      const history = res.data.history || [];
      // 2026.06.24(woojin.jung) 수정 - 히스토리 응답의 로그 ID와 저장된 피드백 복원
      // 2026.10.26(woojin.jung) 수정 - 참고 문서 컨텍스트에 실제 답변 시각을 표시할 수 있도록 메시지 생성 시각 보존
      messages.value = history.map((h) => ({
        role: h.role,
        content: h.role === 'assistant' ? formatResponse(h.content) : escapeHtml(h.content),
        createdAt: h.created_at ?? h.createdAt ?? h.timestamp ?? null,
        citations: normalizeCitations(h.citations || []),
        images: normalizeImages(h.images || []),
        logId: h.log_id ?? h.logId ?? null,
        feedback: normalizeFeedback(h.feedback),
        inputMode: h.input_mode ?? h.inputMode ?? 'text',
        voiceTranscriptionId: h.voice_transcription_id ?? h.voiceTranscriptionId ?? null,
        voiceEdited: Boolean(h.voice_edited ?? h.voiceEdited),
      }));
      await scrollToBottom();

      const lastWithCitations = [...messages.value].reverse().find((m) => m.role === 'assistant' && m.citations?.length > 0);
      if (lastWithCitations) {
        activeCitations.value = lastWithCitations.citations;
        selectedCitationId.value = lastWithCitations.citations[0]?.citation_id ?? null;
        sourcesPanelOpen.value = true;
      }
    } catch {
      messages.value = [];
    }
  };

  const loadModels = async (collectionName) => {
    availableModels.value = [];
    try {
      const res = await chatApi.models(collectionName);
      availableModels.value = res.data.models || [];
    } catch {
      availableModels.value = [];
    }
  };

  const loadUserLlmSetting = async (collectionName) => {
    selectedModel.value = null;
    hasApiKey.value = false;
    openaiApiKey.value = '';
    showApiKeyInput.value = false;

    try {
      const res = await chatApi.userLlmSetting(collectionName);
      const setting = res.data.setting;
      if (setting) {
        const found = availableModels.value.find((m) => m.model_id === setting.model_id);
        selectedModel.value = found || availableModels.value[0] || null;
        hasApiKey.value = setting.has_api_key;
      } else {
        selectedModel.value = availableModels.value[0] || null;
      }
    } catch {
      selectedModel.value = availableModels.value[0] || null;
    }
  };

  const selectCollection = async (col) => {
    if (selectedCollection.value === col.qdrant_name) {
      sidebarOpen.value = false;
      return;
    }

    selectedCollection.value = col.qdrant_name;
    messages.value = [];
    lastError.value = '';
    sourcesPanelOpen.value = false;
    sidebarOpen.value = false;

    await Promise.all([loadChatHistory(col.qdrant_name), loadModels(col.qdrant_name)]);
    await loadUserLlmSetting(col.qdrant_name);
  };

  const saveModelSetting = async (model, apiKey) => {
    if (!authUser.value.user_id) return;

    try {
      await chatApi.saveUserLlmSetting({
        collection_name: selectedCollection.value,
        model_id: model.model_id,
        api_key: apiKey || undefined,
      });
    } catch (e) {
      console.warn('모델 설정 저장 실패:', e);
    }
  };

  const selectModel = async (model) => {
    selectedModel.value = model;
    showApiKeyInput.value = false;

    if (!model.requires_api_key) {
      modelSelectorOpen.value = false;
      await saveModelSetting(model, null);
    } else if (hasApiKey.value) {
      await saveModelSetting(model, null);
    }
  };

  const saveApiKey = async () => {
    if (!openaiApiKey.value || !selectedModel.value) return;
    await saveModelSetting(selectedModel.value, openaiApiKey.value);
    hasApiKey.value = true;
    showApiKeyInput.value = false;
    openaiApiKey.value = '';
    modelSelectorOpen.value = false;
  };

  const sendMessage = async () => {
    const text = userInput.value.trim();
    if (!text || isLoading.value || !selectedCollection.value) return;

    if (selectedModel.value?.requires_api_key && !hasApiKey.value) {
      lastError.value = 'API 키를 먼저 저장해주세요. (+ 버튼 → 저장)';
      return;
    }

    messages.value.push({ role: 'user', content: escapeHtml(text), createdAt: new Date().toISOString() });
    userInput.value = '';
    isLoading.value = true;
    lastError.value = '';
    await scrollToBottom();

    try {
      const res = await chatApi.send({
        query: text,
        collection_name: selectedCollection.value,
        llm_provider: selectedModel.value?.provider || 'local',
        llm_model: selectedModel.value?.model_id,
      });

      const reply = res.data.answer || res.data.response || res.data.message || JSON.stringify(res.data);
      const citations = normalizeCitations(res.data.citations || []);
      const images = normalizeImages(res.data.images || []);
      messages.value.push({
        role: 'assistant',
        content: formatResponse(reply),
        createdAt: new Date().toISOString(),
        citations,
        images,
        logId: res.data.log_id ?? res.data.logId ?? null,
        feedback: normalizeFeedback(res.data.feedback),
      });
      if (citations.length > 0) {
        activeCitations.value = citations;
        sourcesPanelOpen.value = true;
        await nextTick();
        citationPanelRef.value?.setShowAll(true);
      }
    } catch (err) {
      console.error('질의 요청 실패:', err);
      lastError.value = TEMPORARY_ERROR_MESSAGE;
      messages.value.push({
        role: 'assistant',
        content: `<span style="color:#ef4444;">${escapeHtml(TEMPORARY_ERROR_MESSAGE)}</span>`,
        createdAt: new Date().toISOString(),
      });
    } finally {
      isLoading.value = false;
      await scrollToBottom();
    }
  };

  // 2026.10.21(woojin.jung) 수정 - 텍스트·음성 질문을 동일한 스트리밍 흐름으로 전송하고 음성 메타데이터를 전달
  const sendMessageStream = async (messageOptions = null) => {
    const options = messageOptions?.inputMode ? messageOptions : {};
    const text = String(options.text ?? userInput.value).trim();
    if (!text || isLoading.value || !selectedCollection.value) return;

    if (selectedModel.value?.requires_api_key && !hasApiKey.value) {
      lastError.value = 'API 키를 먼저 저장해주세요. (+ 버튼 → 저장)';
      return;
    }

    const inputMode = options.inputMode === 'voice' ? 'voice' : 'text';
    const voiceTranscriptionId = options.voiceTranscriptionId ?? null;
    const voiceEdited = inputMode === 'voice' && Boolean(options.voiceEdited);

    messages.value.push({
      role: 'user',
      content: escapeHtml(text),
      createdAt: new Date().toISOString(),
      inputMode,
      voiceTranscriptionId,
      voiceEdited,
    });
    messages.value.push({ role: 'assistant', content: '', citations: [], images: [], createdAt: new Date().toISOString(), isStage: true, stage: 'searching', isStreaming: true });
    const idx = messages.value.length - 1;

    userInput.value = '';
    isLoading.value = true;
    isStreaming.value = true;
    streamingStage.value = 'searching';
    lastError.value = '';
    await scrollToBottom();

    let rawReply = '';
    let citations = [];
    let images = [];
    let renderFrame = null;

    const renderStreamingReply = async () => {
      renderFrame = null;
      messages.value[idx].content = rawReply ? formatResponse(rawReply) : '';
      await scrollToBottom({ force: false });
    };

    const scheduleStreamingRender = () => {
      if (renderFrame !== null) return;
      renderFrame = window.requestAnimationFrame(renderStreamingReply);
    };

    try {
      const payload = {
        query: text,
        collection_name: selectedCollection.value,
        // 2026.06.05(sooyeon.choi) 수정 - top_k 하드코딩 제거
        //   백엔드 API 기본값(10)을 사용하여 백엔드 설정으로 제어
        //   top_k: 5,
        llm_provider: selectedModel.value?.provider || 'local',
        llm_model: selectedModel.value?.model_id,
      };

      if (inputMode === 'voice') {
        payload.input_mode = 'voice';
        payload.voice_edited = voiceEdited;
        if (voiceTranscriptionId !== null && voiceTranscriptionId !== '') payload.voice_transcription_id = voiceTranscriptionId;
      }

      if (openaiApiKey.value) {
        payload.openai_api_key = openaiApiKey.value;
      }

      await chatStreamApi.send(payload, {
        onEvent: async (event) => {
          if (event.type === 'progress') {
            streamingStage.value = event.stage || '';
            if (!rawReply) {
              messages.value[idx].isStage = true;
              messages.value[idx].stage = event.stage || 'searching';
            }
            await scrollToBottom({ force: false });
            return;
          }

          if (event.type === 'token') {
            streamingStage.value = '';
            rawReply += event.content || '';
            messages.value[idx].isStage = false;
            scheduleStreamingRender();
            return;
          }

          if (event.type === 'citations') {
            citations = normalizeCitations(event.data || []);
            messages.value[idx].citations = citations;
            return;
          }

          // 2026.10.22(woojin.jung) 수정 - SSE images 이벤트를 현재 답변에 연결해 즉시 갤러리 표시
          if (event.type === 'images') {
            images = normalizeImages(event.data || []);
            messages.value[idx].images = images;
            return;
          }

          // 2026.06.19(sooyeon.choi) 추가 - 스트리밍 로그 ID를 피드백 대상 메시지에 연결
          if (event.type === 'meta') {
            messages.value[idx].logId = event.log_id || null;
            return;
          }

          if (event.type === 'error') {
            throw new Error(event.message || TEMPORARY_ERROR_MESSAGE);
          }

          if (event.type === 'done') {
            return;
          }
        },
      });

      if (renderFrame !== null) {
        window.cancelAnimationFrame(renderFrame);
        renderFrame = null;
      }
      messages.value[idx].content = rawReply ? formatResponse(rawReply) : '';
      messages.value[idx].isStage = false;
      messages.value[idx].isStreaming = false;
      messages.value[idx].citations = citations;
      messages.value[idx].images = images;

      if (citations.length > 0) {
        activeCitations.value = citations;
        sourcesPanelOpen.value = true;
        await nextTick();
        citationPanelRef.value?.setShowAll(true);
      }
    } catch (err) {
      console.error('스트리밍 질의 요청 실패:', err);
      lastError.value = TEMPORARY_ERROR_MESSAGE;
      if (renderFrame !== null) {
        window.cancelAnimationFrame(renderFrame);
        renderFrame = null;
      }
      messages.value[idx].isStage = false;
      messages.value[idx].isStreaming = false;
      messages.value[idx].content = `<span style="color:#ef4444;">${escapeHtml(TEMPORARY_ERROR_MESSAGE)}</span>`;
    } finally {
      isLoading.value = false;
      isStreaming.value = false;
      streamingStage.value = '';
      await scrollToBottom({ force: false });
    }
  };

  const sendStreamingMessage = sendMessageStream;

  // 2026.06.24(woojin.jung) 추가 - 피드백 반영 및 실패 시 이전 상태 복구
  const submitMessageFeedback = async (message, value) => {
    if (!message?.logId || message.feedbackPending) return;

    const previousFeedback = message.feedback ?? null;
    const nextFeedback = previousFeedback === value ? null : value;
    message.feedback = nextFeedback;
    message.feedbackPending = true;

    try {
      const res = await chatApi.submitFeedback(message.logId, nextFeedback);
      message.feedback = normalizeFeedback(res.data?.feedback);
      return message.feedback;
    } catch (error) {
      message.feedback = previousFeedback;
      throw error;
    } finally {
      message.feedbackPending = false;
    }
  };

  const newChat = async () => {
    if (!selectedCollection.value) return;
    try {
      await chatApi.reset(selectedCollection.value);
    } catch {
      /* ignore */
    }
    messages.value = [];
    lastError.value = '';
    sourcesPanelOpen.value = false;
    selectedCitationId.value = null;
    activeCitations.value = [];
  };

  const logoutUser = async () => {
    await authStore.logoutAny();
    selectedCollection.value = '';
    messages.value = [];
    lastError.value = '';
    availableModels.value = [];
    selectedModel.value = null;
    sourcesPanelOpen.value = false;
    activeCitations.value = [];
    selectedCitationId.value = null;
    await loadChatCollections();
  };

  const openSourcesPanel = (citation, citations) => {
    activeCitations.value = citations;
    selectedCitationId.value = citation.citation_id;
    sourcesPanelOpen.value = true;
  };

  // 2026.07.10(sooyeon.choi) 수정 - 동일 citation_id가 있는 이전 답변 대신 클릭한 메시지의 출처를 우선 선택
  const openCitationHandler = (citationId, messageIndex = null) => {
    if (Number.isInteger(messageIndex)) {
      const msg = messages.value[messageIndex];
      const found = msg?.citations?.some((c) => c.citation_id === citationId || c.citation_id === String(citationId));
      if (found) {
        activeCitations.value = msg.citations;
        selectedCitationId.value = citationId;
        sourcesPanelOpen.value = true;
        return;
      }
    }

    // messageIndex 없이 호출되는 기존 마크업은 최신 답변부터 탐색한다.
    for (const msg of [...messages.value].reverse()) {
      if (msg.citations?.length > 0) {
        const found = msg.citations.some((c) => c.citation_id === citationId || c.citation_id === String(citationId));
        if (found) {
          activeCitations.value = msg.citations;
          selectedCitationId.value = citationId;
          sourcesPanelOpen.value = true;
          return;
        }
      }
    }
  };

  watch(
    () => route.query.access_denied,
    (val) => {
      if (val) {
        showAccessDeniedModal.value = true;
        router.replace({ path: '/chat' });
      }
    },
    { immediate: true }
  );

  onMounted(async () => {
    await authStore.syncUser();
    await loadChatCollections();
    checkHealth();
    healthCheckTimer = window.setInterval(checkHealth, 30000);
    window.__openCitation = openCitationHandler;
  });

  onUnmounted(() => {
    if (healthCheckTimer) window.clearInterval(healthCheckTimer);
    delete window.__openCitation;
  });

  return {
    showAccessDeniedModal,
    sidebarOpen,
    sidebarCollapsed,
    userInput,
    messages,
    isLoading,
    isStreaming,
    streamingStage,
    streamingStatusText,
    isOnline,
    modelName,
    displayModelName,
    chatArea,
    lastError,
    authUser,
    chatCollections,
    selectedCollection,
    collectionsLoaded,
    currentCollectionName,
    sourcesPanelOpen,
    selectedCitationId,
    activeCitations,
    citationPanelRef,
    modelSelectorOpen,
    availableModels,
    selectedModel,
    hasApiKey,
    openaiApiKey,
    showApiKeyInput,
    selectCollection,
    selectModel,
    saveApiKey,
    sendMessage,
    sendMessageStream,
    sendStreamingMessage,
    submitMessageFeedback,
    newChat,
    logoutUser,
    openSourcesPanel,
    sortCitations,
    renderInlineCitations,
  };
};
