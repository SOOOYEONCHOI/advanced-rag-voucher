"""NEOCON C2 비전검사항목 기본 데이터 — 검사 분류·검사항목·설명·라벨 클래스·측정점. 운영 포함, 멱등.

    python manage.py seed_vision_items                         # 없는 것만 만든다
    python manage.py seed_vision_items --update-descriptions   # 설명(검사항목·측정점)만 이 파일 내용으로 바꾼다

근거는 tmp/docs/NEOCON_C2_문서대장_시트정리 의 성적서·체크시트 항목이다(사용자 결정 2026-10-20).
촬영은 두 가지다 — `VIS-` 는 고정 거치대(흑백 카메라·조명, 높이는 Overlay 로 맞춤), `TAB-` 는 태블릿
(디지털 양식 "사진 넣기"). 1차 판정 대상은 VIS-CLN·VIS-ROT-SF 이고 TAB- 는 학습 데이터부터 모은다.

설명은 같은 머리로 쓴다 — 검사 목적 / 검사 항목(문서·표·번호 원문) / 검사 기준 / 역할 /
촬영 방법 / 라벨링 기준(치수 측정은 측정 방법). 문서에 없는 값(촬영 높이·장수 등)은 "사용자 결정"으로 적는다.

검사 분류(고정 대분류 3개 — `category.ensure_fixed_majors` — › 중분류)를 이름으로 찾아 없으면 만들고, 소속이 빈 검사항목만 그 중분류에 넣는다. 양식 매핑은 화면에서 한다.
없는 것만 만든다 — 이미 있는 검사항목·라벨 클래스·측정점은 화면에서 고친 값을 덮지 않는다(이름·설명·유형 그대로).
설명을 고쳐 다시 넣을 때만 `--update-descriptions` 를 준다. 이름·유형·라벨 클래스·규격은 그때도 그대로다.
"""
from decimal import Decimal
from textwrap import dedent

from django.core.management.base import BaseCommand

from domain.models.data import InspectionCategory, InspectionItem, LabelClass, MeasurementPoint
from domain.services.data import category as categories
from domain.services.data.audit import AuditService
from domain.services.data.item import ItemService
from domain.tenancy import current_tenant, tenant_atomic

T = InspectionItem.TaskType
ROTOR_DEFECTS = [('scratch', '흠집', '#E4572E'), ('dent', '찍힘', '#F3A712'), ('crack', '균열', '#D7263D'),
                 ('contamination', '오염/이물', '#6C757D'), ('coating_peel', '코팅 벗겨짐', '#7B2CBF')]

# 고정 거치대 장비 — 설명마다 같은 문구를 쓴다.
RIG = '고정 거치대에서 찍습니다. 흑백 카메라(2448×2048) + 8mm 렌즈, 조명은 거치대에 달려 있습니다'


def text(body):
    return dedent(body).strip()


