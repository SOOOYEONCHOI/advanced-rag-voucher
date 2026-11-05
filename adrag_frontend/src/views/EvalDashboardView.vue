<!-- 2026.07.22(sychoi) 추가 - RAG 평가 추이/비교 대시보드 (P5) -->
<template>
  <div class="admin-layout">
    <AdminSidebar :isOpen="sidebarOpen" activePage="eval-dashboard" :isAdmin="isAdmin"
      :displayName="displayName" @close="sidebarOpen = false" @logout="logout" />

    <div class="admin-main">
      <header class="admin-header">
        <div class="header-left">
          <button class="btn-hamburger" @click="sidebarOpen = true"><i class="fa-solid fa-bars"></i></button>
          <div class="header-text">
            <h1>평가 대시보드 <span class="admin-badge">관리자</span></h1>
            <p>실행(run) 간 주요 지표 5개와 보조 지표 2개의 추이 및 비교 결과를 확인합니다.</p>
          </div>
        </div>
        <div class="header-actions">
          <button class="refresh-btn" :disabled="isLoading" @click="refreshAll" title="새로고침">
            <i class="fa-solid fa-rotate-right" :class="{ 'fa-spin': isLoading }"></i>
          </button>
        </div>
      </header>

      <main class="admin-content">
        <div v-if="loadError" class="alert error"><i class="fa-solid fa-circle-exclamation"></i> {{ loadError }}</div>

        <!-- 추이 -->
        <section class="card">
          <div class="card-title">
            <i class="fa-solid fa-chart-line"></i> 평가 지표 추이
            <span class="filters">
              <select v-model="trendDatasetFilter" @change="syncTrendRunSelection">
                <option value="">전체 데이터셋</option>
                <option v-for="d in datasetOptions" :key="d" :value="d">{{ d }}</option>
              </select>
            </span>
          </div>

          <!-- 2026.07.24(sychoi) 추가 - run 개별 선택(비어있으면 전체 표시) -->
          <div v-if="trendRunOptions.length" class="run-picker trend-run-picker">
            <label v-for="r in trendRunOptions" :key="r.run_id" class="run-chip"
                   :class="{ on: trendRunIds.includes(r.run_id) }"
                   :title="(r.created_at || '').slice(0, 16).replace('T', ' ')">
              <input type="checkbox" :value="r.run_id" v-model="trendRunIds" />
              {{ r.history_sequence }}. {{ formatRunScope(r.run_type) }}
              <span class="muted">{{ r.dataset_name }}</span>
            </label>
            <span class="picker-hint">
              {{ trendRunIds.length ? `${trendRunIds.length}개 run 선택됨` : `전체 ${trendRunOptions.length}개 run 표시 중` }}
            </span>
          </div>

          <div class="metric-picker">
            <span class="metric-picker-label">주요</span>
            <label v-for="m in PRIMARY_KPI_METRICS" :key="m.key" class="metric-chip"
                   :class="{ on: selectedMetrics.includes(m.key) }">
              <input type="checkbox" :checked="selectedMetrics.includes(m.key)" @change="onToggleMetric(m.key)" />
              {{ m.label }}
            </label>
            <span class="metric-picker-label secondary">보조</span>
            <label v-for="m in SECONDARY_METRICS" :key="m.key" class="metric-chip"
                   :class="{ on: selectedMetrics.includes(m.key) }">
              <input type="checkbox" :checked="selectedMetrics.includes(m.key)" @change="onToggleMetric(m.key)" />
              {{ m.label }}
            </label>
          </div>

          <div v-if="!hasTrendData" class="empty-state">
            <i class="fa-regular fa-chart-bar"></i>
            <p>완료된 실행(run)이 없거나 선택한 지표의 데이터가 없습니다.</p>
          </div>
          <div v-show="hasTrendData" class="chart-container">
            <canvas ref="trendChartRef" aria-label="평가 지표 추이"></canvas>
          </div>
        </section>

        <!-- run 비교 -->
        <section class="card">
          <div class="card-title">
            <i class="fa-solid fa-code-compare"></i> 실행 비교
            <span class="filters">
              <select v-model="compareDatasetFilter">
                <option value="">전체 데이터셋</option>
                <option v-for="d in datasetOptions" :key="d" :value="d">{{ d }}</option>
              </select>
              <button class="btn-mini" :disabled="compareRunIds.length < 2" @click="loadCompare">
                비교 ({{ compareRunIds.length }})
              </button>
            </span>
          </div>

          <p v-if="!compareRunOptions.length" class="hint">완료된 실행이 없습니다.</p>
          <div v-else class="run-picker">
            <label v-for="r in compareRunOptions" :key="r.run_id" class="run-chip"
                   :class="{ on: compareRunIds.includes(r.run_id) }">
              <input type="checkbox" :value="r.run_id" v-model="compareRunIds" />
              {{ r.history_sequence }}. {{ formatRunScope(r.run_type) }}
              <span class="muted">{{ r.dataset_name }}</span>
            </label>
          </div>

          <div v-if="compareTable.runs.length" class="compare-wrap">
            <table class="data-table compare">
              <thead>
                <tr>
                  <th class="metric-col">지표</th>
                  <!-- 2026.07.24(sychoi) 수정 - 데이터셋·골드셋버전 표기(runs 조인) -->
                  <th v-for="r in compareTable.runs" :key="r.run_id">
                    {{ r.history_sequence }}.
                    <div class="muted th-sub">
                      <template v-if="r.dataset_name">{{ r.dataset_name }}<template v-if="r.goldset_version"> v{{ r.goldset_version }}</template> · </template>{{ formatRunScope(r.run_type) }}
                    </div>
                  </th>
                </tr>
              </thead>
              <tbody v-for="g in compareTable.groups" :key="g.name">
                <!-- 2026.07.24(sychoi) 수정 - '기타' 그룹은 접기/펼치기 토글 -->
                <tr class="group-row">
                  <td :colspan="compareTable.runs.length + 1">
                    <button v-if="g.name === '기타'" class="group-toggle" @click="showOtherMetrics = !showOtherMetrics">
                      <i class="fa-solid" :class="showOtherMetrics ? 'fa-chevron-down' : 'fa-chevron-right'"></i>
                      세부 지표 {{ g.items.length }}개 {{ showOtherMetrics ? '접기' : '더보기' }}
                    </button>
                    <template v-else>{{ g.name }}</template>
                  </td>
                </tr>
                <template v-if="g.name !== '기타' || showOtherMetrics">
                  <tr v-for="m in g.items" :key="m.key">
                    <td class="metric-col">{{ m.label }}</td>
                    <!-- 배경은 run 간 상대 비교, 아이콘은 주요 지표별 목표 달성 여부 -->
                    <td v-for="r in compareTable.runs" :key="r.run_id"
                        :class="compareValueClass(m, r)"
                        :title="r.stds[m.key] != null ? ('± ' + formatCompareValue(r.stds[m.key], m)) : ''">
                      {{ formatCompareValue(r.values[m.key], m) }}
                      <i v-if="kpiTargetMark(m.key, r.values[m.key])" class="kpi-mark fa-solid"
                         :class="kpiTargetMark(m.key, r.values[m.key]) === 'pass' ? 'fa-circle-check pass' : 'fa-circle-xmark fail'"
                         :title="kpiTargetMark(m.key, r.values[m.key]) === 'pass'
                           ? `목표 ${(kpiTarget(m.key) * 100).toFixed(0)}% 달성`
                           : `목표 ${(kpiTarget(m.key) * 100).toFixed(0)}% 미달`"></i>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
            <!-- 2026.07.24(sychoi) 추가 - 두 색상 인코딩 범례 -->
            <p class="compare-legend">
              <span class="lg-swatch best"></span> run 간 최고
              <span class="lg-swatch worst"></span> run 간 최저
              <span class="lg-sep">·</span>
              <i class="fa-solid fa-circle-check pass"></i> 주요 지표별 목표 달성
              <i class="fa-solid fa-circle-xmark fail"></i> 주요 지표별 목표 미달
              <span class="lg-sep">·</span> 보조 지표는 목표 판정 없음
            </p>
          </div>
        </section>
      </main>
    </div>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import {
  CategoryScale, Chart, Legend, LinearScale, LineController, LineElement, PointElement, Tooltip,
} from 'chart.js';
import AdminSidebar from '../components/AdminSidebar.vue';
import { useEvalDashboard } from '../composables/useEvalDashboard';

