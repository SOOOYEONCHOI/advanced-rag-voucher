<template>
  <div class="settings-layout">
    <AdminSidebar :isOpen="sidebarOpen" activePage="ui-integration" :isAdmin="false" :displayName="authStore.displayName" @close="sidebarOpen = false" @logout="logout" />

    <main class="settings-main">
      <PageHeader
        title="UI 연동 방식"
        :description="isConfigured ? '선택한 연동 방식과 적용 가이드를 확인하세요.' : '계정에서 사용할 챗봇 연동 방식을 선택하세요.'"
        @openSidebar="sidebarOpen = true"
      />

      <div class="settings-scroll">
        <div class="settings-content">
          <section class="intro-card">
            <div>
              <span class="eyebrow">MY EXPERIENCE</span>
              <h2>{{ isConfigured ? '선택한 UI 연동 방식' : '챗봇을 어디에서 사용할까요?' }}</h2>
              <p>{{ isConfigured ? '이 계정의 연동 방식은 최초 선택으로 확정되어 변경할 수 없습니다.' : '최초 한 번만 선택할 수 있으며, 확정한 뒤에는 변경할 수 없습니다.' }}</p>
            </div>
            <div v-if="isConfigured" class="current-badge">
              <span>선택 완료</span>
              <strong>{{ currentOption?.shortTitle }}</strong>
            </div>
          </section>

          <div v-if="loadError" class="notice error" role="alert">
            <i class="fa-solid fa-circle-exclamation"></i>
            {{ loadError }}
            <button type="button" @click="loadProfile">다시 시도</button>
          </div>

          <section v-if="profileLoaded && !isConfigured" class="option-grid" aria-label="UI 연동 방식 선택">
            <label v-for="option in UI_TYPE_OPTIONS" :key="option.value" class="option-card" :class="[option.accent, { selected: selectedUiType === option.value }]">
              <input v-model="selectedUiType" type="radio" name="ui-type" :value="option.value" :disabled="loading || saving" />
              <span class="selection-mark" aria-hidden="true"><i class="fa-solid fa-check"></i></span>
              <span class="option-number">{{ option.number }}</span>
              <span class="option-icon"><i :class="option.icon"></i></span>
              <strong>{{ option.title }}</strong>
              <span class="option-description">{{ option.description }}</span>
              <span class="option-detail">{{ option.detail }}</span>
              <span class="option-preview" aria-hidden="true">
                <span class="preview-sidebar"></span>
                <span class="preview-content"><span></span><span></span><span></span></span>
                <span v-if="option.value === 'layout_linked'" class="preview-widget"><i class="fa-solid fa-comment-dots"></i></span>
                <span v-if="option.value === 'menu_linked'" class="preview-menu-dot"></span>
              </span>
            </label>
          </section>

          <section v-else-if="currentOption" class="locked-option-card" :class="currentOption.accent" aria-label="선택한 UI 연동 방식">
            <span class="locked-icon"><i :class="currentOption.icon"></i></span>
            <div>
              <span class="locked-label"><i class="fa-solid fa-lock"></i> 최초 선택 완료</span>
              <h2>{{ currentOption.title }}</h2>
              <p>{{ currentOption.description }}</p>
              <span>{{ currentOption.detail }}</span>
            </div>
          </section>

          <section v-if="profileLoaded && !isConfigured" class="save-bar">
            <div class="change-summary">
              <i class="fa-solid fa-circle-info"></i>
              <span>{{ selectedOption ? `${selectedOption.title}(으)로 확정합니다. 확정 후에는 변경할 수 없습니다.` : '연동 방식을 선택해주세요.' }}</span>
            </div>
            <div class="save-actions">
              <button class="save-button" type="button" :disabled="!selectedUiType || loading || saving" @click="openConfirmModal">
                <i :class="saving ? 'fa-solid fa-circle-notch fa-spin' : 'fa-solid fa-lock'"></i>
                {{ saving ? '확정 중...' : '선택 확정' }}
              </button>
            </div>
          </section>

          <section v-if="isConfigured && savedUiType === 'standalone'" class="integration-guide" aria-labelledby="standalone-guide-title">
            <div class="guide-head">
              <div class="guide-title-area">
                <span class="guide-badge"><i class="fa-solid fa-window-maximize"></i> 단독형 서비스</span>
                <h2 id="standalone-guide-title">새 창 호출 연동 가이드</h2>
                <p>고객 솔루션에서 아래 URL을 호출하면 독립된 Ad RAG 챗봇 화면이 새 창 또는 새 탭으로 열립니다.</p>
              </div>
              <button class="preview-button" type="button" @click="openStandalonePreview">
                <i class="fa-solid fa-arrow-up-right-from-square"></i>
                새 창 동작 확인
              </button>
            </div>

            <div class="ownership-notice">
              <i class="fa-solid fa-circle-info"></i>
              <div>
                <strong>호출 UI는 고객사가 결정합니다.</strong>
                <span>버튼, 메뉴, 아이콘의 명칭과 위치는 고객 솔루션에 맞게 구성하고, 아래 URL 또는 예시 코드만 연결하세요.</span>
              </div>
            </div>

            <ol class="guide-steps" aria-label="단독형 서비스 적용 순서">
              <li>
                <span class="step-number">1</span>
                <div><strong>서비스 URL 확인</strong><span>운영 환경의 챗봇 주소를 확인합니다.</span></div>
              </li>
              <li>
                <span class="step-number">2</span>
                <div><strong>고객 UI 선택</strong><span>메뉴, 버튼 등 호출 위치를 결정합니다.</span></div>
              </li>
              <li>
                <span class="step-number">3</span>
                <div><strong>새 창으로 연결</strong><span>아래 예시를 적용하고 동작을 확인합니다.</span></div>
              </li>
            </ol>

            <div class="guide-grid">
              <article class="guide-card url-card">
                <div class="guide-card-head">
                  <div>
                    <span class="guide-card-label">SERVICE URL</span>
                    <h3>챗봇 접속 주소</h3>
                  </div>
                  <span class="environment-badge">제공 주소</span>
                </div>
                <div class="url-box">
                  <code>{{ standaloneUrl }}</code>
                  <button type="button" aria-label="서비스 URL 복사" title="URL 복사" @click="copyGuideText(standaloneUrl, '서비스 URL')">
                    <i class="fa-regular fa-copy"></i>
                  </button>
                </div>
                <p class="card-hint"><i class="fa-solid fa-lock"></i> 접속 후 현재 시스템의 로그인 및 사용자 권한 정책이 적용됩니다.</p>
              </article>

              <article class="guide-card code-card">
                <div class="guide-card-head code-head">
                  <div>
                    <span class="guide-card-label">IMPLEMENTATION</span>
                    <h3>호출 코드 예시</h3>
                  </div>
                  <button class="code-copy-button" type="button" @click="copyGuideText(activeGuideCode, `${activeGuideLabel} 예시 코드`)">
                    <i class="fa-regular fa-copy"></i>
                    코드 복사
                  </button>
                </div>
                <div class="code-tabs" role="tablist" aria-label="호출 코드 종류">
                  <button
                    v-for="tab in guideTabs"
                    :key="tab.value"
                    type="button"
                    role="tab"
                    :aria-selected="activeGuideTab === tab.value"
                    :class="{ active: activeGuideTab === tab.value }"
                    @click="activeGuideTab = tab.value"
                  >
                    {{ tab.label }}
                  </button>
                </div>
                <pre class="code-block"><code>{{ activeGuideCode }}</code></pre>
              </article>
            </div>

            <div class="guide-checklist">
              <div class="checklist-title"><i class="fa-solid fa-list-check"></i> 적용 전 확인사항</div>
              <ul>
                <li><i class="fa-solid fa-check"></i> 새 창 호출은 반드시 사용자의 클릭 이벤트 안에서 실행하세요.</li>
                <li><i class="fa-solid fa-check"></i> HTML 방식은 보안을 위해 <code>rel="noopener noreferrer"</code>를 함께 적용하세요.</li>
                <li><i class="fa-solid fa-check"></i> 운영 도메인이 변경되면 서비스 URL도 운영 주소로 교체하세요.</li>
              </ul>
            </div>
          </section>

          <section v-if="isConfigured && savedUiType === 'menu_linked'" class="integration-guide" aria-labelledby="menu-guide-title">
            <div class="guide-head">
              <div class="guide-title-area">
                <span class="guide-badge violet"><i class="fa-solid fa-bars-staggered"></i> 기존 솔루션 메뉴 연계</span>
                <h2 id="menu-guide-title">메뉴 연동 가이드</h2>
                <p>기존 업무 솔루션의 메뉴에 챗봇 접속 주소를 연결해 사용자가 같은 내비게이션 흐름에서 챗봇을 실행하도록 구성합니다.</p>
              </div>
            </div>
            <ol class="guide-steps" aria-label="메뉴 연계 적용 순서">
              <li>
                <span class="step-number">1</span>
                <div><strong>메뉴 항목 생성</strong><span>업무 솔루션에 AI 챗봇 메뉴를 추가합니다.</span></div>
              </li>
              <li>
                <span class="step-number">2</span>
                <div><strong>접속 주소 연결</strong><span>메뉴 클릭 시 아래 서비스 URL로 이동하도록 설정합니다.</span></div>
              </li>
              <li>
                <span class="step-number">3</span>
                <div><strong>인증 및 권한 확인</strong><span>로그인과 사용자별 접근 권한이 정상 적용되는지 확인합니다.</span></div>
              </li>
            </ol>
            <article class="guide-card url-card compact-guide-card">
              <div class="guide-card-head">
                <div>
                  <span class="guide-card-label">MENU TARGET URL</span>
                  <h3>메뉴 연결 주소</h3>
                </div>
              </div>
              <div class="url-box">
                <code>{{ standaloneUrl }}</code
                ><button type="button" aria-label="메뉴 연결 URL 복사" title="URL 복사" @click="copyGuideText(standaloneUrl, '메뉴 연결 URL')"><i class="fa-regular fa-copy"></i></button>
              </div>
              <pre class="code-block"><code>{{ guideExamples.menu }}</code></pre>
            </article>
          </section>

          <section v-if="isConfigured && savedUiType === 'layout_linked'" class="integration-guide" aria-labelledby="layout-guide-title">
            <div class="guide-head">
              <div class="guide-title-area">
                <span class="guide-badge teal"><i class="fa-solid fa-table-columns"></i> 화면 내 위젯 연계</span>
                <h2 id="layout-guide-title">위젯(레이아웃) 연동 가이드</h2>
                <p>고객사 페이지에 위젯 스크립트를 추가하면 우측 하단에 챗봇 실행 버튼이 표시됩니다. 별도의 iframe이나 마운트 영역은 필요하지 않습니다.</p>
              </div>
            </div>

            <div class="ownership-notice widget-notice">
              <i class="fa-solid fa-circle-info"></i>
              <div>
                <strong>레이아웃 위젯 전용 계정을 사용하세요.</strong>
                <span>전달한 계정의 UI 연동 방식이 <code>위젯(레이아웃)</code>인 경우에만 인증되며, 다른 연동 방식의 계정은 위젯을 사용할 수 없습니다.</span>
              </div>
            </div>

            <ol class="guide-steps" aria-label="레이아웃 위젯 적용 순서">
              <li>
                <span class="step-number">1</span>
                <div><strong>전용 계정 준비</strong><span>UI 연동 방식이 위젯(레이아웃)인 계정 정보를 준비합니다.</span></div>
              </li>
              <li>
                <span class="step-number">2</span>
                <div><strong>스크립트 로드</strong><span>고객사 페이지에 아래 adrag.js 파일을 한 번만 추가합니다.</span></div>
              </li>
              <li>
                <span class="step-number">3</span>
                <div><strong>위젯 초기화</strong><span>계정 정보와 챗봇 이름을 전달해 createChatbot을 호출합니다.</span></div>
              </li>
            </ol>

            <article class="guide-card url-card widget-script-card">
              <div class="guide-card-head">
                <div>
                  <span class="guide-card-label">WIDGET SCRIPT</span>
                  <h3>위젯 스크립트 주소</h3>
                </div>
                <span class="environment-badge">운영 서버</span>
              </div>
              <div class="url-box">
                <code>{{ widgetScriptUrl }}</code>
                <button type="button" aria-label="위젯 스크립트 URL 복사" title="URL 복사" @click="copyGuideText(widgetScriptUrl, '위젯 스크립트 URL')"><i class="fa-regular fa-copy"></i></button>
              </div>
              <p class="card-hint"><i class="fa-solid fa-code"></i> 위젯은 Shadow DOM에 렌더링되어 고객사 페이지의 CSS와 독립적으로 동작합니다.</p>
            </article>

            <div class="widget-guide-grid">
              <article class="guide-card code-card">
                <div class="guide-card-head code-head">
                  <div>
                    <span class="guide-card-label">QUICK START</span>
                    <h3>전체 연동 코드</h3>
                  </div>
                  <button class="code-copy-button" type="button" @click="copyGuideText(widgetGuideCode, '위젯 연동 코드')">
                    <i class="fa-regular fa-copy"></i>
                    코드 복사
                  </button>
                </div>
                <pre class="code-block widget-code-block"><code>{{ widgetGuideCode }}</code></pre>
              </article>

              <article class="guide-card parameter-card">
                <div class="guide-card-head">
                  <div>
                    <span class="guide-card-label">PARAMETERS</span>
                    <h3>초기화 파라미터</h3>
                  </div>
                </div>
                <dl class="parameter-list">
                  <div>
                    <dt>userId <em>필수</em></dt>
                    <dd>위젯 인증에 사용할 사용자 ID</dd>
                  </div>
                  <div>
                    <dt>userPwd <em>필수</em></dt>
                    <dd>위젯 인증에 사용할 사용자 비밀번호</dd>
                  </div>
                  <div>
                    <dt>botName</dt>
                    <dd>위젯 상단에 표시할 챗봇 이름</dd>
                  </div>
                </dl>
              </article>
            </div>

            <div class="widget-api-section">
              <div class="checklist-title"><i class="fa-solid fa-sliders"></i> 위젯 제어 함수</div>
              <div class="widget-api-list">
                <span><code>showChatbot()</code> 열기</span>
                <span><code>hideChatbot()</code> 닫기</span>
                <span><code>toggleChatbot()</code> 열기/닫기</span>
                <span><code>destroyChatbot()</code> 제거</span>
              </div>
            </div>

            <div class="guide-checklist widget-checklist">
              <div class="checklist-title"><i class="fa-solid fa-list-check"></i> 적용 전 확인사항</div>
              <ul>
                <li><i class="fa-solid fa-check"></i> 위젯 스크립트는 한 페이지에서 한 번만 로드하세요.</li>
                <li><i class="fa-solid fa-check"></i> 계정 비밀번호가 브라우저 코드에 포함되므로 위젯 전용 최소 권한 계정을 사용하고 HTTPS로 서비스하세요.</li>
                <li><i class="fa-solid fa-check"></i> API 서버가 다른 도메인이면 <code>apiBaseUrl</code>과 서버의 CORS 허용 도메인을 함께 설정하세요.</li>
                <li><i class="fa-solid fa-check"></i> 적용 후 챗봇 버튼, 로그인, 컬렉션 조회, 질문 전송까지 확인하세요.</li>
              </ul>
            </div>
          </section>
        </div>
      </div>
    </main>

    <div v-if="showConfirmModal" class="modal-overlay" @click.self="closeConfirmModal">
      <div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="ui-type-confirm-title">
        <div class="modal-icon warning"><i class="fa-solid fa-triangle-exclamation"></i></div>
        <h3 id="ui-type-confirm-title">UI 연동 방식을 확정할까요?</h3>
        <p>
          <strong>{{ selectedOption?.title }}</strong
          >(으)로 확정합니다.<br />
          확정 후에는 다른 방식으로 변경할 수 없습니다.
        </p>
        <div class="modal-actions">
          <button class="modal-cancel-btn" type="button" @click="closeConfirmModal">취소</button>
          <button class="modal-confirm-btn" type="button" @click="confirmSelection">확인</button>
        </div>
      </div>
    </div>

    <AppToast :message="toastMessage" :type="toastType" adminPosition @close="toastMessage = ''" />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import AppToast from '../components/AppToast.vue';
