<template>
  <div class="app-layout">
    <!-- 접근 거부 모달 -->
    <div v-if="showAccessDeniedModal" class="modal-overlay" @click.self="showAccessDeniedModal = false">
      <div class="modal-card">
        <div class="modal-icon"><i class="fa-solid fa-lock"></i></div>
        <h3>접근 권한 없음</h3>
        <!-- 2026.11.20(woojin.jung) 수정 - 부서 운영관리자 전용 화면 안내 -->
        <p v-if="accessDeniedReason === 'manager'">관리 화면은 부서 운영관리자만 사용할 수 있습니다.<br />문서·대화 주제 관련 요청은 부서 운영관리자에게 문의하세요.</p>
        <p v-else>관리자 페이지는 관리자 계정으로만 접근할 수 있습니다.</p>
        <button class="modal-confirm-btn" @click="showAccessDeniedModal = false">확인</button>
      </div>
    </div>
    <div v-if="showNewChatConfirm" class="modal-overlay" @click.self="showNewChatConfirm = false">
      <div class="modal-card">
        <div class="modal-icon warning"><i class="fa-solid fa-triangle-exclamation"></i></div>
        <h3>새 대화를 시작할까요?</h3>
        <p>
          이전 채팅 내역은 모두 삭제됩니다.<br />
          계속하려면 확인을 눌러주세요.
        </p>
        <div class="modal-actions">
          <button class="modal-cancel-btn" @click="showNewChatConfirm = false">취소</button>
          <button class="modal-confirm-btn danger" @click="confirmNewChat">확인</button>
        </div>
      </div>
    </div>
    <ImageViewer
      :open="imageViewerOpen"
      :images="imageViewerImages"
      :index="imageViewerIndex"
      :canLocate="Boolean(currentImageCitation)"
      @close="closeImageViewer"
      @change="imageViewerIndex = $event"
      @locate="locateCurrentImage"
      @toast="showToast"
    />
    <AppToast :message="toastMessage" :type="toastType" @close="toastMessage = ''" />
    <ChatSidebar
      :isOpen="sidebarOpen"
      :collapsed="sidebarCollapsed"
      :collectionsLoaded="collectionsLoaded"
      :chatCollections="chatCollections"
      :selectedCollection="selectedCollection"
      :authUser="authUser"
      @close="
        sidebarOpen = false;
        sidebarCollapsed = true;
      "
      @selectCollection="selectCollection"
      @logout="logoutUser"
    />

    <!-- 메인 영역 -->
    <div ref="mainContainerRef" class="main-container" :class="{ resizing: citationResizing }">
      <div class="chat-column">
        <PageHeader
          :showMenu="sidebarCollapsed"
          @openSidebar="
            sidebarOpen = true;
            sidebarCollapsed = false;
          "
        >
          <template #title>
            {{ currentCollectionName || 'RAG Assistant' }}
            <span class="status-dot" :class="{ offline: !isOnline }"></span>
          </template>
          <template #actions>
            <div class="header-actions">
              <div class="header-model">{{ displayModelName }}</div>
              <button v-if="selectedCollection" class="btn-reset-chat" @click="requestNewChat" :disabled="isLoading || messages.length === 0" title="현재 대화를 초기화하고 새로 시작합니다">
                <i class="fa-solid fa-rotate-right"></i>
                <span>새 대화</span>
              </button>
            </div>
          </template>
        </PageHeader>

        <div class="chat-scroll-area" :class="{ 'has-voice-panel': voiceState !== 'idle' }" ref="chatArea">
          <!-- 대화 주제 미선택 안내 -->
          <!-- 2026.11.23(woojin.jung) 수정 - 소속 부서가 비활성이면 이유를 안내 -->
          <div v-if="!selectedCollection && authUser?.department_active === false" class="welcome">
            <div class="welcome-icon"><i class="fa-solid fa-lock"></i></div>
            <h2>소속 부서가 비활성화되었습니다</h2>
            <p>지금은 사용할 수 있는 대화 주제가 없습니다. 다시 사용하려면 관리자에게 문의하세요.</p>
          </div>
          <!-- 2026.11.23(woojin.jung) 추가 - 개인 차단 등으로 쓸 수 있는 주제가 없을 때 -->
          <div v-else-if="!selectedCollection && collectionsLoaded && chatCollections.length === 0" class="welcome">
            <div class="welcome-icon"><i class="fa-solid fa-lock"></i></div>
            <h2>사용할 수 있는 대화 주제가 없습니다</h2>
            <p>대화 주제 접근 권한이 필요하면 부서 운영관리자에게 문의하세요.</p>
          </div>
          <div v-else-if="!selectedCollection" class="welcome">
            <div class="welcome-icon"><i class="fa-solid fa-comments"></i></div>
            <h2>대화 주제를 선택하세요</h2>
            <!-- 2026.11.23(woojin.jung) 수정 - 휴대폰에서는 목록이 왼쪽 패널이 아니라 메뉴(☰) 안에 있어 위치 대신 '대화 주제 목록'으로 안내 -->
            <p>대화 주제 목록에서 주제를 선택하면 해당 문서 범위로 질문할 수 있습니다.</p>
          </div>

          <!-- 메시지 목록 -->
          <template v-else>
            <!-- 2026.11.12(woojin.jung) 수정 - 시작 화면에 추천 질문(대화 주제 설정 등록)·많이 찾는 질문(질의 로그 집계) 표시, 클릭 시 바로 질문 -->
            <div v-if="messages.length === 0 && !isLoading" class="welcome faq-welcome">
              <div class="welcome-icon"><i class="fa-solid fa-robot"></i></div>
              <h2>무엇을 도와드릴까요?</h2>
              <p>
                {{ currentCollectionName ? `${currentCollectionName} 문서를 기반으로 답변합니다.` : '문서 기반 질의응답과 안전 규정 검색을 지원합니다.' }}
                <template v-if="startQuestions.recommended.length || startQuestions.popular.length"> 아래 질문을 눌러 바로 시작해 보세요.</template>
              </p>
              <div v-if="startQuestions.recommended.length || startQuestions.popular.length" class="faq-columns" :class="{ single: !startQuestions.recommended.length || !startQuestions.popular.length }">
                <section v-if="startQuestions.recommended.length" class="faq-group registered" aria-label="추천 질문">
                  <div class="faq-group-head"><i class="fa-solid fa-thumbtack"></i><strong>추천 질문</strong></div>
                  <div class="faq-list">
                    <button v-for="question in startQuestions.recommended" :key="question" type="button" class="faq-item" @click="sendStartQuestion(question, 'recommended')">
                      <span class="faq-pin"><i class="fa-solid fa-circle"></i></span>
                      <span class="faq-q">{{ question }}</span>
                      <i class="fa-solid fa-arrow-right go"></i>
                    </button>
                  </div>
                </section>
                <section v-if="startQuestions.popular.length" class="faq-group popular" aria-label="많이 찾는 질문">
                  <div class="faq-group-head"><i class="fa-solid fa-arrow-trend-up"></i><strong>많이 찾는 질문</strong><span>최근 {{ startQuestions.popularDays }}일</span></div>
                  <div class="faq-list">
                    <button v-for="(item, pIdx) in startQuestions.popular" :key="item.question" type="button" class="faq-item" @click="sendStartQuestion(item.question, 'popular')">
                      <span class="faq-rank">{{ pIdx + 1 }}</span>
                      <span class="faq-q">{{ item.question }}</span>
                      <span class="faq-cnt">{{ item.count }}회</span>
                      <i class="fa-solid fa-arrow-right go"></i>
                    </button>
                  </div>
                </section>
              </div>
            </div>

            <div v-for="(msg, idx) in messages" :key="idx" class="message" :class="[msg.role, { 'source-answer-active': isSourceAnswer(idx) }]" :data-message-index="idx">
              <div class="avatar" :class="msg.role">
                <i :class="msg.role === 'user' ? 'fa-solid fa-user' : 'fa-solid fa-robot'"></i>
              </div>
              <div v-if="msg.isStage" class="stage-bubble" :class="{ generating: msg.stage === 'generating' }">
                <i class="fa-solid fa-circle-notch stage-icon"></i>
                <div>
                  <div class="stage-text">{{ msg.stage === 'generating' ? '답변 생성 중...' : '문서 검색 중...' }}</div>
                  <div class="stage-sub">{{ msg.stage === 'generating' ? 'AI가 답변을 작성하고 있습니다.' : '관련 문서를 찾고 있습니다.' }}</div>
                </div>
              </div>
              <div v-else class="message-body">
                <div class="bubble">
                  <div
                    v-html="
                      msg.role === 'assistant'
                        ? renderInlineCitations(msg.content, msg.citations || [], msg.isStreaming, msg.citations === activeCitations ? selectedCitationId : null, idx, msg.images || [])
                        : msg.content
                    "
                  ></div>
                  <!-- 2026.11.06(sooyeon.choi) 수정 - 출처 사진 전체 장수(total)·"전체 N장 보기" → 출처 패널 -->
                  <ChatImageGallery
                    v-if="msg.role === 'assistant' && msg.images?.length"
                    :images="msg.images"
                    :total="msg.imagesTotal || msg.images.length"
                    @open="openImageViewer(msg.images, $event, msg.citations || [])"
                    @open-sources="openImageSources(msg, $event)"
                  />
                  <div v-if="msg.role === 'assistant' && msg.citations && msg.citations.length > 0" class="reference-section">
                    <div class="ref-title">[참고 문서]</div>
                    <div v-for="group in groupCitationsByDocument(msg.citations)" :key="group.key" class="ref-item">
                      <span class="ref-filename" :title="group.filename">{{ group.filename }}</span>
                      <div class="ref-pages" aria-label="참고 페이지 목록">
                        <button
                          v-for="page in group.pages"
                          :key="page.pageKey"
                          type="button"
                          class="ref-page"
                          :class="{ active: msg.citations === activeCitations && selectedCitationId == page.citation.citation_id }"
                          :title="`${group.filename} ${citationDisplayPage(page.citation) != null ? `${citationDisplayPage(page.citation)}페이지` : '참고문서'} 보기`"
                          @click="openSourcesPanel(page.citation, msg.citations)"
                        >
                          {{ citationDisplayPage(page.citation) != null ? `p.${citationDisplayPage(page.citation)}` : `[${page.citation.citation_id}]` }}
                        </button>
                      </div>
                    </div>
                  </div>
                  <div v-if="msg.role === 'assistant' && !msg.isStreaming" class="message-actions assistant-actions">
                    <button class="message-action-btn" @click="copyMessage(msg)" title="Copy">
                      <i class="fa-regular fa-copy"></i>
                    </button>
                    <button class="message-action-btn" @click="retryMessage(idx)" :disabled="isLoading" title="Retry">
                      <i class="fa-solid fa-rotate-right"></i>
                    </button>
                    <div class="action-divider"></div>
                    <button
                      class="message-action-btn"
                      :class="{ active: msg.feedback === 'like', 'like-active': msg.feedback === 'like' }"
                      :disabled="!msg.logId || msg.feedbackPending"
                      :aria-pressed="msg.feedback === 'like'"
                      @click="setMessageFeedback(msg, 'like')"
                      title="Like"
                    >
                      <i class="fa-regular fa-thumbs-up"></i>
                    </button>
                    <button
                      class="message-action-btn"
                      :class="{ active: msg.feedback === 'dislike', 'dislike-active': msg.feedback === 'dislike' }"
                      :disabled="!msg.logId || msg.feedbackPending"
                      :aria-pressed="msg.feedback === 'dislike'"
                      @click="setMessageFeedback(msg, 'dislike')"
                      title="Dislike"
                    >
                      <i class="fa-regular fa-thumbs-down"></i>
                    </button>
                  </div>
                  <!-- 2026.11.05(woojin.jung) 추가 - 좋아요/별로에요 선택 후 사유·의견 입력 패널 -->
                  <ChatFeedbackPanel
                    v-if="msg.role === 'assistant' && msg.feedback && msg.feedbackPanel"
                    :key="`${msg.logId}-${msg.feedback}`"
                    :feedback="msg.feedback"
                    :done="msg.feedbackPanel === 'done'"
                    :pending="msg.feedbackPending"
                    :source-label="feedbackSourceLabel(msg.citations)"
                    @submit="submitFeedbackDetail(msg, $event)"
                    @close="msg.feedbackPanel = null"
                  />
                </div>
                <span v-if="msg.role === 'user' && msg.inputMode === 'voice'" class="voice-origin">
                  <i class="fa-solid fa-microphone"></i>
                  음성 질문
                  <span v-if="msg.voiceEdited" class="edited">· 인식 결과 수정됨</span>
                </span>
                <!-- 2026.11.12(woojin.jung) 추가 - 시작 화면 질문으로 보낸 질문 표시 -->
                <span v-else-if="msg.role === 'user' && (msg.inputMode === 'recommended' || msg.inputMode === 'popular')" class="text-origin">
                  <i :class="msg.inputMode === 'recommended' ? 'fa-solid fa-thumbtack' : 'fa-solid fa-arrow-trend-up'"></i>
                  {{ msg.inputMode === 'recommended' ? '추천 질문' : '많이 찾는 질문' }}
                </span>
                <div v-if="msg.role === 'user'" class="message-actions user-actions">
                  <button class="message-action-btn" @click="copyMessage(msg)">
                    <i class="fa-regular fa-copy"></i>
                  </button>
                </div>
              </div>
            </div>

            <div v-if="isLoading && !isStreaming" class="message assistant">
              <div class="avatar assistant"><i class="fa-solid fa-robot"></i></div>
              <div class="bubble loading-bubble">
                <span v-if="streamingStatusText" class="loading-text">{{ streamingStatusText }}</span>
                <template v-else><span class="dot"></span><span class="dot"></span><span class="dot"></span></template>
              </div>
            </div>
          </template>
        </div>

        <!-- 입력 영역 -->
        <div ref="inputWrapperRef" class="input-wrapper" v-if="selectedCollection">
          <div v-if="lastError" class="collection-notice error"><i class="fa-solid fa-circle-exclamation"></i> {{ lastError }}</div>

          <!-- 2026.10.14(woojin.jung) 추가 - 음성 녹음 중·완료·오류 상태 UI 및 녹음 파일 미리듣기 -->
          <section v-if="voiceState !== 'idle'" class="voice-preview" :class="voiceState" role="status" aria-live="polite">
            <!-- 2026.10.21(woojin.jung) 추가 - 마이크 장치 준비 전 별도 연결 상태 표시 -->
            <template v-if="voiceState === 'requesting'">
              <div class="voice-preview-icon"><i class="fa-solid fa-circle-notch fa-spin"></i></div>
              <div class="voice-preview-content">
                <strong>마이크 연결 중...</strong>
                <span>브라우저의 마이크 권한과 장치를 확인하고 있습니다.</span>
              </div>
              <div class="voice-preview-actions">
                <button type="button" class="voice-close-btn" @click="cancelRecording" aria-label="마이크 연결 취소" title="마이크 연결 취소"><i class="fa-solid fa-xmark"></i></button>
              </div>
            </template>

            <template v-else-if="voiceState === 'recording'">
              <div class="voice-preview-icon"><i class="fa-solid fa-wave-square"></i></div>
              <div class="voice-preview-content">
                <strong>말씀해 주세요</strong>
                <span v-if="!silenceDetected">말을 마치면 [녹음 완료]를 눌러 주세요.</span>
                <span v-else class="voice-warning"><i class="fa-solid fa-triangle-exclamation"></i> 마이크 입력이 감지되지 않습니다.</span>
                <div class="voice-timer">
                  <div class="voice-level" aria-hidden="true">
                    <i v-for="(level, index) in audioLevels" :key="index" :style="{ height: `${6 + level * 14}px` }"></i>
                  </div>
                  <b>{{ formatVoiceDuration(elapsedMs) }}</b>
                  <span>/ {{ formatVoiceDuration(maxDurationMs) }}</span>
                </div>
              </div>
              <div class="voice-preview-actions">
                <button type="button" class="voice-control-btn stop" @click="stopRecording()"><i class="fa-solid fa-stop"></i> 녹음 완료</button>
                <button type="button" class="voice-close-btn" @click="cancelRecording" aria-label="녹음 취소" title="녹음 취소"><i class="fa-solid fa-xmark"></i></button>
              </div>
            </template>

            <template v-else-if="voiceState === 'ready'">
              <div class="voice-preview-icon ready-icon"><i class="fa-solid fa-check"></i></div>
              <div class="voice-preview-content">
                <strong>녹음이 완료되었습니다 <em>전송 준비 완료</em></strong>
                <span>{{ recordedFile?.name }} · {{ formatFileSize(recordedFile?.size) }} · {{ formatVoiceDuration(elapsedMs) }}</span>
                <!-- 2026.10.15(woojin.jung) 수정 - WebM 첫 재생 메타데이터 지연 영향을 받지 않는 커스텀 미리듣기 플레이어 적용 -->
                <div class="voice-audio-player">
                  <audio
                    ref="voiceAudioRef"
                    class="voice-audio-element"
                    :src="audioUrl"
                    preload="auto"
                    @loadedmetadata="handleVoiceAudioLoaded"
                    @timeupdate="handleVoiceTimeUpdate"
                    @play="isVoicePlaying = true"
                    @pause="isVoicePlaying = false"
                    @ended="handleVoiceAudioEnded"
                    @error="handleVoiceAudioError"
                  >
                    오디오 미리듣기를 지원하지 않는 브라우저입니다.
                  </audio>
                  <button
                    type="button"
                    class="voice-play-btn"
                    :aria-label="isVoicePlaying ? '녹음 일시정지' : '녹음 재생'"
                    :title="isVoicePlaying ? '일시정지' : '재생'"
                    :disabled="!audioUrl"
                    @click="toggleVoicePlayback"
                  >
                    <i :class="isVoicePlaying ? 'fa-solid fa-pause' : 'fa-solid fa-play'"></i>
                  </button>
                  <input
                    class="voice-progress"
                    type="range"
                    min="0"
                    :max="voiceDurationSeconds || 0.1"
                    step="0.01"
                    :value="voicePlaybackTime"
                    :style="{ '--voice-progress': `${voicePlaybackProgress}%` }"
                    aria-label="녹음 재생 위치"
                    @input="seekVoicePlayback"
                  />
                  <span class="voice-playback-time"> {{ formatVoiceDuration(voicePlaybackTime * 1000) }} / {{ formatVoiceDuration(elapsedMs) }} </span>
                </div>
                <!-- 2026.10.16(sooyeon.choi) 추가 -->
                <span v-if="isTranscribing">음성을 텍스트로 변환하고 있습니다.</span>
                <span v-if="transcriptionError" class="voice-warning" role="alert">{{ transcriptionError }}</span>
                <template v-if="hasTranscription">
                  <label for="voice-transcript">인식 결과 · 내용을 확인하고 수정해 주세요.</label>
                  <textarea
                    id="voice-transcript"
                    v-model="voiceTranscript"
                    class="voice-transcript-input"
                    rows="3"
                    :disabled="isTranscribing || isVoiceSubmitting"
                    @keydown.ctrl.enter.prevent="submitVoiceQuestion"
                  />
                  <span class="voice-submit-hint">Ctrl+Enter를 누르면 바로 질문합니다.</span>
                </template>
              </div>
              <div class="voice-preview-actions">
                <!-- 2026.10.21(woojin.jung) 수정 - 인식 결과를 입력창에 적용하지 않고 편집 후 바로 질문 전송 -->
                <button v-if="!hasTranscription" type="button" class="voice-control-btn" :disabled="isTranscribing" @click="transcribeRecording">
                  <i :class="isTranscribing ? 'fa-solid fa-spinner fa-spin' : 'fa-solid fa-file-lines'"></i> {{ isTranscribing ? '변환 중' : '텍스트 변환' }}
                </button>
                <button v-if="hasTranscription" type="button" class="voice-control-btn" :disabled="isTranscribing || isVoiceSubmitting" @click="retryRecording">
                  <i class="fa-solid fa-rotate-left"></i> 다시 녹음
                </button>
                <button
                  v-if="hasTranscription"
                  type="button"
                  class="voice-control-btn send"
                  :disabled="isTranscribing || isLoading || isVoiceSubmitting || !voiceTranscript.trim()"
                  @click="submitVoiceQuestion"
                >
                  <i :class="isVoiceSubmitting ? 'fa-solid fa-spinner fa-spin' : 'fa-solid fa-paper-plane'"></i>
                  {{ isVoiceSubmitting ? '질문 중' : '질문하기' }}
                </button>
              </div>
              <!-- 2026.10.21(woojin.jung) 수정 - 닫기는 우측 상단, 주요 동작은 편집 영역 하단에 분리 배치 -->
              <button type="button" class="voice-close-btn voice-panel-close" :disabled="isVoiceSubmitting" @click="dismissVoice" aria-label="음성 입력 닫기" title="음성 입력 닫기">
                <i class="fa-solid fa-xmark"></i>
              </button>
            </template>

            <template v-else>
              <div class="voice-preview-icon error-icon"><i class="fa-solid fa-microphone-slash"></i></div>
              <div class="voice-preview-content">
                <strong>음성 입력을 시작하지 못했습니다</strong>
                <span class="voice-warning">{{ voiceErrorMessage }}</span>
              </div>
              <div class="voice-preview-actions">
                <button v-if="isVoiceSupported" type="button" class="voice-control-btn" @click="startRecording"><i class="fa-solid fa-rotate-left"></i> 다시 시도</button>
                <button type="button" class="voice-close-btn" @click="dismissVoice" aria-label="오류 닫기"><i class="fa-solid fa-xmark"></i></button>
              </div>
            </template>
          </section>

          <!-- 모델 선택 팝업 -->
          <div ref="modelSelectorPopupRef" v-if="modelSelectorOpen" class="model-selector-popup" :style="modelSelectorPopupStyle" @click.self="modelSelectorOpen = false">
            <div class="model-selector-card">
              <div class="model-selector-title"><i class="fa-solid fa-microchip"></i> MODEL</div>

              <div v-if="availableModels.length === 0" class="model-loading"><i class="fa-solid fa-circle-notch fa-spin"></i> 로딩 중...</div>
              <div v-for="m in availableModels" :key="m.model_id" class="model-option" :class="{ active: selectedModel && selectedModel.model_id === m.model_id }" @click="selectModel(m)">
                {{ m.model_name }}
                <i v-if="selectedModel && selectedModel.model_id === m.model_id" class="fa-solid fa-check model-check"></i>
              </div>

              <!-- API 키 섹션 (openai 모델 선택 시) -->
              <div v-if="selectedModel && selectedModel.requires_api_key" class="model-api-key-section">
                <label class="api-key-label">
                  OpenAI API Key
                  <span v-if="hasApiKey" class="api-key-saved-badge"> <i class="fa-solid fa-check"></i> 저장됨 </span>
                </label>
                <div v-if="!hasApiKey || showApiKeyInput" class="api-key-input-row">
                  <input v-model="openaiApiKey" type="password" placeholder="sk-..." class="api-key-input" @click.stop />
                  <button class="api-key-save-btn" @click.stop="saveApiKey" :disabled="!openaiApiKey">저장</button>
                </div>
                <button v-else class="api-key-change-btn" @click.stop="showApiKeyInput = true"><i class="fa-solid fa-pen"></i> 변경</button>
              </div>
            </div>
          </div>

          <div class="input-bar">
            <button ref="modelButtonRef" class="icon-btn model-btn" @click="toggleModelSelector" :title="selectedModel ? selectedModel.model_name : '모델 선택'">
              <i class="fa-solid fa-plus"></i>
            </button>
            <!-- 2026.10.14(woojin.jung) 추가 - 음성 녹음 시작 및 완료 마이크 버튼 -->
            <button
              type="button"
              class="icon-btn voice-btn"
              :class="{ recording: isVoiceRecording, requesting: isVoiceRequesting }"
              :disabled="isLoading || !isVoiceSupported || isVoiceRequesting"
              :aria-pressed="String(isVoiceRecording)"
              :title="voiceButtonTitle"
              @click="toggleVoiceRecording"
            >
              <i :class="isVoiceRequesting ? 'fa-solid fa-circle-notch fa-spin' : isVoiceRecording ? 'fa-solid fa-stop' : 'fa-solid fa-microphone'"></i>
            </button>
            <input v-model="userInput" @keyup.enter="sendMessageStream" placeholder="질문을 입력하세요.." :disabled="isLoading || isVoiceRecording" />
            <!-- <button v-if="isStreaming" class="icon-btn stop" @click="stopStreaming" title="Stop">
              <i class="fa-solid fa-stop"></i>
            </button> -->
            <button class="icon-btn send" @click="sendMessageStream" :disabled="isLoading || !userInput.trim()">
              <i class="fa-solid fa-arrow-up"></i>
            </button>
          </div>
          <div class="input-hint">
            <span v-if="selectedModel" class="selected-model-badge">
              <i class="fa-solid fa-microchip"></i>
              {{ selectedModel.model_name }}
              <span v-if="selectedModel.requires_api_key && hasApiKey" style="color: #22c55e">
                <i class="fa-solid fa-lock" style="font-size: 0.65rem"></i>
              </span>
              <span v-if="selectedModel.requires_api_key && !hasApiKey" style="color: #f59e0b"> · API 키 필요 </span>
            </span>
            <span v-else style="color: #94a3b8">모델을 선택해주세요</span>
            AI 답변에는 오류가 있을 수 있으니, 중요한 내용은 참고 문서와 함께 확인해 주세요.
          </div>
        </div>
      </div>

      <div v-if="sourcesPanelOpen && activeCitations.length > 0" class="citation-resizer" @mousedown="startCitationResize"></div>

      <CitationPanel
        ref="citationPanelRef"
        :citations="activeCitations"
        :collectionName="selectedCollection"
        :selectedCitationId="selectedCitationId"
        :sourceQuestion="activeSourceContext.question"
        :sourceAnswerTime="activeSourceContext.answerTime"
        :sourceMessageIndex="activeSourceContext.messageIndex"
        :isOpen="sourcesPanelOpen && activeCitations.length > 0"
        :panelWidth="citationPanelWidth"
        @close="sourcesPanelOpen = false"
        @selectCitation="selectedCitationId = $event"
        @scrollToAnswer="scrollToSourceAnswer"
        @toast="showToast"
        @openImages="openCitationImages"
      />
    </div>
  </div>