// 기존 AdminStatisticsView와 동일한 트리셰이킹 등록 패턴 (신규 의존성 없음)
Chart.register(CategoryScale, Legend, LinearScale, LineController, LineElement, PointElement, Tooltip);

const {
  isAdmin, displayName, sidebarOpen, isLoading, loadError,
  selectedMetrics, trendChartData, hasTrendData,
  datasetOptions, trendDatasetFilter,
  trendRunIds, trendRunOptions, syncTrendRunSelection,
  compareRunIds, compareTable, compareDatasetFilter, compareRunOptions,
  loadTrend, loadRuns, loadCompare, toggleMetric, logout,
  formatCompareValue, compareValueClass, kpiTargetMark, kpiTarget, formatRunScope,
  TREND_METRICS, PRIMARY_KPI_METRICS, SECONDARY_METRICS, KPI_TARGETS,
} = useEvalDashboard();

// 비교 표의 '기타' 그룹 접기/펼치기 (뷰 로컬 상태)
const showOtherMetrics = ref(false);

const trendChartRef = ref(null);
let trendChart = null;

const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  plugins: {
    // 2026.07.24(sychoi) 수정 - 범례를 차트 하단으로 이동(목표선 포함 전체 계열 표기)
    legend: { position: 'bottom', labels: { boxWidth: 24, font: { size: 11 }, padding: 14 } },
    tooltip: {
      callbacks: {
        label(ctx) {
          const v = ctx.parsed.y;
          return v == null ? `${ctx.dataset.label}: -` : `${ctx.dataset.label}: ${(v * 100).toFixed(1)}%`;
        },
      },
    },
  },
  scales: {
    // 실행 이력 화면과 동일한 순번을 x축에 표시한다.
    x: {
      grid: { display: true, color: '#f1f5f9' },
      ticks: { color: '#64748b' },
      title: { display: true, text: '실행 이력 순번', font: { size: 11 } },
    },
    y: {
      beginAtZero: true, suggestedMax: 1,
      grid: { color: '#f1f5f9' },
      ticks: { color: '#64748b', callback: (v) => `${(v * 100).toFixed(0)}%` },
    },
  },
};