import AdminSidebar from '../components/AdminSidebar.vue';
import PageHeader from '../components/PageHeader.vue';
import { uiIntegrationApi } from '../api/uiIntegrationApi';
import { UI_TYPE_OPTIONS, isUiType, normalizeUiType } from '../constants/uiTypes';
import { useAuthStore } from '../stores/authStore';

const router = useRouter();
const authStore = useAuthStore();
const sidebarOpen = ref(false);
const loading = ref(true);
const profileLoaded = ref(false);
const saving = ref(false);
const loadError = ref('');
const selectedUiType = ref('');
const savedUiType = ref('');
const isConfigured = ref(false);
const showConfirmModal = ref(false);
const toastMessage = ref('');
const toastType = ref('success');
const activeGuideTab = ref('html');
let toastTimer = null;

const guideTabs = [
  { value: 'html', label: 'HTML' },
  { value: 'javascript', label: 'JavaScript' },
];
const currentOption = computed(() => UI_TYPE_OPTIONS.find((option) => option.value === savedUiType.value) || null);
const selectedOption = computed(() => UI_TYPE_OPTIONS.find((option) => option.value === selectedUiType.value) || null);
const standaloneUrl = computed(() => 'http://10.10.10.109');
const widgetScriptUrl = computed(() => `${standaloneUrl.value}/adrag.js`);
const widgetGuideCode = computed(() =>
  [
    '<script>',
    ';(function () {',
    '  const chatbotParams = {',
    '    chatInfo: {',
    "      userId: 'chatbot',",
    "      userPwd: '발급받은 비밀번호',",
    "      botName: 'CHATBOT',",
    '    }',
    '  };',
    '  window.chatbotParams = chatbotParams',
    "  if (!document.getElementById('adrag-widget-script')) {",
    "    const script = document.createElement('script')",
    "    script.id = 'adrag-widget-script'",
    "    script.src = '../dist/adrag.js'",
    '    script.async = true',
    '    document.head.appendChild(script)',
    '    script.onload = () => window.createChatbot(chatbotParams)',
    "    script.onerror = () => console.error('Failed to load ADRAG chatbot script.')",
    '  } else {',
    '    window.createChatbot(chatbotParams)',
    '  }',
    '})()',
    '</scr' + 'ipt>',
  ].join('\n')
);
const guideExamples = computed(() => ({
  html: `<a\n  href="${standaloneUrl.value}"\n  target="_blank"\n  rel="noopener noreferrer"\n>\n  AI 챗봇\n</a>`,
  javascript: `function openAdRagChatbot() {\n  window.open(\n    '${standaloneUrl.value}',\n    '_blank',\n    'noopener,noreferrer'\n  );\n}`,
  menu: `{\n  "label": "AI 챗봇",\n  "url": "${standaloneUrl.value}",\n  "openInNewWindow": true\n}`,
}));
const activeGuideCode = computed(() => guideExamples.value[activeGuideTab.value]);
const activeGuideLabel = computed(() => guideTabs.find((tab) => tab.value === activeGuideTab.value)?.label || 'HTML');