</template>

<script>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import CitationPanel from '../components/CitationPanel.vue';
import ChatSidebar from '../components/ChatSidebar.vue';
import AppToast from '../components/AppToast.vue';
import PageHeader from '../components/PageHeader.vue';
import ChatImageGallery from '../components/ChatImageGallery.vue';
import ImageViewer from '../components/ImageViewer.vue';
import ChatFeedbackPanel from '../components/ChatFeedbackPanel.vue';
import { useChatView } from '../composables/useChatView';
import { useVoiceRecorder } from '../composables/useVoiceRecorder';
import { citationDisplayPage, groupCitationsByDocument } from '../utils/textFormat';

export default {
  components: { CitationPanel, ChatSidebar, AppToast, PageHeader, ChatImageGallery, ImageViewer, ChatFeedbackPanel },
  setup() {
    const router = useRouter();
    const route = useRoute();
    const chatView = useChatView({ router, route });
    const voiceRecorder = useVoiceRecorder();
    const voiceAudioRef = ref(null);
    const voicePlaybackTime = ref(0);
    const isVoicePlaying = ref(false);
    const isVoiceSubmitting = ref(false);
    const inputWrapperRef = ref(null);
    const mainContainerRef = ref(null);
    const modelButtonRef = ref(null);
    const modelSelectorPopupRef = ref(null);
    const modelSelectorPopupStyle = ref({});
    const showNewChatConfirm = ref(false);
    const toastMessage = ref('');
    const toastType = ref('success');
    const citationPanelWidth = ref(380);
    const citationResizing = ref(false);
    const imageViewerOpen = ref(false);
    const imageViewerImages = ref([]);
    const imageViewerIndex = ref(0);
    const imageViewerCitations = ref([]);
    const preferredImageCitation = ref(null);
    let toastTimer = null;

    const messageText = (html) => {
      const element = document.createElement('div');
      element.innerHTML = String(html || '');
      return element.textContent?.trim() || '';
    };

    const formatSourceTime = (value) => {
      if (!value) return '';
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return '';
      return new Intl.DateTimeFormat('ko-KR', { hour: 'numeric', minute: '2-digit' }).format(date);
    };

    // 2026.10.27(woojin.jung) 수정 - 답변 순번 대신 현재 참고 문서가 속한 직전 사용자 질문과 실제 시각을 컨텍스트로 제공
    const activeSourceContext = computed(() => {
      const messageIndex = chatView.messages.value.findIndex((message) => message.role === 'assistant' && message.citations === chatView.activeCitations.value);
      if (messageIndex < 0) return { messageIndex: -1, answerTime: '', question: '' };

      let question = '';
      for (let index = messageIndex - 1; index >= 0; index -= 1) {
        if (chatView.messages.value[index]?.role !== 'user') continue;
        question = messageText(chatView.messages.value[index].content);
        break;
      }

      const answerTime = formatSourceTime(chatView.messages.value[messageIndex]?.createdAt);
      return { messageIndex, answerTime, question };
    });

    const isSourceAnswer = (messageIndex) => {
      return chatView.sourcesPanelOpen.value && activeSourceContext.value.messageIndex === messageIndex;
    };

    const scrollToSourceAnswer = async () => {
      const messageIndex = activeSourceContext.value.messageIndex;
      if (messageIndex < 0) return;
      // 2026.11.03(woojin.jung) 수정 - 답변과 함께 직전 사용자 질문이 보이도록 질문 위치로 스크롤
      let targetIndex = messageIndex;
      for (let index = messageIndex - 1; index >= 0; index -= 1) {
        if (chatView.messages.value[index]?.role !== 'user') continue;
        targetIndex = index;
        break;
      }
      await nextTick();
      const messageElement = chatView.chatArea.value?.querySelector(`[data-message-index="${targetIndex}"]`);
      messageElement?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    // 2026.10.22(woojin.jung) 수정 - 이미지의 문서·컨텍스트 정보를 현재 답변의 인용 위치와 연결
    const findImageCitation = (image) => {
      if (!image) return null;
      if (preferredImageCitation.value) return preferredImageCitation.value;
      return (
        imageViewerCitations.value.find((citation) => String(citation.citation_id) === String(image.context_no) && citation.document_id === image.document_id) ||
        imageViewerCitations.value.find((citation) => citation.document_id === image.document_id && citation.sheet_name === image.sheet_name) ||
        null
      );
    };

    const currentImageCitation = computed(() => findImageCitation(imageViewerImages.value[imageViewerIndex.value]));

    // 2026.10.22(woojin.jung) 수정 - 답변 갤러리와 출처 패널이 공용 이미지 뷰어 상태를 사용하도록 통합
    const openImageViewer = (images, index = 0, citations = [], preferredCitation = null) => {
      if (!images?.length) return;
      imageViewerImages.value = images;
      imageViewerIndex.value = Math.min(Math.max(Number(index) || 0, 0), images.length - 1);
      imageViewerCitations.value = citations;
      preferredImageCitation.value = preferredCitation;
      imageViewerOpen.value = true;
    };

    const closeImageViewer = () => {
      imageViewerOpen.value = false;
    };

    const openCitationImages = ({ images, index, citation, citations }) => {
      openImageViewer(images, index, citations || [citation], citation);
    };

    // 2026.11.06(sooyeon.choi) 추가 - 답변 사진 "전체 N장 보기": 첫 사진의 출처 카드(없으면 사진이 연결된 첫 출처)를 선택해 출처 패널 열기
    const openImageSources = (message, image) => {
      const citations = message?.citations || [];
      const citation =
        citations.find((c) => String(c.citation_id) === String(image?.citation_id)) ||
        citations.find((c) => c.resource_ids?.length) ||
        citations[0];
      if (citation) chatView.openSourcesPanel(citation, citations);
    };

    const locateCurrentImage = () => {
      const citation = currentImageCitation.value;
      if (!citation) return;
      closeImageViewer();
      chatView.openSourcesPanel(citation, imageViewerCitations.value.length ? imageViewerCitations.value : [citation]);
    };

    const openAnswerImage = (messageIndex, imageIndex) => {
      const message = chatView.messages.value[messageIndex];
      if (!message?.images?.length) return;
      openImageViewer(message.images, imageIndex, message.citations || []);
    };

    const clampCitationWidth = (width) => {
      const containerWidth = mainContainerRef.value?.clientWidth || window.innerWidth;
      const maxWidth = Math.max(280, Math.min(720, containerWidth - 600));
      return Math.min(Math.max(width, 280), maxWidth);
    };

    const updateCitationWidth = (clientX) => {
      const containerRect = mainContainerRef.value?.getBoundingClientRect();
      const right = containerRect?.right || window.innerWidth;
      citationPanelWidth.value = clampCitationWidth(right - clientX);
    };

    const handleCitationResizeMove = (event) => {
      if (!citationResizing.value) return;
      updateCitationWidth(event.clientX);
    };

    const stopCitationResize = () => {
      if (!citationResizing.value) return;
      citationResizing.value = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    const startCitationResize = (event) => {
      citationResizing.value = true;
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      updateCitationWidth(event.clientX);
      event.preventDefault();
    };

    const updateModelSelectorPosition = () => {
      const wrapperEl = inputWrapperRef.value;
      const buttonEl = modelButtonRef.value;
      if (!wrapperEl || !buttonEl) return;

      const wrapperRect = wrapperEl.getBoundingClientRect();
      const buttonRect = buttonEl.getBoundingClientRect();
      modelSelectorPopupStyle.value = {
        left: `${buttonRect.left - wrapperRect.left}px`,
        bottom: `${wrapperRect.bottom - buttonRect.top + 8}px`,
      };
    };

    const toggleModelSelector = async () => {
      chatView.modelSelectorOpen.value = !chatView.modelSelectorOpen.value;
      if (chatView.modelSelectorOpen.value) {
        await nextTick();
        updateModelSelectorPosition();
      }
    };

    const requestNewChat = () => {
      if (chatView.isLoading.value || chatView.messages.value.length === 0) return;
      showNewChatConfirm.value = true;
    };

    const confirmNewChat = async () => {
      showNewChatConfirm.value = false;
      await chatView.newChat();
    };

    const messageToPlainText = (message) => {
      if (!message?.content) return '';
      const el = document.createElement('div');
      el.innerHTML = message.content;
      return el.innerText || el.textContent || '';
    };

    const copyText = async (text) => {
      if (!text) return;
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return;
      }

      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
    };

    const showToast = (message, type = 'success') => {
      toastMessage.value = message;
      toastType.value = type;
      if (toastTimer) window.clearTimeout(toastTimer);
      toastTimer = window.setTimeout(() => {
        toastMessage.value = '';
      }, 1800);
    };

    const formatVoiceDuration = (milliseconds = 0) => {
      const totalSeconds = Math.floor(milliseconds / 1000);
      const minutes = Math.floor(totalSeconds / 60);
      const seconds = totalSeconds % 60;
      return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    };

    const formatFileSize = (bytes = 0) => {
      if (bytes < 1024) return `${bytes} B`;
      if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
      return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    };

    const voiceDurationSeconds = computed(() => Math.max(0, voiceRecorder.elapsedMs.value / 1000));
    const voicePlaybackProgress = computed(() => {
      if (!voiceDurationSeconds.value) return 0;
      return Math.min(100, Math.max(0, (voicePlaybackTime.value / voiceDurationSeconds.value) * 100));
    });

    // 2026.10.15(woojin.jung) 수정 - 녹음 시간 기준 진행률 표시 및 첫 재생 위치 0초 초기화
    const resetVoicePlayback = () => {
      const audio = voiceAudioRef.value;
      if (audio) {
        audio.pause();
        try {
          audio.currentTime = 0;
        } catch {
          /* 메타데이터 로드 전에는 currentTime 설정을 무시 */
        }
      }
      voicePlaybackTime.value = 0;
      isVoicePlaying.value = false;
    };

    const handleVoiceAudioLoaded = () => {
      resetVoicePlayback();
    };

    const handleVoiceTimeUpdate = (event) => {
      const currentTime = Number(event.currentTarget.currentTime);
      if (!Number.isFinite(currentTime)) return;
      voicePlaybackTime.value = Math.min(voiceDurationSeconds.value || currentTime, Math.max(0, currentTime));
    };

    const handleVoiceAudioEnded = () => {
      isVoicePlaying.value = false;
      voicePlaybackTime.value = voiceDurationSeconds.value;
    };

    const handleVoiceAudioError = () => {
      if (!voiceRecorder.audioUrl.value) return;
      resetVoicePlayback();
      showToast('녹음 파일을 재생할 수 없습니다. 다시 녹음해 주세요.', 'error');
    };

    const toggleVoicePlayback = async () => {
      const audio = voiceAudioRef.value;
      if (!audio || !voiceRecorder.audioUrl.value) return;

      if (!audio.paused) {
        audio.pause();
        return;
      }

      if (audio.ended || !Number.isFinite(audio.currentTime) || voicePlaybackTime.value >= voiceDurationSeconds.value - 0.05) {
        try {
          audio.currentTime = 0;
        } catch {
          /* 메타데이터가 준비되지 않은 경우 play()가 0초부터 재생 */
        }
        voicePlaybackTime.value = 0;
      }

      try {
        await audio.play();
      } catch (error) {
        if (error?.name === 'AbortError') return;
        handleVoiceAudioError();
      }
    };

    const seekVoicePlayback = (event) => {
      const audio = voiceAudioRef.value;
      const targetTime = Math.min(voiceDurationSeconds.value, Math.max(0, Number(event.target.value)));
      if (!audio || !Number.isFinite(targetTime)) return;
      try {
        audio.currentTime = targetTime;
        voicePlaybackTime.value = targetTime;
      } catch {
        /* 브라우저가 탐색 가능한 상태가 될 때까지 현재 위치 유지 */
      }
    };

    // 2026.10.14(woojin.jung) 추가 - 마이크 버튼 클릭에 따른 녹음 시작·완료 상태 전환
    const toggleVoiceRecording = async () => {
      chatView.modelSelectorOpen.value = false;
      if (voiceRecorder.isRecording.value) {
        voiceRecorder.stopRecording();
        return;
      }
      await voiceRecorder.startRecording();
    };

    const dismissVoice = async () => {
      await voiceRecorder.dismiss();
    };

    // 2026.10.21(woojin.jung) 수정 - 편집한 음성 인식 결과를 채팅 입력창을 거치지 않고 즉시 질문 전송
    const submitVoiceQuestion = async () => {
      const text = voiceRecorder.transcript.value.trim();
      if (!text || chatView.isLoading.value || voiceRecorder.isTranscribing.value || isVoiceSubmitting.value) return;

      const originalText = voiceRecorder.originalTranscript.value.trim();
      const request = chatView.sendMessageStream({
        text,
        inputMode: 'voice',
        voiceTranscriptionId: voiceRecorder.transcriptionId.value,
        voiceEdited: text !== originalText,
      });

      if (!chatView.isLoading.value) {
        await request;
        return;
      }

      isVoiceSubmitting.value = true;
      await dismissVoice();
      try {
        await request;
      } finally {
        isVoiceSubmitting.value = false;
      }
    };

    // 2026.10.14(woojin.jung) 추가 - ESC 입력 시 녹음 취소 및 음성 패널 닫기
    const handleVoiceEscape = (event) => {
      if (event.key !== 'Escape' || voiceRecorder.state.value === 'idle') return;
      event.preventDefault();
      dismissVoice();
    };

    // 2026.10.14(woojin.jung) 추가 - 브라우저 탭 이탈 시 녹음 취소 및 장치 해제
    const handleVisibilityChange = () => {
      if (document.hidden && (voiceRecorder.isRecording.value || voiceRecorder.isRequesting.value)) voiceRecorder.cancelRecording();
    };

    const voiceButtonTitle = computed(() => {
      if (!voiceRecorder.isSupported.value) return '이 브라우저에서는 음성 입력을 사용할 수 없습니다.';
      if (voiceRecorder.isRequesting.value) return '마이크 연결 중...';
      if (voiceRecorder.isRecording.value) return '녹음 완료';
      return voiceRecorder.hasRecording.value ? '새로 녹음하기' : '음성으로 질문하기';
    });

    const copyMessage = async (message) => {
      try {
        await copyText(messageToPlainText(message));
        showToast('복사가 완료되었습니다.');
      } catch {
        showToast('복사에 실패했습니다.', 'error');
      }
    };

    const retryMessage = async (messageIndex) => {
      if (chatView.isLoading.value) return;
      const previousUserMessage = [...chatView.messages.value]
        .slice(0, messageIndex)
        .reverse()
        .find((message) => message.role === 'user');

      const text = messageToPlainText(previousUserMessage).trim();
      if (!text) return;

      if (previousUserMessage.inputMode === 'voice') {
        await chatView.sendMessageStream({
          text,
          inputMode: 'voice',
          voiceTranscriptionId: previousUserMessage.voiceTranscriptionId,
          voiceEdited: previousUserMessage.voiceEdited,
        });
        return;
      }

      // 2026.11.12(woojin.jung) 추가 - 시작 화면 질문을 다시 보낼 때도 입력 경로 유지 (많이 찾는 질문 집계 제외)
      if (previousUserMessage.inputMode === 'recommended' || previousUserMessage.inputMode === 'popular') {
        await chatView.sendStartQuestion(text, previousUserMessage.inputMode);
        return;
      }

      chatView.userInput.value = text;
      await nextTick();
      await chatView.sendMessageStream();
    };

    // 2026.06.24(woojin.jung) 수정 - 화면 상태 변경 대신 쿼리 로그 피드백 API 호출
    const setMessageFeedback = async (message, value) => {
      if (!message?.logId || message.feedbackPending) return;

      try {
        const feedback = await chatView.submitMessageFeedback(message, value);
        // 2026.11.05(woojin.jung) 수정 - 평가 저장 시 토스트 대신 사유·의견 패널을 연다
        message.feedbackPanel = feedback ? 'open' : null;
        if (!feedback) showToast('피드백이 취소되었습니다.');
      } catch (error) {
        const detail = error.response?.data?.detail || '피드백 저장에 실패했습니다.';
        showToast(detail, 'error');
      }
    };

    // 2026.11.05(woojin.jung) 추가 - 피드백 사유·의견 저장 후 완료 안내를 잠시 보여 주고 닫는다
    const submitFeedbackDetail = async (message, detail) => {
      try {
        await chatView.submitMessageFeedbackDetail(message, detail);
        message.feedbackPanel = 'done';
        setTimeout(() => {
          if (message.feedbackPanel === 'done') message.feedbackPanel = null;
        }, 2500);
      } catch (error) {
        showToast(error.response?.data?.detail || '의견 저장에 실패했습니다.', 'error');
      }
    };

    const feedbackSourceLabel = (citations) => {
      const groups = groupCitationsByDocument(citations || []);
      if (!groups.length) return '';
      return groups.length > 1 ? `${groups[0].filename} 외 ${groups.length - 1}건` : groups[0].filename;
    };

    const handleModelSelectorOutsideClick = (event) => {
      if (!chatView.modelSelectorOpen.value) return;

      const target = event.target;
      const popupEl = modelSelectorPopupRef.value;
      const buttonEl = modelButtonRef.value;
      if (popupEl?.contains(target) || buttonEl?.contains(target)) return;

      chatView.modelSelectorOpen.value = false;
    };

    watch(chatView.modelSelectorOpen, async (isOpen) => {
      if (!isOpen) return;
      await nextTick();
      updateModelSelectorPosition();
    });

    watch(voiceRecorder.autoStopped, (didAutoStop) => {
      if (didAutoStop) showToast('최대 60초까지 녹음할 수 있어 자동으로 종료했습니다.');
    });

    watch(voiceRecorder.audioUrl, async () => {
      resetVoicePlayback();
      await nextTick();
      voiceAudioRef.value?.load();
    });

    watch(chatView.selectedCollection, () => {
      if (voiceRecorder.state.value !== 'idle') voiceRecorder.cancelRecording();
      closeImageViewer();
    });

    onMounted(() => {
      // 2026.10.22(woojin.jung) 수정 - v-html로 렌더링된 [IMG:ref] 배지 클릭을 Vue 이미지 뷰어와 연결
      window.__openAnswerImage = openAnswerImage;
      window.addEventListener('resize', updateModelSelectorPosition);
      document.addEventListener('click', handleModelSelectorOutsideClick);
      document.addEventListener('mousemove', handleCitationResizeMove);
      document.addEventListener('mouseup', stopCitationResize);
      document.addEventListener('keydown', handleVoiceEscape);
      document.addEventListener('visibilitychange', handleVisibilityChange);
    });

    onBeforeUnmount(() => {
      delete window.__openAnswerImage;
      window.removeEventListener('resize', updateModelSelectorPosition);
      document.removeEventListener('click', handleModelSelectorOutsideClick);
      document.removeEventListener('mousemove', handleCitationResizeMove);
      document.removeEventListener('mouseup', stopCitationResize);
      document.removeEventListener('keydown', handleVoiceEscape);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      if (toastTimer) window.clearTimeout(toastTimer);
      stopCitationResize();
    });

    return {
      ...chatView,
      voiceState: voiceRecorder.state,
      // 2026.10.16(sooyeon.choi) 추가
      voiceTranscript: voiceRecorder.transcript,
      originalVoiceTranscript: voiceRecorder.originalTranscript,
      voiceTranscriptionId: voiceRecorder.transcriptionId,
      hasTranscription: voiceRecorder.hasTranscription,
      isTranscribing: voiceRecorder.isTranscribing,
      transcriptionError: voiceRecorder.transcriptionError,
      transcribeRecording: voiceRecorder.transcribeRecording,
      isVoiceSubmitting,
      submitVoiceQuestion,
      elapsedMs: voiceRecorder.elapsedMs,
      audioLevels: voiceRecorder.audioLevels,
      silenceDetected: voiceRecorder.silenceDetected,
      voiceErrorMessage: voiceRecorder.errorMessage,
      recordedFile: voiceRecorder.recordedFile,
      pendingVoiceFile: voiceRecorder.recordedFile,
      audioUrl: voiceRecorder.audioUrl,
      voiceAudioRef,
      voicePlaybackTime,
      voiceDurationSeconds,
      voicePlaybackProgress,
      isVoicePlaying,
      maxDurationMs: voiceRecorder.maxDurationMs,
      isVoiceSupported: voiceRecorder.isSupported,
      isVoiceRecording: voiceRecorder.isRecording,
      isVoiceRequesting: voiceRecorder.isRequesting,
      startRecording: voiceRecorder.startRecording,
      stopRecording: voiceRecorder.stopRecording,
      cancelRecording: voiceRecorder.cancelRecording,
      retryRecording: voiceRecorder.retryRecording,
      buildVoiceUploadFormData: voiceRecorder.buildUploadFormData,
      dismissVoice,
      toggleVoiceRecording,
      voiceButtonTitle,
      formatVoiceDuration,
      formatFileSize,
      handleVoiceAudioLoaded,
      handleVoiceTimeUpdate,
      handleVoiceAudioEnded,
      handleVoiceAudioError,
      toggleVoicePlayback,
      seekVoicePlayback,
      inputWrapperRef,
      mainContainerRef,
      modelButtonRef,
      modelSelectorPopupRef,
      modelSelectorPopupStyle,
      showNewChatConfirm,
      toastMessage,
      toastType,
      showToast,
      copyMessage,
      retryMessage,
      setMessageFeedback,
      submitFeedbackDetail,
      feedbackSourceLabel,
      citationPanelWidth,
      citationResizing,
      startCitationResize,
      toggleModelSelector,
      requestNewChat,
      confirmNewChat,
      imageViewerOpen,
      imageViewerImages,
      imageViewerIndex,
      currentImageCitation,
      openImageViewer,
      closeImageViewer,
      openCitationImages,
      openImageSources, // 2026.11.06(sooyeon.choi) 추가
      locateCurrentImage,
      citationDisplayPage,
      groupCitationsByDocument,
      activeSourceContext,
      isSourceAnswer,
      scrollToSourceAnswer,
    };
  },
};
</script>

<style scoped>
.app-layout {
  display: flex;
  height: 100dvh;
  background: #f3f4f6;
  overflow: hidden;
}
/* ── 메인 ── */
.main-container {
  display: flex;
  flex: 1;
  height: 100%;
  min-width: 0;
  min-height: 0;
}
.main-container.resizing {
  cursor: col-resize;
}
.main-container.resizing :deep(.sources-panel) {
  transition: none;
}
.chat-column {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #fff;
  position: relative;
  min-width: 0;
}
.citation-resizer {
  width: 8px;
  margin-left: -4px;
  margin-right: -4px;
  cursor: col-resize;
  flex-shrink: 0;
  position: relative;
  z-index: 2;
}
.citation-resizer::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 3px;
  width: 1px;
  background: #e2e8f0;
  transition:
    background 0.15s,
    width 0.15s;
}
.citation-resizer:hover::before,
.main-container.resizing .citation-resizer::before {
  left: 2px;
  width: 3px;
  background: #3b82f6;
}
.header-model {
  color: #64748b;
  font-size: 0.85rem;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex-shrink: 0;
}
.btn-reset-chat {
  height: 36px;
  border: 1px solid #dbe4f0;
  border-radius: 8px;
  background: #f8fafc;
  color: #334155;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 0 0.85rem;
  font-size: 0.88rem;
  font-weight: 600;
  white-space: nowrap;
  transition:
    background 0.15s,
    border-color 0.15s,
    color 0.15s;
}
.btn-reset-chat:hover:not(:disabled) {
  background: #eff6ff;
  border-color: #bfdbfe;
  color: #2563eb;
}
.btn-reset-chat:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  background: #22c55e;
  border-radius: 50%;
  flex-shrink: 0;
  vertical-align: middle;
}
.status-dot.offline {
  background: #ef4444;
}

