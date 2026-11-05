<template>
  <div class="admin-layout">
    <AdminSidebar :isOpen="sidebarOpen" activePage="statistics" :isAdmin="isAdmin" :displayName="displayName" @close="sidebarOpen = false" @logout="logout" />

    <div class="admin-main">
      <PageHeader description="전체 부서 및 사용자 기반의 AI 챗봇 사용 현황을 통합 모니터링합니다." @openSidebar="sidebarOpen = true">
        <template #title>
          통계 대시보드
          <span class="admin-badge">관리자</span>
        </template>
        <template #actions>
          <div class="header-actions">
            <button class="refresh-btn" :disabled="isLoading" @click="loadAllStatistics" title="새로고침">
              <i class="fa-solid fa-rotate-right" :class="{ 'fa-spin': isLoading }"></i>
            </button>
            <select v-model="selectedPeriod" class="period-select" aria-label="조회 기간">
              <option v-for="period in periods" :key="period.value" :value="period.value">{{ period.label }}</option>
            </select>
          </div>
        </template>
      </PageHeader>

      <main class="admin-content">
        <div v-if="loadError" class="alert error">
          <i class="fa-solid fa-circle-exclamation"></i>
          {{ loadError }}
        </div>

        <div class="section-label"><i class="fa-solid fa-layer-group"></i> 전체 요약</div>
        <section class="summary-grid">
          <article v-for="item in summaryCards" :key="item.label" class="stat-card" :class="item.color">
            <div class="stat-title">
              <i :class="item.icon"></i>
              {{ item.label }}
            </div>
            <div class="stat-value">{{ item.value }}</div>
            <div class="stat-trend" :class="`trend-${item.trendType}`">
              <i :class="trendIcon(item.trendType)"></i>
              {{ item.trend }}
            </div>
          </article>
        </section>

        <section class="charts-grid">
          <article class="card">
            <div class="card-header">
              <div class="card-title"><i class="fa-solid fa-chart-line"></i> 일별 질의 및 API 비용 추이</div>
              <div class="date-filter">
                <button v-for="period in periods" :key="period.value" class="filter-btn" :class="{ active: selectedChartPeriod === period.value }" @click="selectedChartPeriod = period.value">
                  {{ period.shortLabel }}
                </button>
              </div>
            </div>
            <div v-if="!canShowChartStats || !hasChartData" class="empty-state">
              <i class="fa-regular fa-chart-bar"></i>
              <p>{{ canShowChartStats ? '선택한 기간의 질의 로그가 없습니다.' : '통계 데이터를 불러오면 차트가 표시됩니다.' }}</p>
            </div>
            <div v-show="canShowChartStats && hasChartData" class="chart-container">
              <canvas ref="queryChartRef" aria-label="일별 질의 및 API 비용 추이"></canvas>
            </div>
          </article>

          <article class="card">
            <div class="card-title"><i class="fa-solid fa-hashtag"></i> 인기 검색 키워드 Top 5</div>
            <div v-if="keywords.length === 0" class="empty-state compact">
              <i class="fa-regular fa-message"></i>
              <p>집계할 질의 로그가 없습니다.</p>
            </div>
            <div v-else class="keyword-list">
              <div v-for="keyword in keywords" :key="keyword.name" class="keyword-row">
                <div class="keyword-item">
                  <span class="kw-name">{{ keyword.name }}</span>
                  <span class="kw-count">{{ keyword.count }}회</span>
                </div>
                <div class="kw-bar-bg">
                  <div class="kw-bar-fill" :style="{ width: `${keyword.percent}%` }"></div>
                </div>
              </div>
            </div>
          </article>
        </section>

        <div class="section-label"><i class="fa-solid fa-building-user"></i> 부서별 사용현황</div>
        <section class="dept-grid">
            <article class="card">
              <div class="card-header">
                <div class="card-title no-margin"><i class="fa-solid fa-bars-progress"></i> 부서별 질의 수 & 만족도</div>
                <span class="muted-caption">{{ periodLabel }} 기준</span>
              </div>
              <div v-if="departments.length === 0" class="empty-state compact">
                <i class="fa-regular fa-building"></i>
                <p>부서별 사용 데이터가 없습니다.</p>
              </div>
              <div v-else class="dept-list">
                <div v-for="dept in departments" :key="dept.name" class="dept-item">
                  <div class="dept-meta">
                    <div class="dept-name">
                      <span class="dept-dot" :style="{ background: dept.color }"></span>
                      {{ dept.name }}
                    </div>
                    <div class="dept-stats">
                      <span class="dept-count">{{ dept.queryCount.toLocaleString('ko-KR') }}회</span>
                      <span class="badge" :class="Number(dept.satisfaction || 0) >= 90 ? 'badge-ok' : 'badge-warn'">만족도 {{ dept.satisfaction ?? '-' }}%</span>
                    </div>
                  </div>
                  <div class="dept-bar-bg"><div class="dept-bar-fill" :style="{ width: `${dept.percent}%`, background: dept.color }"></div></div>
                </div>
              </div>
            </article>

            <article class="card">
              <div class="card-title"><i class="fa-solid fa-ranking-star"></i> 사용자별 활동 Top 10</div>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>순위</th>
                      <th>사용자</th>
                      <th>부서</th>
                      <th>질의 수</th>
                      <th>만족도</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="user in userRankings" :key="`${user.rank}-${user.name}`">
                      <td><span class="rank-badge" :class="`rank-${user.rank <= 3 ? user.rank : 'n'}`">{{ user.rank }}</span></td>
                      <td>{{ user.name }}</td>
                      <td>{{ user.department }}</td>
                      <td><strong>{{ user.queryCount.toLocaleString('ko-KR') }}</strong></td>
                      <td><span class="badge" :class="Number(user.satisfaction || 0) >= 90 ? 'badge-ok' : 'badge-warn'">{{ user.satisfaction ?? '-' }}%</span></td>
                    </tr>
                    <tr v-if="userRankings.length === 0">
                      <td colspan="5" class="empty-cell">사용자 활동 데이터가 없습니다.</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </article>
        </section>

        <div class="section-label"><i class="fa-solid fa-users"></i> 사용자 활동</div>

        <section class="bottom-grid">
          <article class="card">
            <div class="card-title"><i class="fa-solid fa-file-invoice"></i> 최다 참조 문서 Top 5</div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>문서명</th>
                    <th>컬렉션</th>
                    <th>참조 횟수</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="doc in referencedDocs" :key="doc.document_id || doc.filename">
                    <td>
                      <button class="doc-link" :disabled="openingDocId === docKey(doc)" :title="docName(doc)" @click="openOriginalDocument(doc)">
                        <i :class="docIcon(docName(doc))"></i>
                        <span>{{ docName(doc) }}</span>
                        <i v-if="openingDocId === docKey(doc)" class="fa-solid fa-spinner fa-spin"></i>
                      </button>
                    </td>
                    <td>{{ collectionLabel(doc.collection_name) }}</td>
                    <td>
                      <strong>{{ doc.citation_count ?? doc.reference_count ?? doc.count ?? '-' }}</strong>
                    </td>
                  </tr>
                  <tr v-if="referencedDocs.length === 0">
                    <td colspan="3" class="empty-cell">참조된 문서가 없습니다.</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-if="docOpenError" class="inline-error">{{ docOpenError }}</div>
          </article>

          <article class="card">
            <div class="card-title"><i class="fa-solid fa-triangle-exclamation"></i> 주의 요망 질의</div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>질의 내용</th>
                    <th>유형</th>
                    <th>일시</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="issue in queryIssues" :key="`${issue.query}-${issue.time}`">
                    <td>
                      {{ issue.query }}
                      <!-- 2026.11.05(woojin.jung) 추가 - 부정 피드백 사유·의견 -->
                      <div v-if="issue.feedbackReasons.length || issue.feedbackComment" class="issue-feedback">
                        <span v-for="reason in issue.feedbackReasons" :key="reason" class="issue-feedback-reason">{{ reason }}</span>
                        <p v-if="issue.feedbackComment" class="issue-feedback-comment">“{{ issue.feedbackComment }}”</p>
                      </div>
                    </td>
                    <td>
                      <span class="badge badge-error">{{ issue.type }}</span>
                    </td>
                    <td>{{ issue.time }}</td>
                  </tr>
                  <tr v-if="queryIssues.length === 0">
                    <td colspan="3" class="empty-cell">주의 요망 질의가 없습니다.</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </article>
        </section>

        <div class="section-label"><i class="fa-solid fa-file-shield"></i> 문서 상태</div>
        <section class="dead-docs-section card">
          <div class="dead-docs-summary">
            <div v-for="item in documentHealthSummary" :key="item.label" class="dead-mini-card">
              <div class="dead-mini-icon" :class="item.type"><i :class="item.icon"></i></div>
              <div>
                <div class="dead-mini-label">{{ item.label }}</div>
                <div class="dead-mini-value">{{ item.value }}</div>
              </div>
            </div>
          </div>

          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>문서명</th>
                  <th>컬렉션</th>
                  <th>상태</th>
                  <th>마지막 인용</th>
                  <th>경과일</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="doc in documentHealthItems" :key="doc.document_id">
                  <td>
                    <i :class="docIcon(doc.document_name)"></i>
                    {{ doc.document_name }}
                  </td>
                  <td>{{ doc.collection_name || '-' }}</td>
                  <td><span class="badge badge-stale">{{ healthStatusLabel(doc.health_status) }}</span></td>
                  <td>{{ formatDateTime(doc.last_cited_at) }}</td>
                  <td><span class="days-chip" :class="daysClass(doc.days_since_last_citation)">{{ doc.days_since_last_citation }}일</span></td>
                </tr>
                <tr v-if="documentHealthItems.length === 0">
                  <td colspan="5" class="empty-cell">주의가 필요한 문서가 없습니다.</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  </div>