DESCRIPTIONS = {
    'VIS-CLN': text(f'''
        ■ 검사 목적
        설비를 닦아 낸 흰 천의 사진으로 오염도를 1~10단계로 분류하고, 단계에 따라 적합·재세정·부적합을 정합니다. 출하 검수의 외관검사(Cleaning)에서 씁니다.

        ■ 검사 항목
        - 출하검수Sheet(문서대장 18번 시트) › ▣ 외관검사 - Cleaning 검사 › 1 제습 Module <C2-1> · 2 제습 Module <C2-2> · 3 POWER BOX · 4 Filter Duct · 5 Bypass Duct Cleaning 검사. 측정 값 칸에 단계(" 단계")를 적습니다
        - 같은 시트의 오염도 견본표 — 1단계~10단계 견본 사진과 단계별 조치
        - 전장 ASSY Check Sheet(6번 시트) › 1. 외관 검사 › 외관 공통 Cleaning 검사 No 30 "모든 제품 세정 상태 확인." (검사 TOOL: 육안, 와이퍼, 렌턴)

        ■ 검사 기준
        - 출하 Cleaning 1~5: 판정 기준 "외관기준서", SPEC "없을 것"
        - 견본표 조치: 1~2단계 "라인 반입" / 3~4단계 "Cleaning 後 재 측정" / 5~10단계 "반출 및 업체 cleaning 후 재 측정"
        - 전장 No 30: "제품 상에 이물, 오염물 없을 것. "A" 등급 이상 CLEAN ROOM 입고 가능. "B~C" 등급 재세정 할 것. "D~E" 등급 부적합 (반출)"
        - 시트의 주의 문구: "※ 설비 內 Bolt, Nut, Tie, 이물질 방치 여부 必 확인  것"

        ■ 역할
        - AI: 흰 천 사진의 오염도 단계(1~10)를 분류하고 세 가지로 정합니다 — 적합(1~2단계), 재세정(3~4단계), 부적합(5~10단계)
        - 사람: 닦을 부위·닦는 방법, 설비 안 Bolt·Nut·Tie·이물질 방치 확인, 성적서 판정 기록

        ■ 촬영 방법
        - {RIG}(확산 조명)
        - 높이 약 300mm. 화면의 Overlay 윤곽에 천이 맞도록 테이블 높이를 맞춥니다
        - 부위(1~5)마다 새 흰 천으로 닦고, 닦은 면이 위로 오게 무광 검은 바탕 가운데에 펴서 1장씩 찍습니다 — 설비 1대에 5장
        - 천이 접히거나 그림자가 지지 않게 하고, 천 말고 다른 물건이 화면에 들어가지 않게 합니다

        ■ 라벨링 기준
        - 견본표 사진과 견줘 가장 가까운 단계 하나를 고릅니다(1단계~10단계). 3단계부터 불량 클래스입니다
    '''),
    'VIS-ROT-SF': text(f'''
        ■ 검사 목적
        입고된 Rotor Assy 앞·뒷면 사진에서 큰 표면 결함(흠집·찍힘·균열·오염/이물·코팅 벗겨짐)을 AI 이상 탐지로 찾아 정상/이상으로 판정합니다. 수입 검사(원류 관리 › Rotor 입고 검수)에서 씁니다.

        ■ 검사 항목
        - Rotor수입검사성적서(문서대장 5번 시트) › Rotor Assy 성적서(을지) › 점검표 외관검사 1 흠집 · 2 찍힘 · 3 균열 · 4 오염/이물 · 5 Silicin 코팅
        - 대상: 품명 ASSY_ROTOR_450X100T_DRI(도면 MODEL: AT-450카세트)
        - 샘플링: 갑지 "2. 샘플링 검사표_KS B ISO 2768-1 을 참조한 예스티 자체기준" 보통검사. "샘플검사 中 부적합 발생 時 전수검사 적용함."
        - 기록: 을지 검사자명·검사일자, Rotor S/N

        ■ 검사 기준
        - 1 흠집: 허용 "깊이 0.2mm 이하, 길이 10mm 이하 허용(비접촉면)" / 불합격 "깊이 0.2mm 초과 또는 Scratch 10mm 이상 접촉면에서의 흠집 발생 시"
        - 2 찍힘: 허용 "직경 1mm 이하, 깊이 0.1mm 이하 적용(비접촉면)" / 불합격 "1mm 초과 또는 접촉면에 위치한 경우"
        - 3 균열: "균열 확인 시 전량 폐기" / "허용 불가"
        - 4 오염/이물: 불합격 "고착된 오염물, 유분, 녹 능 제거 불가능한 경우" / 허용 "세척으로 제거 가능한 수준 허용"
        - 5 Silicin 코팅: "Silicon 도포 상태 균일 및 Center Bearing Silicon 접착 부 떨어짐 확인" / "벗겨짐 2mm 초과, 면적 5% 이상 균일 시 · Silicon 접착 부 떨어짐 없을 것"

        ■ 역할
        - AI: 사진에 보이는 결함 — 코팅 벗겨짐, 이물, 큰 찍힘·흠집, 눈에 띄는 균열
        - 사람: 깊이(0.2mm·0.1mm), 직경 1mm 이하 찍힘, 미세 균열. 출하검수Sheet Rotor 검사 기준의 방법대로 "300 ~ 500 Lux 조도 환경에서 맨눈 또는 확대경(5배 이내)", 필요하면 "크랙확인을 위한 침투 탐상 검사(PT)"
        - AI 가 정상이어도 성적서 판정은 검사자가 합니다

        ■ 촬영 방법
        - {RIG}(저각 조명 — 표면 결함의 그림자가 보이게)
        - 높이 약 560mm. 화면의 Overlay 윤곽에 Rotor 테두리가 맞도록 테이블 높이를 맞춥니다
        - 비닐 포장을 벗기고 무광 검은 바탕 가운데에 놓습니다. 앞면 1장, 뒤집어 뒷면 1장 — Rotor 1개에 2장
        - 손·공구·라벨지가 화면에 들어가지 않게 하고, 반사광이 생기면 조명 각도를 바꿉니다

        ■ 라벨링 기준
        - 결함마다 Polygon 으로 둘러쌉니다: 흠집 scratch, 찍힘 dent, 균열 crack, 오염/이물 contamination, 코팅 벗겨짐 coating_peel
        - 결함이 없으면 영역 없이 작업 완료합니다(정상)
    '''),
    'VIS-ROT-DIM': text(f'''
        ■ 검사 목적
        입고된 Rotor 카세트를 크기를 아는 기준물과 함께 위에서 찍으면, 클라이언트가 사진에서 POINT A·B·C 길이를 재서 보내고 서버가 규격으로 합격·불합격을 정합니다. 수입 검사에서 씁니다.

        ■ 검사 항목
        - Rotor수입검사성적서(문서대장 5번 시트) › Rotor Assy 성적서(을지) › 점검표 외관검사 6 치수
        - 같은 을지 › 치수검사 › POINT A 540±1(mm) · B 540±1 (mm) · C 154±1 (mm). 측정값 1st·2nd·3nd 칸, 측정기기 원문 "줄자(철자), 벨트 텐션측정기"

        ■ 검사 기준
        - 외관검사 6 치수: "설계 치수 기준 (±) 공차 이내" / 불합격 "공차 범위 초과 시"
        - 갑지 일반공차표(KS B ISO 2768-1): 400초과 1000이하 정 ±0.3 · 중 ±0.8 · 하 ±2, 120초과 400이하 ±0.2 · ±0.5 · ±1.2. "도면에 수치차, 등급의 표시가 없을때에는 중급을 적용함."
        - POINT 규격(±1)이 있으면 그 값으로 판정합니다

        ■ 역할
        - 비전(클라이언트 계산): POINT A·B·C 평면 치수. 측정점 하나라도 범위를 벗어나면 불합격입니다
        - 사람: POINT D·E·F·G Timing Belt Tension 90±5(Hz) — 벨트 텐션측정기, "Tension 측정시 Rotor의 Belt block이 4ea가 Belt에 물려 있어야 함". POINT H·I·J·K Seal Gap 0.08±0.03(mm) — Gap Gauge. POINT L 은 규격이 비어 있어 넣지 않았습니다
        - 이 장비로 재는 것은 ±0.3~1mm 급 평면 치수입니다. ±0.05mm 급·깊이·Gap 은 게이지로 잽니다

        ■ 촬영 방법
        - {RIG}
        - 높이 약 650mm(약 0.28mm/화소, 한 장 범위 약 690×580mm). 화면의 Overlay 윤곽에 카세트가 맞도록 테이블 높이를 맞춥니다
        - 크기를 아는 기준물을 카세트와 같은 높이의 면에 함께 놓고 1장 찍습니다. 클라이언트가 기준물로 사진마다 배율(mm/화소)을 구합니다
        - 카메라가 수직으로 내려다보게 합니다. 기울어 찍히면 다시 찍습니다

        ■ 측정 방법
        - 측정점마다 어디서 어디까지 재는지는 측정점의 측정 방법에 적었습니다(A·B·C). 클라이언트는 측정점 코드로 값을 mm 로 보냅니다
    '''),
    'TAB-IMK': text('''
        ■ 검사 목적
        설비·모듈의 볼트 체결부를 태블릿으로 찍어 I-Marking 누락·불량을 찾는 AI 학습 데이터를 모읍니다. 지금은 사람이 판정하고 사진은 학습용입니다. 조립·중간 검수·출하 검수에서 디지털 양식 "사진 넣기"로 올립니다.

        ■ 검사 항목
        - 출하검수Sheet(문서대장 18번 시트) › ▣ 8계통 검사 › 2 "설비 內 체결되는 기구부 모든 Bolt 1줄(빨간색)로 I-Marking 표식 누락여부 확인" (판정 기준 육안확인, SPEC 없을 것)
        - 전장 ASSY Check Sheet(6번 시트) › 1. 외관 검사 › I∙Marking 작업 상태 검사 No 20 "I∙Marking 상태 확인."
        - Module Check Sheet(13번 시트) › Rotor · FAN · Heater A'ssy 작업 Check Sheet › "Bolt I-Marking" (SPEC "YEST 8계통 기준 ver Rev.2_251118")
        - 중간 검수 성적서(16번 시트) › 조립·공통, 전장·공통 "I-Marking 확인"
        - Recheck Sheet(14번 시트) › 8계통-체결 I-Marking 불량·누락 카드

        ■ 검사 기준
        - 출하 8계통 검사 방법: "I-Marking 표시는 Bolt에서 모재까지 연결되게 표식 I-Marking 색상은 최종상태 "적색" 을 적용", "설비 내부 : 체결部 전체 I-Marking 적용"
        - 전장 No 20: "I∙Marking은 외적으로 보이는 방향으로 할 것. (설계적, 구조적 방향 미준수 허용)" · "I∙Marking은 Edding Pen 사용을 사용 할 것. (네임펜 사용 불가)" · "I∙Marking 번짐, 이중 Marking 없을 것."

        ■ 역할
        - AI(학습 뒤): 사진에 보이는 I-Marking 누락·번짐·이중 Marking·끊김
        - 사람: 지금의 판정 전부, 그리고 토크·재체결 확인(조립 SOP "볼트 체결 후 아이 마킹 검사법" — 너트 회전량·금매김)
        - 배관 꺾임·I-Marking(출하 8계통 3)은 이 항목이 아닙니다

        ■ 촬영 방법
        - 태블릿으로 디지털 양식의 비전 연결 이미지 칸에서 "사진 넣기"로 찍습니다
        - 체결부 정면에서 볼트 머리와 주변 모재가 함께 보이게, 한 장에 볼트 1~4개, 볼트가 화면 절반 이상을 차지하도록 가까이 찍습니다
        - 플래시 반사가 마킹을 가리지 않게 하고, 초점이 볼트 머리에 맞았는지 확인합니다

        ■ 라벨링 기준
        - 박스로 표시합니다. I-Marking 이 없는 볼트는 I-Marking 누락(imark_missing)
        - 번짐·이중 Marking·끊김·모재까지 이어지지 않음·적색이 아님은 I-Marking 불량(imark_bad)
        - 볼트가 없는 체결 Hole 은 볼트 미체결(bolt_missing), 막지 않은 미사용 Hole 은 미사용 Hole 미마감(hole_open), 와셔가 없음은 와셔 누락(washer_missing) — 8계통 Check Sheet(15번 시트) 체결 기준
        - 정상 볼트는 표시하지 않습니다(박스가 없으면 정상)
    '''),
    'TAB-LBL': text('''
        ■ 검사 목적
        설비 면마다 안전라벨·명판 사진을 모아 라벨 손상·오염·오부착을 찾는 AI 학습 데이터를 만듭니다. 출하 검수의 안전 표기 확인에서 씁니다. 지금은 사람이 판정합니다.

        ■ 검사 항목
        - 출하검수Sheet(문서대장 18번 시트) › ▣ 안전 표기 부착 위치(판정 기준 "제품사양서")
          · 1 "비상정지 스위치 표시 확인[EMS Switch] - Pendent, 전장 Box 정면" — 2 POINT
          · 2 "제습 Module의 안전표기 라벨 부착 확인 [ 회전하는 팬 경고, 고온 경고, 감전 경고 ]" — 10 POINT
          · 3 "전장 Box의 안전표기 라벨 부착 확인 [ 감전 경고, 지시 라벨(장금장치) ]" — 2 POINT
          · 4 "전장 Box의 제품 명판 부착 확인 [ 사양, Serail No. ]" — 1 POINT
        - 전장 ASSY Check Sheet(6번 시트) › 1. 외관 검사 › 라벨 작업 상태 검사 No 18 "各 Part, Unit別 라벨 부착 상태 확인." · No 19 "안정라벨 기준 준수 및 부착상태 확인."
        - Recheck Sheet(14번 시트) › 안전라벨 부착 누락·명판 장착 누락·비상정지 스위치(EMS) Cover 장착 누락 카드

        ■ 검사 기준
        - 전장 No 18: "누락, 손상, 오염, 오기입, 오부착 없을 것. LINE別 라벨 색상 구분 할 것."
        - 전장 No 19: "안전 라벨 기준서와 일치 할 것. 안전 라벨 부착은 임의의로 부착 하지 않을 것."
        - 출하 안전 표기 참고: "[안전표지 사이즈] S : 105 x 35 M : 135 x 45 L : 195 x 65", 크기를 바꿔도 "가로×세로 비율은 맞춰야 한다"

        ■ 역할
        - AI(학습 뒤): 라벨 손상·오염·오부착(위치·방향·종류)
        - 사람: 부착 누락은 면별 사진의 라벨 개수를 POINT 수(EMS 2, 제습 Module 10, 전장 Box 2, 명판 1)와 견줘 판단합니다. 라벨 내용과 명판 사양·Serial No. 대조도 사람이 합니다

        ■ 촬영 방법
        - 태블릿으로 디지털 양식의 비전 연결 이미지 칸에서 "사진 넣기"로 찍습니다
        - 면마다 1장: 제습 Module UPPER · LEFT · RIGHT · Front, 전장 Box 정면(EMS·감전 경고·지시 라벨·명판), Pendent EMS
        - 그 면의 라벨이 모두 들어오고 라벨 글자가 읽히는 거리에서 정면으로 찍습니다

        ■ 라벨링 기준
        - 박스로 표시합니다. 찢김·벗겨짐·들뜸은 라벨 손상(label_damaged), 오염·변색·글자가 안 보임은 라벨 오염(label_dirty)
        - 위치·방향·종류가 기준과 다르면 라벨 오부착(label_misplaced)
        - 비상정지 스위치(EMS) Cover 가 없으면 EMS Cover 누락(ems_cover_missing) — Recheck Sheet(14번 시트) 카드
        - 정상 라벨은 표시하지 않습니다
    '''),
    'TAB-ROT': text('''
        ■ 검사 목적
        출하 전 제습 Module 에 설치된 Rotor 를 모듈마다 찍어 출하검수Sheet 의 Rotor 사진 칸을 채우고, Rotor 파손 이상 탐지 학습 데이터를 모읍니다. 지금은 사람이 판정합니다.

        ■ 검사 항목
        - 출하검수Sheet(문서대장 18번 시트) › ▣ 외관검사 - Rotor 파손 검사 › 1 흠집(Scratch) · 2 찍힘(Dent) · 3 균열(Crack) · 4 오염 / 이물 · 5 도색 / 코팅 · 6 치수 이상 · 7 샤프트 변형. 측정 값 칸에 "이상없음"이 미리 적혀 있습니다
        - 같은 구역의 "■ 제습 Module 1 Rotor 사진." · "2" · "3" 실물 사진 첨부 칸과 "■ Rotor 양품 사진"

        ■ 검사 기준
        - 1 흠집: "깊이 0.2mm 이하, 길이 10mm 이하 허용 (비접촉면)" / 불합격 "깊이 0.2mm 초과 또는 접촉면에서의 흠집 발생 시"
        - 2 찍힘: "직경 1mm 이하, 깊이 0.1mm 이하 적용 (비접촉면)" / 불합격 "1mm 초과 또는 접촉면에 위치한 경우"
        - 3 균열: "허용 불가" / "균열 확인 시 전량 폐기"
        - 4 오염 / 이물: "세척으로 제거 가능한 수준 허용" / 불합격 "고착된 오염물, 유분, 녹 능 제거 불가능한 경우"
        - 5 도색 / 코팅: "벗겨짐, 기포, 색상 불균일 등 없을 것" / 불합격 "벗겨짐 2mm 초과 또는 면적 5% 이상 균일 시"
        - "상기 기준 중 하나라도 불량 판정 기준에 해당하면 "불합격"으로 간주 함"

        ■ 역할
        - AI(학습 뒤): 사진에 보이는 1~5
        - 사람: 6 치수 이상("협력업체 성적서 참조"), 7 샤프트 변형("동심도, 진직도"), 깊이·미세 결함 — "300 ~ 500 Lux 조도 환경에서 맨눈 또는 확대경(5배 이내)"

        ■ 촬영 방법
        - 태블릿으로 디지털 양식의 비전 연결 이미지 칸에서 "사진 넣기"로 찍습니다
        - 모듈마다 Rotor 전체가 한 장에 들어오게 1장(제습 Module 1·2·3), 시트의 Rotor 양품 사진과 같은 방향에서 찍습니다
        - 결함이 보이면 그 자리를 가까이 1장 더 찍습니다

        ■ 라벨링 기준
        - 결함마다 Polygon 으로 둘러쌉니다: 흠집 scratch, 찍힘 dent, 균열 crack, 오염/이물 contamination, 코팅 벗겨짐 coating_peel
        - 결함이 없으면 영역 없이 작업 완료합니다(정상)
    '''),
    'TAB-TRM': text('''
        ■ 검사 목적
        전장 Box·모듈의 단자대·커넥터를 가까이 찍어 압착 불량·심선 손상·PIN 빠짐을 찾는 AI 학습 데이터를 모읍니다. 지금은 사람이 판정합니다.

        ■ 검사 항목
        - 전장 ASSY Check Sheet(문서대장 6번 시트) › 1. 외관 검사 › 압착 상태 검사(LUG, PIN Type Cable, Harness) No 1 "단자 압착 상태." · No 2 "압착 후 심선 손상, 파손 상태." · Connector 작업 상태 검사 No 6 "Connector PIN 삽입 상태."
        - 출하검수Sheet(18번 시트) › ▣ 8계통 검사 › 7 "설비 內 Cable 피복 손상이 있는 확인" · 8 "Cable 심선은 압착단자 In/Out 단 1mm 이하 관리여부 확인"
        - 중간 검수 성적서(16번 시트) › 전장·Local 배선 "Connector Pin 빠짐 확인"

        ■ 검사 기준
        - 전장 No 1: "접합부 중앙에 압착 할 것. 피복과의 거리 확인 할 것. (1mm 이하) 1단자 1전선 압착 할 것. 피복 압착부 모양, 입착 정도 이상이 없을 것."
        - 전장 No 2: "심선 1개 이하로 손상, 파손 없을 것."
        - 전장 No 6: "PIN 심선분리, 끊어짐, 빠짐 없을 것."
        - 중간 검수: "Pin 빠짐 없을 것"

        ■ 역할
        - AI(학습 뒤): 사진에 보이는 압착 위치 벗어남·심선 노출·PIN 빠짐
        - 사람: 당김(인장) 확인, 전용 압착 공구 사용, O형 Lug 사용 여부

        ■ 촬영 방법
        - 태블릿으로 디지털 양식의 비전 연결 이미지 칸에서 "사진 넣기"로 찍습니다
        - 단자대·커넥터 구역마다 단자 4~8개가 한 장에 들어오게 가까이, 피복 끝부터 단자 끝까지 보이게 정면에서 찍습니다
        - 그림자·반사가 압착부를 가리지 않게 합니다

        ■ 라벨링 기준
        - 박스로 표시합니다. 압착 위치 벗어남·피복 거리 1mm 초과·한 단자에 두 전선은 압착 불량(crimp_bad)
        - 심선 노출·끊김은 심선 손상(strand_damage), PIN 빠짐·들뜸은 PIN 빠짐(pin_out)
        - 전장 ASSY Check Sheet(6번 시트)·8계통 Check Sheet(15번 시트) 기준으로 더 표시합니다: 커넥터 들뜸·체결 누락 connector_loose, 넘버링 빠짐·번짐 numbering_bad,
          단자 꺾임 terminal_bent, Y형 등 단자 형식 불량 lug_wrong, 접지 체결 불량(1개소 여러 Cable 등) ground_bad, 단자 이물 terminal_foreign
        - 정상 단자는 표시하지 않습니다
    '''),
    'TAB-PRT': text('''
        ■ 검사 목적
        입고된 판금·가공품(BOX·COVER·FRAME 등)을 태블릿으로 찍어 찍힘·Scratch·Crack·오염·Burr·부식·용접 결함·도장 박리를 찾는 AI 학습 데이터를 모읍니다. 수입 검사에서 디지털 양식 "사진 넣기"로 올립니다. 지금은 사람이 판정합니다.

        ■ 검사 항목
        - 수입검사성적서(가공품)(문서대장 4번 시트) › ■ 공통 검사 항목 › 용접 후 외관검사 "산화, 부식, 백화" · "Crack, Broken", 제품 외관검사 "찍힘" · "Scratch" · "오염" · "이물질, Burr 가공Chip". 측정값 칸은 Point 수입니다
        - 전장 ASSY Check Sheet(6번 시트) › 1. 외관 검사 › 가공품 외관 상태 검사(판금, 제관품) No 21 "가공품 외관 상태 확인." · No 22 "후처리 외관 상태 확인."
        - 수량 파악 및 자재 이동(8번 시트) › "포장 제거 후 파트 스크래치 확인" · "도장품 상태(스크레치/도장 깨짐)" · "가공품 상태"
        - 중간 검수 성적서(16번 시트) › 입고·육안 검수 11 "판/가공품 포장 제거 후 Scrach 및 수량 확인 후 Cleaning"

        ■ 검사 기준
        - 4번 시트: 용접 후 외관검사 "(이상 없을 것)", 제품 외관검사 "(이상 없을것)", Spec "0 Point"
        - 6번 No 21: "외부 노출부 찍힘, Scratch, Crack, Burr 없을 것." "(외부 비노출부(내부) 찍힘, Scratch 덧칠 허용)" · "용입, 언더필, 스패터, 기공, 균열, 변형 없을 것." · "녹, 변형, 백화, 오염, 얼룩이 없을 것."
        - 6번 No 22: "도장은 색상, 광택, 박리, 도막두께 이상 없을 것."
        - 16번 11: "Scrach 없을 것"

        ■ 역할
        - AI(학습 뒤): 사진에 보이는 결함의 위치·종류와 개수(Point)
        - 사람: 색상·광택·도막두께, 내부 비노출부 덧칠 허용 판단, 청정 등급(VIS-CLN), 수량 확인

        ■ 촬영 방법
        - 태블릿으로 디지털 양식의 비전 연결 이미지 칸에서 "사진 넣기"로 찍습니다
        - 포장을 벗긴 뒤 부품 전체가 들어오게 면마다 1장, 결함이 보이면 그 자리를 가까이 1장 더 찍습니다
        - 도장면 반사가 결함을 가리지 않게 각도를 바꿔 찍습니다

        ■ 라벨링 기준
        - 박스로 표시합니다: Scratch scratch, 찍힘 dent, Crack·Broken·균열 crack, 오염·얼룩·이물질 contamination, Burr·가공 Chip burr, 산화·부식·백화·녹 corrosion
        - 언더컷·오버랩·스패터·기공·Back bead 는 용접 결함(weld_defect), 도장 박리는 코팅 벗겨짐(coating_peel)
        - 정상 부위는 표시하지 않습니다
    '''),
    'TAB-EPD': text('''
        ■ 검사 목적
        재생 Heater·FAN 모듈의 EPDM·단열재 부착 상태(이음부 틈·미부착·찢어짐)를 태블릿으로 찍어 AI 학습 데이터를 모읍니다. 조립 검사에서 씁니다. 지금은 사람이 판정합니다.

        ■ 검사 항목
        - Module Check Sheet(문서대장 13번 시트) › Heater A'ssy 작업 Check Sheet 46 "단열재 부착 확인"
        - 재생 Heater Module 조립(11번 시트) › 1단계 "① EDPM 부착 - 부착부에 틈이 없을 것" · 5단계 "① HEATER BOX 조립 - 단열재 적용 (EPDM) 사용 : □ 미사용 : □" · 6단계 "① EDPM 부착 - 부착부에 틈이 없을 것"
        - FAN Module 조립(9번 시트) › 조립 중요 Point "적색 표시부 EPDM 부착 10X3T" · "COVER 설치 시 밀폐가 되어 함."
        - 중간 검수 성적서(16번 시트) › Heater A'ssy 27 "Heater Room 내부 단열재 부착" · 29 "EPDM 부착 확인"

        ■ 검사 기준
        - 13번 46: SPEC "미 부착 부위 최소화"
        - 11번 조립 중요 Point: "적색 표시부 EPDM 부착 10X3T 이음부에 간격이 없어야 함." · "내부 적색 표시부 EPDM 부착 10X10T 이음부 간격이 없어야 함." · "히터 COVER 내부 단열제 부착. (?)10T 전체 면적"
        - EPDM 부착 방법(9·11번): "EPDM 길이 = 1M * 최소한의 이음부로 부착" · "이음부는 최소한의 간격으로 부착"
        - 16번: 27 "빈틈 최소화" · 29 "EPDM 찢어짐 없을 것"

        ■ 역할
        - AI(학습 뒤): 이음부 틈, 미부착 부위, 찢어짐
        - 사람: 두께 규격(10X3T·10X10T), 밀폐·Leak 확인(성능 TEST)

        ■ 촬영 방법
        - 태블릿으로 디지털 양식의 비전 연결 이미지 칸에서 "사진 넣기"로 찍습니다
        - COVER 를 덮기 전에 부착 구간(적색·노란색 표시부)마다 이음부가 보이게 가까이 1장씩 찍습니다

        ■ 라벨링 기준
        - 박스로 표시합니다. 이음부 틈 epdm_gap, 붙어 있어야 할 곳이 비어 있음 epdm_missing, 찢어짐 epdm_torn
        - 정상 구간은 표시하지 않습니다
    '''),
    'TAB-FAN': text('''
        ■ 검사 목적
        FAN Module 의 Process FAN 장착 상태(볼 마우스와 FAN 간섭, 방진고무 뒤틀림)를 태블릿으로 찍어 AI 학습 데이터를 모읍니다. 조립 검사에서 씁니다. 지금은 사람이 판정합니다.

        ■ 검사 항목
        - Module Check Sheet(문서대장 13번 시트) › FAN A'ssy 작업 Check Sheet 30~31 "Fan 조립 확인"
        - FAN Module 조립(9번 시트) › 조립 중요 Point "방진 고무 조립시 과토크로 인한 방진고무 뒤틀림 없을 것." · "MODULE 측 설치 시 적색 표시부가 수직이 되도록 설치. (COVER 측 벨마우스 설치시 간섭발생 확인)"
        - 제조-검수 AX 적용 List 2.1 FAN Module 조립 "볼 마우스 위치 검사(FAN 간섭 여부)"

        ■ 검사 기준
        - 13번 30~31: SPEC "방진 패드 흔들림 없을 것 Torque : 118kgf·cm" · "볼 마우스 고정 확인"
        - 9번 조립 중요 Point 원문 위와 같음

        ■ 역할
        - AI(학습 뒤): 볼 마우스와 FAN 간섭(위치 어긋남), 방진고무 뒤틀림
        - 사람: 흔들림·유격, 체결 Torque 118kgf·cm(Digital Wrench)

        ■ 촬영 방법
        - 태블릿으로 디지털 양식의 비전 연결 이미지 칸에서 "사진 넣기"로 찍습니다
        - COVER 쪽에서 볼 마우스와 FAN 날개 사이가 보이게 1장, 방진고무 4곳이 보이게 1장 찍습니다

        ■ 라벨링 기준
        - 박스로 표시합니다. 볼 마우스와 FAN 이 닿거나 어긋남 bellmouth_interference, 방진고무 뒤틀림 mount_twist
        - 정상이면 표시하지 않습니다
    '''),
    'TAB-HTR': text('''
        ■ 검사 목적
        재생 Heater 의 히터 코일·PAD 조립 상태를 태블릿으로 찍어 이상 탐지 학습 데이터를 모읍니다. 조립 SOP 에 "* 제어 온도 ISSUE (중요)"로 적힌 항목입니다. 지금은 사람이 판정합니다.

        ■ 검사 항목
        - 재생 Heater Module 조립(문서대장 11번 시트) › 2단계 "① HEATER 조립 - 수평으로 조립 되었는가 - 코일에 뒤틀림이 있는가 - 간격은 일정한가" · 4단계 "① SENSOR 조립 … - PAD 설치 확인"
        - 중간 검수 성적서(16번 시트) › Heater A'ssy 24 "Heater Coil 체결 확인-1" · 25 "Heater Coil 체결 확인-2" · 26 "Heater Coil 체결 확인-3" · 28 "현열 교환기 상태 확인"

        ■ 검사 기준
        - 11번 조립 중요 Point: "히터 코일이 수평으로 설치 되어야 함." · "코일 간격이 일정하게 설치 되어야 함." · "히터 코일이 뒤틀림이 없어야 함." · "PAD 조립시 과눌림으로 인한 변형이 없어야 함."
        - 16번: 24 "수평 설치" · 25 "간격 일정 할 것" · 26 "Pin 구부러짐 없을 것" · 28 "파손(구부러짐) 없을 것"

        ■ 역할
        - AI(학습 뒤): 코일 수평 불량·뒤틀림·간격 불균일·Pin 구부러짐, PAD 이탈·과눌림 변형
        - 사람: 히터 온도·출력(성능 TEST), Leak

        ■ 촬영 방법
        - 태블릿으로 디지털 양식의 비전 연결 이미지 칸에서 "사진 넣기"로 찍습니다
        - CASE 를 닫기 전에 코일 전체가 들어오게 정면 1장, 옆에서 1장 찍습니다

        ■ 라벨링 기준
        - 결함마다 Polygon 으로 둘러쌉니다: 수평 불량 coil_tilt, 코일 뒤틀림·Pin 구부러짐 coil_twist, 간격 불균일 coil_gap, PAD 이탈·과눌림 변형 pad_bad
        - 결함이 없으면 영역 없이 작업 완료합니다(정상)
    '''),
    'TAB-SNS': text('''
        ■ 검사 목적
        모듈의 온습도·온도 센서와 FAN Controller 설치 상태를 태블릿으로 찍어 AI 학습 데이터를 모읍니다. 조립 검사에서 씁니다. 지금은 사람이 판정합니다.

        ■ 검사 항목
        - Module Check Sheet(문서대장 13번 시트) › FAN A'ssy 32 "Exhaust TC Sensor" · 34 "FAN Controller", Heater A'ssy 48 "Exhaust TC Sensor"
        - FAN Module 조립(9번 시트) › 8단계 "① 온/습도 센서 조립 상태 (조립 후 보호캡 제거 확인)", 작업 내용 "TEMP SENSOR - 볼트 나사선 돌출 길이 확인"
        - 재생 Heater Module 조립(11번 시트) › 1단계 "① Sensor 설치 - 고정용 볼트 방향 확인" · 4단계 "① SENSOR 조립 - PT측 SEALING 확인 - SENSOR 높이 확인"

        ■ 검사 기준
        - 13번: 32·48 SPEC "Teflon Tape 마감 확인" · 34 SPEC "들뜸 없을 것"
        - 11번 조립 중요 Point: "SENSOR 조립시 나사부 SEAL TAPE 필히 사용."

        ■ 역할
        - AI(학습 뒤): Seal(Teflon) Tape 미마감, 보호캡 미제거, Controller 들뜸, 고정 볼트 방향
        - 사람: 흔들림, 센서 높이·나사선 돌출 길이(문서에 수치가 없습니다), 단선·표시값

        ■ 촬영 방법
        - 태블릿으로 디지털 양식의 비전 연결 이미지 칸에서 "사진 넣기"로 찍습니다
        - 센서·Controller 마다 나사부와 고정 볼트가 보이게 가까이 1장씩 찍습니다

        ■ 라벨링 기준
        - 박스로 표시합니다. Tape 없음·덜 감김 seal_tape_missing, 보호캡이 그대로 있음 cap_not_removed, Controller 가 떠 있음 controller_lifted, 고정 볼트 방향이 다름 bolt_direction
        - 정상이면 표시하지 않습니다
    '''),
    'TAB-BLT': text('''
        ■ 검사 목적
        제습 Rotor Module 의 Belt 장착 상태와 Tension 수치 기입을 태블릿으로 찍어 AI 학습 데이터를 모읍니다. 조립 검사에서 씁니다. 지금은 사람이 판정합니다.

        ■ 검사 항목
        - 제습 Rotor Module 조립(문서대장 10번 시트) › CASSETTE ROTOR 조립 관련 BELT TENSION SETTING 1 "Belt가 CASE 지지대 Bolt 안 쪽에 위치해 있는지 확인 한다." · 2 "Rotor 측 Belt Gear Rivet과 Belt 간의 간섭이 없도록 위치시킨다." · 2-1 1) "Motor Pulley와 Rotor Belt Gear의 위치가 같은지 확인 한다." · 5 "아래 그림과 같이 주파수를 측정하여 정면 Bolt Cap에 수치를 기입한다."
        - 같은 절의 "SETTING 완료 이미지 첨부" 칸(예시 사진: Bolt Cap 4곳 손글씨 수치와 "로터 시리얼번호" 라벨)
        - 제조-검수 AX 적용 List 2.3 제습 Rotor Module 조립 "외관 검사, 조립, Belt tension 측정"

        ■ 검사 기준
        - 10번 절차 원문 위와 같음. AX 적용 List 의 Tension 기준 "90 Hz ± 5 Hz"

        ■ 역할
        - AI(학습 뒤): Belt 위치 이탈, Rivet 간섭, Bolt Cap 수치 미기입
        - 사람: Tension 값(텐션 미터), 구동 회전·Slip, 기입한 수치 읽기

        ■ 촬영 방법
        - 태블릿으로 디지털 양식의 비전 연결 이미지 칸에서 "사진 넣기"로 찍습니다
        - SETTING 완료 이미지와 같은 구도로 정면 Bolt Cap 4곳과 로터 시리얼번호 라벨이 보이게 1장, Belt Gear 쪽을 가까이 1장 찍습니다

        ■ 라벨링 기준
        - 박스로 표시합니다. Belt 가 지지대 Bolt 바깥에 있거나 Gear 와 어긋남 belt_off, Rivet 과 Belt 가 닿음 rivet_interference, 수치가 없는 Bolt Cap tension_mark_missing
        - 정상이면 표시하지 않습니다
    '''),
    'TAB-CFN': text('''
        ■ 검사 목적
        재생 Heater 의 Cooling FAN 조립 방향과 보호 Cover 를 태블릿으로 찍어 정상·역조립·보호 Cover 누락으로 분류하는 AI 학습 데이터를 모읍니다. 조립 검사에서 씁니다. 지금은 사람이 판정합니다.

        ■ 검사 항목
        - 재생 Heater Module 조립(문서대장 11번 시트) › 7단계 "① COOLING FAN 조립 - FAN 방향 확인 - 전원 케이블 방향 확인" · 8단계 "① 각 PART - FAN 방향 확인 - 전원 케이블 방향 확인"
        - 중간 검수 성적서(16번 시트) › Heater A'ssy 30 "Cooling FAN 공급 방향 확인"
        - 8계통 Check Sheet(15번 시트) › 6.5 "① Fan설치시 보호Cover는 전, 후면 모두 부착"

        ■ 검사 기준
        - 11번 조립 중요 Point: "FNA 조립시 공급방향 확인 후 조립."
        - 16번 30: SPEC "공급 방향 : ↑"

        ■ 역할
        - AI(학습 뒤): 사진 한 장을 정상·역조립·보호 Cover 누락 중 하나로 분류
        - 사람: FAN 망 진동, 동작·회전 확인

        ■ 촬영 방법
        - 태블릿으로 디지털 양식의 비전 연결 이미지 칸에서 "사진 넣기"로 찍습니다
        - Cooling FAN 정면에서 FAN 몸체의 방향 표시(화살표)·전원 케이블·보호 Cover 가 함께 보이게 1장 찍습니다

        ■ 라벨링 기준
        - 사진마다 하나를 고릅니다: 정상 fan_ok, 방향·전원 케이블 방향이 반대 fan_reversed, 보호 Cover 가 없음 cover_missing
        - fan_ok 만 불량이 아닙니다
    '''),
    'TAB-CBL': text('''
        ■ 검사 목적
        전장 Box·모듈 배선의 정리·마감 상태(Cable Tie 끝단, 미사용 Port 마감, Cable 말림·꺾임, 커넥터 고정)를 태블릿으로 찍어 AI 학습 데이터를 모읍니다. 품질 검사(8계통·중간 검수)에서 씁니다. 지금은 사람이 판정합니다.

        ■ 검사 항목
        - 8계통 Check Sheet(문서대장 15번 시트) › 1.1 ④ "부품, 배관, Cover 등 Cable Tie를 사용하여 고정시켜서는 안됩니다." · 5.5 ① "Cable이 과도하게 눌리지 않도록 고정한다." · 5.9 ① "설비내 모든 Cable은 말아 놓지 않도록 Cable 길이 표준화 적용" · 5.9 ③ "미사용 Signal Port 및 Connector는 고정형 또는 고리형 End-Cap으로 마감한다."
        - Recheck Sheet(14번 시트) › 8계통-전장/제어 카드 "전장 Box 내부 Cable Tie Cutting 누락" · "FDC LAN PORT Part 체결 불량", 8계통-전장 카드 "미사용 통신 Port 마감 누락" · "Process Fan Controller 미사용 Port 마감 누락"
        - 전장 ASSY Check Sheet(6번 시트) › 1. 외관 검사 No 10 "Duct Cover 내부 배선 확인." · No 26 "Connector Spare 처리 상태 확인." · No 28 "Cable 정리 상태 확인."
        - 중간 검수 성적서(16번 시트) › FAN A'ssy 17 "Cable 포설 구간 간섭 및 고정 상태 확인", Module Check Sheet(13번 시트) "Module內 배선 고정"

        ■ 검사 기준
        - 6번 No 28: "Cable Tie 미절단 없을 것." · "Cable Tie 고정부 과조임, 풀림, 빠짐, 손상 없을 것."
        - 6번 No 26: "Spare부 막음처리 할 것." · No 10: "Duct 내에 배선 꼬임, 물성 불리, 케이블타이 적용 하지 않을 것."
        - 16번 17: "간섭 없을 것" · 13번: "배선 고정 확인(간섭)"

        ■ 역할
        - AI(학습 뒤): Tie 끝단 미절단, Tie 로 부품을 고정함, 미사용 Port·Spare 미마감, Cable 말아 둠, 꺾임·눌림, 커넥터 고정 불량
        - 사람: 강전·약전과 물성 분리, 곡률 반경, Duct 용적률(배선 사양이 있어야 판정합니다)

        ■ 촬영 방법
        - 태블릿으로 디지털 양식의 비전 연결 이미지 칸에서 "사진 넣기"로 찍습니다
        - 전장 Box·모듈의 배선 구역마다 Tie 끝단과 Port 가 보이게 1장, 이상이 보이면 가까이 1장 더 찍습니다

        ■ 라벨링 기준
        - 박스로 표시합니다. tie_uncut Tie 끝단 미절단, tie_misuse Tie 로 부품·배관 고정, port_open 미사용 Port·Hole·Spare 미마감, cable_coiled Cable 말아 둠, cable_bent 꺾임·눌림, connector_loose 커넥터 고정 불량
        - 정상이면 표시하지 않습니다
    '''),
    'TAB-EXT': text('''
        ■ 검사 목적
        출하 전 설비 외관(도장 손상·찍힘·틈·오염·이물 방치)을 면마다 태블릿으로 찍어 이상 탐지 학습 데이터를 모읍니다. 지금은 사람이 판정합니다. 닦아 낸 천의 오염도 단계는 VIS-CLN 이 봅니다.

        ■ 검사 항목
        - 출하검수Sheet(문서대장 18번 시트) › 외관검사 구역의 "※ 설비 內 Bolt, Nut, Tie, 이물질 방치 여부 必 확인  것"
        - Recheck Sheet(14번 시트) › 8계통-기타 카드 "Module 외부 이물/오염" · "Module ASSY 조립 불량", 외관-형상·손상·찍힘 카드
        - 8계통 Check Sheet(15번 시트) › 1.1 ⑦ "미 사용된 Screw(Bolt)가 설비 내부에 방치되어서는 안되며 체결 후 반드시 확인해야 한다." · 6.2 ① "Indicators(지시계, 유리, Case, 온도검출기등)는 손상이 없어야 한다." · 7.1 "도장 불량 및 부식, 파손"

        ■ 검사 기준
        - 15번 7.1 ①: "코팅 및 도장의 손상이 없어야 한다." · ③ "육안 확인 가능한 외장 손상(Cover 및 부속품의 찌그러짐, 표면 돌기)은 안전사고의 위험이 있음으로 없어야 한다." · ④ "Cover간 틈새는 없어야 한다.(2mm이하 유지)"

        ■ 역할
        - AI(학습 뒤): 도장 손상, 찍힘·찌그러짐, 틈·단차, 오염·얼룩, 이물(Bolt·Nut·Tie) 방치
        - 사람: 틈새 2mm 수치, 경첩 마모, 부식 내구성, Cleaning 단계(VIS-CLN)

        ■ 촬영 방법
        - 태블릿으로 디지털 양식의 비전 연결 이미지 칸에서 "사진 넣기"로 찍습니다
        - 설비 면마다 1장(UPPER · LEFT · RIGHT · Front), 이상이 보이면 그 자리를 가까이 1장 더 찍습니다

        ■ 라벨링 기준
        - 결함마다 Polygon 으로 둘러쌉니다: 도장 손상 paint_damage, 찍힘·찌그러짐 dent, 틈·단차 gap_step, 오염·얼룩 stain, 이물 방치 foreign_object
        - 결함이 없으면 영역 없이 작업 완료합니다(정상)
    '''),
}

