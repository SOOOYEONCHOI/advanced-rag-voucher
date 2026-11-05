"""
Kiwi 형태소 분석기 싱글톤 모듈.

법령 도메인 특화 패턴(정규식·약어)이 등록된 Kiwi 인스턴스를
애플리케이션 전역에서 공유한다.

참조: reference_code/Chatbot_Backend_v1/app/services/kiwi_tokenizer.py
  - KiwiTokenizer 클래스의 _kiwi 클래스 변수 패턴을 모듈 수준 싱글톤으로 적용
  - morphs(), morphs_query(), nouns() 메서드를 독립 함수로 제공

사용처:
  - app/utils/kiwi_tokenizer.py ← app/repositories/vector_repository.py  (BM25 토크나이즈)
  - app/utils/kiwi_tokenizer.py ← app/graphs/preprocessing/query_preprocessor.py (키워드 추출)
"""

import re
import unicodedata
from typing import List

from app.utils.dictionary_loader import load_korean_search_dictionary
from app.utils.log.log import LoggingLogger

# 2026.07.16(sooyeon.choi) 수정 - 모듈별 named logger 적용 (B16)
logger = LoggingLogger().getLogger(__name__)

# ── 품사 태그 상수 ─────────────────────────────────────────────────────────────
# 참조: kiwi_tokenizer.py morphs_query()
#   NNG(일반명사), NNP(고유명사), SL(알파벳), SH(한자), SN(숫자), VA(형용사), MAG(일반부사)
#   → 조사·어미·접미사 제외하여 키워드 검색 품질 향상
# 2026.06.29(sooyeon.choi) 수정 - BM25 query는 검색 기여도가 높은 명사/영문/한자만 사용
SEARCH_POS_TAGS = frozenset({"NNG", "NNP", "SL", "SH"})

# 2026.06.29(sooyeon.choi) 수정 - corpus에서도 조사/어미/접사/구두점을 제외해 query와 대칭화
CORPUS_EXCLUDE_TAGS = frozenset({
    "JKS", "JKC", "JKG", "JKO", "JKB", "JKV", "JKQ",
    "JX", "JC",
    "EP", "EF", "EC", "ETN", "ETM",
    "XPN", "XSN", "XSV", "XSA",
    "IC",
    "SF", "SP", "SS", "SE", "SO", "SW",
})

# 명사 추출용 품사 태그 (키워드 필터링·인덱싱에 사용)
NOUN_POS_TAGS = frozenset({"NNG", "NNP", "SL"})

# ── 싱글톤 인스턴스 ────────────────────────────────────────────────────────────
_kiwi = None