/* 채팅 영역 */
.chat-scroll-area {
  flex: 1;
  padding: 2rem;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  padding-bottom: 180px;
}
.welcome {
  text-align: center;
  margin: auto;
  color: #64748b;
}
.welcome-icon {
  font-size: 2rem;
  margin-bottom: 1rem;
  color: #2563eb;
}
.welcome h2 {
  font-size: 1.5rem;
  color: #1e293b;
  margin-bottom: 0.5rem;
}
.message {
  display: flex;
  gap: 1rem;
  max-width: 85%;
}
.message.user {
  flex-direction: row-reverse;
  align-self: flex-end;
}
.message-body {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.35rem;
  min-width: 0;
  position: relative;
}
.message.assistant .message-body {
  border-radius: 12px;
  transition:
    outline-color 0.2s,
    box-shadow 0.2s;
}
/* 2026.10.26(woojin.jung) 수정 - 참고 문서 패널과 연결된 답변 영역을 채팅 화면에서 식별 가능하게 강조 */
.message.assistant.source-answer-active .message-body {
  outline: 2px solid #60a5fa;
  outline-offset: 7px;
  box-shadow: 0 0 0 8px rgba(219, 234, 254, 0.55);
}
.message.user .message-body {
  align-items: flex-end;
}
.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 0.85rem;
}
.avatar.assistant {
  background: #eff6ff;
  color: #3b82f6;
}
.avatar.user {
  background: #f1f5f9;
  color: #64748b;
}
.bubble {
  max-width: 100%;
  min-width: 0;
  padding: 1rem 1.25rem;
  border-radius: 12px;
  line-height: 1.7;
  font-size: 0.95rem;
  overflow-wrap: anywhere;
}
.message.assistant .bubble {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  color: #1e293b;
}
.message.user .bubble {
  background: #2563eb;
  color: white;
}
.voice-origin {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 9px;
  border: 1px solid #bfdbfe;
  border-radius: 999px;
  background: #eff6ff;
  color: #2563eb;
  font-size: 0.72rem;
}
.voice-origin .edited {
  color: #64748b;
}
/* 2026.11.12(woojin.jung) 추가 - 시작 화면 질문으로 보낸 질문 배지 */
.text-origin {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 9px;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  background: #f1f5f9;
  color: #64748b;
  font-size: 0.72rem;
}
/* 2026.11.12(woojin.jung) 추가 - 시작 화면: 추천 질문 + 많이 찾는 질문 */
.welcome.faq-welcome {
  width: 100%;
  max-width: 820px;
  padding-top: 1rem;
}
.faq-welcome .welcome-icon {
  width: 52px;
  height: 52px;
  margin: 0 auto 0.9rem;
  border-radius: 14px;
  background: #eff6ff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.4rem;
}
.faq-welcome > p {
  margin: 0 0 1.75rem;
  font-size: 0.92rem;
}
.faq-columns {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  text-align: left;
}
.faq-columns.single {
  grid-template-columns: minmax(0, 420px);
  justify-content: center;
}
.faq-group {
  min-width: 0;
  padding: 0.85rem;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #f8fafc;
}
.faq-group-head {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 0 0.15rem 0.6rem;
}
.faq-group-head i {
  font-size: 0.82rem;
}
.faq-group.registered .faq-group-head i {
  color: #2563eb;
}
.faq-group.popular .faq-group-head i {
  color: #ea580c;
}
.faq-group-head strong {
  font-size: 0.88rem;
  color: #1e293b;
}
.faq-group-head span {
  margin-left: auto;
  font-size: 0.72rem;
  color: #94a3b8;
}
.faq-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.faq-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 0.62rem 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
  background: #fff;
  color: #1e293b;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.15s,
    box-shadow 0.15s;
}
.faq-item:hover,
.faq-item:focus-visible {
  border-color: #bfdbfe;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.08);
  outline: none;
}
.faq-pin,
.faq-rank {
  width: 18px;
  flex-shrink: 0;
  text-align: center;
}
.faq-pin {
  font-size: 0.4rem;
  color: #93c5fd;
}
.faq-rank {
  font-size: 0.8rem;
  font-weight: 700;
  color: #ea580c;
}
.faq-q {
  flex: 1;
  min-width: 0;
  font-size: 0.86rem;
  line-height: 1.45;
}
.faq-cnt {
  flex-shrink: 0;
  font-size: 0.7rem;
  color: #94a3b8;
  font-variant-numeric: tabular-nums;
}
.faq-item .go {
  flex-shrink: 0;
  color: #cbd5e1;
  font-size: 0.75rem;
  transition:
    color 0.15s,
    transform 0.15s;
}
.faq-item:hover .go {
  color: #2563eb;
  transform: translateX(2px);
}
@media (max-width: 768px) {
  .faq-columns {
    grid-template-columns: 1fr;
  }
  .faq-welcome > p {
    margin-bottom: 1.25rem;
  }
}
.message-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  margin-top: 10px;
}
.user-actions {
  position: absolute;
  right: calc(100% - 8px);
  bottom: 4px;
  padding-right: 10px;
  margin-top: 0;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.2s;
}
.message.user:hover .user-actions {
  opacity: 1;
  pointer-events: auto;
}
.message-action-btn {
  width: 31px;
  height: 31px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.95rem;
  padding: 6px;
  transition:
    background 0.15s,
    color 0.15s;
}
.message-action-btn:hover:not(:disabled),
.message-action-btn.active {
  background: #f1f5f9;
  color: #475569;
}
.message-action-btn.like-active {
  background: #eff6ff;
  color: #2563eb;
}
.message-action-btn.dislike-active {
  background: #fef2f2;
  color: #dc2626;
}
.message-action-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.action-divider {
  width: 1px;
  height: 14px;
  background: #cbd5e1;
  margin: 0 4px;
}
:deep(.message.assistant .bubble p) {
  margin: 0.35rem 0;
}
:deep(.message.assistant .bubble p:first-child) {
  margin-top: 0;
}
:deep(.message.assistant .bubble p:last-child) {
  margin-bottom: 0;
}
:deep(.message.assistant .bubble ul),
:deep(.message.assistant .bubble ol) {
  margin: 0.5rem 0;
  padding-left: 1.4rem;
}
:deep(.message.assistant .bubble li) {
  margin: 0.25rem 0;
}
:deep(.message.assistant .bubble pre) {
  margin: 0.75rem 0;
  padding: 0.85rem 1rem;
  overflow-x: auto;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
  line-height: 1.55;
}
:deep(.message.assistant .bubble code) {
  font-family: Consolas, Monaco, 'Courier New', monospace;
  font-size: 0.88em;
}
:deep(.message.assistant .bubble :not(pre) > code) {
  padding: 0.12rem 0.32rem;
  border-radius: 4px;
  background: #e2e8f0;
  color: #0f172a;
}
:deep(.message.assistant .bubble blockquote) {
  margin: 0.75rem 0;
  padding-left: 0.9rem;
  border-left: 3px solid #cbd5e1;
  color: #475569;
}
/* 넓은 표는 말풍선 안에서 가로 스크롤 */
:deep(.message.assistant .bubble table) {
  display: block;
  max-width: 100%;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  margin: 0.75rem 0;
  border-collapse: collapse;
  font-size: 0.9rem;
}
:deep(.message.assistant .bubble th),
:deep(.message.assistant .bubble td) {
  min-width: 4.5em;
  overflow-wrap: normal;
  word-break: keep-all;
  border: 1px solid #cbd5e1;
  padding: 0.45rem 0.55rem;
  text-align: left;
}
:deep(.message.assistant .bubble th) {
  background: #f1f5f9;
  font-weight: 700;
}
:deep(.message.assistant .bubble a) {
  color: #2563eb;
  text-decoration: underline;
}
.loading-bubble {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 1rem 1.5rem;
}
.loading-text {
  color: #64748b;
  font-size: 0.92rem;
  font-weight: 500;
}
.stage-bubble {
  min-width: 256px;
  padding: 0.9rem 1.25rem;
  border-radius: 14px;
  background: #f8fafc;
  border: 1px solid #dbe4f0;
  color: #334155;
  display: flex;
  align-items: center;
  gap: 12px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
}
.stage-bubble.generating {
  background: #f8fffb;
  border-color: #bbf7d0;
}
.stage-icon {
  color: #3b82f6;
  font-size: 1.1rem;
  flex-shrink: 0;
  animation: spin 1.1s linear infinite;
}
.stage-bubble.generating .stage-icon {
  color: #22c55e;
}
.stage-text {
  color: #334155;
  font-size: 0.98rem;
  font-weight: 700;
  line-height: 1.35;
}
.stage-bubble.generating .stage-text {
  color: #15803d;
}
.stage-sub {
  margin-top: 4px;
  color: #64748b;
  font-size: 0.86rem;
  line-height: 1.35;
}
.dot {
  width: 8px;
  height: 8px;
  background: #94a3b8;
  border-radius: 50%;
  animation: bounce 1.4s infinite ease-in-out both;
}
.dot:nth-child(1) {
  animation-delay: -0.32s;
}
.dot:nth-child(2) {
  animation-delay: -0.16s;
}
@keyframes bounce {
  0%,
  80%,
  100% {
    transform: scale(0);
  }
  40% {
    transform: scale(1);
  }
}