const showToast = (message, type = 'success') => {
  toastMessage.value = message;
  toastType.value = type;
  if (toastTimer) window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    toastMessage.value = '';
  }, 2200);
};

const copyGuideText = async (text, label) => {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
    }
    showToast(`${label}이(가) 복사되었습니다.`);
  } catch {
    showToast('복사에 실패했습니다.', 'error');
  }
};

const openStandalonePreview = () => {
  window.open(standaloneUrl.value, '_blank', 'noopener,noreferrer');
};

const loadProfile = async () => {
  loading.value = true;
  profileLoaded.value = false;
  loadError.value = '';
  try {
    // 2026.09.17(woojin.jung) 수정 - 인증 스토어가 아닌 UI 연동 설정 API에서 조회
    const response = await uiIntegrationApi.get();
    const data = response.data || {};
    const configuredFlag = data.is_configured ?? data.ui_type_configured ?? data.is_ui_type_selected;
    const hasSavedUiType = isUiType(data.ui_type);
    isConfigured.value = configuredFlag === undefined ? hasSavedUiType : Boolean(configuredFlag && hasSavedUiType);
    savedUiType.value = isConfigured.value ? normalizeUiType(data.ui_type) : '';
    selectedUiType.value = savedUiType.value;
    profileLoaded.value = true;
  } catch (error) {
    loadError.value = error.response?.data?.detail || '사용자 설정을 불러오지 못했습니다.';
  } finally {
    loading.value = false;
  }
};