</template>

<script setup>
import { Chart, BarController, BarElement, CategoryScale, Filler, Legend, LinearScale, LineController, LineElement, PointElement, Tooltip } from 'chart.js';
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { adminApi } from '../api/adminApi';
import AdminSidebar from '../components/AdminSidebar.vue';
import PageHeader from '../components/PageHeader.vue';
import { useAdminStatistics } from '../composables/useAdminStatistics';

Chart.register(BarController, BarElement, CategoryScale, Filler, Legend, LinearScale, LineController, LineElement, PointElement, Tooltip);

const {
  isAdmin,
  displayName,
  sidebarOpen,
  selectedPeriod,
  selectedChartPeriod,
  isLoading,
  loadError,
  periods,
  periodLabel,
  canShowChartStats,
  activeChart,
  hasChartData,
  summaryCards,
  keywords,
  departments,
  userRankings,
  referencedDocs,
  queryIssues,
  documentHealthSummary,
  documentHealthItems,
  loadAllStatistics,
  logout,
  trendIcon,
  collectionLabel,
  docIcon,
  daysClass,
  formatDateTime,
} = useAdminStatistics();

const queryChartRef = ref(null);
const openingDocId = ref(null);
const docOpenError = ref('');
let queryChart = null;

const chartData = computed(() => ({
  labels: activeChart.value.labels,
  queries: activeChart.value.queries,
  costs: activeChart.value.costs,
}));