/* 입력 영역 */
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
.input-wrapper {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 1.5rem;
  background: linear-gradient(to top, #fff 80%, transparent);
  display: flex;
  flex-direction: column;
  align-items: center;
}
.collection-notice {
  width: 100%;
  max-width: 700px;
  font-size: 0.82rem;
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 0.5rem;
  padding: 0.4rem 0.75rem;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
}
.collection-notice.error {
  color: #dc2626;
  background: #fef2f2;
  border-color: #fecaca;
}

.chat-scroll-area.has-voice-panel {
  padding-bottom: 300px;
}
.voice-preview {
  width: 100%;
  max-width: 700px;
  margin-bottom: 0.65rem;
  padding: 0.75rem 0.9rem;
  border: 1px solid #bfdbfe;
  border-radius: 14px;
  background: #eff6ff;
  color: #1e3a8a;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.08);
}
.voice-preview.recording {
  border-color: #fecaca;
  background: #fff7f7;
  color: #b91c1c;
}
.voice-preview.requesting {
  border-color: #bfdbfe;
  background: #f8fbff;
  color: #2563eb;
}
.voice-preview.requesting .voice-preview-icon {
  background: #dbeafe;
  color: #2563eb;
}
.voice-preview.ready {
  position: relative;
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr);
  align-items: start;
  column-gap: 0.75rem;
  row-gap: 0;
  padding: 0.9rem 3.4rem 0.85rem 0.9rem;
}
.voice-preview.ready .voice-preview-icon {
  grid-column: 1;
  grid-row: 1;
}
.voice-preview.ready .voice-preview-content {
  grid-column: 2;
  grid-row: 1;
  width: 100%;
  gap: 0.35rem;
}
.voice-preview.ready .voice-preview-actions {
  grid-column: 2;
  grid-row: 2;
  width: 100%;
  margin-top: 0.65rem;
  padding-top: 0.65rem;
  border-top: 1px solid #dbeafe;
  justify-content: flex-end;
}
.voice-preview.error {
  border-color: #fed7aa;
  background: #fffaf5;
  color: #c2410c;
}
.voice-preview-icon {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: #dbeafe;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.voice-preview.recording .voice-preview-icon {
  background: #fee2e2;
  animation: voice-pulse 1.4s ease-in-out infinite;
}
.voice-preview-icon.ready-icon {
  background: #dcfce7;
  color: #15803d;
}
.voice-preview-icon.error-icon {
  background: #ffedd5;
  color: #c2410c;
}
.voice-preview-content {
  min-width: 0;
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 0.18rem;
  font-size: 0.82rem;
}
.voice-preview-content strong {
  color: #1e293b;
  font-size: 0.88rem;
}
.voice-preview.recording .voice-preview-content strong {
  color: #991b1b;
}
.voice-preview-content strong em {
  margin-left: 0.35rem;
  padding: 0.12rem 0.4rem;
  border-radius: 999px;
  background: #dcfce7;
  color: #15803d;
  font-size: 0.68rem;
  font-style: normal;
  font-weight: 700;
}
.voice-preview-content > span {
  overflow: hidden;
  color: #64748b;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.voice-warning {
  color: #dc2626 !important;
}
.voice-preview-actions {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-shrink: 0;
}
.voice-control-btn,
.voice-close-btn {
  min-height: 34px;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  background: #fff;
  color: #2563eb;
  cursor: pointer;
  font-size: 0.78rem;
  font-weight: 600;
  padding: 0.42rem 0.6rem;
  white-space: nowrap;
}
.voice-control-btn:hover,
.voice-close-btn:hover {
  background: #f8fafc;
}
.voice-control-btn.stop {
  border-color: #fecaca;
  color: #dc2626;
}
.voice-control-btn.send {
  border-color: #2563eb;
  background: #2563eb;
  color: #fff;
}
.voice-control-btn.send:hover:not(:disabled) {
  background: #1d4ed8;
}
.voice-control-btn:disabled,
.voice-close-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.voice-close-btn {
  width: 34px;
  border-color: transparent;
  color: #64748b;
  padding: 0.42rem;
}
.voice-panel-close {
  position: absolute;
  top: 0.65rem;
  right: 0.65rem;
  z-index: 1;
}
.voice-timer {
  min-height: 22px;
  display: flex;
  align-items: center;
  gap: 7px;
  color: #64748b;
  font-variant-numeric: tabular-nums;
}
.voice-timer b {
  color: #b91c1c;
}
.voice-level {
  height: 20px;
  display: flex;
  align-items: center;
  gap: 3px;
}
.voice-level i {
  width: 4px;
  border-radius: 3px;
  background: #dc2626;
  transition: height 0.1s ease;
}
.voice-audio-element {
  display: none;
}
/* 2026.10.16(sooyeon.choi) 추가 */
.voice-transcript-input {
  width: 100%;
  box-sizing: border-box;
  padding: 8px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font: inherit;
  resize: vertical;
}
.voice-submit-hint {
  margin-top: 2px;
  color: #94a3b8 !important;
  font-size: 0.72rem;
}
.voice-audio-player {
  width: min(100%, 390px);
  min-height: 34px;
  margin-top: 0.3rem;
  padding: 0.25rem 0.45rem;
  border: 1px solid #bfdbfe;
  border-radius: 9px;
  background: #fff;
  display: flex;
  align-items: center;
  gap: 0.55rem;
}
.voice-play-btn {
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: #2563eb;
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  cursor: pointer;
  font-size: 0.72rem;
}
.voice-play-btn:hover:not(:disabled) {
  background: #1d4ed8;
}
.voice-play-btn:focus-visible {
  outline: 3px solid rgba(37, 99, 235, 0.25);
  outline-offset: 2px;
}
.voice-play-btn:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}
.voice-progress {
  --voice-progress: 0%;
  flex: 1;
  min-width: 80px;
  height: 4px;
  margin: 0;
  border-radius: 999px;
  background: linear-gradient(to right, #2563eb 0%, #2563eb var(--voice-progress), #dbeafe var(--voice-progress), #dbeafe 100%);
  appearance: none;
  cursor: pointer;
}
.voice-progress::-webkit-slider-runnable-track {
  height: 4px;
  border-radius: 999px;
  background: transparent;
}
.voice-progress::-webkit-slider-thumb {
  width: 12px;
  height: 12px;
  margin-top: -4px;
  border: 2px solid #fff;
  border-radius: 50%;
  background: #2563eb;
  box-shadow: 0 0 0 1px #2563eb;
  appearance: none;
}
.voice-progress::-moz-range-track {
  height: 4px;
  border-radius: 999px;
  background: #dbeafe;
}
.voice-progress::-moz-range-progress {
  height: 4px;
  border-radius: 999px;
  background: #2563eb;
}
.voice-progress::-moz-range-thumb {
  width: 10px;
  height: 10px;
  border: 2px solid #fff;
  border-radius: 50%;
  background: #2563eb;
  box-shadow: 0 0 0 1px #2563eb;
}
.voice-playback-time {
  color: #64748b !important;
  font-size: 0.72rem;
  font-variant-numeric: tabular-nums;
  white-space: nowrap !important;
}
@keyframes voice-pulse {
  50% {
    transform: scale(1.08);
  }
}

/* 모델 선택 팝업 */
.model-selector-popup {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 1.5rem;
  z-index: 100;
}
.model-selector-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  padding: 0.5rem;
  min-width: 240px;
}
.model-selector-title {
  font-size: 0.72rem;
  font-weight: 700;
  color: #94a3b8;
  letter-spacing: 0.08em;
  padding: 0.4rem 0.75rem;
  text-transform: uppercase;
}
.model-loading {
  font-size: 0.85rem;
  color: #94a3b8;
  padding: 0.6rem 0.75rem;
}
.model-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.6rem 0.75rem;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.9rem;
  color: #334155;
  transition: background 0.15s;
}
.model-option:hover {
  background: #f8fafc;
}
.model-option.active {
  background: #eff6ff;
  color: #2563eb;
  font-weight: 600;
}
.model-check {
  font-size: 0.8rem;
  color: #2563eb;
}