# 검사 분류 — (대분류, [중분류]). 대분류는 수입검사·품질검사·미분류로 고정이다(category.FIXED_MAJORS, 사용자 결정 2026-10-21)
# — 옛 조립검사·출하검사의 중분류는 품질검사 아래다. 중분류 순서가 화면·메뉴 순서다. 양식 매핑은 여기서 넣지 않는다 —
# 다음에 도는 seed_dig_form 이 이름이 같은 중분류에 매핑한다(사용자 결정 2026-10-22).
INCOMING, MINOR_ROTOR, MINOR_PART, MINOR_ELEC = '수입검사', 'Rotor 수입검사 성적서', '수입검사성적서(가공품)', '전장 ASSY Check Sheet'
MINOR_MODULE, MINOR_8SYS, MINOR_SHIP = 'Module Check Sheet', '8계통 Check Sheet', '출하검수 Sheet'
CATEGORIES = [
    (INCOMING, [MINOR_ROTOR, MINOR_PART, MINOR_ELEC]),
    ('품질검사', [MINOR_MODULE, MINOR_8SYS, MINOR_SHIP]),
]

# (코드, 이름, 유형, 중분류, [(클래스명, 표시명, 색, 불량 여부)]). 설명은 DESCRIPTIONS[코드].
# 이미 있는 항목에 클래스를 더하면 다음 실행 때 없는 클래스만 만든다.
ITEMS = [
    ('VIS-CLN', 'Cleaning 오염도', T.CLASSIFICATION, MINOR_SHIP,
     [(f'stage_{n:02d}', f'{n}단계', color, n >= 3) for n, color in enumerate(
         ['#2E86AB', '#3FA7D6', '#F6C85F', '#F3A712', '#E4572E', '#D7263D', '#B5179E', '#7B2CBF', '#560BAD', '#3A0CA3'],
         start=1)]),
    ('VIS-ROT-SF', 'Rotor 표면 결함(수입)', T.ANOMALY_DETECTION, MINOR_ROTOR,
     [(name, ko, color, True) for name, ko, color in ROTOR_DEFECTS]),
    ('TAB-IMK', 'Bolt I-Marking', T.OBJECT_DETECTION, MINOR_MODULE,
     [('imark_missing', 'I-Marking 누락', '#D7263D', True), ('imark_bad', 'I-Marking 불량', '#F3A712', True),
      ('bolt_missing', '볼트 미체결', '#B5179E', True), ('hole_open', '미사용 Hole 미마감', '#3FA7D6', True),
      ('washer_missing', '와셔 누락', '#7B2CBF', True)]),
    ('TAB-LBL', '안전라벨·명판', T.OBJECT_DETECTION, MINOR_SHIP,
     [('label_damaged', '라벨 손상', '#D7263D', True), ('label_dirty', '라벨 오염', '#6C757D', True),
      ('label_misplaced', '라벨 오부착', '#F3A712', True), ('ems_cover_missing', 'EMS Cover 누락', '#B5179E', True)]),
    ('TAB-ROT', 'Rotor 설치 상태(출하)', T.ANOMALY_DETECTION, MINOR_SHIP,
     [(name, ko, color, True) for name, ko, color in ROTOR_DEFECTS]),
    ('TAB-TRM', '단자 압착·Pin', T.OBJECT_DETECTION, MINOR_ELEC,
     [('crimp_bad', '압착 불량', '#D7263D', True), ('strand_damage', '심선 손상', '#E4572E', True),
      ('pin_out', 'PIN 빠짐', '#F3A712', True), ('connector_loose', '커넥터 들뜸', '#B5179E', True),
      ('numbering_bad', '넘버링 불량', '#3FA7D6', True), ('terminal_bent', '단자 꺾임', '#7B2CBF', True),
      ('lug_wrong', '단자 형식 불량', '#560BAD', True), ('ground_bad', '접지 체결 불량', '#2E86AB', True),
      ('terminal_foreign', '단자 이물', '#6C757D', True)]),
    ('VIS-ROT-DIM', 'Rotor 치수(수입)', T.MEASUREMENT, MINOR_ROTOR, []),
    # 검사 분류와 함께 더한 수집 항목(설계 2026-10-21 §8)
    ('TAB-PRT', '판금·가공품 외관(수입)', T.OBJECT_DETECTION, MINOR_PART,
     [('scratch', 'Scratch', '#E4572E', True), ('dent', '찍힘', '#F3A712', True), ('crack', '균열', '#D7263D', True),
      ('contamination', '오염/이물', '#6C757D', True), ('burr', 'Burr/가공 Chip', '#3FA7D6', True),
      ('corrosion', '산화/부식/백화', '#B5179E', True), ('weld_defect', '용접 결함', '#560BAD', True),
      ('coating_peel', '도장 박리', '#7B2CBF', True)]),
    ('TAB-EPD', 'EPDM·단열재 부착', T.OBJECT_DETECTION, MINOR_MODULE,
     [('epdm_gap', '이음부 틈', '#F3A712', True), ('epdm_missing', '미부착', '#D7263D', True),
      ('epdm_torn', '찢어짐', '#E4572E', True)]),
    ('TAB-FAN', 'FAN 장착(볼 마우스·방진고무)', T.OBJECT_DETECTION, MINOR_MODULE,
     [('bellmouth_interference', '볼 마우스 간섭', '#D7263D', True), ('mount_twist', '방진고무 뒤틀림', '#F3A712', True)]),
    ('TAB-HTR', 'Heater 코일·PAD 조립', T.ANOMALY_DETECTION, MINOR_MODULE,
     [('coil_tilt', '수평 불량', '#F3A712', True), ('coil_twist', '코일 뒤틀림', '#D7263D', True),
      ('coil_gap', '간격 불균일', '#E4572E', True), ('pad_bad', 'PAD 이탈/과눌림', '#7B2CBF', True)]),
    ('TAB-SNS', '센서·컨트롤러 설치', T.OBJECT_DETECTION, MINOR_MODULE,
     [('seal_tape_missing', 'Teflon Tape 미마감', '#F3A712', True), ('cap_not_removed', '보호캡 미제거', '#D7263D', True),
      ('controller_lifted', '컨트롤러 들뜸', '#E4572E', True), ('bolt_direction', '고정 볼트 방향 불량', '#7B2CBF', True)]),
    ('TAB-BLT', 'Rotor Belt 장착·Tension 표기', T.OBJECT_DETECTION, MINOR_MODULE,
     [('belt_off', 'Belt 위치 이탈', '#D7263D', True), ('rivet_interference', 'Rivet 간섭', '#F3A712', True),
      ('tension_mark_missing', 'Tension 수치 미기입', '#3FA7D6', True)]),
    ('TAB-CFN', 'Cooling FAN 방향·보호 Cover', T.CLASSIFICATION, MINOR_MODULE,
     [('fan_ok', '정상', '#2E86AB', False), ('fan_reversed', '역조립', '#D7263D', True),
      ('cover_missing', '보호 Cover 누락', '#F3A712', True)]),
    ('TAB-CBL', '전장 배선 정리·포트 마감', T.OBJECT_DETECTION, MINOR_8SYS,
     [('tie_uncut', 'Tie 끝단 미절단', '#F3A712', True), ('tie_misuse', 'Tie 로 부품 고정', '#E4572E', True),
      ('port_open', '미사용 Port/Hole 미마감', '#D7263D', True), ('cable_coiled', 'Cable 말아둠', '#3FA7D6', True),
      ('cable_bent', 'Cable 꺾임/눌림', '#7B2CBF', True), ('connector_loose', '커넥터 고정 불량', '#B5179E', True)]),
    ('TAB-EXT', '설비 외관 손상·오염·이물 방치', T.ANOMALY_DETECTION, MINOR_SHIP,
     [('paint_damage', '도장 손상', '#7B2CBF', True), ('dent', '찍힘/찌그러짐', '#F3A712', True),
      ('gap_step', '틈/단차', '#3FA7D6', True), ('stain', '오염/얼룩', '#6C757D', True),
      ('foreign_object', '이물 방치', '#D7263D', True)]),
]

