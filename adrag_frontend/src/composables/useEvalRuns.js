// 2026.07.22(sychoi) 추가 - RAG 평가: 실행/결과 화면 로직 (P3-③ 최소 UI)
import { storeToRefs } from 'pinia';
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { evalApi } from '../api/evalApi';
import { useAuthStore } from '../stores/authStore';

const POLL_INTERVAL_MS = 3000;

const QUESTION_TYPE_LABELS = {
  factual: '사실형', procedural: '절차형', comparative: '비교형', multihop: '멀티홉',
  // 2026.11.19(sooyeon.choi) 추가 - 단일 출처 생성 문항
  law: '법령', general: '일반',
};
// 2026.11.19(sooyeon.choi) 추가 - 항목별 결과 '문제 항목' 판정용 지표 4 목표(첫 토큰 반환 시간, ms)
const FIRST_TOKEN_TARGET_MS = 5000;

const STATUS_LABELS = {
  pending: '대기', running: '실행 중', completed: '완료', failed: '실패', cancelled: '취소됨',
};

const RUN_TYPE_LABELS = {
  retrieval: '검색·재정렬', full: '전체 RAG',
};

export const useEvalRuns = () => {
  const router = useRouter();
  const authStore = useAuthStore();
  const { isAdmin, displayName } = storeToRefs(authStore);

  const sidebarOpen = ref(false);
  const isLoading = ref(false);
  const loadError = ref('');

  const goldsets = ref([]);
  const runs = ref([]);
  const selectedRun = ref(null);
  const runResults = ref([]);
  const resultsTotal = ref(0);
  const resultsPage = ref(1);
  const resultsPageSize = ref(20);
  const detailItem = ref(null);
  const deleteRunId = ref(null);
  const isDeletingRun = ref(false);
  const downloadingRunId = ref(null);

  const resultsTypeFilter = ref('');
  const resultsLawFilter = ref(''); // 2026.11.20(sooyeon.choi) 수정 - 합본 실행 법령 필터
  const resultsFailedOnly = ref(false);
  const resultsSortBy = ref('worst'); // 'worst'(낮은 점수부터) | 'dataset_sequence'(번호순)

  const runForm = ref({
    goldset_id: null,
    scope: 'full',
    retrieval_top_n: 10,
    rerank_top_k: 5,
  });

  const toast = ref({ visible: false, message: '', type: 'success' });
  let toastTimer = null;
  const showToast = (message, type = 'success') => {
    if (toastTimer) clearTimeout(toastTimer);
    toast.value = { visible: true, message, type };
    toastTimer = setTimeout(() => { toast.value.visible = false; }, 2500);
  };

  let pollTimer = null;

  const isRunning = computed(() => ['pending', 'running'].includes(selectedRun.value?.status));
  const isFullRun = computed(() => (selectedRun.value?.scope || selectedRun.value?.run_type) === 'full');
  // 2026.11.20(sooyeon.choi) 수정 - 합본 실행: 법령별 값(같은 실행 항목을 법령으로 나눈 참고 값)·법령 열
  const isMergedRun = computed(() => selectedRun.value?.dataset_kind === 'merged');
  const lawMetrics = computed(() => selectedRun.value?.law_metrics || []);
  const lawOptions = computed(() => lawMetrics.value.map((row) => row.law));
  const lawShortLabel = (law) => law || ''; // 법령 이름 그대로(축약 시 혼동 방지)
  const lawBreakdown = (kpi) => lawMetrics.value
    .map((row) => {
      const value = row.metrics?.[kpi.key];
      if (!value) return null;
      return `${lawShortLabel(row.law)} ${formatMetricState({ ...kpi, ...value, status: value.value == null ? 'excluded' : 'evaluated' })}`;
    })
    .filter(Boolean)
    .join(' · ');
  const progressPercent = computed(() => {
    const run = selectedRun.value;
    if (!run || !run.progress_total) return 0;
    return Math.round((run.progress_done / run.progress_total) * 100);
  });
  const resultsTotalPages = computed(() =>
    Math.max(1, Math.ceil(resultsTotal.value / resultsPageSize.value))
  );

  const runCutoffs = computed(() => {
    let config = selectedRun.value?.config || selectedRun.value?.config_json || {};
    if (typeof config === 'string') {
      try { config = JSON.parse(config); } catch { config = {}; }
    }
    return {
      n: Number(config.retrieval_top_n ?? config.top_k) || 10,
      k: Number(config.rerank_top_k) || 5,
    };
  });

  const _catalogKpi = (metric) => {
    // 인증 목표는 서버 카탈로그에 정의된 공식 지표에만 적용한다.
    const target = metric.target ?? null;
    const invert = metric.direction === 'le';
    const notMeasured = metric.status === 'not_measured';
    // 2026.11.23(sooyeon.choi) 수정 - 평가 진행 중에는 값이 없는 필수 지표를 '미측정' 대신 '평가 중'으로 표시
    if (notMeasured && isRunning.value) {
      return { ...metric, status: 'measuring', target, invert, pass: null, desc: '평가가 끝나면 집계합니다' };
    }
    return {
      ...metric,
      status: metric.status === 'incomplete' ? 'incomplete' : notMeasured ? 'not_measured' : metric.evaluated_count > 0
        ? 'evaluated' : metric.error_count > 0 ? 'error' : 'excluded',
      target,
      invert,
      pass: metric.value == null || target == null ? null : invert ? metric.value <= target : metric.value >= target,
      desc: notMeasured
        ? `미측정 · ${metric.not_measured_reason || ''}`
        : `${metric.evaluated_count}/${metric.total_count}건 평가 · 제외 ${metric.excluded_count}건 · 오류 ${metric.error_count}건`,
    };
  };

  const primaryKpis = computed(() => (selectedRun.value?.primary_metrics || []).map(_catalogKpi));
  // 2026.11.19(sooyeon.choi) 수정 - 서버 카탈로그 group(search/answer) 기준으로 나눔
  const searchKpis = computed(() => primaryKpis.value.filter(
    (metric) => (metric.group ? metric.group === 'search' : metric.key.startsWith('retrieval.')),
  ));
  const hasSearchKpis = computed(() => searchKpis.value.length > 0);

  const secondaryKpis = computed(() => (selectedRun.value?.secondary_metrics || []).map(
    (metric) => _catalogKpi({ ...metric, target: null }),
  ));

  // 답변 및 인용 주요 지표는 전체 RAG 평가에서만 노출한다.
  const answerKpis = computed(() => {
    const visibleKeys = new Set([
      'answer.correctness',
      'citation.completeness',
    ]);
    // 2026.11.19(sooyeon.choi) 수정 - 지표 4 카드에 함께 볼 지표(companion_key, 예: 전체 반환 시간)를 붙인다
    return primaryKpis.value
      .filter((metric) => (metric.group ? metric.group === 'answer' : visibleKeys.has(metric.key)))
      .map((metric) => {
        const companion = metric.companion_key
          && secondaryKpis.value.find((item) => item.key === metric.companion_key);
        return companion ? { ...metric, companion } : metric;
      });
  });
  const hasAnswerKpis = computed(() => answerKpis.value.length > 0);

  const displayResults = computed(() => {
    let list = runResults.value;
    if (resultsFailedOnly.value) {
      list = list.filter((item) => item.status !== 'ok' || item._failed);
    }
    // 2026.07.24(sychoi) 수정 - 정렬 선택(낮은 점수부터/번호순) 지원
    const sorted = [...list];
    if (resultsSortBy.value === 'dataset_sequence') {
      sorted.sort((a, b) => (a.dataset_sequence ?? 0) - (b.dataset_sequence ?? 0));
    }
    else sorted.sort((a, b) => a._worst - b._worst);
    return sorted;
  });

  // 2026.07.24(sychoi) 추가 - 항목별 결과 페이지 이동 (reference 페이저 복원).
  // 서버가 page 단위로만 결과를 내려주므로 페이저 없이는 page_size 초과 항목에 접근 불가.
  const goToResultsPage = async (page) => {
    const target = Math.min(Math.max(1, page), resultsTotalPages.value);
    if (target === resultsPage.value) return;
    resultsPage.value = target;
    await loadRunResults();
  };

  const loadGoldsets = async () => {
    try {
      const { data } = await evalApi.listGoldsets();
      goldsets.value = data.items || [];
      if (!runForm.value.goldset_id && goldsets.value.length) {
        runForm.value.goldset_id = goldsets.value[0].goldset_id;
      }
    } catch (e) {
      loadError.value = e.response?.data?.detail || '골드셋 목록을 불러오지 못했습니다.';
    }
  };

  const loadRuns = async () => {
    isLoading.value = true;
    try {
      const { data } = await evalApi.listRuns();
      runs.value = data.items || [];
    } catch (e) {
      loadError.value = e.response?.data?.detail || '실행 이력을 불러오지 못했습니다.';
    } finally {
      isLoading.value = false;
    }
  };

  const startRun = async () => {
    if (!runForm.value.goldset_id) {
      loadError.value = '골드셋을 선택하세요.';
      return;
    }
    loadError.value = '';
    // 검색은 항상 실행. 답변평가 포함이면 검색+답변(full), 아니면 검색만(retrieval).
    const scope = runForm.value.scope === 'full' ? 'full' : 'retrieval';
    const topN = Number(runForm.value.retrieval_top_n) || 10;
    const rerankTopK = Number(runForm.value.rerank_top_k) || 5;
    if (topN < 1 || rerankTopK < 1) {
      loadError.value = '검색 후보 수 N과 최종 문서 수 K는 1 이상이어야 합니다.';
      return;
    }
    if (rerankTopK > topN) {
      loadError.value = '최종 문서 수 K는 검색 후보 수 N보다 클 수 없습니다.';
      return;
    }
    const config = {
      retrieval_top_n: topN,
      rerank_top_k: rerankTopK,
      retrieval_channel: 'rrf',
    };
    try {
      const { data } = await evalApi.createRun({
        goldset_id: runForm.value.goldset_id,
        scope,
        config,
      });
      await loadRuns();
      const created = runs.value.find((r) => r.run_id === data.run_id);
      if (created) await selectRun(created);
      const goldset = goldsets.value.find((g) => g.goldset_id === runForm.value.goldset_id);
      const target = goldset ? `'${goldset.dataset_name || goldset.collection_name}' v${goldset.version}` : '';
      const scopeLabel = scope === 'full' ? '전체 RAG' : '검색·재정렬';
      // 2026.08.03(sooyeon.choi) 수정 - 평가 대상과 실행 정보를 의미 단위로 개행
      showToast(`${target} 평가 실행을 시작했습니다.\n${data.total}건 · ${scopeLabel}`);
    } catch (e) {
      showToast(e.response?.data?.detail || '평가 실행 요청에 실패했습니다.', 'error');
    }
  };

  const selectRun = async (run) => {
    stopPolling();
    try {
      const { data } = await evalApi.getRun(run.run_id);
      selectedRun.value = data;
      resultsPage.value = 1;
      await loadRunResults();
      if (isRunning.value) pollTimer = setInterval(refreshSelectedRun, POLL_INTERVAL_MS);
    } catch (e) {
      loadError.value = e.response?.data?.detail || '실행 정보를 불러오지 못했습니다.';
    }
  };

  const refreshSelectedRun = async () => {
    if (!selectedRun.value) return;
    try {
      const { data } = await evalApi.getRun(selectedRun.value.run_id);
      selectedRun.value = data;
      if (!['pending', 'running'].includes(data.status)) {
        stopPolling();
        await Promise.all([loadRunResults(), loadRuns()]);
        if (data.status === 'completed') {
          showToast(`평가 실행이 완료되었습니다.\n총 ${data.progress_done}건을 평가했습니다.`);
        } else if (data.status === 'failed') {
          showToast(`평가 실행에 실패했습니다.\n${data.error_message || '원인 미상'}`, 'error');
        } else if (data.status === 'cancelled') {
          showToast('평가 실행이 취소되었습니다.');
        }
      }
    } catch {
      stopPolling();
    }
  };

  const loadRunResults = async () => {
    if (!selectedRun.value) return;
    try {
      const { data } = await evalApi.listRunResults(selectedRun.value.run_id, {
        type: resultsTypeFilter.value || undefined,
        law: resultsLawFilter.value || undefined,
        page: resultsPage.value,
        pageSize: resultsPageSize.value,
      });
      runResults.value = (data.items || []).map((item) => {
        const retrieval = safeParse(item.retrieval_json, null);
        const citation = safeParse(item.citation_json, null);
        const metrics = item.metrics || safeParse(item.metric_status_json, {});
        const { n, k } = runCutoffs.value;
        const legacyMetric = (value) => typeof value === 'number'
          ? { value, status: 'evaluated', reason: null } : undefined;
        const recallMetric = metrics[`retrieval.rrf.recall@${n}`]
          || legacyMetric(retrieval?.rrf?.[`recall@${n}`]);
        const rerankedNdcgMetric = metrics[`retrieval.rerank.ndcg@${k}`]
          || legacyMetric(retrieval?.rerank?.[`ndcg@${k}`]);
        const correctnessMetric = metrics['answer.correctness']
          || metrics['answer.correctness_v2_shadow'];
        const correctnessJudgeMetric = metrics['answer.correctness.judge'];
        const correctnessF2Metric = metrics['answer.correctness.f2']
          || metrics['answer.correctness_v2_f2_shadow'];
        const correctnessV2F2Metric = correctnessF2Metric;
        const citationCompletenessMetric = metrics['citation.completeness']
          || legacyMetric(citation?.completeness);
        // 2026.11.19(sooyeon.choi) 추가 - 항목별 결과는 주요 지표만: 지표 1 Recall@10(적중 여부), 지표 2 NDCG@5,
        //   지표 4 첫 토큰 반환 시간(전체 반환 시간 함께). 컷오프는 합의서 고정값 10·5
        const hit10Metric = metrics['retrieval.rrf.hit@10'] || legacyMetric(retrieval?.rrf?.['hit@10']);
        const ndcg5Metric = metrics['retrieval.rerank.ndcg@5'] || legacyMetric(retrieval?.rerank?.['ndcg@5']);
        const timing = safeParse(item.timing_json, {}) || {};
        const firstTokenMs = typeof timing.first_token_ms === 'number' ? timing.first_token_ms : null;
        const primaryIssue = hit10Metric?.value === 0 || ndcg5Metric?.value === 0
          || (firstTokenMs != null && firstTokenMs > FIRST_TOKEN_TARGET_MS);
        const recallN = recallMetric?.value ?? null;
        const rerankedNdcg = rerankedNdcgMetric?.value ?? null;
        const citationCompleteness = citationCompletenessMetric?.value ?? null;
        const correctness = correctnessMetric?.value ?? null;
        const citationDiagnostics = citation?.skipped ? {} : (citation || {});
        const citationIssues = [];
        if (citationDiagnostics.invalid_citation_count) {
          citationIssues.push({
            type: 'invalid',
            label: `잘못된 인용 ${citationDiagnostics.invalid_citation_count}건`,
            detail: citationDiagnostics.invalid_numbers?.length
              ? `유효하지 않은 번호: ${citationDiagnostics.invalid_numbers.join(', ')}`
              : '유효하지 않은 인용 번호가 있습니다.',
          });
        }
        if (citationDiagnostics.missing_citation) {
          citationIssues.push({
            type: 'missing',
            label: '필수 인용 누락',
            detail: '답변에 필수 인용 번호가 없습니다.',
          });
        }
        // F2 shadow 오류는 기존 운영 지표의 성공/실패 판정에 영향을 주지 않는다.
        const metricError = Object.entries(metrics).some(
          ([key, metric]) => key !== 'answer.correctness_v2_f2_shadow' && metric?.status === 'error',
        );
        const diagnosticIssue = citationIssues.length > 0;
        // 2026.11.19(sooyeon.choi) 수정 - '낮은 점수부터' 정렬도 주요 지표(지표 1·2) 기준
        const vals = [hit10Metric?.value, ndcg5Metric?.value].filter((v) => typeof v === 'number');
        return {
          ...item,
          retrieval, metrics, citation, citationDiagnostics, citationIssues,
          citationDetail: safeParse(item.citation_detail_json, null),
          // 상세 모달용 골드/근거 데이터 파싱
          goldChunkTexts: safeParse(item.gold_chunk_texts, []),
          goldChunkIds: safeParse(item.gold_chunk_ids, []),
          goldDocumentIds: safeParse(item.gold_document_ids, []),
          goldSourceMeta: safeParse(item.source_meta_json, {}),
          recallN, rerankedNdcg, correctness,
          recallMetric, rerankedNdcgMetric, correctnessMetric,
          correctnessV2F2Metric,
          citationCompletenessMetric, citationCompleteness,
          hit10Metric, ndcg5Metric, firstTokenMs,
          // 2026.11.19(sooyeon.choi) 수정 - '문제 항목' = 평가·지표 오류 또는 주요 지표 미달
          //   (Recall@10 미적중, 재랭킹 상위 5 밖, 첫 토큰 5초 초과). 인용 진단은 항목 목록에서 제외
          _failed: item.status !== 'ok' || metricError || primaryIssue,
          _issueType: item.status !== 'ok' || metricError ? 'metric_error' : null,
          _worst: vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 1,
        };
      });
      resultsTotal.value = data.total || 0;
    } catch {
      runResults.value = [];
    }
  };

  const cancelRun = async () => {
    if (!selectedRun.value) return;
    try {
      await evalApi.cancelRun(selectedRun.value.run_id);
      showToast('실행 취소를 요청했습니다.\n진행 중인 항목이 끝나면 중단됩니다.');
    } catch (e) {
      showToast(e.response?.data?.detail || '취소 요청에 실패했습니다.', 'error');
    }
  };

  const deleteRun = (runId) => {
    deleteRunId.value = runId;
  };

  const responseFilename = (contentDisposition, fallback) => {
    const utf8Match = contentDisposition?.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8Match) {
      try {
        return decodeURIComponent(utf8Match[1]);
      } catch {
        return fallback;
      }
    }
    const asciiMatch = contentDisposition?.match(/filename="?([^";]+)"?/i);
    return asciiMatch?.[1] || fallback;
  };

  const blobErrorDetail = async (error) => {
    const data = error.response?.data;
    if (!(data instanceof Blob)) return data?.detail;
    try {
      return JSON.parse(await data.text()).detail;
    } catch {
      return null;
    }
  };

  const downloadRunExcel = async (run) => {
    if (!run || run.status !== 'completed' || downloadingRunId.value !== null) return;
    downloadingRunId.value = run.run_id;
    try {
      const response = await evalApi.downloadRunExcel(run.run_id);
      const blob = response.data instanceof Blob
        ? response.data
        : new Blob([response.data], { type: response.headers['content-type'] });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = responseFilename(
        response.headers['content-disposition'],
        `eval_run_${run.run_id}.xlsx`,
      );
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      showToast((await blobErrorDetail(error)) || '평가 결과 Excel 다운로드에 실패했습니다.', 'error');
    } finally {
      downloadingRunId.value = null;
    }
  };

  const closeDeleteRunModal = () => {
    if (!isDeletingRun.value) deleteRunId.value = null;
  };

  const confirmDeleteRun = async () => {
    const runId = deleteRunId.value;
    if (runId == null || isDeletingRun.value) return;
    isDeletingRun.value = true;
    try {
      await evalApi.deleteRun(runId);
      if (selectedRun.value?.run_id === runId) selectedRun.value = null;
      deleteRunId.value = null;
      await loadRuns();
      showToast('평가 실행 이력을 삭제했습니다.');
    } catch (e) {
      showToast(e.response?.data?.detail || '실행 삭제에 실패했습니다.', 'error');
    } finally {
      isDeletingRun.value = false;
    }
  };

  const showDetail = (item) => { detailItem.value = item; };
  const closeDetail = () => { detailItem.value = null; };

  // ── 상세 모달 헬퍼 (reference EvalRunView 이식) ──────────────────────────
  const channelLabel = (c) => ({
    dense: '벡터 검색 (Dense)', kiwi_bm25: '키워드 검색 (Kiwi BM25)',
    rrf: '하이브리드 (RRF)', rerank: '리랭킹 후 (Top-5)',
  }[c] || c);
  const formatHeaderPath = (hp) => (Array.isArray(hp) && hp.length ? hp.join(' > ') : '');

  // 골드/시스템 참조를 동일 형태로 통일: {num, documentId, name, headerPath, pageNumber, referencedInAnswer}
  const goldRefs = (item) => {
    if (!item?.goldDocumentIds?.length) return [];
    const single = item.goldDocumentIds.length === 1;
    return item.goldDocumentIds.map((docId, i) => ({
      num: i + 1,
      documentId: docId,
      name: (single && item.goldSourceMeta?.original_filename) || docId,
      headerPath: single ? (formatHeaderPath(item.goldSourceMeta?.header_path) || item.goldSourceMeta?.section_title || '') : '',
      pageNumber: single ? item.goldSourceMeta?.page_number : null,
    }));
  };
  const systemRefs = (item, onlyReferenced = false) => {
    if (!item?.citationDetail?.cited?.length) return [];
    const list = onlyReferenced
      ? item.citationDetail.cited.filter((c) => c.referenced_in_answer)
      : item.citationDetail.cited;
    return list.map((c) => ({
      num: c.citation_id,
      documentId: c.document_id,
      name: c.original_filename || c.document_id,
      headerPath: formatHeaderPath(c.header_path),
      pageNumber: c.page_number,
      referencedInAnswer: c.referenced_in_answer,
    }));
  };
  // 참조 문서 클릭 → 원본 PDF를 해당 페이지로 연다 (기존 ingest 파일 엔드포인트 재사용)
  const openDocument = async (documentId, pageNumber) => {
    if (!documentId) return;
    try {
      const blob = await evalApi.getDocumentFile(documentId);
      const blobUrl = window.URL.createObjectURL(blob);
      const page = Number(pageNumber) || 1;
      window.open(`${blobUrl}#page=${page}`, '_blank', 'noopener,noreferrer');
      window.setTimeout(() => window.URL.revokeObjectURL(blobUrl), 60000);
    } catch {
      showToast('원본 문서를 열 수 없습니다.', 'error');
    }
  };
  const prettyJson = (obj) => JSON.stringify(obj, null, 2);

  const stopPolling = () => {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  };

  const logout = async () => {
    await authStore.logoutAny();
    router.push('/login');
  };

  const safeParse = (value, fallback) => {
    if (!value) return fallback;
    try {
      return typeof value === 'string' ? JSON.parse(value) : value;
    } catch {
      return fallback;
    }
  };

  // C3 — 화면 전체 비율 지표 표기 통일: 0~1 값을 백분율(소수1자리)로 표시한다.
  //   (기존 toFixed(3)은 KPI 카드·대시보드의 % 표기와 불일치했다. 모든 formatMetric
  //   사용처는 hit/recall/rr/ndcg/citation 등 0~1 비율 지표이므로 % 통일이 안전하다.)
  const formatMetric = (value) => (typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : '-');
  const formatMetricState = (metric) => {
    if (!metric) return '-';
    if (metric.status === 'measuring') return '평가 중'; // 2026.11.23(sooyeon.choi) 추가 - 진행 중 필수 지표
    if (metric.status === 'not_measured') return '미측정'; // 2026.11.19(sooyeon.choi) 추가
    if (metric.status === 'incomplete') return '측정 미완료';
    if (metric.status === 'excluded') return '제외';
    if (metric.status === 'error') return '오류';
    // 2026.11.19(sooyeon.choi) 추가 - ms 단위(반환 시간)는 초로 표시
    if (metric.unit === 'ms') return typeof metric.value === 'number' ? `${(metric.value / 1000).toFixed(2)}초` : '-';
    return formatMetric(metric.value);
  };
  // 2026.11.19(sooyeon.choi) 추가 - 목표·표준편차 표시(비율 %, ms는 초)
  const formatKpiTarget = (kpi) => {
    if (kpi.target == null) return '';
    const value = kpi.unit === 'ms' ? `${(kpi.target / 1000).toFixed(0)}초` : `${(kpi.target * 100).toFixed(0)}%`;
    return `목표 ${kpi.invert ? '≤' : '≥'} ${value}`;
  };
  const formatKpiStd = (kpi) => (kpi.unit === 'ms'
    ? `표준편차 ± ${(kpi.std / 1000).toFixed(2)}초`
    : `표준편차 ± ${(kpi.std * 100).toFixed(1)}%p`);
  const formatPct = (value) => (typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : '-');
  const formatLatency = (value) => (typeof value === 'number' ? `${(value / 1000).toFixed(1)}s` : '-');
  // 2026.11.19(sooyeon.choi) 추가 - 항목별 Recall@10 적중 여부, 초 단위 시간
  const formatHit = (metric) => {
    if (!metric) return '-';
    if (metric.status === 'excluded') return '제외';
    if (metric.status === 'error') return '오류';
    return metric.value === 1 ? '적중' : metric.value === 0 ? '미적중' : '-';
  };
  const formatSeconds = (ms) => (typeof ms === 'number' ? `${(ms / 1000).toFixed(2)}초` : '-');
  const questionTypeLabel = (type) => QUESTION_TYPE_LABELS[type] || type || '-';
  const statusLabel = (status) => STATUS_LABELS[status] || status;
  const runTypeLabel = (t) => RUN_TYPE_LABELS[t] || t;
  // 저장 형식 '2026-07-23T10:24:43+09:00'(KST) → '2026-07-23 10:24:43'
  const formatDate = (v, len = 19) => (v || '').slice(0, len).replace('T', ' ');
  watch(resultsTypeFilter, () => { resultsPage.value = 1; loadRunResults(); });
  watch(resultsLawFilter, () => { resultsPage.value = 1; loadRunResults(); });
  onBeforeUnmount(() => {
    stopPolling();
    if (toastTimer) clearTimeout(toastTimer);
  });

  return {
    isAdmin, displayName, sidebarOpen, isLoading, loadError, toast,
    goldsets, runs, selectedRun, runResults, displayResults, resultsTotal,
    resultsPage, resultsPageSize, resultsTotalPages, detailItem,
    deleteRunId, isDeletingRun, downloadingRunId,
    resultsTypeFilter, resultsFailedOnly, resultsSortBy,
    resultsLawFilter, isMergedRun, lawMetrics, lawOptions, lawShortLabel, lawBreakdown,
    runForm, isRunning, isFullRun, progressPercent, runCutoffs,
    searchKpis, hasSearchKpis, secondaryKpis,
    answerKpis, hasAnswerKpis,
    loadGoldsets, loadRuns, startRun, selectRun, loadRunResults, goToResultsPage,
    cancelRun, downloadRunExcel, deleteRun, closeDeleteRunModal, confirmDeleteRun,
    showDetail, closeDetail, logout,
    formatMetric, formatPct, formatLatency, formatHit, formatSeconds, questionTypeLabel,
    statusLabel, runTypeLabel, formatDate,
    // 상세 모달
    channelLabel, goldRefs, systemRefs, openDocument, prettyJson, formatMetricState, formatKpiTarget, formatKpiStd,
  };
};