/* API 키 섹션 */
.model-api-key-section {
  border-top: 1px solid #e2e8f0;
  margin-top: 0.4rem;
  padding: 0.6rem 0.75rem 0.5rem;
}
.api-key-label {
  font-size: 0.75rem;
  color: #64748b;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.4rem;
}
.api-key-saved-badge {
  font-size: 0.7rem;
  color: #22c55e;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 3px;
}
.api-key-input-row {
  display: flex;
  gap: 6px;
}
.api-key-input {
  flex: 1;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 0.45rem 0.6rem;
  font-size: 0.82rem;
  color: #334155;
  outline: none;
}
.api-key-input:focus {
  border-color: #2563eb;
}
.api-key-save-btn {
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 8px;
  padding: 0.45rem 0.75rem;
  font-size: 0.8rem;
  cursor: pointer;
  white-space: nowrap;
}
.api-key-save-btn:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}
.api-key-change-btn {
  width: 100%;
  background: #f1f5f9;
  color: #64748b;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 0.4rem;
  font-size: 0.8rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}
.api-key-change-btn:hover {
  background: #e2e8f0;
}

/* 입력 바 */
.input-bar {
  width: 100%;
  max-width: 700px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 24px;
  padding: 0.75rem 1rem;
  display: flex;
  align-items: center;
  gap: 10px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}