const makeDatasets = () => {
  const { labels } = trendChartData.value;
  const series = trendChartData.value.datasets.map((d) => ({
    label: d.label,
    data: d.data,
    borderColor: d.color,
    backgroundColor: d.color,
    borderWidth: 2,
    pointRadius: 3,
    spanGaps: true,
    tension: 0.2,
  }));
  // 선택된 주요 지표의 고유 목표값만 점선으로 표시한다.
  if (labels.length) {
    const selectedTargets = [...new Set(
      selectedMetrics.value
        .map((key) => KPI_TARGETS[key])
        .filter((target) => typeof target === 'number')
    )].sort((a, b) => b - a);
    selectedTargets.forEach((target) => series.push({
      label: `목표 ${(target * 100).toFixed(0)}%`,
      data: labels.map(() => target),
      borderColor: '#94a3b8',
      backgroundColor: 'transparent',
      borderDash: [6, 4],
      borderWidth: 1.5,
      pointRadius: 0,
      spanGaps: true,
      tension: 0,
    }));
  }
  return series;
};

const renderChart = async () => {
  await nextTick();
  if (!trendChartRef.value || !hasTrendData.value) return;
  if (!trendChart) {
    trendChart = new Chart(trendChartRef.value, {
      type: 'line',
      data: { labels: trendChartData.value.labels, datasets: makeDatasets() },
      options: chartOptions,
    });
    return;
  }
  trendChart.data.labels = trendChartData.value.labels;
  trendChart.data.datasets = makeDatasets();
  trendChart.update();
};