def get_kiwi():
    """법령 도메인 패턴이 등록된 Kiwi 싱글톤을 반환한다.

    최초 호출 시 1회만 초기화하며, kiwipiepy 미설치 시 None을 반환한다.
    """
    global _kiwi
    if _kiwi is not None:
        return _kiwi

    try:
        from kiwipiepy import Kiwi  # type: ignore[import-untyped]

        _kiwi = Kiwi()

        # 참조: kiwi_tokenizer.py — 법령 도메인 정규식 패턴 등록
        #   패턴 순서: '제2조'가 '2조'로 인식되지 않도록 법령 조문 패턴을 먼저 등록
        # 2026.06.26(sooyeon.choi) 수정 - 문자 클래스 내 | 오용 제거 및 법령 파생 패턴 보강
        _kiwi.add_re_word(r'[0-9.\-]+(?:%|년|명|위|인|장|조|호|회)', 'NNP')  # 숫자+단위
        _kiwi.add_re_word(
            r'제[0-9]+(?:조(?:의[0-9]+)?|장|항|호)(?:제[0-9]+(?:항|호))*',
            'NNP',
        )  # 법령 조문
        _kiwi.add_re_word(r'별표\s*[0-9]+', 'NNP')
        _kiwi.add_re_word(r'별지\s*제[0-9]+호서식', 'NNP')
        _kiwi.add_re_word(r'부칙\s*(?:제[0-9]+조)?', 'NNP')
        _kiwi.add_re_word(r'[가나다라마바사아자차카타파하]+[목]', 'NNP')      # 한글 목록 기호
        _kiwi.add_re_word(r'<[^>]+>', 'NNP')                                 # HTML 태그형 표현
        _kiwi.add_re_word(r'「[^」]+」', 'NNP')                              # 법령명 인용 괄호
        _kiwi.add_re_word(
            r'[0-9,]+(?:개월|미터|단계|만원|킬로그램|킬로미터)',
            'NNP',
        )  # 복합 수량 단위
        _kiwi.add_re_word(
            r'((\d{4})|\d{2})?(-|/|.|년 )?(?P<month>[1-9]|0[1-9]|1[0-2])'
            r'(-|/|.|월 )(?P<date>([1-9]|0[1-9]|[1-2][0-9]|3[01]))일',
            'NNP',
        )  # 날짜 패턴

        # 2026.06.26(sooyeon.choi) 수정 - YAML 통합 사전 기반으로 약어/복합어/영문 alias 등록
        dictionary = load_korean_search_dictionary()
        for term in dictionary.compound_terms:
            _kiwi.add_user_word(term, "NNP")

        # 2026.06.26(sooyeon.choi) 수정 - 약어/정식명 변수명을 의미가 드러나도록 정리
        for abbreviation, full_name in dictionary.abbreviations.items():
            _kiwi.add_user_word(full_name, "NNP")
            _kiwi.add_pre_analyzed_word(abbreviation, [(full_name, "NNP", 0, 0)])

        for alias, full_name in dictionary.aliases.items():
            _kiwi.add_user_word(alias, "SL")
            _kiwi.add_user_word(full_name, "NNP")

        # 워밍업 호출 — 첫 tokenize() 호출이 느린 현상 방지
        _kiwi.tokenize("예열")
        logger.info(
            "Kiwi 형태소 분석기 초기화 완료 (정규식 패턴 10개, 약어 %d개, 복합어 %d개, alias %d개 등록)",
            len(dictionary.abbreviations),
            len(dictionary.compound_terms),
            len(dictionary.aliases),
        )

    except ImportError:
        logger.warning(
            "kiwipiepy 미설치 — 형태소 분석 기능을 사용할 수 없습니다. "
            "BM25는 공백 분리, 키워드 추출은 빈 결과로 동작합니다."
        )
        _kiwi = None
    except Exception as exc:
        logger.error("Kiwi 초기화 실패: %s", exc)
        _kiwi = None

    return _kiwi


# ── 토크나이즈 함수 ────────────────────────────────────────────────────────────

def tokenize_corpus(text: str) -> List[str]:
    """BM25 corpus용 전체 형태소 토크나이즈.

    조사/어미/접사/구두점을 제외하고 2글자 이상의 형태소를 반환한다.
    Kiwi 불가 시 공백 분리 폴백.
    """
    kiwi = get_kiwi()
    if kiwi:
        # 2026.06.29(sooyeon.choi) 수정 - BM25 corpus/query의 명사 토큰 정책 대칭화
        return [
            token.form
            for token in kiwi.tokenize(text)
            if token.tag not in CORPUS_EXCLUDE_TAGS and len(token.form) >= 2
        ]
    return text.lower().split()


def tokenize_query(text: str) -> List[str]:
    """BM25 쿼리용 검색 품사 한정 토크나이즈.

    참조: kiwi_tokenizer.py morphs_query()
      - SEARCH_POS_TAGS에 해당하는 형태소만 추출 (조사·어미·접미사 제외)
      - 추출 결과가 없으면 전체 형태소를 반환하여 시맨틱 검색에 영향을 주지 않음
    Kiwi 불가 시 공백 분리 폴백.
    """
    kiwi = get_kiwi()
    if kiwi:
        # 2026.06.29(sooyeon.choi) 수정 - 단독 숫자/형용사/부사를 제외하고 최소 길이 통일
        return [
            t.form
            for t in kiwi.tokenize(text)
            if t.tag in SEARCH_POS_TAGS and len(t.form) >= 2
        ]
    return text.lower().split()


# 2026.06.29(sooyeon.choi) 수정 - Dense 검색은 자연어를 유지하고 BM25·메타데이터 검색은 불용어를 제거하도록 용도별 함수 분리
def _normalize_compound_spacing(text: str, compound_terms: List[str]) -> str:
    """복합어 내부의 한 칸 이상 띄어쓰기 변형을 붙여 쓴 표준형으로 바꾼다."""
    for term in sorted(compound_terms, key=len, reverse=True):
        if len(term) < 2:
            continue
        spaced_pattern = r"\s*".join(re.escape(char) for char in term)
        # 2026.06.29(sooyeon.choi) 수정 - 뒤에 조사가 붙은 복합어도 정규화하되 일반 단어 내부 매칭은 제한
        right_boundary = (
            r"(?=$|[^0-9A-Za-z가-힣]|"
            r"(?:은|는|이|가|을|를|의|에|도|만|와|과|로|으로|에서|부터|까지))"
        )
        pattern = rf"(?<![0-9A-Za-z가-힣]){spaced_pattern}{right_boundary}"
        text = re.sub(pattern, term, text)
    return text