const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  plugins: {
    legend: {
      position: 'top',
      labels: {
        boxWidth: 12,
        font: { size: 12 },
      },
    },
    tooltip: {
      callbacks: {
        label(context) {
          const value = context.parsed.y ?? 0;
          return context.dataset.yAxisID === 'y1' ? `${context.dataset.label}: $${Number(value).toFixed(2)}` : `${context.dataset.label}: ${value}`;
        },
      },
    },
  },
  scales: {
    x: {
      grid: { display: false },
      ticks: { color: '#64748b', maxRotation: 0, autoSkip: true, maxTicksLimit: 8 },
    },
    y: {
      type: 'linear',
      display: true,
      position: 'left',
      beginAtZero: true,
      grid: { color: '#f1f5f9' },
      title: { display: true, text: '질의 수', font: { size: 11 } },
      ticks: { precision: 0, color: '#64748b' },
    },
    y1: {
      type: 'linear',
      display: true,
      position: 'right',
      beginAtZero: true,
      grid: { drawOnChartArea: false },
      title: { display: true, text: '비용 ($)', font: { size: 11 } },
      ticks: { color: '#64748b' },
    },
  },
};

const makeDatasets = () => [
  {
    type: 'bar',
    label: '질의 수',
    data: chartData.value.queries,
    backgroundColor: 'rgba(59, 130, 246, 0.7)',
    borderColor: '#3b82f6',
    borderWidth: 0,
    borderRadius: 4,
    yAxisID: 'y',
  },
  {
    type: 'line',
    label: 'API 사용 비용 ($)',
    data: chartData.value.costs,
    borderColor: '#8b5cf6',
    backgroundColor: '#8b5cf6',
    borderWidth: 2,
    borderDash: [5, 5],
    tension: 0.3,
    fill: false,
    pointRadius: 3,
    yAxisID: 'y1',
  },
];

