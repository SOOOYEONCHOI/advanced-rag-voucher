<template>
  <div class="admin-layout">
    <AdminSidebar :isOpen="sidebarOpen" activePage="statistics" :isAdmin="isAdmin" :displayName="displayName" @close="sidebarOpen = false" @logout="logout" />

    <div class="admin-main">
      <PageHeader title="내 활동 현황" description="나의 AI 챗봇 사용 이력과 답변 현황을 확인합니다." @openSidebar="sidebarOpen = true">
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
            <div v-if="!hasChartData" class="empty-state">
              <i class="fa-regular fa-chart-bar"></i>
              <p>선택한 기간의 질의 로그가 없습니다.</p>
            </div>
            <div v-show="hasChartData" class="chart-container">
              <canvas ref="queryChartRef" aria-label="일별 질의 및 API 비용 추이"></canvas>
            </div>
          </article>

          <article class="card">
            <div class="card-title"><i class="fa-solid fa-hashtag"></i> 자주 찾은 키워드 Top 5</div>
            <div v-if="keywords.length === 0" class="empty-state compact">
              <i class="fa-regular fa-message"></i>
              <p>집계할 키워드가 없습니다.</p>
            </div>
            <div v-else class="keyword-list">
              <div v-for="keyword in keywords" :key="keyword.keyword" class="keyword-row">
                <div class="keyword-item">
                  <span class="kw-name">{{ keyword.keyword }}</span>
                  <span class="kw-count">{{ formatNumber(keyword.count) }}회</span>
                </div>
                <div class="kw-bar-bg">
                  <div class="kw-bar-fill" :style="{ width: `${keyword.ratioPct}%` }"></div>
                </div>
              </div>
            </div>
          </article>
        </section>

        <section class="bottom-grid">
          <article class="card">
            <div class="card-title"><i class="fa-solid fa-file-invoice"></i> 많이 참조한 문서 Top 5</div>
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
                  <tr v-for="doc in referencedDocs" :key="doc.documentId || doc.documentName">
                    <td>
                      <button class="doc-link" :disabled="!doc.documentId || openingDocId === doc.documentId" :title="doc.documentName" @click="openOriginalDocument(doc)">
                        <i :class="docIcon(doc.documentName)"></i>
                        <span>{{ doc.documentName }}</span>
                        <i v-if="openingDocId === doc.documentId" class="fa-solid fa-spinner fa-spin"></i>
                      </button>
                    </td>
                    <td>{{ doc.collectionName || '-' }}</td>
                    <td>
                      <strong>{{ formatNumber(doc.citationCount) }}</strong>
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
                  <tr v-for="issue in queryIssues" :key="issue.logId">
                    <td>{{ issue.queryText }}</td>
                    <td>
                      <span class="badge badge-error">{{ issue.issueLabel }}</span>
                    </td>
                    <td>{{ formatDateTime(issue.createdAt) }}</td>
                  </tr>
                  <tr v-if="queryIssues.length === 0">
                    <td colspan="3" class="empty-cell">주의 요망 질의가 없습니다.</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </article>
        </section>
      </main>
    </div>
  </div>
</template>

<script setup>
import { BarController, BarElement, CategoryScale, Chart, Filler, Legend, LinearScale, LineController, LineElement, PointElement, Tooltip } from 'chart.js';
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import AdminSidebar from '../components/AdminSidebar.vue';
import PageHeader from '../components/PageHeader.vue';
import { useUserStatistics } from '../composables/useUserStatistics';

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
  chartData,
  hasChartData,
  summaryCards,
  keywords,
  referencedDocs,
  queryIssues,
  openingDocId,
  docOpenError,
  loadAllStatistics,
  logout,
  openOriginalDocument,
  trendIcon,
  docIcon,
  formatNumber,
  formatDateTime,
} = useUserStatistics();

const queryChartRef = ref(null);
let queryChart = null;

const currentChartData = computed(() => ({
  labels: chartData.value.labels,
  queries: chartData.value.queries,
  costs: chartData.value.costs,
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
          return context.dataset.yAxisID === 'y1' ? `${context.dataset.label}: $${Number(value).toFixed(4)}` : `${context.dataset.label}: ${value}`;
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
    data: currentChartData.value.queries,
    backgroundColor: 'rgba(59, 130, 246, 0.7)',
    borderColor: '#3b82f6',
    borderWidth: 0,
    borderRadius: 4,
    yAxisID: 'y',
  },
  {
    type: 'line',
    label: 'API 사용 비용 ($)',
    data: currentChartData.value.costs,
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
        labels: currentChartData.value.labels,
        datasets: makeDatasets(),
      },
      options: chartOptions,
    });
    return;
  }

  queryChart.data.labels = currentChartData.value.labels;
  queryChart.data.datasets = makeDatasets();
  queryChart.update();
};

watch(currentChartData, renderChart, { deep: true, immediate: true });
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

.stat-card.purple::before {
  background: #8b5cf6;
}

.stat-card.teal::before {
  background: #14b8a6;
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

.card {
  padding: 1.5rem;
  min-width: 0;
}

.card-header {
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

.card-header .card-title {
  margin-bottom: 0;
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

.badge-error {
  background: #fee2e2;
  color: #dc2626;
}

@media (max-width: 1100px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .charts-grid,
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

  .card-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .date-filter {
    width: 100%;
  }

  .filter-btn {
    flex: 1;
  }
}

@media (max-width: 520px) {
  .summary-grid {
    grid-template-columns: 1fr;
  }
}

/* 2026.11.02(woojin.jung) 수정 - 반응형(태블릿/모바일) 대응 */
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