def normalize_query(text: str) -> str:
    """Dense 의미를 보존하며 기본 정규화, 복합어 결합, 약어 확장을 수행한다."""
    # 2026.06.29(sooyeon.choi) 수정 - 불용어를 제거하지 않는 Dense 공용 정규화 경로 분리
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[^\S \t\n\r]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", "\n", text).strip()

    # 2026.06.29(sooyeon.choi) 수정 - 띄어 쓴 법령 조문을 Kiwi 보호 패턴의 표준형으로 결합
    text = re.sub(
        r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?",
        lambda match: (
            f"제{match.group(1)}조"
            + (f"의{match.group(2)}" if match.group(2) else "")
        ),
        text,
    )
    text = re.sub(r"제\s*(\d+)\s*(항|호)", r"제\1\2", text)

    dictionary = load_korean_search_dictionary()
    text = _normalize_compound_spacing(text, dictionary.compound_terms)
    for abbreviation, full_name in dictionary.abbreviations.items():
        text = text.replace(abbreviation, full_name)
    return text


def extract_search_terms(text: str) -> List[str]:
    """metadata boost/filter 후보용 검색어를 추출하고 기능성 불용어를 제거한다."""
    # 2026.06.29(sooyeon.choi) 수정 - 자연어 Dense query와 분리된 검색 후보 전용 불용어 정책
    dictionary = load_korean_search_dictionary()
    functional_stopwords = dictionary.stopwords_query_functional
    seen: set[str] = set()
    result: List[str] = []

    for raw_token in text.split():
        token = raw_token.strip(".,!?()[]{}<>\"'“”‘’")
        if (
            len(token) >= 2
            and token not in seen
            and token not in functional_stopwords
            and not token.endswith(("줘", "요", "세요", "주세요", "습니다"))
        ):
            seen.add(token)
            result.append(token)

    for token in extract_nouns(text, min_len=2):
        if token not in seen and token not in functional_stopwords:
            seen.add(token)
            result.append(token)
    return result


def tokenize_query_for_bm25(text: str) -> List[str]:
    """복합어·약어를 정규화한 뒤 BM25 query용 검색어를 반환한다."""
    # 2026.06.29(sooyeon.choi) 수정 - Kiwi BM25 채널 전용 진입점 추가
    normalized = normalize_query(text)
    dictionary = load_korean_search_dictionary()
    tokens = tokenize_query(normalized)
    filtered = [
        token
        for token in tokens
        if token not in dictionary.stopwords_query_functional
        and not token.endswith(("줘", "요", "세요", "주세요", "습니다"))
    ]
    # 2026.06.29(sooyeon.choi) 수정 - Kiwi 명사 토큰을 우선 사용하고 분석 결과가 없을 때만 공백 토큰으로 보완
    return list(dict.fromkeys(filtered)) if filtered else extract_search_terms(normalized)


def is_domain_weak_term(term: str) -> bool:
    """낮은 metadata boost를 적용할 도메인 약한 검색어인지 반환한다."""
    # 2026.06.29(sooyeon.choi) 수정 - 완전 제거 불용어와 약한 boost 후보를 명시적으로 분리
    return term in load_korean_search_dictionary().stopwords_domain_weak


def extract_nouns(text: str, min_len: int = 2) -> List[str]:
    """명사 키워드 추출 (NNG/NNP/SL, 중복 제거, 순서 유지).

    참조: kiwi_tokenizer.py nouns() — NNG/NNP/SL 품사 명사 반환.
    query_preprocessor의 _extract_keywords()에서 사용한다.

    Args:
        text: 분석할 텍스트.
        min_len: 반환할 토큰 최소 길이 (기본 2, 1글자 단어 제외).

    Returns:
        중복 제거된 명사 키워드 목록 (입력 순서 유지).
    """
    kiwi = get_kiwi()
    if kiwi is None:
        return []
    try:
        seen: set[str] = set()
        result: List[str] = []
        for token in kiwi.tokenize(text):
            if (
                token.tag in NOUN_POS_TAGS
                and len(token.form) >= min_len
                and token.form not in seen
            ):
                seen.add(token.form)
                result.append(token.form)
        return result
    except Exception as exc:
        logger.error("형태소 분석 중 오류: %s", exc)
        return []
