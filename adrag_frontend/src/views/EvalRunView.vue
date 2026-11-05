<!-- 2026.07.22(sychoi) 추가 - RAG 평가 실행/결과 화면 (P3-③ 최소 UI) -->
<template>
  <div class="admin-layout">
    <AdminSidebar :isOpen="sidebarOpen" activePage="eval" :isAdmin="isAdmin"
      :displayName="displayName" @close="sidebarOpen = false" @logout="logout" />

    <div class="admin-main">
      <header class="admin-header">
        <div class="header-left">
          <button class="btn-hamburger" @click="sidebarOpen = true"><i class="fa-solid fa-bars"></i></button>
          <div class="header-text">
            <h1>평가 실행 <span class="admin-badge">관리자</span></h1>
            <p>골드셋으로 RAG 파이프라인을 평가하고 핵심 성과지표(목표 80%)를 확인합니다.</p>
          </div>
        </div>
      </header>

      <main class="admin-content">
        <div v-if="loadError" class="alert error"><i class="fa-solid fa-circle-exclamation"></i> {{ loadError }}</div>

        <div class="grid-2">
          <!-- 새 평가 실행 -->
          <section class="card run-create-card">
            <div class="card-title"><i class="fa-solid fa-sliders"></i> 새 평가 실행</div>
            <div class="form-row">
              <label>골드셋</label>
              <select v-model="runForm.goldset_id" :disabled="!goldsets.length">
                <option v-if="!goldsets.length" value="" disabled>생성된 골드셋이 없습니다</option>
                <option v-for="g in goldsets" :key="g.goldset_id" :value="g.goldset_id">
                  {{ g.dataset_name || g.collection_name }} v{{ g.version }} ({{ g.item_count }}건)
                </option>
              </select>
            </div>
            <div class="form-row">
              <label>평가 범위</label>
              <select v-model="runForm.scope">
                <option value="retrieval">검색·재정렬 평가</option>
                <option value="full">전체 RAG 평가</option>
              </select>
              <span class="hint">{{ runForm.scope === 'full'
                ? '검색·재정렬과 답변·인용 품질을 함께 평가합니다. 실제 답변 생성이 포함됩니다.'
                : '답변을 생성하지 않고 검색 및 재정렬 품질만 빠르게 평가합니다.' }}</span>
            </div>
            <div class="form-grid">
              <div><label>검색 후보 수 N</label><input type="number" v-model="runForm.retrieval_top_n" min="1" /></div>
              <div><label>최종 문서 수 K</label><input type="number" v-model="runForm.rerank_top_k" min="1" :max="runForm.retrieval_top_n" /></div>
            </div>
            <button class="btn-primary"
                    :disabled="!runForm.goldset_id"
                    @click="startRun">
              <i class="fa-solid fa-play"></i> 실행 시작
            </button>
            <div v-if="!goldsets.length" class="goldset-empty-hint">
              <strong>평가를 시작하려면 확정된 골드셋이 필요합니다.</strong>
              <span>먼저 '평가 데이터셋'에서 골드셋을 생성해주세요.</span>
            </div>
          </section>

          <!-- 실행 이력 -->
          <section class="card history-card">
            <div class="card-title"><i class="fa-solid fa-clock-rotate-left"></i> 실행 이력
              <span v-if="runs.length" class="count-hint">총 {{ runs.length }}건</span>
              <button class="refresh-btn" :disabled="isLoading" title="새로고침" @click="loadRuns">
                <i class="fa-solid fa-rotate-right" :class="{ 'fa-spin': isLoading }"></i>
              </button>
            </div>
            <p v-if="!runs.length" class="hint">실행 이력이 없습니다.</p>
            <div v-else class="history-scroll">
            <table class="data-table">
              <thead><tr><th class="center">순번</th><th>데이터셋</th><th class="center">유형</th><th class="center">상태</th><th class="center">진행</th><th class="center">실행일</th><th class="center">다운로드</th><th class="center">삭제</th></tr></thead>
              <tbody>
                <tr v-for="(r, index) in runs" :key="r.run_id" :class="{ sel: selectedRun && selectedRun.run_id === r.run_id }"
                    @click="selectRun(r)">
                  <td class="center">{{ runs.length - index }}</td>
                  <td class="ds-cell">
                    <span class="strong">{{ r.dataset_name || r.collection_name || '-' }}</span>
                    <span v-if="r.goldset_version" class="ver">v{{ r.goldset_version }}</span>
                  </td>
                  <td class="center">{{ runTypeLabel(r.run_type) }}</td>
                  <td class="center"><span class="status-badge" :class="r.status">{{ statusLabel(r.status) }}</span></td>
                  <td class="center">{{ r.progress_done }}/{{ r.progress_total }}</td>
                  <td class="center nowrap">{{ formatDate(r.created_at) }}</td>
                  <td class="center">
                    <button class="btn-download-excel"
                            :disabled="r.status !== 'completed' || downloadingRunId !== null"
                            :title="r.status === 'completed'
                              ? '평가 결과 Excel 다운로드'
                              : ['pending', 'running'].includes(r.status)
                                ? '평가 완료 후 다운로드할 수 있습니다'
                                : '완료된 평가만 다운로드할 수 있습니다'"
                            @click.stop="downloadRunExcel(r)">
                      <i class="fa-solid"
                         :class="downloadingRunId === r.run_id ? 'fa-spinner fa-spin' : 'fa-file-excel'"></i>
                    </button>
                  </td>
                  <td class="center">
                    <button class="btn-delete-doc"
                            :disabled="['pending', 'running'].includes(r.status)"
                            :title="['pending', 'running'].includes(r.status)
                              ? '실행 중에는 삭제할 수 없습니다. 먼저 취소해주세요.' : '실행 이력 삭제'"
                            @click.stop="deleteRun(r.run_id)">
                      <i class="fa-solid fa-trash"></i>
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
            </div>
          </section>
        </div>

        <!-- 선택된 run 상세 -->
        <template v-if="selectedRun">
          <section class="card" v-if="isRunning">
            <div class="progress-head">
              <span>실행 중… {{ selectedRun.progress_done }}/{{ selectedRun.progress_total }} ({{ progressPercent }}%)</span>
              <button class="btn-secondary" @click="cancelRun"><i class="fa-solid fa-stop"></i> 취소</button>
            </div>
            <div class="progress-bar"><div class="progress-fill" :style="{ width: progressPercent + '%' }"></div></div>
          </section>

          <section class="card run-settings" v-if="selectedRun.status === 'completed'">
            <div class="card-title"><i class="fa-solid fa-gear"></i> 실행 설정</div>
            <div class="run-contract-meta">
              평가 범위: {{ runTypeLabel(selectedRun.scope || selectedRun.run_type) }} ·
              검색 후보 N={{ runCutoffs.n }} · 최종 문서 K={{ runCutoffs.k }}
              <span v-if="selectedRun.legacy" class="mini-badge warn">과거 실행</span>
            </div>
          </section>

          <!-- 주요 지표 -->
          <section class="card primary-metrics" v-if="hasSearchKpis || hasAnswerKpis">
            <div class="card-title"><i class="fa-solid fa-bullseye"></i> 주요 지표</div>

            <div class="primary-metric-groups">
            <div class="primary-metric-group" v-if="hasSearchKpis">
              <div class="primary-metric-title">검색 품질</div>
              <p class="metric-section-desc">
                검색기가 정답 근거를 후보에 확보하고 재정렬 결과 상위에 배치하는 능력을 평가합니다.
              </p>
              <div class="kpi-grid">
                <div v-for="kpi in searchKpis" :key="kpi.key" class="kpi-card"
                     :class="{ pass: kpi.pass === true, fail: kpi.pass === false }" :title="kpi.desc">
                  <div class="kpi-label">{{ kpi.label }}</div>
                  <div class="kpi-value">{{ formatMetricState(kpi) }}</div>
                  <div class="kpi-std" v-if="kpi.value != null && kpi.std != null">표준편차 ± {{ (kpi.std * 100).toFixed(1) }}%p</div>
                  <div class="kpi-desc">{{ kpi.desc }}</div>
                  <div class="kpi-target">목표 {{ kpi.invert ? '≤' : '≥' }}{{ (kpi.target * 100).toFixed(0) }}%</div>
                  <div class="kpi-status" v-if="kpi.pass !== null">
                    {{ kpi.pass ? '달성' : '미달' }}
                  </div>
                </div>
              </div>
            </div>

            <div class="primary-metric-group primary-metric-divider" v-if="hasAnswerKpis"
                 :class="{ divided: hasSearchKpis }">
              <div class="primary-metric-title">답변 및 인용 품질</div>
              <p class="metric-section-desc">
                생성 답변의 의미 유사도와 답변에 제시된 인용 근거의 정확성·충분성을 평가합니다.
              </p>
              <div class="kpi-grid">
                <div v-for="kpi in answerKpis" :key="kpi.key" class="kpi-card"
                     :class="{ pass: kpi.pass === true, fail: kpi.pass === false }" :title="kpi.desc">
                  <div class="kpi-label">{{ kpi.label }}</div>
                  <div class="kpi-value">{{ formatMetricState(kpi) }}</div>
                  <div class="kpi-std" v-if="kpi.value != null && kpi.std != null">표준편차 ± {{ (kpi.std * 100).toFixed(1) }}%p</div>
                  <div class="kpi-desc">{{ kpi.desc }}</div>
                  <div class="kpi-target">목표 {{ kpi.invert ? '≤' : '≥' }}{{ (kpi.target * 100).toFixed(0) }}%</div>
                  <div class="kpi-status" v-if="kpi.pass !== null">
                    {{ kpi.pass ? '달성' : '미달' }}
                  </div>
                </div>
              </div>
            </div>
            </div>
          </section>

          <details class="card secondary-metrics" v-if="secondaryKpis.length">
            <summary class="card-title">
              <span><i class="fa-solid fa-chart-line"></i> 보조 지표 {{ secondaryKpis.length }}개 보기</span>
              <span class="secondary-metrics-hint">
                클릭하여 펼쳐 보세요
                <i class="fa-solid fa-chevron-down secondary-metrics-chevron"></i>
              </span>
            </summary>
            <div class="kpi-grid">
              <div v-for="kpi in secondaryKpis" :key="kpi.key" class="kpi-card" :title="kpi.desc">
                <div class="kpi-label">{{ kpi.label }}</div>
                <div class="kpi-value">{{ formatMetricState(kpi) }}</div>
                <div class="kpi-std" v-if="kpi.std != null">± {{ (kpi.std * 100).toFixed(1) }}%p</div>
                <div class="kpi-target">{{ kpi.desc }}</div>
              </div>
            </div>
          </details>

          <!-- 항목별 결과 -->
          <section class="card">
            <div class="card-title">
              <i class="fa-solid fa-list-check"></i> 항목별 결과 ({{ resultsTotal }}건)
              <span class="filters">
                <label><input type="checkbox" v-model="resultsFailedOnly" /> 문제 항목만</label>
                <select v-model="resultsTypeFilter">
                  <option value="">전체 유형</option>
                  <option value="factual">사실형</option>
                  <option value="procedural">절차형</option>
                  <option value="comparative">비교형</option>
                  <option value="multihop">멀티홉</option>
                </select>
                <!-- 2026.07.24(sychoi) 추가 - 정렬 선택 -->
                <select v-model="resultsSortBy">
                  <option value="worst">낮은 점수부터</option>
                  <option value="dataset_sequence">번호순</option>
                </select>
              </span>
            </div>
            <p v-if="!displayResults.length" class="hint">결과가 없습니다.</p>
            <div v-else class="results-table-scroll" :style="questionColumnStyle" @mousedown="startQuestionResizeFromHeader">
            <table class="data-table results-table">
              <colgroup>
                <col class="col-qa" />
                <col class="col-type" />
                <col class="col-question" />
              </colgroup>
              <thead>
                <tr>
                  <th>번호</th><th class="center">유형</th><th class="question-header" title="오른쪽 경계를 드래그해 너비 조절">질문</th>
                  <th class="center">Retriever Recall</th><th class="center">Reranked NDCG</th>
                  <th v-if="isFullRun" class="center">Answer Correctness</th>
                  <th v-if="isFullRun" class="center">Citation Completeness</th>
                  <th class="center">평가 소요 시간</th><th class="center">상세보기</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in displayResults" :key="item.result_id">
                  <td :title="`내부 QA ID: ${item.qa_id}`">{{ item.dataset_sequence ?? '-' }}</td>
                  <td class="center"><span class="type-badge">{{ questionTypeLabel(item.question_type) }}</span></td>
                  <td class="q-cell" :class="{ expanded: isQuestionExpanded(item.result_id) }"
                      title="더블클릭하여 질문 전체 보기/접기" @dblclick="toggleQuestion(item.result_id)">
                    <span class="question-text">{{ item.question || '' }}</span>
                    <span v-if="item.status !== 'ok'" class="evaluation-error-badge"
                          :title="item.error_message || '평가 처리 중 오류가 발생했습니다.'">
                      <i class="fa-solid fa-circle-exclamation"></i> 평가 오류
                    </span>
                    <span v-else-if="item._issueType === 'metric_error'" class="evaluation-error-badge">지표 오류</span>
                    <template v-else-if="item._issueType === 'diagnostic_issue'">
                      <span v-for="issue in item.citationIssues" :key="issue.type"
                            class="evaluation-error-badge" :title="issue.detail">
                        {{ issue.label }}
                      </span>
                    </template>
                  </td>
                  <td class="center"><span class="mini-badge" :class="metricBadgeClass(item.recallN, PRIMARY_THRESHOLDS.retrieverRecall)">{{ formatMetricState(item.recallMetric) }}</span></td>
                  <td class="center"><span class="mini-badge" :class="metricBadgeClass(item.rerankedNdcg, PRIMARY_THRESHOLDS.rerankedNdcg)">{{ formatMetricState(item.rerankedNdcgMetric) }}</span></td>
                  <td v-if="isFullRun" class="center"><span class="mini-badge" :class="metricBadgeClass(item.correctness, PRIMARY_THRESHOLDS.answerCorrectness)">{{ formatMetricState(item.correctnessMetric) }}</span></td>
                  <td v-if="isFullRun" class="center"><span class="mini-badge" :class="metricBadgeClass(item.citationCompleteness, PRIMARY_THRESHOLDS.citationCompleteness)">{{ formatMetricState(item.citationCompletenessMetric) }}</span></td>
                  <td class="center latency-cell">{{ formatLatency(item.latency_ms) }}</td>
                  <td class="center"><button class="btn-detail" @click="showDetail(item)">상세</button></td>
                </tr>
              </tbody>
            </table>
            </div>
            <!-- 2026.07.24(sychoi) 추가 - 페이저 복원. 서버가 page 단위로만 결과를 내려주므로
                 페이저 없이는 page_size(20) 초과 항목에 접근 불가했음 -->
            <div class="pagination" v-if="resultsTotalPages > 1">
              <button :disabled="resultsPage <= 1" @click="goToResultsPage(resultsPage - 1)">이전</button>
              <span>{{ resultsPage }} / {{ resultsTotalPages }}</span>
              <button :disabled="resultsPage >= resultsTotalPages" @click="goToResultsPage(resultsPage + 1)">다음</button>
            </div>
          </section>
        </template>
      </main>
    </div>

    <!-- 실행 이력 삭제 확인 모달 -->
    <div v-if="deleteRunId != null" class="modal-overlay delete-run-overlay" @click.self="closeDeleteRunModal">
      <div class="modal confirm-modal" role="dialog" aria-modal="true" aria-labelledby="delete-run-title">
        <div class="confirm-icon"><i class="fa-solid fa-triangle-exclamation"></i></div>
        <h3 id="delete-run-title">평가 실행 이력을 삭제할까요?</h3>
        <p>
          해당 실행의 항목별 결과와 모든 지표가 삭제됩니다.<br />
          삭제 후에는 복구할 수 없습니다.
        </p>
        <div class="confirm-actions">
          <button class="btn-secondary" :disabled="isDeletingRun" @click="closeDeleteRunModal">취소</button>
          <button class="btn-danger" :disabled="isDeletingRun" @click="confirmDeleteRun">
            <i class="fa-solid fa-trash"></i> {{ isDeletingRun ? '삭제 중…' : '삭제' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 상세 모달: 답변 비교·인용 진단·근거 청크·채널 순위 -->
    <div v-if="detailItem" class="modal-overlay" @click.self="closeDetail">
      <div class="modal xwide">
        <div class="modal-head">
          <h3><i class="fa-solid fa-magnifying-glass"></i> QA 결과 상세</h3>
          <button class="btn-icon" @click="closeDetail"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="detail-body">
          <div v-if="detailItem.error_message" class="alert error">
            <i class="fa-solid fa-circle-exclamation"></i> {{ detailItem.error_message }}
          </div>

          <!-- 질문 -->
          <div v-if="detailItem.question" class="detail-question">
            <span class="q-badge">Q</span> {{ detailItem.question }}
          </div>

          <!-- 답변 비교: 골드 vs 시스템 -->
          <div class="answer-compare" v-if="detailItem.gold_answer || detailItem.answer_text">
            <div class="answer-col">
              <div class="answer-col-label gold"><i class="fa-solid fa-medal"></i> 정답(Gold) 답변</div>
              <div class="answer-box gold">
                {{ detailItem.gold_answer || '(등록된 정답 없음)' }}
                <div v-if="goldRefs(detailItem).length" class="citation-ref-map gold">
                  <div class="citation-ref-title gold">참조 문서</div>
                  <div v-for="ref in goldRefs(detailItem)" :key="ref.num"
                       class="citation-ref-item ref-clickable" @click="openDocument(ref.documentId, ref.pageNumber)">
                    <span class="ref-num gold">[{{ ref.num }}]</span>
                    <span class="ref-content">
                      <span class="ref-name">{{ ref.name }}</span>
                      <span v-if="ref.headerPath || ref.pageNumber" class="ref-meta">
                        <span v-if="ref.headerPath" class="ref-section">{{ ref.headerPath }}</span>
                        <span v-if="ref.pageNumber" class="ref-page">페이지 p.{{ ref.pageNumber }}</span>
                      </span>
                    </span>
                    <i class="fa-solid fa-arrow-up-right-from-square open-icon"></i>
                  </div>
                </div>
              </div>
            </div>
            <div class="answer-col">
              <div class="answer-col-label system"><i class="fa-solid fa-robot"></i> 시스템 생성 답변</div>
              <div class="answer-box system">
                {{ detailItem.answer_text || '(답변 없음)' }}
                <div v-if="systemRefs(detailItem).length" class="citation-ref-map">
                  <div class="citation-ref-title">참조 문서</div>
                  <div v-for="ref in systemRefs(detailItem)" :key="ref.num"
                       class="citation-ref-item ref-clickable" :class="{ unused: !ref.referencedInAnswer }"
                       @click="openDocument(ref.documentId, ref.pageNumber)">
                    <span class="ref-num">[{{ ref.num }}]</span>
                    <span class="ref-content">
                      <span class="ref-name">{{ ref.name }}</span>
                      <span v-if="ref.headerPath || ref.pageNumber || !ref.referencedInAnswer" class="ref-meta">
                        <span v-if="ref.headerPath" class="ref-section">{{ ref.headerPath }}</span>
                        <span v-if="ref.pageNumber" class="ref-page">페이지 p.{{ ref.pageNumber }}</span>
                        <span v-if="!ref.referencedInAnswer" class="ref-unused-badge">미인용</span>
                      </span>
                    </span>
                    <i class="fa-solid fa-arrow-up-right-from-square open-icon"></i>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div v-if="detailItem.correctnessV2F2Metric" class="detail-section">
            <h4><i class="fa-solid fa-flask"></i> Answer Correctness v2 F2 Shadow</h4>
            <div class="citation-metric-row">
              <span class="mini-badge" :class="badgeClass(detailItem.correctnessV2F2Metric.value)">
                종합 {{ formatMetricState(detailItem.correctnessV2F2Metric) }}
              </span>
              <span class="mini-badge">
                Gold Coverage {{ formatMetric(detailItem.correctnessV2F2Metric.metadata?.gold_coverage) }}
              </span>
              <span class="mini-badge">
                System Precision {{ formatMetric(detailItem.correctnessV2F2Metric.metadata?.system_precision) }}
              </span>
            </div>
            <p class="hint">기존 v2 임베딩 정렬 결과를 재사용하며 Gold Coverage에 더 높은 가중치를 둔 F2 점수입니다.</p>
          </div>

          <div v-if="detailItem.citationDiagnostics && Object.keys(detailItem.citationDiagnostics).length"
               class="detail-section">
            <h4><i class="fa-solid fa-stethoscope"></i> Citation 진단</h4>
            <div class="citation-metric-row">
              <span class="mini-badge" :class="detailItem.citationDiagnostics.invalid_citation_count ? 'bad' : 'good'">
                잘못된 인용 {{ detailItem.citationDiagnostics.invalid_citation_count || 0 }}건
              </span>
              <span class="mini-badge" :class="detailItem.citationDiagnostics.missing_citation ? 'bad' : 'good'">
                필수 인용 {{ detailItem.citationDiagnostics.missing_citation ? '누락' : '확인' }}
              </span>
            </div>
            <p v-if="detailItem.citationDiagnostics.invalid_numbers?.length" class="hint">
              유효하지 않은 번호: {{ detailItem.citationDiagnostics.invalid_numbers.join(', ') }}
            </p>
            <p v-if="detailItem.citationDiagnostics.missing_gold_chunk_ids?.length" class="hint">
              누락된 골드 청크: {{ detailItem.citationDiagnostics.missing_gold_chunk_ids.join(', ') }}
            </p>
          </div>

          <!-- 근거인용 비교 -->
          <div v-if="detailItem.citation" class="detail-section">
            <h4><i class="fa-solid fa-quote-left"></i> 근거인용 비교</h4>
            <div class="citation-metric-row">
              <span class="mini-badge" :class="badgeClass(detailItem.citation.completeness)">
                Citation Completeness {{ formatMetric(detailItem.citation.completeness) }}
              </span>
            </div>
            <div class="citation-compare">
              <div class="citation-col">
                <div class="citation-col-label">정답 근거 문서 (Gold)</div>
                <ul class="citation-list gold" v-if="goldRefs(detailItem).length">
                  <li v-for="ref in goldRefs(detailItem)" :key="ref.num"
                      class="citation-document-item ref-clickable"
                      @click="openDocument(ref.documentId, ref.pageNumber)">
                    <i class="fa-solid fa-file-lines citation-doc-icon gold-icon"></i>
                    <span class="ref-content">
                      <span class="ref-name">{{ ref.name }}</span>
                      <span v-if="ref.headerPath || ref.pageNumber" class="ref-meta">
                        <span v-if="ref.headerPath" class="citation-section">{{ ref.headerPath }}</span>
                        <span v-if="ref.pageNumber" class="ref-page">페이지 p.{{ ref.pageNumber }}</span>
                      </span>
                    </span>
                    <i class="fa-solid fa-arrow-up-right-from-square open-icon"></i>
                  </li>
                </ul>
                <div v-else class="empty-mini">등록된 정답 문서 없음</div>
              </div>
              <div class="citation-col">
                <div class="citation-col-label">시스템이 실제 인용한 문서</div>
                <ul class="citation-list system" v-if="systemRefs(detailItem, true).length">
                  <li v-for="ref in systemRefs(detailItem, true)" :key="ref.num"
                      class="citation-document-item ref-clickable"
                      :class="{ match: detailItem.goldDocumentIds?.includes(ref.documentId) }"
                      @click="openDocument(ref.documentId, ref.pageNumber)">
                    <i class="citation-doc-icon"
                       :class="detailItem.goldDocumentIds?.includes(ref.documentId) ? 'fa-solid fa-check ok' : 'fa-solid fa-xmark no'"></i>
                    <span class="ref-content">
                      <span class="ref-name">{{ ref.name }}</span>
                      <span v-if="ref.headerPath || ref.pageNumber" class="ref-meta">
                        <span v-if="ref.headerPath" class="citation-section">{{ ref.headerPath }}</span>
                        <span v-if="ref.pageNumber" class="ref-page">페이지 p.{{ ref.pageNumber }}</span>
                      </span>
                    </span>
                    <i class="fa-solid fa-arrow-up-right-from-square open-icon"></i>
                  </li>
                </ul>
                <div v-else-if="!detailItem.citationDiagnostics.cited_numbers?.length" class="empty-mini">
                  답변에 인용 표시([N])가 없음
                </div>
                <div v-else-if="detailItem.citationDiagnostics.invalid_numbers?.length" class="empty-mini">
                  답변의 인용 번호가 유효 범위를 벗어남
                  ({{ detailItem.citationDiagnostics.invalid_numbers.join(', ') }})
                </div>
                <div v-else class="empty-mini">인용 번호를 근거 청크에 매핑하지 못함</div>
              </div>
            </div>
          </div>

          <!-- 정답 근거 청크 원문 -->
          <div v-if="detailItem.goldChunkTexts?.length" class="detail-section">
            <h4><i class="fa-solid fa-file-lines"></i> 정답 근거 청크 원문</h4>
            <pre v-for="(text, i) in detailItem.goldChunkTexts" :key="i" class="chunk-text">{{ text }}</pre>
          </div>

          <!-- 채널별 검색 결과 -->
          <div v-if="detailItem.retrieval" class="detail-section">
            <h4><i class="fa-solid fa-magnifying-glass-chart"></i> 채널별 검색 결과</h4>
            <table class="data-table mini">
              <thead><tr><th>채널</th><th class="center">Hit@5</th><th class="center">Recall@5</th><th class="center">MRR@5</th><th class="center">정답 청크 순위</th></tr></thead>
              <tbody>
                <tr v-for="(m, channel) in detailItem.retrieval" :key="channel">
                  <td>{{ channelLabel(channel) }}</td>
                  <td class="center">{{ formatMetric(m['hit@5']) }}</td>
                  <td class="center">{{ formatMetric(m['recall@5']) }}</td>
                  <td class="center">{{ formatMetric(m['rr@5']) }}</td>
                  <td class="center">{{ m.gold_ranks?.length ? m.gold_ranks.join(', ') + '위' : '미검출' }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 원본 JSON (디버깅) -->
          <details class="raw-json">
            <summary>원본 JSON 보기 (디버깅용)</summary>
            <pre class="json-view">{{ prettyJson({ metrics: detailItem.metrics, retrieval: detailItem.retrieval, citation: detailItem.citation, citationDetail: detailItem.citationDetail }) }}</pre>
          </details>
        </div>
        <div class="modal-actions">
          <button class="btn-secondary" @click="closeDetail">닫기</button>
        </div>
      </div>
    </div>

    <AppToast :message="toast.visible ? toast.message : ''" :type="toast.type" admin-position
      @close="toast.visible = false" />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import AdminSidebar from '../components/AdminSidebar.vue';
import AppToast from '../components/AppToast.vue';
import { useEvalRuns } from '../composables/useEvalRuns';

const {
  isAdmin, displayName, sidebarOpen, isLoading, loadError, toast,
  goldsets, runs, selectedRun, displayResults, resultsTotal,
  resultsPage, resultsTotalPages, goToResultsPage,
  resultsTypeFilter, resultsFailedOnly, resultsSortBy, detailItem,
  deleteRunId, isDeletingRun, downloadingRunId,
  runForm, isRunning, isFullRun, progressPercent, runCutoffs,
  searchKpis, hasSearchKpis, secondaryKpis, answerKpis, hasAnswerKpis,
  loadGoldsets, loadRuns, startRun, selectRun, cancelRun, downloadRunExcel, deleteRun,
  closeDeleteRunModal, confirmDeleteRun,
  showDetail, closeDetail, logout,
  formatMetric, formatLatency, questionTypeLabel,
  statusLabel, runTypeLabel, formatDate, badgeClass, metricBadgeClass, PRIMARY_THRESHOLDS,
  channelLabel, goldRefs, systemRefs, openDocument, prettyJson, formatMetricState,
} = useEvalRuns();

// 0~1 비율 값 색상 등급 (요약 타일 막대) — badgeClass와 동일 기준
const pctClass = (v) => (v >= 0.8 ? 'good' : v >= 0.5 ? 'mid' : 'bad');

const questionColumnWidth = ref(280);
const expandedQuestionIds = ref(new Set());
let questionResizeState = null;

const questionColumnStyle = computed(() => ({
  '--question-column-width': `${questionColumnWidth.value}px`,
}));

const stopQuestionResize = () => {
  if (!questionResizeState) return;
  window.removeEventListener('mousemove', onQuestionResizeMove);
  window.removeEventListener('mouseup', stopQuestionResize);
  questionResizeState = null;
};

const onQuestionResizeMove = (event) => {
  if (!questionResizeState) return;
  const delta = event.clientX - questionResizeState.startX;
  questionColumnWidth.value = Math.min(640, Math.max(180, questionResizeState.startWidth + delta));
};

const startQuestionResizeFromHeader = (event) => {
  const header = event.currentTarget?.querySelector('.question-header');
  if (!header || !header.contains(event.target)) return;
  const rect = header.getBoundingClientRect();
  if (rect.right - event.clientX > 12) return;
  event.preventDefault();
  stopQuestionResize();
  questionResizeState = { startX: event.clientX, startWidth: questionColumnWidth.value };
  window.addEventListener('mousemove', onQuestionResizeMove);
  window.addEventListener('mouseup', stopQuestionResize);
};

const isQuestionExpanded = (resultId) => expandedQuestionIds.value.has(resultId);
const toggleQuestion = (resultId) => {
  const next = new Set(expandedQuestionIds.value);
  if (next.has(resultId)) next.delete(resultId);
  else next.add(resultId);
  expandedQuestionIds.value = next;
};

onMounted(() => {
  loadGoldsets();
  loadRuns();
});

onBeforeUnmount(stopQuestionResize);
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
.admin-badge { font-size: 0.65rem; background: #fef3c7; color: #b45309; padding: 2px 8px; border-radius: 10px; vertical-align: middle; }
.btn-hamburger { display: none; background: none; border: none; font-size: 1.2rem; cursor: pointer; }
.admin-content { --evaluation-overview-card-height: clamp(390px, 45vh, 460px); flex: 1; padding: 1.5rem 2rem; overflow-y: auto; display: flex; flex-direction: column; gap: 1.25rem; }
.grid-2 { display: grid; grid-template-columns: 360px minmax(0, 1fr); gap: 1.25rem; }
.run-create-card, .history-card { min-height: var(--evaluation-overview-card-height); box-sizing: border-box; }
.history-card { display: flex; flex-direction: column; }
.history-scroll { flex: 1 1 0; height: 0; min-height: 0; overflow-y: auto; margin-top: 0.2rem; }
/* 스크롤 중에도 헤더 고정 */
.history-scroll thead th { position: sticky; top: 0; background: #fff; z-index: 1; }
.count-hint { font-size: 0.8rem; font-weight: 400; color: #94a3b8; }
.refresh-btn { margin-left: auto; background: #fff; border: 1px solid #cbd5e1; border-radius: 6px;
  width: 30px; height: 30px; cursor: pointer; color: #475569; font-size: 0.8rem; flex-shrink: 0; }
.refresh-btn:hover:not(:disabled) { background: #f8fafc; color: #2563eb; }
.refresh-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.ds-cell .ver { margin-left: 6px; font-size: 0.72rem; color: #64748b; }
.nowrap { white-space: nowrap; }
.card { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 1.5rem; }
.run-settings { display: flex; align-items: center; flex-wrap: wrap; gap: 0.5rem 1rem; padding-top: 1rem; padding-bottom: 1rem; }
.run-settings > .card-title { flex-shrink: 0; margin-bottom: 0; }
.run-contract-meta { color: #64748b; font-size: 0.82rem; }
.card-title { font-weight: 700; font-size: 0.95rem; margin-bottom: 0.9rem; display: flex; align-items: center; gap: 8px; }
.card-title .filters { margin-left: auto; display: flex; gap: 0.75rem; font-weight: 400; font-size: 0.8rem; align-items: center; }
.form-row { display: flex; flex-direction: column; gap: 4px; margin-bottom: 0.7rem; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.7rem; margin-bottom: 0.7rem; }
.form-row label, .form-grid label { font-size: 0.78rem; color: #475569; }
select, input { padding: 0.5rem 0.6rem; border: 1px solid #cbd5e1; border-radius: 8px;
  font-size: 0.85rem; box-sizing: border-box; }
input[type="checkbox"] { width: auto; padding: 0; border: none; flex-shrink: 0; }
.form-row select, .form-row input, .form-grid select, .form-grid input { width: 100%; }
.card-title .filters label { white-space: nowrap; display: inline-flex; align-items: center; gap: 5px; }
.card-title .filters select { min-width: 120px; }
.btn-primary { background: #2563eb; color: #fff; border: none; border-radius: 8px; padding: 0.6rem 1rem; font-size: 0.88rem; cursor: pointer; display: inline-flex; gap: 8px; align-items: center; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary { background: #fff; border: 1px solid #cbd5e1; border-radius: 8px; padding: 0.4rem 0.8rem; cursor: pointer; }
.btn-icon { background: none; border: none; color: #64748b; cursor: pointer; padding: 4px; }
.btn-icon:hover { color: #ef4444; }
/* 문서 관리(AdminView)·평가 데이터셋과 동일 스펙의 삭제 버튼 */
.btn-delete-doc {
  background: none;
  border: 1px solid #fecaca;
  color: #dc2626;
  width: 30px;
  height: 30px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.8rem;
  transition: all 0.15s;
}
.btn-delete-doc:hover:not(:disabled) { background: #fef2f2; }
.btn-delete-doc:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-download-excel {
  background: none; border: 1px solid #bbf7d0; color: #15803d; width: 30px; height: 30px;
  border-radius: 6px; cursor: pointer; display: flex; align-items: center; justify-content: center;
  margin: 0 auto; font-size: 0.8rem; transition: all 0.15s;
}
.btn-download-excel:hover:not(:disabled) { background: #f0fdf4; }
.btn-download-excel:disabled { opacity: 0.45; cursor: not-allowed; }
.hint { color: #94a3b8; font-size: 0.8rem; margin-top: 0.5rem; }
.goldset-empty-hint { color: #94a3b8; margin-top: 1rem; }
.goldset-empty-hint strong { display: block; color: #334155; font-size: 0.9rem; font-weight: 700; }
.goldset-empty-hint span { display: block; margin-top: 0.2rem; font-size: 0.78rem; }
.data-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
.data-table th { text-align: left; color: #64748b; font-weight: 600; padding: 0.4rem 0.5rem; border-bottom: 1px solid #e2e8f0; }
.data-table td { padding: 0.45rem 0.5rem; border-bottom: 1px solid #f1f5f9; }
.data-table th.center, .data-table td.center { text-align: center; }
.data-table td.center .btn-delete-doc { margin: 0 auto; }
.data-table tbody tr { cursor: pointer; }
.data-table tbody tr.sel { background: #eff6ff; }
.results-table-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }
.results-table { min-width: calc(var(--question-column-width, 280px) + 920px); table-layout: fixed; }
.results-table .col-qa { width: 64px; }
.results-table .col-type { width: 78px; }
.results-table .col-question { width: var(--question-column-width, 280px); }
.results-table .question-header { position: relative; cursor: col-resize; user-select: none; padding-right: 1.6rem; }
.results-table .question-header::after { content: '\2194'; position: absolute; top: 0; right: 0; bottom: 0; width: 18px;
  border-right: 2px solid #cbd5e1; color: #94a3b8; display: flex; align-items: center; justify-content: center; }
.results-table .question-header:hover::after { border-right-color: #2563eb; color: #2563eb; }
.q-cell { width: var(--question-column-width, 280px); max-width: var(--question-column-width, 280px); }
.q-cell .question-text { display: inline-block; max-width: calc(var(--question-column-width, 280px) - 70px); overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; vertical-align: middle; }
.q-cell.expanded { vertical-align: top; }
.q-cell.expanded .question-text { display: block; max-width: none; overflow: visible; text-overflow: clip; white-space: normal; line-height: 1.55; }
.evaluation-error-badge { display: inline-flex; align-items: center; gap: 3px; margin-left: 6px; padding: 2px 6px;
  border-radius: 999px; background: #fee2e2; color: #b91c1c; font-size: 0.68rem; font-weight: 700; white-space: nowrap; vertical-align: middle; }
.type-badge { display: inline-block; min-width: 46px; padding: 3px 8px; border-radius: 10px; background: #f1f5f9; color: #475569; font-size: 0.72rem; font-weight: 600; white-space: nowrap; }
.latency-cell { color: #64748b; white-space: nowrap; }
.btn-detail { padding: 6px 14px; border: 1px solid #dbe3ed; border-radius: 8px; background: #fff; color: #334155; font-size: 0.78rem; cursor: pointer; white-space: nowrap; }
.btn-detail:hover { border-color: #94a3b8; background: #f8fafc; color: #0f172a; }
.status-badge { font-size: 0.7rem; padding: 2px 8px; border-radius: 10px; background: #e2e8f0; color: #475569; }
.status-badge.running, .status-badge.pending { background: #dbeafe; color: #1d4ed8; }
.status-badge.completed, .status-badge.ok { background: #dcfce7; color: #15803d; }
.status-badge.failed, .status-badge.error { background: #fee2e2; color: #b91c1c; }
.status-badge.cancelled { background: #f1f5f9; color: #64748b; }
.primary-metrics > .card-title { margin-bottom: 1rem; }
.primary-metric-groups { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); }
.primary-metric-group { min-width: 0; }
.primary-metric-title { margin-bottom: 0.25rem; color: #334155; font-size: 0.9rem; font-weight: 700; }
.metric-section-desc { margin: 0 0 0.75rem; color: #64748b; font-size: 0.78rem; line-height: 1.45; }
.primary-metric-divider.divided { margin-left: 1.25rem; padding-left: 1.25rem; border-left: 1px solid #e2e8f0; }
.secondary-metrics > summary { display: flex; align-items: center; justify-content: flex-start; gap: 0.75rem; cursor: pointer; }
.secondary-metrics-hint { display: inline-flex; align-items: center; gap: 0.35rem; color: #94a3b8; font-size: 0.7rem; font-weight: 400; }
.secondary-metrics-chevron { transition: transform 0.2s ease; }
.secondary-metrics[open] .secondary-metrics-chevron { transform: rotate(180deg); }
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.8rem; }
.kpi-card { border: 1px solid #e2e8f0; border-radius: 10px; padding: 0.65rem 0.75rem; text-align: center; }
.kpi-card.pass { border-color: #86efac; background: #f0fdf4; }
.kpi-card.fail { border-color: #fca5a5; background: #fef2f2; }
.kpi-label { font-size: 0.75rem; color: #475569; line-height: 1.3; }
.kpi-value { font-size: 1.5rem; font-weight: 800; margin: 0.15rem 0; }
.kpi-std { font-size: 0.72rem; color: #94a3b8; margin-bottom: 0.1rem; }
.kpi-desc { min-height: 2em; margin: 0.2rem 0; color: #64748b; font-size: 0.72rem; line-height: 1.35; }
.kpi-target { display: inline-block; margin-right: 0.45rem; color: #64748b; font-size: 0.7rem; }
.kpi-status { display: inline-block; padding: 0.08rem 0.65rem; border-radius: 999px; font-size: 0.7rem; font-weight: 700; }
.kpi-card.pass .kpi-status { background: #dcfce7; color: #15803d; }
.kpi-card.fail .kpi-status { background: #fee2e2; color: #b91c1c; }
.pagination { display: flex; justify-content: center; align-items: center; gap: 12px; margin-top: 0.9rem; font-size: 0.82rem; color: #475569; }
.pagination button { padding: 0.35rem 0.9rem; border: 1px solid #cbd5e1; background: #fff; border-radius: 6px; cursor: pointer; }
.pagination button:disabled { opacity: 0.4; cursor: not-allowed; }
.mini-badge { font-size: 0.72rem; padding: 2px 7px; border-radius: 8px; background: #e2e8f0; color: #475569; }
.mini-badge.good { background: #dcfce7; color: #15803d; }
.mini-badge.warn { background: #fef9c3; color: #a16207; }
.mini-badge.bad { background: #fee2e2; color: #b91c1c; }
.mini-badge.na { background: #f1f5f9; color: #94a3b8; }
.progress-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.6rem; font-size: 0.85rem; }
.progress-bar { height: 8px; background: #e2e8f0; border-radius: 4px; overflow: hidden; }
.progress-fill { height: 100%; background: #2563eb; transition: width 0.3s; }
.alert.error { background: #fef2f2; color: #b91c1c; padding: 0.7rem 1rem; border-radius: 8px; font-size: 0.85rem; }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 60; }
.delete-run-overlay { left: 260px; align-items: flex-start; padding: clamp(96px, 18vh, 180px) 1rem 1rem; box-sizing: border-box; }
.modal { background: #fff; border-radius: 12px; width: min(680px, 92vw); max-height: 86vh; overflow: auto; }
.modal.xwide { width: min(920px, 94vw); }
.modal-head { display: flex; justify-content: space-between; align-items: center; padding: 1rem 1.25rem; border-bottom: 1px solid #e2e8f0; position: sticky; top: 0; background: #fff; z-index: 1; }
.modal-head h3 { display: flex; align-items: center; gap: 8px; font-size: 1rem; font-weight: 700; }
.confirm-modal { width: min(420px, 92vw); padding: 1.5rem; text-align: center; box-shadow: 0 18px 48px rgba(15, 23, 42, 0.22); }
.confirm-icon { width: 48px; height: 48px; margin: 0 auto 0.9rem; border-radius: 50%; display: grid; place-items: center; background: #fee2e2; color: #dc2626; font-size: 1.2rem; }
.confirm-modal h3 { font-size: 1.05rem; font-weight: 700; color: #0f172a; }
.confirm-modal p { margin: 0.75rem 0 1.25rem; color: #64748b; font-size: 0.88rem; line-height: 1.65; }
.confirm-modal strong { color: #0f172a; }
.confirm-actions { display: flex; justify-content: flex-end; gap: 0.6rem; }
.btn-danger { border: 1px solid #dc2626; border-radius: 8px; padding: 0.5rem 0.9rem; background: #dc2626; color: #fff; font-weight: 600; cursor: pointer; }
.btn-danger:hover:not(:disabled) { background: #b91c1c; border-color: #b91c1c; }
.btn-danger:disabled { opacity: 0.55; cursor: not-allowed; }

/* ── 상세 모달 본문 (reference 이식) ── */
.detail-body { padding: 1.1rem 1.25rem; display: flex; flex-direction: column; gap: 1.1rem; }
.detail-question { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 0.7rem 0.9rem; font-size: 0.9rem; font-weight: 600; }
.q-badge { background: #2563eb; color: #fff; border-radius: 6px; padding: 1px 8px; margin-right: 6px; font-size: 0.8rem; }
.detail-section { border-top: 1px solid #f1f5f9; padding-top: 0.9rem; }
.detail-section h4 { font-size: 0.85rem; font-weight: 700; margin-bottom: 0.7rem; display: flex; align-items: center; gap: 6px; color: #334155; }

.answer-compare { display: grid; grid-template-columns: 1fr 1fr; gap: 0.9rem; }
.answer-col-label { font-size: 0.78rem; font-weight: 600; margin-bottom: 5px; display: flex; align-items: center; gap: 6px; }
.answer-col-label.gold { color: #b45309; }
.answer-col-label.system { color: #1d4ed8; }
.answer-box { border: 1px solid #e2e8f0; border-radius: 8px; padding: 0.75rem 0.85rem; font-size: 0.83rem; white-space: pre-wrap; word-break: break-word; }
.answer-box.gold { background: #fffbeb; border-color: #fde68a; }
.answer-box.system { background: #eff6ff; border-color: #bfdbfe; }
.citation-ref-map { margin-top: 0.7rem; padding-top: 0.6rem; border-top: 1px dashed #e2e8f0; }
.citation-ref-title { font-size: 0.72rem; color: #64748b; margin-bottom: 4px; }
.citation-ref-item { font-size: 0.76rem; display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: start; gap: 6px; padding: 5px 0; }
.citation-ref-item.unused { opacity: 0.55; }
.ref-num { font-weight: 700; color: #1d4ed8; }
.ref-num.gold { color: #b45309; }
.ref-content { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.ref-name { font-weight: 500; white-space: normal; word-break: normal; overflow-wrap: anywhere; line-height: 1.35; }
.ref-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 10px; font-size: 0.7rem; line-height: 1.35; }
.ref-section, .ref-page { color: #64748b; }
.ref-page { white-space: nowrap; }
.ref-unused-badge { font-size: 0.66rem; background: #e2e8f0; color: #64748b; padding: 0 6px; border-radius: 6px; }
.ref-clickable { cursor: pointer; }
.ref-clickable:hover .ref-name { text-decoration: underline; color: #2563eb; }
.open-icon { font-size: 0.65rem; color: #94a3b8; margin: 3px 0 0 2px; flex-shrink: 0; }

.citation-metric-row { display: flex; gap: 6px; margin-bottom: 0.7rem; }
.citation-compare { display: grid; grid-template-columns: 1fr 1fr; gap: 0.9rem; }
.citation-col-label { font-size: 0.76rem; color: #64748b; margin-bottom: 5px; }
.citation-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.citation-list li { font-size: 0.78rem; padding: 7px 8px; border-radius: 7px; }
.citation-list li.citation-document-item { display: grid; grid-template-columns: 16px minmax(0, 1fr) auto; align-items: start; gap: 7px; }
.citation-doc-icon { width: 16px; margin-top: 3px; text-align: center; flex-shrink: 0; }
.citation-doc-icon.gold-icon { color: #d97706; }
.citation-list.gold li { background: #fffbeb; }
.citation-list.system li { background: #f8fafc; }
.citation-list.system li.match { background: #f0fdf4; }
.citation-list .ok { color: #16a34a; }
.citation-list .no { color: #ef4444; }
.citation-section { color: #64748b; overflow-wrap: anywhere; }
.empty-mini { font-size: 0.78rem; color: #94a3b8; padding: 4px 0; }

.chunk-text { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 0.6rem 0.7rem; font-size: 0.76rem; white-space: pre-wrap; word-break: break-word; margin-bottom: 0.4rem; max-height: 240px; overflow-y: auto; }
.data-table.mini th, .data-table.mini td { font-size: 0.78rem; }
.raw-json { font-size: 0.78rem; }
.raw-json summary { cursor: pointer; color: #64748b; }
.json-view { background: #0f172a; color: #e2e8f0; border-radius: 8px; padding: 0.8rem; font-size: 0.72rem; overflow-x: auto; margin-top: 0.5rem; max-height: 320px; overflow-y: auto; }
.modal-actions { padding: 0.8rem 1.25rem; border-top: 1px solid #e2e8f0; display: flex; justify-content: flex-end; position: sticky; bottom: 0; background: #fff; }
.alert.error { background: #fef2f2; color: #b91c1c; padding: 0.7rem 1rem; border-radius: 8px; font-size: 0.85rem; }

@media (max-width: 900px) {
  .grid-2 { grid-template-columns: 1fr; }
  .primary-metric-groups { grid-template-columns: 1fr; }
  .primary-metric-divider.divided { margin: 1.25rem 0 0; padding: 1.25rem 0 0; border-top: 1px solid #e2e8f0; border-left: 0; }
  .answer-compare, .citation-compare { grid-template-columns: 1fr; }
}

/* 2026.11.02(woojin.jung) 수정 - 반응형(태블릿/모바일) 대응 */
@media (max-width: 1024px) {
  .admin-header { padding: 1rem 1.5rem; }
  .admin-content { padding: 1.25rem 1.5rem; }
  .modal-overlay { padding: 16px; box-sizing: border-box; }
  .modal { width: min(680px, calc(100vw - 32px)); max-height: calc(100dvh - 32px); }
  .modal.xwide { width: min(920px, calc(100vw - 32px)); }
  .confirm-modal { width: min(420px, calc(100vw - 32px)); }
  .card-title { flex-wrap: wrap; }
  .card-title .filters { flex-wrap: wrap; }
}
/* 2026.11.03(woojin.jung) 수정 - 태블릿 가로는 데스크톱, 세로는 모바일 레이아웃(사이드바 숨김) */
@media (max-width: 768px), (max-width: 1024px) and (orientation: portrait), (max-width: 1024px) and (max-height: 500px) {
  .btn-hamburger { display: grid; place-items: center; width: 40px; height: 40px; flex-shrink: 0; }
  .delete-run-overlay { left: 0; }
}
@media (max-width: 900px) {
  .grid-2 { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 768px) {
  .admin-header { padding: 0.85rem 1rem; }
  .header-text h1 { font-size: 1.1rem; }
  .header-text p { display: none; }
  .admin-content { padding: 1rem; gap: 1rem; }
  .card { padding: 1rem; }
  .delete-run-overlay { padding-top: 12vh; }
  .card-title .filters { margin-left: 0; width: 100%; gap: 0.5rem; }
  .card-title .filters select { flex: 1 1 120px; }
  .history-scroll { overflow: auto; -webkit-overflow-scrolling: touch; }
  .history-scroll .data-table { min-width: 680px; }
  .history-scroll .data-table th, .history-scroll .status-badge { white-space: nowrap; }
  .citation-metric-row { flex-wrap: wrap; }
  .detail-section { min-width: 0; overflow-x: auto; }
  .modal-head { padding: 0.85rem 1rem; }
  .detail-body { padding: 1rem; }
  .modal-actions { padding: 0.7rem 1rem; }
  .btn-icon { width: 40px; height: 40px; }
  .btn-detail { min-height: 36px; }
}
</style>
