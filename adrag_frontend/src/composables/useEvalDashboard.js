// 2026.07.22(sychoi) 추가 - RAG 평가: 추이/비교 대시보드 로직 (P5)
import { storeToRefs } from 'pinia';
import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';
import { evalApi } from '../api/evalApi';
import { useAuthStore } from '../stores/authStore';

export const KPI_TARGETS = Object.freeze({
  'retrieval.rrf.recall@10': 0.80,
  'retrieval.rerank.ndcg@5': 0.80,
  'answer.correctness': 0.80,
  'answer.correctness.v1': 0.80,
  'answer.correctness.v2': 0.80,
  'answer.correctness.judge': 0.80,
  'answer.correctness.f2': 0.80,
  // 하위 호환 — 이전 평가 run 표시용
  'answer.correctness_v2_shadow': 0.80,
  'answer.correctness_v2_f2_shadow': 0.80,
  'citation.correctness': 0.80,
  'citation.completeness': 0.80,
});

export const PRIMARY_KPI_METRICS = [
  { key: 'retrieval.rrf.recall@10', label: 'Retriever Recall@10' },
  { key: 'retrieval.rerank.ndcg@5', label: 'Reranked NDCG@5' },
  { key: 'answer.correctness', label: 'Answer Correctness' },
  { key: 'answer.correctness.v1', label: 'Answer Correctness (v1)' },
  { key: 'answer.correctness.v2', label: 'Answer Correctness (v2)' },
  { key: 'answer.correctness.judge', label: 'Answer Correctness (Judge)' },
  { key: 'answer.correctness.f2', label: 'Answer Correctness (F2)' },
  { key: 'citation.correctness', label: 'Citation Correctness' },
  { key: 'citation.completeness', label: 'Citation Completeness' },
];

export const SECONDARY_METRICS = [
  { key: 'retrieval.rerank.mrr@5', label: 'Reranked MRR@5' },
  { key: 'retrieval.rrf.ndcg@10', label: 'Retriever NDCG@10' },
];

export const TREND_METRICS = [
  ...PRIMARY_KPI_METRICS,
  ...SECONDARY_METRICS,
];

const METRIC_META = {
  'retrieval.rrf.recall@10': { group: '주요 지표', label: 'Retriever Recall@10', pct: true },
  'retrieval.rerank.ndcg@5': { group: '주요 지표', label: 'Reranked NDCG@5', pct: true },
  'answer.correctness': { group: '주요 지표', label: 'Answer Correctness', pct: true },
  'answer.correctness.v1': { group: '주요 지표', label: 'Answer Correctness (v1)', pct: true },
  'answer.correctness.v2': { group: '주요 지표', label: 'Answer Correctness (v2)', pct: true },
  'answer.correctness.judge': { group: '주요 지표', label: 'Answer Correctness (Judge)', pct: true },
  'answer.correctness.f2': { group: '주요 지표', label: 'Answer Correctness (F2)', pct: true },
  // 하위 호환 — 이전 평가 run 표시용
  'answer.correctness_v2_shadow': { group: '주요 지표', label: 'Answer Correctness (F1, legacy)', pct: true },
  'answer.correctness_v2_f2_shadow': { group: '주요 지표', label: 'Answer Correctness (F2, legacy)', pct: true },
  'citation.correctness': { group: '주요 지표', label: 'Citation Correctness', pct: true },
  'citation.completeness': { group: '주요 지표', label: 'Citation Completeness', pct: true },
  'retrieval.rerank.mrr@5': { group: '보조 지표', label: 'Reranked MRR@5', pct: true },
  'retrieval.rrf.ndcg@10': { group: '보조 지표', label: 'Retriever NDCG@10', pct: true },
};
const GROUP_ORDER = ['주요 지표', '보조 지표'];
const DASHBOARD_METRIC_KEYS = new Set(Object.keys(METRIC_META));
const metaFor = (key) => METRIC_META[key] || { group: '기타', label: key, pct: false };

// 차트 색상 팔레트 (핵심 KPI 4종 우선)
export const CHART_COLORS = ['#2563eb', '#16a34a', '#f59e0b', '#8b5cf6', '#ef4444', '#0891b2', '#db2777'];

