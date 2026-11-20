import DOMPurify from 'dompurify';
import { marked } from 'marked';

marked.setOptions({
  breaks: true,
  gfm: true,
});

export const escapeHtml = (value = '') => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

export const formatResponse = (text = '') => {
  const html = marked.parse(String(text || ''));
  return DOMPurify.sanitize(html, {
    ADD_ATTR: ['target', 'rel'],
  });
};

export const sortCitations = (citations = []) => [...citations].sort((a, b) => (parseInt(a.citation_id) || 0) - (parseInt(b.citation_id) || 0));

// 동일한 문서는 한 번만 표시하고, 선택 가능한 페이지 목록을 함께 구성한다.
// 2026.07.10(sooeyon.choi) 추가 - 매핑된 매뉴얼 citation은 표시용 원본 PDF 기준 파일명/페이지 사용
export const citationDisplayFilename = (citation) =>
  citation?.manual_display_mapped
    ? citation.display_filename || citation.original_filename || citation.document_name || '문서명 없음'
    : citation?.original_filename || citation?.document_name || '문서명 없음';

export const citationDisplayPage = (citation) => (citation?.manual_display_mapped ? citation.display_page_number : citation?.page_number);

export const groupCitationsByDocument = (citations = []) => {
  const groups = new Map();

  sortCitations(citations).forEach((citation) => {
    const displayFilename = citationDisplayFilename(citation);
    const displayPage = citationDisplayPage(citation);
    const documentKey = String(displayFilename).trim().toLocaleLowerCase('ko-KR');
    if (!groups.has(documentKey)) {
      groups.set(documentKey, { key: documentKey, filename: displayFilename, pages: [] });
    }

    const group = groups.get(documentKey);
    const pageKey = displayPage == null ? `citation-${citation.citation_id}` : `page-${displayPage}`;
    if (!group.pages.some((item) => item.pageKey === pageKey)) {
      group.pages.push({ pageKey, citation });
    }
  });

  return [...groups.values()].map((group) => ({
    ...group,
    pages: group.pages.sort((a, b) => {
      const pageA = Number(citationDisplayPage(a.citation));
      const pageB = Number(citationDisplayPage(b.citation));
      if (Number.isFinite(pageA) && Number.isFinite(pageB)) return pageA - pageB;
      if (Number.isFinite(pageA)) return -1;
      if (Number.isFinite(pageB)) return 1;
      return (parseInt(a.citation.citation_id) || 0) - (parseInt(b.citation.citation_id) || 0);
    }),
  }));
};

// 2026.07.10(sooyeon.choi) 수정 - 답변별로 반복되는 citation_id를 구분하도록 메시지 인덱스 전달
export const renderInlineCitations = (html, citations = [], renderPending = false, selectedCitationId = null, messageIndex = null, images = []) => {
  let rendered = html;

  if (citations?.length || renderPending)
    rendered = rendered.replace(/\[(\d+)\]/g, (match, num) => {
      const id = parseInt(num);
      const exists = citations.some((c) => c.citation_id === id || c.citation_id === String(id));
      const isActive = selectedCitationId != null && (selectedCitationId === id || selectedCitationId === String(id));
      if (!exists) {
        if (!renderPending) return match;
        return `<span class="inline-citation pending${isActive ? ' active' : ''}" data-citation-id="${id}">[${num}]</span>`;
      }
      const messageArg = Number.isInteger(messageIndex) ? `, ${messageIndex}` : '';
      return `<span class="inline-citation${isActive ? ' active' : ''}" data-citation-id="${id}" onclick="window.__openCitation(${id}${messageArg})">[${num}]</span>`;
    });

  // 2026.10.22(woojin.jung) 수정 - 답변의 [IMG:ref]를 해당 메시지 이미지 뷰어를 여는 번호 배지로 변환
  // 2026.11.04 수정 - 스트리밍 중 LLM이 대괄호 없이 쓴 img:ref도 같은 배지로 변환
  return rendered.replace(/\[IMG:([A-Za-z0-9_-]{1,160})\]|(?<![[\w])img:([A-Za-z0-9_-]{1,160})/gi, (match, tagRef, bareRef) => {
    const ref = tagRef || bareRef;
    const imageIndex = images.findIndex((image) => image?.ref === ref);
    if (imageIndex < 0) return renderPending ? '<span class="image-ref pending"><i class="fa-regular fa-image"></i></span>' : '';
    const imageNumber = imageIndex + 1;
    const messageArg = Number.isInteger(messageIndex) ? messageIndex : -1;
    return `<button type="button" class="image-ref" title="사진 ${imageNumber} 원본 보기" onclick="window.__openAnswerImage(${messageArg}, ${imageIndex})"><i class="fa-regular fa-image"></i> ${imageNumber}</button>`;
  });
};

export const formatFileSize = (bytes) => {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
};

export const formatTime = (value) => {
  if (!value) return '-';

  const raw = String(value).trim();
  const match = raw.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})/);

  return match ? `${match[1]} ${match[2]}` : raw;
};

export const docTypeLabel = (type) => {
  const map = { law: '법령', manual: '매뉴얼', general: '일반', spreadsheet: '스프레드시트', drawing: '도면' };
  return map[type] || type || '-';
};
export const docTypeSourceLabel = (source) => {
  const map = {
    user_selected: '사용자 선택',
    auto_detected: '자동 감지',
    file_extension: '파일 확장자',
  };
  return map[source] || source || '-';
};

// 서버 내부 파서 식별자를 문서 목록에 노출할 사용자용 이름으로 변환한다.
export const parserTypeLabel = (type) => {
  const map = {
    excel_ingest: '엑셀 처리기',
    drawing_ingest: '도면 처리기',
  };
  return map[type] || type || '-';
};