# 치수 측정 항목의 측정점 {검사항목 코드: [(코드, 이름, 기준값, 공차, 측정 방법)]}. 하한·상한은 기준값±공차다.
# 측정 방법은 Rotor수입검사성적서 을지 제품 도해의 POINT 글상자 위치다. 클라이언트 화면에 보인다.
POINTS = {'VIS-ROT-DIM': [
    ('A', '치수 A', '540', '1', '을지 제품 도해 측면도 오른쪽 가운데(Process Air 화살표 옆) 글상자 A 의 길이입니다. '
                               '규격 540±1mm, 성적서 측정기기 "줄자(철자)".'),
    ('B', '치수 B', '540', '1', '을지 제품 도해 정면도 아래 글상자 B 의 길이입니다. 규격 540±1mm. '
                               '글상자가 Ø640 치수 옆에 있어 어디서 어디까지인지 도면 확인이 필요합니다.'),
    ('C', '치수 C', '154', '1', '을지 제품 도해 측면도 위 73 · 154 · 73 가운데 154 구간의 길이입니다. 규격 154±1mm.'),
]}


class Command(BaseCommand):
    help = 'NEOCON C2 비전검사항목·라벨 클래스·측정점을 만든다(없는 것만, 멱등). --update-descriptions 는 설명만 바꾼다.'

    def add_arguments(self, parser):
        parser.add_argument('--update-descriptions', action='store_true',
                            help='이미 있는 검사항목·측정점의 설명을 이 명령의 내용으로 바꾼다(이름·유형·규격은 그대로)')

    def handle(self, *args, **options):
        tenant = current_tenant()
        created_items = created_classes = created_points = created_categories = 0
        updated_items = updated_points = 0
        with tenant_atomic(tenant):
            moved, removed = categories.ensure_fixed_majors(tenant)
            minors = {}
            for major_name, minor_names in CATEGORIES:
                major = InspectionCategory.objects.get(tenant=tenant, parent=None, name=major_name)
                for minor_order, minor_name in enumerate(minor_names, start=1):
                    minors[minor_name], made = InspectionCategory.objects.get_or_create(
                        tenant=tenant, parent=major, name=minor_name, defaults={'sort_order': minor_order})
                    created_categories += made
            for order, (code, name, task_type, minor_name, classes) in enumerate(ITEMS):
                description = DESCRIPTIONS[code]
                # 촬영 방식은 코드 머리로 정한다 — TAB- 는 태블릿, VIS- 는 고정 거치대
                capture = InspectionItem.CaptureMethod.TABLET if code.startswith('TAB-') else InspectionItem.CaptureMethod.RIG
                item, created = InspectionItem.objects.get_or_create(
                    code=code, defaults={'tenant': tenant, 'name': name, 'task_type': task_type, 'capture_method': capture,
                                         'description': description, 'display_order': 10 + order,
                                         'category': minors[minor_name]})
                # 소속은 비어 있을 때만 채운다 — 화면에서 옮긴 것은 그대로 둔다
                if not created and item.category_id is None:
                    item.category = minors[minor_name]
                    item.save(update_fields=['category', 'updated_at'])
                if created:
                    created_items += 1
                    ItemService.get_or_create_upload_dataset(item)
                    AuditService.record(tenant=tenant, item=item, event_type='PROJECT_CREATED',
                                        payload={'task_type': task_type})
                elif options['update_descriptions'] and item.description != description:
                    item.description = description
                    item.save(update_fields=['description', 'updated_at'])
                    updated_items += 1
                for sort_order, (cls_name, ko, color, is_defect) in enumerate(classes):
                    _, made = LabelClass.objects.get_or_create(
                        tenant=tenant, item=item, name=cls_name,
                        defaults={'display_name_ko': ko, 'color': color, 'is_defect': is_defect,
                                  'sort_order': sort_order})
                    created_classes += made
                for sort_order, (point_code, point_name, nominal, tolerance, how) in enumerate(POINTS.get(code, [])):
                    nominal, tolerance = Decimal(nominal), Decimal(tolerance)
                    point, made = MeasurementPoint.objects.get_or_create(
                        tenant=tenant, item=item, code=point_code,
                        defaults={'name': point_name, 'nominal': nominal, 'lower': nominal - tolerance,
                                  'upper': nominal + tolerance, 'description': how, 'sort_order': sort_order})
                    created_points += made
                    if not made and options['update_descriptions'] and point.description != how:
                        point.description = how
                        point.save(update_fields=['description'])
                        updated_points += 1
                self.stdout.write(f'{code} {name} — {"만듦" if created else "이미 있음"}')
        self.stdout.write(self.style.SUCCESS(
            f'비전검사항목 {len(ITEMS)}개 중 새로 {created_items}개 / 라벨 클래스 새로 {created_classes}개'
            f' / 측정점 새로 {created_points}개 / 검사 분류 새로 {created_categories}개'))
        if removed:
            self.stdout.write(f'옛 대분류 {removed}개를 지우고 중분류 {moved}개를 옮김(대분류는 수입검사·품질검사·미분류 고정)')
        if options['update_descriptions']:
            self.stdout.write(f'설명을 바꾼 비전검사항목 {updated_items}개 / 측정점 {updated_points}개')
