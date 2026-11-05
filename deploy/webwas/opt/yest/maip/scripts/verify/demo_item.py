"""화면 검증 스크립트가 여는 데모 검사항목(seed_demo `FAN-PANEL-DET`)의 id. id 는 DB 마다 달라 코드로 찾는다."""
DEMO_ITEM_CODE = 'FAN-PANEL-DET'

LIST_JS = """url => fetch(url, {headers: {'X-Requested-With': 'XMLHttpRequest'}}).then(r => r.json())"""


def demo_item_id(page, base, code=DEMO_ITEM_CODE):
    """로그인한 page 로 검사항목 목록을 불러 code 의 id 를 돌려준다. 없으면 seed_demo 를 돌리라고 멈춘다."""
    rows = page.evaluate(LIST_JS, base + '/api/item/item_admin?action=list')['rows']
    found = next((row['id'] for row in rows if row['code'] == code), None)
    if found is None:
        raise SystemExit(f'비전검사항목 {code} 가 없다. seed_demo 를 먼저 돌려라.')
    return found