export const useEvalDashboard = () => {
  const router = useRouter();
  const authStore = useAuthStore();
  const { isAdmin, displayName } = storeToRefs(authStore);

  const sidebarOpen = ref(false);
  const isLoading = ref(false);
  const loadError = ref('');

  const selectedMetrics = ref(PRIMARY_KPI_METRICS.map((m) => m.key));
  const trendItems = ref([]);

  const runs = ref([]);
  const compareRunIds = ref([]);
  const compareItems = ref([]);
  const compareDatasetFilter = ref('');
  const trendDatasetFilter = ref('');

  const datasetOptions = computed(() =>
    [...new Set(runs.value.map((r) => r.dataset_name).filter(Boolean))]
  );
  const compareRunOptions = computed(() =>
    runs.value.filter((r) => !compareDatasetFilter.value || r.dataset_name === compareDatasetFilter.value)
  );

  // 2026.07.24(sychoi) 추가 - 추이 차트 run 개별 선택(비어있으면 전체). 데이터셋 필터에 종속.
  const trendRunIds = ref([]);
  const trendRunOptions = computed(() =>
    runs.value.filter((r) => !trendDatasetFilter.value || r.dataset_name === trendDatasetFilter.value)
  );
  // 데이터셋 필터가 바뀌면 그 데이터셋에 속하지 않는 run 선택은 정리
  const syncTrendRunSelection = () => {
    const allowed = new Set(trendRunOptions.value.map((r) => r.run_id));
    trendRunIds.value = trendRunIds.value.filter((id) => allowed.has(id));
  };

  // 추이 데이터 → Chart.js 형태 (데이터셋 필터 적용)
  const trendChartData = computed(() => {
    const byRun = new Map();
    const runsById = new Map(runs.value.map((r) => [r.run_id, r]));
    for (const item of trendItems.value) {
      if (trendDatasetFilter.value && item.dataset_name !== trendDatasetFilter.value) continue;
      if (trendRunIds.value.length && !trendRunIds.value.includes(item.run_id)) continue;
      if (!byRun.has(item.run_id)) {
        const historySequence = runsById.get(item.run_id)?.history_sequence;
        byRun.set(item.run_id, {
          run_id: item.run_id, label: `${historySequence || item.run_id}.`,
          dataset_name: item.dataset_name, values: {},
        });
      }
      byRun.get(item.run_id).values[item.metric_key] = item.metric_value;
    }
    const points = [...byRun.values()].sort((a, b) => a.run_id - b.run_id);
    return {
      labels: points.map((p) => p.label),
      datasets: selectedMetrics.value.map((key, i) => ({
        key,
        label: TREND_METRICS.find((m) => m.key === key)?.label || key,
        data: points.map((p) => (key in p.values ? p.values[key] : null)),
        color: CHART_COLORS[i % CHART_COLORS.length],
      })),
    };
  });

  const hasTrendData = computed(() => trendChartData.value.labels.length > 0);

  // 비교 표: 그룹(검색/인용/답변/운영)별 한글 라벨.
  // 2026.07.24(sychoi) 수정 - .std를 버리지 않고 stds 맵으로 보존(셀 ± 툴팁),
  //   compare 응답에 없는 dataset_name/goldset_version은 runs 목록과 run_id로 조인(백엔드 무변경).
  const compareTable = computed(() => {
    if (!compareItems.value.length) return { groups: [], runs: [] };
    const runsById = new Map(runs.value.map((r) => [r.run_id, r]));
    const keys = new Set();
    for (const run of compareItems.value) {
      for (const m of run.metrics || []) {
        if (
          m.segment === 'all'
          && !m.metric_key.endsWith('.std')
          && DASHBOARD_METRIC_KEYS.has(m.metric_key)
        ) {
          keys.add(m.metric_key);
        }
      }
    }
    const runsData = compareItems.value.map((run) => {
      const map = {};
      const stds = {};
      for (const m of run.metrics || []) {
        if (m.segment !== 'all') continue;
        if (m.metric_key.endsWith('.std')) stds[m.metric_key.slice(0, -4)] = m.metric_value;
        else map[m.metric_key] = m.metric_value;
      }
      const meta = runsById.get(run.run_id) || {};
      return {
        run_id: run.run_id, run_type: run.run_type, created_at: run.created_at,
        dataset_name: meta.dataset_name, goldset_version: meta.goldset_version,
        history_sequence: meta.history_sequence,
        values: map, stds,
      };
    });

    const byGroup = new Map();
    for (const key of keys) {
      const meta = metaFor(key);
      if (!byGroup.has(meta.group)) byGroup.set(meta.group, []);
      byGroup.get(meta.group).push({ key, ...meta });
    }
    const groups = GROUP_ORDER.filter((g) => byGroup.has(g)).map((g) => ({
      name: g,
      items: byGroup.get(g).sort((a, b) => a.label.localeCompare(b.label)),
    }));
    return { groups, runs: runsData };
  });

  const loadTrend = async () => {
    if (!selectedMetrics.value.length) return;
    isLoading.value = true;
    loadError.value = '';
    try {
      const { data } = await evalApi.trend(selectedMetrics.value, undefined, 100);
      trendItems.value = data.items || [];
    } catch (e) {
      loadError.value = e.response?.data?.detail || '추이 데이터를 불러오지 못했습니다.';
    } finally {
      isLoading.value = false;
    }
  };

  const loadRuns = async () => {
    try {
      const { data } = await evalApi.listRuns();
      const items = data.items || [];
      runs.value = items
        .map((run, index) => ({ ...run, history_sequence: items.length - index }))
        .filter((run) => run.status === 'completed');
    } catch {
      runs.value = [];
    }
  };

  const loadCompare = async () => {
    if (compareRunIds.value.length < 2) {
      loadError.value = '비교할 run을 2개 이상 선택하세요.';
      return;
    }
    loadError.value = '';
    try {
      const { data } = await evalApi.compare(compareRunIds.value);
      compareItems.value = data.items || [];
    } catch (e) {
      loadError.value = e.response?.data?.detail || '비교 데이터를 불러오지 못했습니다.';
    }
  };

  const toggleMetric = (key) => {
    const idx = selectedMetrics.value.indexOf(key);
    if (idx >= 0) selectedMetrics.value.splice(idx, 1);
    else selectedMetrics.value.push(key);
  };

  const logout = async () => {
    await authStore.logoutAny();
    router.push('/login');
  };

  // 비교 셀 표시 — 지표 성격에 맞춰 %/점수/원값
  const formatCompareValue = (value, meta) => {
    if (typeof value !== 'number') return '-';
    if (meta.pct) return `${(value * 100).toFixed(1)}%`;
    if (meta.scaleMax) return `${value.toFixed(2)} / ${meta.scaleMax}`;
    return value.toFixed(2);
  };

  // 2026.07.24(sychoi) 수정 - 비교 대상(3+ run) 중 지표별 최고/최저 하이라이트.
  //   invert(오류율·지연처럼 낮을수록 좋음) 지표는 최고/최저 판정을 뒤집는다.
  //   (기존 임계 good/bad 대신 run 간 상대 비교로 전환 — reference 파리티)
  const compareValueClass = (item, run) => {
    const values = compareTable.value.runs
      .map((r) => r.values[item.key])
      .filter((v) => typeof v === 'number');
    if (values.length < 2) return '';
    const value = run.values[item.key];
    if (typeof value !== 'number') return '';
    const max = Math.max(...values);
    const min = Math.min(...values);
    if (max === min) return '';
    const bestIsMax = !item.invert;
    if ((value === max && bestIsMax) || (value === min && !bestIsMax)) return 'best-cell';
    if ((value === min && bestIsMax) || (value === max && !bestIsMax)) return 'worst-cell';
    return '';
  };

  const kpiTargetMark = (key, value) => {
    if (typeof value !== 'number') return '';
    const target = KPI_TARGETS[key];
    if (typeof target !== 'number') return '';
    const pass = value >= target;
    return pass ? 'pass' : 'fail';
  };
  const kpiTarget = (key) => KPI_TARGETS[key] ?? null;
  const formatRunScope = (runType) => ({
    full: '전체 RAG 평가',
    retrieval: '검색·재정렬 평가',
  })[runType] || runType || '-';

  return {
    isAdmin, displayName, sidebarOpen, isLoading, loadError,
    selectedMetrics, trendItems, trendChartData, hasTrendData,
    runs, datasetOptions, trendDatasetFilter,
    trendRunIds, trendRunOptions, syncTrendRunSelection,
    compareRunIds, compareItems, compareTable, compareDatasetFilter, compareRunOptions,
    loadTrend, loadRuns, loadCompare, toggleMetric, logout,
    formatCompareValue, compareValueClass, kpiTargetMark, kpiTarget, formatRunScope,
    TREND_METRICS, PRIMARY_KPI_METRICS, SECONDARY_METRICS, KPI_TARGETS,
  };
};