.input-bar input {
  flex: 1;
  border: none;
  outline: none;
  font-size: 1rem;
  color: #334155;
  background: transparent;
  min-width: 0;
}
.icon-btn.voice-btn {
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid #bfdbfe;
  flex-shrink: 0;
}
.icon-btn.voice-btn:hover:not(:disabled) {
  background: #dbeafe;
}
.icon-btn.voice-btn.recording {
  background: #ef4444;
  border-color: #ef4444;
  color: #fff;
}
.icon-btn.voice-btn.requesting,
.icon-btn.voice-btn.requesting:disabled {
  border-color: #bfdbfe;
  background: #dbeafe;
  color: #2563eb;
  opacity: 1;
}
.icon-btn {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.icon-btn.send {
  background: #2563eb;
  color: white;
}
.icon-btn.stop {
  background: #ef4444;
  color: white;
}
.icon-btn.send:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}
.icon-btn.model-btn {
  background: #f1f5f9;
  color: #64748b;
  border: 1px solid #e2e8f0;
  flex-shrink: 0;
}
.icon-btn.model-btn:hover {
  background: #e2e8f0;
}
.input-hint {
  font-size: 0.75rem;
  color: #94a3b8;
  margin-top: 0.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  flex-wrap: wrap;
}
.selected-model-badge {
  color: #2563eb;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 4px;
}