const renderChart = async () => {
  await nextTick();
  if (!queryChartRef.value || !hasChartData.value) return;

  if (!queryChart) {
    queryChart = new Chart(queryChartRef.value, {
      type: 'bar',
      data: {
        labels: chartData.value.labels,
        datasets: makeDatasets(),
      },
      options: chartOptions,
    });
    return;
  }

  queryChart.data.labels = chartData.value.labels;
  queryChart.data.datasets = makeDatasets();
  queryChart.update();
};

const docName = (doc) => doc?.filename || doc?.original_filename || doc?.document_name || '';
const docKey = (doc) => doc?.document_id || docName(doc);

const resolveDocumentId = async (doc) => {
  if (doc?.document_id) return doc.document_id;

  const filename = docName(doc);
  if (!filename) return null;

  const res = await adminApi.documents();
  const documents = res.data.documents || [];
  const found = documents.find((item) => {
    const candidates = [item.filename, item.original_filename, item.document_name].filter(Boolean);
    return candidates.some((name) => name === filename);
  });

  return found?.document_id || null;
};

const healthStatusLabel = (status) => {
  const labels = {
    uncited: '미참조',
    review_overdue_and_uncited: '검토 필요/미참조',
  };
  return labels[status] || status || '-';
};

const openOriginalDocument = async (doc) => {
  if (!doc || openingDocId.value) return;

  const key = docKey(doc);
  openingDocId.value = key;
  docOpenError.value = '';

  try {
    const documentId = await resolveDocumentId(doc);
    if (!documentId) {
      throw new Error('원본 문서를 찾을 수 없습니다.');
    }

    const res = await adminApi.documentFile(documentId);
    const contentType = res.headers?.['content-type'] || 'application/octet-stream';
    const blobUrl = window.URL.createObjectURL(new Blob([res.data], { type: contentType }));
    window.open(blobUrl, '_blank', 'noopener,noreferrer');
    window.setTimeout(() => window.URL.revokeObjectURL(blobUrl), 60000);
  } catch (err) {
    docOpenError.value = err.response?.data?.detail || err.message || '원본 문서를 열 수 없습니다.';
  } finally {
    openingDocId.value = null;
  }
};

watch(chartData, renderChart, { deep: true, immediate: true });
watch(hasChartData, (visible) => {
  if (visible) renderChart();
});

onBeforeUnmount(() => {
  queryChart?.destroy();
  queryChart = null;
});
</script>

<style scoped>
* {
  box-sizing: border-box;
}

.admin-layout {
  display: flex;
  height: 100dvh;
  background: #f1f5f9;
  overflow: hidden;
  font-family: 'Inter', 'Apple SD Gothic Neo', sans-serif;
}

.admin-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}

.refresh-btn,
.period-select {
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  border-radius: 6px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
}

.refresh-btn {
  width: 36px;
  height: 36px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
}

.period-select {
  height: 36px;
  padding: 0 2.1rem 0 0.85rem;
  border: 1px solid #cbd5e1;
  background: #fff;
  color: #334155;
  font: inherit;
  font-size: 0.85rem;
  font-weight: 500;
  appearance: none;
  background-image: linear-gradient(45deg, transparent 50%, #64748b 50%), linear-gradient(135deg, #64748b 50%, transparent 50%);
  background-position:
    calc(100% - 15px) 50%,
    calc(100% - 10px) 50%;
  background-size:
    5px 5px,
    5px 5px;
  background-repeat: no-repeat;
}

.refresh-btn:hover:not(:disabled) {
  background: #f1f5f9;
  color: #1e293b;
}

.refresh-btn:disabled {
  cursor: wait;
  opacity: 0.7;
}

.admin-content {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.alert {
  display: flex;
  align-items: center;
  gap: 8px;
  border-radius: 10px;
  padding: 0.8rem 1rem;
  font-size: 0.9rem;
  font-weight: 600;
}

.alert.error {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #dc2626;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1.25rem;
}

.stat-card,
.card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
}

.stat-card {
  position: relative;
  overflow: hidden;
  padding: 1.25rem;
}

.stat-card::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 4px;
}

