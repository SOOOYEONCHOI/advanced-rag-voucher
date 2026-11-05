export const DEFAULT_UI_TYPE = 'standalone';

export const UI_TYPE_OPTIONS = [
  {
    value: 'standalone',
    number: '01',
    title: '단독형 서비스',
    shortTitle: '단독형',
    description: '독립된 챗봇 화면에서 모든 기능을 사용합니다.',
    detail: '별도 서비스 주소로 접속해 넓은 화면에서 대화와 참고 문서를 함께 확인할 때 적합합니다.',
    icon: 'fa-solid fa-window-maximize',
    accent: 'blue',
  },
  {
    value: 'menu_linked',
    number: '02',
    title: '기존 솔루션 메뉴 연계',
    shortTitle: '메뉴 연계형',
    description: '기존 업무 솔루션의 메뉴에서 챗봇을 실행합니다.',
    detail: '사용 중인 솔루션의 내비게이션 흐름을 유지하면서 챗봇 화면으로 이동할 때 적합합니다.',
    icon: 'fa-solid fa-bars-staggered',
    accent: 'violet',
  },
  {
    value: 'layout_linked',
    number: '03',
    title: '화면 내 위젯(레이아웃) 연계',
    shortTitle: '위젯 연계형',
    description: '업무 화면 안에서 위젯 형태로 챗봇을 사용합니다.',
    detail: '현재 작업 화면을 벗어나지 않고 필요한 순간에 작은 패널을 열어 질문할 때 적합합니다.',
    icon: 'fa-solid fa-table-columns',
    accent: 'teal',
  },
];

export const isUiType = (value) => UI_TYPE_OPTIONS.some((option) => option.value === value);

export const normalizeUiType = (value) => (isUiType(value) ? value : DEFAULT_UI_TYPE);