/* 참고 문서 */
.reference-section {
  margin-top: 1.5rem;
  border-top: 1px solid #e2e8f0;
  padding-top: 1rem;
  font-size: 0.9rem;
}
.ref-title {
  font-weight: 600;
  margin-bottom: 0.5rem;
  color: #475569;
  font-size: 0.85rem;
}
.ref-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px;
  border-radius: 6px;
  color: #334155;
  transition: all 0.2s;
  margin-bottom: 4px;
}
.ref-item:hover {
  background: #eff6ff;
}
/* .ref-item.active {
  background: #dbeafe;
  color: #1d4ed8;
  font-weight: 600;
} */
.ref-filename {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ref-pages {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 5px;
}
.ref-page {
  min-width: 38px;
  padding: 3px 7px;
  border: 1px solid #bfdbfe;
  border-radius: 999px;
  color: #2563eb;
  background: #fff;
  font: inherit;
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.15s;
}
.ref-page:hover,
.ref-page.active {
  border-color: #2563eb;
  color: #fff;
  background: #2563eb;
}
:deep(.inline-citation) {
  color: #2563eb;
  font-weight: 600;
  font-size: 0.75rem;
  vertical-align: super;
  cursor: pointer;
  text-decoration: none;
  margin-left: 2px;
  background-color: #dbeafe;
  padding: 1px 4px;
  border-radius: 4px;
}
:deep(.inline-citation.pending) {
  cursor: default;
  opacity: 0.75;
}
:deep(.image-ref) {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-left: 3px;
  padding: 1px 6px;
  border: 0;
  border-radius: 4px;
  background: #dbeafe;
  color: #2563eb;
  font: inherit;
  font-size: 0.72rem;
  font-weight: 700;
  line-height: 1.5;
  vertical-align: middle;
  cursor: zoom-in;
  margin-bottom: 0.8rem;
}
:deep(.image-ref:hover) {
  background: #bfdbfe;
  color: #1d4ed8;
}
:deep(.image-ref.pending) {
  cursor: default;
  opacity: 0.65;
}
/* :deep(.inline-citation.active) {
  color: #1d4ed8;
  background-color: #bfdbfe;
  box-shadow: 0 0 0 1px #60a5fa inset;
} */

/* 모달 */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
}
.modal-card {
  background: white;
  border-radius: 16px;
  padding: 2rem 2.5rem;
  max-width: 360px;
  width: 90%;
  text-align: center;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.25);
}
.modal-icon {
  font-size: 2rem;
  color: #ef4444;
  margin-bottom: 1rem;
}
.modal-icon.warning {
  color: #f59e0b;
}
.modal-card h3 {
  font-size: 1.1rem;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 0.5rem;
}
.modal-card p {
  font-size: 0.9rem;
  color: #64748b;
  margin-bottom: 1.5rem;
  line-height: 1.6;
  word-break: keep-all; /* 2026.11.23(woojin.jung) 추가 - "있습/니다"처럼 단어 중간에서 줄이 바뀌지 않게 */
}
.modal-confirm-btn {
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 8px;
  padding: 0.65rem 1.6rem;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
}
.modal-confirm-btn:hover {
  background: #1d4ed8;
}
.modal-actions {
  display: flex;
  justify-content: center;
  gap: 10px;
}
.modal-cancel-btn {
  background: #f8fafc;
  color: #475569;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 0.65rem 1.4rem;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
}
.modal-cancel-btn:hover {
  background: #f1f5f9;
}
.modal-confirm-btn.danger {
  background: #dc2626;
}
.modal-confirm-btn.danger:hover {
  background: #b91c1c;
}