const openConfirmModal = () => {
  if (isConfigured.value || !isUiType(selectedUiType.value) || loading.value || saving.value) return;
  showConfirmModal.value = true;
};

const closeConfirmModal = () => {
  if (saving.value) return;
  showConfirmModal.value = false;
};

const confirmSelection = async () => {
  showConfirmModal.value = false;
  await save();
};

const save = async () => {
  if (isConfigured.value || !isUiType(selectedUiType.value) || saving.value) return;
  saving.value = true;
  try {
    const normalized = normalizeUiType(selectedUiType.value);
    const response = await uiIntegrationApi.update(normalized);
    const uiType = normalizeUiType(response.data?.ui_type || normalized);
    savedUiType.value = uiType;
    selectedUiType.value = uiType;
    isConfigured.value = true;
    showToast('UI 연동 방식이 확정되었습니다.');
  } catch (error) {
    if (error.response?.status === 409) {
      await loadProfile();
      showToast(error.response?.data?.detail || '이미 UI 연동 방식이 확정되어 변경할 수 없습니다.', 'error');
      return;
    }
    showToast(error.response?.data?.detail || 'UI 연동 방식 확정에 실패했습니다.', 'error');
  } finally {
    saving.value = false;
  }
};

const logout = async () => {
  await authStore.logoutAny();
  await router.push('/login');
};