.stat-card.blue::before {
  background: #3b82f6;
}

.stat-card.green::before {
  background: #10b981;
}

.stat-card.orange::before {
  background: #f59e0b;
}

.stat-card.purple::before {
  background: #8b5cf6;
}

.stat-card.teal::before {
  background: #14b8a6;
}

.stat-card.red::before {
  background: #ef4444;
}

.admin-badge {
  display: inline-flex;
  align-items: center;
  margin-left: 6px;
  padding: 2px 8px;
  border-radius: 12px;
  background: #dbeafe;
  color: #2563eb;
  font-size: 0.75rem;
  font-weight: 600;
  vertical-align: middle;
}

.stat-title,
.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.stat-title {
  color: #64748b;
  font-size: 0.85rem;
  font-weight: 500;
  margin-bottom: 0.5rem;
}

.stat-value {
  color: #0f172a;
  font-size: 1.8rem;
  font-weight: 700;
  margin-bottom: 0.25rem;
}

.stat-trend {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.75rem;
  font-weight: 500;
}

.trend-up {
  color: #10b981;
}

.trend-down {
  color: #ef4444;
}

.trend-neutral {
  color: #64748b;
}

.charts-grid {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr);
  gap: 1.25rem;
}

.bottom-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1.25rem;
}

.dept-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(420px, 1fr);
  gap: 1.25rem;
}

.card {
  padding: 1.5rem;
  min-width: 0;
}

.card-header,
.dead-docs-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.card-title {
  color: #1e293b;
  font-size: 0.95rem;
  font-weight: 600;
  margin-bottom: 1rem;
}

.card-header .card-title,
.no-margin {
  margin-bottom: 0;
}

.section-label {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #64748b;
  font-size: 0.8rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.section-label::after {
  content: '';
  height: 1px;
  flex: 1;
  background: #e2e8f0;
}

.muted-caption {
  color: #94a3b8;
  font-size: 0.78rem;
  white-space: nowrap;
}

.date-filter {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
}

.filter-btn {
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  color: #64748b;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.85rem;
  padding: 0.5rem 1rem;
  transition: all 0.2s;
  white-space: nowrap;
}

.filter-btn:hover {
  background: #e2e8f0;
  color: #334155;
}

.filter-btn.active {
  background: #2563eb;
  border-color: #2563eb;
  color: white;
}

.chart-container {
  position: relative;
  width: 100%;
  height: 260px;
}

.keyword-list {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}

.keyword-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.5rem 0.75rem;
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  border-radius: 6px;
}

.kw-name {
  color: #334155;
  font-size: 0.85rem;
  font-weight: 500;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kw-count {
  color: #64748b;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  font-size: 0.8rem;
  padding: 2px 8px;
  white-space: nowrap;
}

.kw-bar-bg {
  height: 8px;
  background: #e2e8f0;
  border-radius: 4px;
  margin-top: 8px;
  overflow: hidden;
}

.kw-bar-fill {
  height: 100%;
  background: #2563eb;
  border-radius: 4px;
}

.empty-state {
  min-height: 260px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  color: #94a3b8;
  text-align: center;
}

.empty-state.compact {
  min-height: 180px;
}

.empty-state i {
  font-size: 1.8rem;
}

.empty-state p {
  margin: 0;
  font-size: 0.88rem;
}

.table-wrap {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  min-width: 620px;
  text-align: left;
  font-size: 0.85rem;
}

th {
  background: #f8fafc;
  color: #475569;
  font-weight: 600;
}

th,
td {
  border-bottom: 1px solid #f1f5f9;
  padding: 0.75rem;
  vertical-align: middle;
}

.empty-cell {
  color: #94a3b8;
  text-align: center;
}

.doc-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  color: #2563eb;
  cursor: pointer;
  font: inherit;
  font-weight: 500;
  text-align: left;
}