/* 반응형 */
@media (max-width: 768px) {
  .chat-scroll-area {
    padding: 1rem;
    padding-bottom: 200px;
  }
  .chat-scroll-area.has-voice-panel {
    padding-bottom: 360px;
  }
  .message {
    max-width: 95%;
  }
  .input-wrapper {
    padding: 1rem;
  }
  .voice-preview {
    align-items: flex-start;
    flex-wrap: wrap;
  }
  .voice-preview-content {
    flex-basis: calc(100% - 52px);
  }
  .voice-preview-actions {
    width: 100%;
    justify-content: flex-end;
  }
  .voice-preview.ready {
    grid-template-columns: 36px minmax(0, 1fr);
    padding: 0.85rem 3.2rem 0.8rem 0.8rem;
  }
  .voice-preview.ready .voice-preview-content {
    flex-basis: auto;
  }
  .voice-preview.ready .voice-preview-actions {
    grid-column: 1 / -1;
    flex-wrap: wrap;
  }
  .voice-preview-content > span {
    white-space: normal;
  }
  .header-model {
    display: none;
  }
}

/* 2026.11.02(woojin.jung) 수정 - 반응형(태블릿/모바일) 대응 */
/* 2026.11.03(woojin.jung) 수정 - 태블릿 가로는 데스크톱, 세로는 모바일 레이아웃(사이드바 숨김) */
@media (max-width: 768px), (max-width: 1024px) and (orientation: portrait), (max-width: 1024px) and (max-height: 500px) {
  /* 모바일 레이아웃에서는 참고 문서 패널이 하단 시트로 열리므로 폭 조절 핸들 제거 */
  .citation-resizer {
    display: none;
  }
}
@media (max-width: 768px) {
  .message {
    gap: 0.6rem;
  }
  .avatar {
    width: 30px;
    height: 30px;
    font-size: 0.75rem;
  }
  .bubble {
    padding: 0.8rem 0.95rem;
  }
  .stage-bubble {
    min-width: 0;
  }
  .message.assistant.source-answer-active .message-body {
    outline-offset: 3px;
    box-shadow: 0 0 0 4px rgba(219, 234, 254, 0.55);
  }
  .ref-item {
    flex-wrap: wrap;
    gap: 6px;
  }
  .ref-filename {
    flex-basis: 100%;
  }
  .ref-pages {
    justify-content: flex-start;
  }
  .message-action-btn {
    width: 36px;
    height: 36px;
  }
  .input-hint {
    font-size: 0.7rem;
    line-height: 1.4;
    text-align: center;
  }
}
@media (max-width: 480px) {
  .btn-reset-chat {
    width: 36px;
    padding: 0;
  }
  .btn-reset-chat span {
    display: none;
  }
}
</style>