const onToggleMetric = async (key) => {
  toggleMetric(key);
  await loadTrend();   // 선택 지표가 바뀌면 서버에서 다시 조회
};

const refreshAll = async () => {
  await Promise.all([loadRuns(), loadTrend()]);
};

watch(trendChartData, renderChart, { deep: true });

onMounted(async () => {
  await refreshAll();
  await renderChart();
});

onBeforeUnmount(() => {
  if (trendChart) { trendChart.destroy(); trendChart = null; }
});
</script>

<style scoped>
/* 기존 관리 화면(AdminStatisticsView/UserPermissionsView)과 동일한 레이아웃 여백 */
/* 헤더 고정 + 콘텐츠 영역만 스크롤 (통계 화면과 동일 구조) */
.admin-layout { display: flex; height: 100dvh; overflow: hidden; background: #f1f5f9; color: #0f172a;
  font-family: Inter, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif; }
.admin-main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; }
.admin-header { display: flex; justify-content: space-between; align-items: center;
  padding: 1.25rem 2rem; background: #fff; border-bottom: 1px solid #e2e8f0; flex-shrink: 0; gap: 1rem; }
.header-left { display: flex; align-items: center; gap: 0.75rem; }
.header-text h1 { font-size: 1.25rem; font-weight: 700; }
.header-text p { color: #64748b; font-size: 0.85rem; margin-top: 2px; }
.admin-badge { font-size: 0.65rem; background: #fef3c7; color: #b45309; padding: 2px 8px; border-radius: 10px; }
.btn-hamburger { display: none; background: none; border: none; font-size: 1.2rem; cursor: pointer; }
.refresh-btn { background: #fff; border: 1px solid #cbd5e1; border-radius: 8px; width: 36px; height: 36px; cursor: pointer; color: #475569; }
.admin-content { flex: 1; padding: 1.5rem 2rem; overflow-y: auto; display: flex; flex-direction: column; gap: 1.25rem; }
.card { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 1.5rem; }
.card-title { font-weight: 700; font-size: 0.95rem; margin-bottom: 0.9rem; display: flex; align-items: center; gap: 8px; }
.card-title .filters { margin-left: auto; display: flex; gap: 0.5rem; align-items: center; font-weight: 400; }
.metric-picker { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 1rem; }
.metric-picker-label { align-self: center; color: #334155; font-size: 0.75rem; font-weight: 700; }
.metric-picker-label.secondary { margin-left: 0.4rem; }
.metric-chip { font-size: 0.75rem; border: 1px solid #cbd5e1; border-radius: 14px; padding: 3px 10px; cursor: pointer; color: #64748b; display: inline-flex; align-items: center; gap: 5px; }
.metric-chip.on { background: #eff6ff; border-color: #93c5fd; color: #1d4ed8; }
.metric-chip input { display: none; }
.chart-container { height: 320px; }
.empty-state { text-align: center; color: #94a3b8; padding: 2.5rem 0; }
.empty-state i { font-size: 1.6rem; margin-bottom: 0.5rem; }
.run-picker { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 1rem; }
.run-chip { font-size: 0.76rem; border: 1px solid #cbd5e1; border-radius: 8px; padding: 4px 10px; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }
.run-chip.on { background: #eff6ff; border-color: #93c5fd; }
.run-chip input { margin: 0; }
.muted { color: #94a3b8; }
.hint { color: #94a3b8; font-size: 0.82rem; }
.compare-wrap { overflow-x: auto; }
.data-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
.data-table th { text-align: left; color: #64748b; font-weight: 600; padding: 0.45rem 0.6rem; border-bottom: 1px solid #e2e8f0; white-space: nowrap; }
.data-table td { padding: 0.4rem 0.6rem; border-bottom: 1px solid #f1f5f9; white-space: nowrap; }
.th-sub { font-size: 0.7rem; font-weight: 400; }
.metric-col { min-width: 180px; }
.group-row td { background: #f8fafc; font-weight: 700; color: #475569; font-size: 0.78rem; }
.data-table td.good { color: #15803d; font-weight: 600; }
.data-table td.bad { color: #b91c1c; font-weight: 600; }
/* 2026.07.24(sychoi) 추가 - run 간 최고/최저 하이라이트 */
.data-table td.best-cell { background: #f0fdf4; color: #15803d; font-weight: 700; }
.data-table td.worst-cell { background: #fef2f2; color: #b91c1c; }
/* '기타' 그룹 접기 토글 */
.group-toggle { background: none; border: none; color: #475569; font-weight: 700; font-size: 0.78rem; cursor: pointer; padding: 0; display: inline-flex; align-items: center; gap: 6px; }
.group-toggle:hover { color: #2563eb; }
/* 추이 run-picker 힌트 */
.trend-run-picker { align-items: center; }
.picker-hint { font-size: 0.74rem; color: #94a3b8; }
/* 핵심 KPI 목표 달성 마커 (배경 하이라이트와 병행) */
.kpi-mark { margin-left: 5px; font-size: 0.72rem; }
.kpi-mark.pass, .compare-legend .pass { color: #16a34a; }
.kpi-mark.fail, .compare-legend .fail { color: #dc2626; }
.compare-legend { margin-top: 0.7rem; font-size: 0.74rem; color: #64748b; display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.compare-legend .lg-swatch { display: inline-block; width: 12px; height: 12px; border-radius: 3px; }
.compare-legend .lg-swatch.best { background: #f0fdf4; border: 1px solid #86efac; }
.compare-legend .lg-swatch.worst { background: #fef2f2; border: 1px solid #fca5a5; }
.compare-legend .lg-sep { color: #cbd5e1; margin: 0 2px; }
.btn-mini { background: #fff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 0.35rem 0.8rem; font-size: 0.78rem; cursor: pointer; }
.btn-mini:disabled { opacity: 0.5; cursor: not-allowed; }
select { padding: 0.4rem 0.6rem; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 0.8rem; }
.alert.error { background: #fef2f2; color: #b91c1c; padding: 0.7rem 1rem; border-radius: 8px; font-size: 0.85rem; }
/* 2026.11.02(woojin.jung) 수정 - 반응형(태블릿/모바일) 대응 */
@media (max-width: 1024px) {
  .admin-header { padding: 1rem 1.5rem; }
  .admin-content { padding: 1.25rem 1.5rem; }
  .card-title { flex-wrap: wrap; }
  .chart-container { position: relative; min-width: 0; }
}
/* 2026.11.03(woojin.jung) 수정 - 태블릿 가로는 데스크톱, 세로는 모바일 레이아웃(사이드바 숨김) */
@media (max-width: 768px), (max-width: 1024px) and (orientation: portrait), (max-width: 1024px) and (max-height: 500px) {
  .btn-hamburger { display: grid; place-items: center; width: 40px; height: 40px; flex-shrink: 0; }
}
@media (max-width: 768px) {
  .admin-header { padding: 0.85rem 1rem; }
  .header-text h1 { font-size: 1.1rem; }
  .header-text p { display: none; }
  .refresh-btn { width: 40px; height: 40px; flex-shrink: 0; }
  .admin-content { padding: 1rem; gap: 1rem; }
  .card { padding: 1rem; }
  .card-title .filters { margin-left: 0; width: 100%; }
  .card-title .filters select { flex: 1; min-width: 0; }
  .btn-mini { min-height: 36px; }
  .chart-container { height: 380px; }
  .metric-col { min-width: 140px; }
}
</style>