onMounted(loadProfile);
onBeforeUnmount(() => {
  if (toastTimer) window.clearTimeout(toastTimer);
});
</script>

<style scoped>
.settings-layout {
  display: flex;
  width: 100%;
  height: 100dvh;
  overflow: hidden;
  color: #1e293b;
  background: #f4f7fb;
}
.settings-main {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
.settings-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.intro-card h2,
.intro-card p {
  margin: 0;
}
.settings-content {
  width: min(1180px, calc(100% - 64px));
  padding: 34px 0 44px;
  margin: 0 auto;
}
.intro-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 26px 28px;
  margin-bottom: 24px;
  overflow: hidden;
  border: 1px solid #dbeafe;
  border-radius: 16px;
  background: linear-gradient(120deg, #fff 20%, #eff6ff);
  box-shadow: 0 10px 30px rgba(37, 99, 235, 0.06);
}
.eyebrow {
  color: #2563eb;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.13em;
}
.intro-card h2 {
  margin-top: 7px;
  font-size: clamp(22px, 2.4vw, 30px);
  letter-spacing: -0.025em;
}
.intro-card p {
  margin-top: 9px;
  color: #64748b;
  font-size: 14px;
}
.current-badge {
  flex: 0 0 auto;
  min-width: 132px;
  padding: 13px 17px;
  border: 1px solid #bfdbfe;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.88);
}
.current-badge span,
.current-badge strong {
  display: block;
}
.current-badge span {
  color: #64748b;
  font-size: 11px;
}
.current-badge strong {
  margin-top: 5px;
  color: #1d4ed8;
  font-size: 14px;
}
.locked-option-card {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 24px 26px;
  border: 1px solid #bfdbfe;
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 7px 22px rgba(15, 23, 42, 0.06);
}
.locked-icon {
  display: grid;
  flex: 0 0 58px;
  width: 58px;
  height: 58px;
  place-items: center;
  border-radius: 16px;
  color: #2563eb;
  background: #eff6ff;
  font-size: 23px;
}
.locked-option-card.violet {
  border-color: #ddd6fe;
}
.locked-option-card.violet .locked-icon {
  color: #7c3aed;
  background: #f5f3ff;
}
.locked-option-card.teal {
  border-color: #99f6e4;
}
.locked-option-card.teal .locked-icon {
  color: #0f766e;
  background: #f0fdfa;
}
.locked-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #15803d;
  font-size: 11px;
  font-weight: 800;
}
.locked-option-card h2 {
  margin: 6px 0 5px;
  font-size: 20px;
}
.locked-option-card p {
  margin: 0 0 5px;
  color: #334155;
  font-size: 14px;
  font-weight: 650;
}
.locked-option-card div > span:last-child {
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
}
.option-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
}
.option-card {
  position: relative;
  display: flex;
  min-width: 0;
  min-height: 410px;
  flex-direction: column;
  padding: 23px;
  overflow: hidden;
  border: 2px solid transparent;
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 6px 22px rgba(15, 23, 42, 0.07);
  cursor: pointer;
  transition:
    transform 0.18s,
    border-color 0.18s,
    box-shadow 0.18s;
}
.option-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.11);
}
.option-card.selected {
  border-color: #2563eb;
  box-shadow: 0 12px 30px rgba(37, 99, 235, 0.15);
}
.option-card.violet.selected {
  border-color: #7c3aed;
}
.option-card.teal.selected {
  border-color: #0f766e;
}
.option-card input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
}
.selection-mark {
  position: absolute;
  top: 18px;
  right: 18px;
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  border: 1px solid #cbd5e1;
  border-radius: 50%;
  color: transparent;
  background: #fff;
  font-size: 11px;
}
.selected .selection-mark {
  border-color: #2563eb;
  color: #fff;
  background: #2563eb;
}
.violet.selected .selection-mark {
  border-color: #7c3aed;
  background: #7c3aed;
}
.teal.selected .selection-mark {
  border-color: #0f766e;
  background: #0f766e;
}
.option-number {
  color: #94a3b8;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.12em;
}
.option-icon {
  display: grid;
  width: 48px;
  height: 48px;
  place-items: center;
  margin: 17px 0;
  border-radius: 13px;
  color: #2563eb;
  background: #eff6ff;
  font-size: 19px;
}
.violet .option-icon {
  color: #7c3aed;
  background: #f5f3ff;
}
.teal .option-icon {
  color: #0f766e;
  background: #f0fdfa;
}
.option-card > strong {
  font-size: 18px;
}
.option-description {
  margin-top: 9px;
  color: #334155;
  font-size: 13px;
  font-weight: 650;
  line-height: 1.55;
}
.option-detail {
  margin-top: 8px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
}
.option-preview {
  position: relative;
  display: flex;
  height: 104px;
  margin-top: auto;
  overflow: hidden;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #f8fafc;
}
.preview-sidebar {
  width: 23%;
  background: #dbe4f0;
}
.preview-content {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 8px;
  padding: 18px;
}
.preview-content span {
  width: 72%;
  height: 7px;
  border-radius: 99px;
  background: #dbe4f0;
}
.preview-content span:nth-child(2) {
  width: 92%;
}
.preview-content span:nth-child(3) {
  width: 55%;
}
.preview-widget {
  position: absolute;
  right: 9px;
  bottom: 8px;
  display: grid;
  width: 25%;
  height: 80%;
  place-items: center;
  border: 2px solid #99f6e4;
  border-radius: 9px;
  color: #0f766e;
  background: #fff;
  box-shadow: 0 5px 14px rgba(15, 118, 110, 0.15);
}
.preview-menu-dot {
  position: absolute;
  top: 16px;
  left: 6%;
  width: 11%;
  height: 8px;
  border-radius: 99px;
  background: #8b5cf6;
}
.save-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 17px 19px;
  margin-top: 22px;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 7px 22px rgba(15, 23, 42, 0.06);
}
.change-summary {
  display: flex;
  align-items: center;
  gap: 9px;
  color: #475569;
  font-size: 13px;
}
.change-summary i {
  color: #2563eb;
}
.save-actions {
  display: flex;
  gap: 9px;
}
.cancel-button,
.save-button,
.notice button {
  border: 0;
  border-radius: 9px;
  cursor: pointer;
  font-weight: 700;
}
.cancel-button,
.save-button {
  min-height: 40px;
  padding: 9px 16px;
}
.cancel-button {
  color: #475569;
  background: #f1f5f9;
}
.save-button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #fff;
  background: #2563eb;
}
.integration-guide {
  padding: 26px;
  margin-top: 24px;
  border: 1px solid #dbeafe;
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 8px 26px rgba(15, 23, 42, 0.07);
}
.guide-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
}
.guide-title-area {
  min-width: 0;
}
.guide-badge {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 5px 9px;
  border-radius: 999px;
  color: #1d4ed8;
  background: #eff6ff;
  font-size: 11px;
  font-weight: 800;
}
.guide-badge.violet {
  color: #6d28d9;
  background: #f5f3ff;
}
.guide-badge.teal {
  color: #0f766e;
  background: #f0fdfa;
}
.compact-guide-card {
  max-width: 760px;
}
.compact-guide-card .code-block {
  margin-top: 14px;
}
.guide-head h2 {
  margin: 11px 0 6px;
  color: #0f172a;
  font-size: 21px;
  letter-spacing: -0.02em;
}
.guide-head p {
  margin: 0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
}
.preview-button {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  padding: 9px 14px;
  border: 1px solid #bfdbfe;
  border-radius: 9px;
  color: #1d4ed8;
  background: #eff6ff;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.preview-button:hover {
  border-color: #93c5fd;
  background: #dbeafe;
}
.ownership-notice {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  padding: 13px 15px;
  margin-top: 20px;
  border: 1px solid #fde68a;
  border-radius: 10px;
  color: #92400e;
  background: #fffbeb;
}
.ownership-notice > i {
  margin-top: 2px;
  color: #d97706;
}
.ownership-notice strong,
.ownership-notice span {
  display: block;
}
.ownership-notice strong {
  font-size: 13px;
}
.ownership-notice span {
  margin-top: 3px;
  font-size: 12px;
  line-height: 1.5;
}
.ownership-notice code {
  padding: 1px 4px;
  border-radius: 4px;
  color: #115e59;
  background: #ccfbf1;
  font-family: Consolas, Monaco, monospace;
}
.ownership-notice.widget-notice {
  border-color: #99f6e4;
  color: #115e59;
  background: #f0fdfa;
}
.ownership-notice.widget-notice > i {
  color: #0f766e;
}
.guide-steps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  padding: 0;
  margin: 20px 0;
  list-style: none;
}
.guide-steps li {
  display: flex;
  align-items: center;
  gap: 11px;
  min-width: 0;
  padding: 13px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #f8fafc;
}
.step-number {
  display: grid;
  flex: 0 0 28px;
  width: 28px;
  height: 28px;
  place-items: center;
  border-radius: 50%;
  color: #fff;
  background: #2563eb;
  font-size: 11px;
  font-weight: 800;
}
.guide-steps strong,
.guide-steps li div > span {
  display: block;
}
.guide-steps strong {
  color: #334155;
  font-size: 12px;
}
.guide-steps li div > span {
  margin-top: 3px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.4;
}
.guide-grid {
  display: grid;
  grid-template-columns: minmax(280px, 0.85fr) minmax(420px, 1.4fr);
  gap: 16px;
}
.guide-card {
  min-width: 0;
  padding: 18px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #fff;
}
.guide-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 14px;
}
.guide-card-label {
  color: #2563eb;
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0.11em;
}
.guide-card h3 {
  margin: 4px 0 0;
  color: #1e293b;
  font-size: 14px;
}
.environment-badge {
  flex: 0 0 auto;
  padding: 4px 7px;
  border-radius: 6px;
  color: #15803d;
  background: #f0fdf4;
  font-size: 10px;
  font-weight: 700;
}
.url-box {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 10px 10px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 9px;
  background: #f8fafc;
}
.url-box code {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: #0f172a;
  font-family: Consolas, Monaco, monospace;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.url-box button {
  display: grid;
  flex: 0 0 32px;
  width: 32px;
  height: 32px;
  place-items: center;
  border: 0;
  border-radius: 7px;
  color: #2563eb;
  background: #dbeafe;
  cursor: pointer;
}
.card-hint {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: 11px 0 0;
  color: #64748b;
  font-size: 11px;
  line-height: 1.5;
}
.card-hint i {
  margin-top: 2px;
  color: #94a3b8;
}
.code-head {
  margin-bottom: 10px;
}
.code-copy-button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 9px;
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  color: #475569;
  background: #fff;
  font-size: 10px;
  font-weight: 700;
  cursor: pointer;
}
.code-copy-button:hover {
  color: #1d4ed8;
  border-color: #93c5fd;
  background: #eff6ff;
}
.code-tabs {
  display: flex;
  gap: 5px;
  margin-bottom: 8px;
}
.code-tabs button {
  padding: 6px 10px;
  border: 0;
  border-radius: 6px;
  color: #64748b;
  background: transparent;
  font-size: 10px;
  font-weight: 700;
  cursor: pointer;
}
.code-tabs button.active {
  color: #1d4ed8;
  background: #eff6ff;
}
.code-block {
  min-height: 145px;
  padding: 14px;
  margin: 0;
  overflow: auto;
  border-radius: 9px;
  color: #dbeafe;
  background: #0f172a;
  font-family: Consolas, Monaco, monospace;
  font-size: 11px;
  line-height: 1.55;
  white-space: pre;
}
.widget-script-card {
  margin-bottom: 16px;
}
.widget-guide-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(300px, 0.85fr);
  gap: 16px;
}
.widget-code-block {
  min-height: 290px;
}
.parameter-list {
  display: grid;
  gap: 0;
  margin: 0;
}
.parameter-list > div {
  padding: 12px 0;
  border-bottom: 1px solid #e2e8f0;
}
.parameter-list > div:first-child {
  padding-top: 0;
}
.parameter-list > div:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}
.parameter-list dt {
  color: #0f172a;
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
  font-weight: 700;
}
.parameter-list dt em {
  padding: 2px 5px;
  margin-left: 5px;
  border-radius: 5px;
  color: #b91c1c;
  background: #fee2e2;
  font-family: inherit;
  font-size: 9px;
  font-style: normal;
}
.parameter-list dd {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 11px;
  line-height: 1.5;
}
.widget-api-section {
  display: grid;
  grid-template-columns: 170px 1fr;
  gap: 18px;
  padding: 15px;
  margin-top: 16px;
  border: 1px solid #ccfbf1;
  border-radius: 10px;
  background: #f0fdfa;
}
.widget-api-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.widget-api-list span {
  padding: 6px 8px;
  border: 1px solid #99f6e4;
  border-radius: 7px;
  color: #475569;
  background: #fff;
  font-size: 10px;
}
.widget-api-list code {
  color: #0f766e;
  font-family: Consolas, Monaco, monospace;
  font-weight: 700;
}
.widget-checklist {
  margin-top: 12px;
}
.guide-checklist {
  display: grid;
  grid-template-columns: 170px 1fr;
  gap: 18px;
  padding: 15px;
  margin-top: 16px;
  border-radius: 10px;
  background: #f8fafc;
}
.checklist-title {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  color: #334155;
  font-size: 12px;
  font-weight: 800;
}
.checklist-title i {
  margin-top: 2px;
  color: #2563eb;
}
.guide-checklist ul {
  display: grid;
  gap: 7px;
  padding: 0;
  margin: 0;
  list-style: none;
}
.guide-checklist li {
  color: #64748b;
  font-size: 11px;
  line-height: 1.5;
}
.guide-checklist li > i {
  margin-right: 6px;
  color: #22c55e;
}
.guide-checklist code {
  padding: 1px 4px;
  border-radius: 4px;
  color: #334155;
  background: #e2e8f0;
  font-family: Consolas, Monaco, monospace;
}
button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
.notice {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 12px 14px;
  margin-bottom: 18px;
  border-radius: 10px;
  font-size: 13px;
}
.notice.error {
  border: 1px solid #fecaca;
  color: #b91c1c;
  background: #fff1f2;
}
.notice button {
  padding: 5px 9px;
  margin-left: auto;
  color: #b91c1c;
  background: #fee2e2;
}
.modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.5);
}
.modal-card {
  width: 90%;
  max-width: 360px;
  padding: 2rem 2.5rem;
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.25);
  text-align: center;
}
.modal-icon {
  margin-bottom: 1rem;
  color: #ef4444;
  font-size: 2rem;
}
.modal-icon.warning {
  color: #f59e0b;
}
.modal-card h3 {
  margin: 0 0 0.5rem;
  color: #1e293b;
  font-size: 1.1rem;
  font-weight: 700;
}
.modal-card p {
  margin: 0 0 1.5rem;
  color: #64748b;
  font-size: 0.9rem;
  line-height: 1.6;
}
.modal-card strong {
  color: #334155;
}
.modal-actions {
  display: flex;
  justify-content: center;
  gap: 10px;
}
.modal-cancel-btn,
.modal-confirm-btn {
  padding: 0.65rem 1.4rem;
  border-radius: 8px;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
}
.modal-cancel-btn {
  border: 1px solid #cbd5e1;
  color: #475569;
  background: #f8fafc;
}
.modal-cancel-btn:hover {
  background: #f1f5f9;
}
.modal-confirm-btn {
  border: 0;
  color: #fff;
  background: #2563eb;
}
.modal-confirm-btn:hover {
  background: #1d4ed8;
}
@media (max-width: 1050px) {
  .option-grid {
    grid-template-columns: 1fr;
  }
  .option-card {
    min-height: 330px;
  }
  .guide-grid {
    grid-template-columns: 1fr;
  }
  .widget-guide-grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 768px) {
  .settings-content {
    width: calc(100% - 28px);
    padding: 20px 0 28px;
  }
  .intro-card,
  .save-bar,
  .locked-option-card {
    align-items: stretch;
    flex-direction: column;
  }
  .current-badge {
    min-width: 0;
  }
  .save-actions {
    width: 100%;
  }
  .cancel-button,
  .save-button {
    flex: 1;
  }
  .integration-guide {
    padding: 18px;
  }
  .guide-head,
  .guide-checklist,
  .widget-api-section {
    grid-template-columns: 1fr;
    flex-direction: column;
  }
  .preview-button {
    width: 100%;
    justify-content: center;
  }
  .guide-steps {
    grid-template-columns: 1fr;
  }
  .guide-checklist {
    gap: 12px;
  }
  .guide-card-head {
    align-items: flex-start;
  }
}
/* 2026.11.02(woojin.jung) 수정 - 반응형(태블릿/모바일) 대응 */
@media (max-width: 768px) {
  .intro-card,
  .locked-option-card {
    padding: 18px;
  }
  .url-box button {
    flex-basis: 40px;
    width: 40px;
    height: 40px;
  }
  .code-copy-button,
  .code-tabs button {
    min-height: 36px;
  }
  .modal-overlay {
    padding: 16px;
  }
  .modal-card {
    width: min(360px, calc(100vw - 32px));
    max-height: calc(100dvh - 32px);
    padding: 1.5rem 1.25rem;
    box-sizing: border-box;
    overflow-y: auto;
  }
}
</style>