.doc-link span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-link:hover:not(:disabled) span {
  text-decoration: underline;
}

.doc-link:disabled {
  cursor: wait;
  opacity: 0.7;
}

.inline-error {
  margin-top: 0.75rem;
  color: #dc2626;
  font-size: 0.82rem;
}

.badge {
  display: inline-flex;
  align-items: center;
  border-radius: 10px;
  font-size: 0.72rem;
  font-weight: 600;
  padding: 3px 8px;
  white-space: nowrap;
}

.badge-error,
.badge-stale {
  background: #fee2e2;
  color: #dc2626;
}

/* 2026.11.05(woojin.jung) 추가 - 부정 피드백 사유·의견 */
.issue-feedback {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}
.issue-feedback-reason {
  padding: 1px 8px;
  border: 1px solid #fecaca;
  border-radius: 999px;
  background: #fef2f2;
  color: #b91c1c;
  font-size: 0.72rem;
}
.issue-feedback-comment {
  flex-basis: 100%;
  margin: 2px 0 0;
  color: #64748b;
  font-size: 0.78rem;
  white-space: pre-wrap;
  word-break: break-word;
}

.badge-warn {
  background: #fef3c7;
  color: #d97706;
}

.badge-ok {
  background: #d1fae5;
  color: #059669;
}

.dept-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.dept-item {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.dept-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.dept-name,
.dept-stats {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.dept-name {
  color: #334155;
  font-size: 0.9rem;
  font-weight: 600;
}

.dept-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex-shrink: 0;
}

.dept-count {
  color: #475569;
  font-size: 0.82rem;
  font-weight: 700;
  white-space: nowrap;
}

.dept-bar-bg {
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: #e2e8f0;
}

.dept-bar-fill {
  height: 100%;
  border-radius: inherit;
}

.rank-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  color: #fff;
  font-size: 0.76rem;
  font-weight: 700;
}

.rank-1 {
  background: #f59e0b;
}

.rank-2 {
  background: #64748b;
}

.rank-3 {
  background: #b45309;
}

.rank-n {
  background: #cbd5e1;
  color: #475569;
}

.dead-docs-section {
  display: flex;
  flex-direction: column;
}

.dead-docs-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.dead-mini-card {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 0.75rem 1rem;
}

.dead-mini-icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  flex-shrink: 0;
}

.dead-mini-icon.error {
  background: #fee2e2;
  color: #dc2626;
}

.dead-mini-icon.warn {
  background: #fef3c7;
  color: #d97706;
}

.dead-mini-icon.info {
  background: #dbeafe;
  color: #2563eb;
}

.dead-mini-label {
  color: #94a3b8;
  font-size: 0.72rem;
}

.dead-mini-value {
  color: #0f172a;
  font-size: 1.1rem;
  font-weight: 700;
  line-height: 1.2;
}

.days-chip {
  display: inline-block;
  border-radius: 10px;
  font-size: 0.72rem;
  font-weight: 600;
  padding: 2px 7px;
}

.days-90 {
  background: #fee2e2;
  color: #dc2626;
}

.days-60 {
  background: #fef3c7;
  color: #d97706;
}

.days-30 {
  background: #dbeafe;
  color: #2563eb;
}

@media (max-width: 1100px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .charts-grid,
  .dept-grid,
  .bottom-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {

  .admin-content {
    padding: 1rem;
  }

  .card,
  .stat-card {
    padding: 1rem;
  }

  .card-header,
  .dead-docs-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .date-filter {
    width: 100%;
  }

  .filter-btn {
    flex: 1;
  }

  .dead-docs-summary {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 520px) {
  .summary-grid {
    grid-template-columns: 1fr;
  }
}

/* 2026.11.02(woojin.jung) 수정 - 반응형(태블릿/모바일) 대응 */
@media (max-width: 1024px) {
  .days-chip {
    white-space: nowrap;
  }
}

@media (max-width: 768px) {
  .refresh-btn {
    width: 40px;
    height: 40px;
  }

  .period-select,
  .filter-btn {
    min-height: 40px;
  }
}
</style>
