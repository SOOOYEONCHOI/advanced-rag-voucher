import { authConfig, http } from './http';

// UI 연동 방식 조회 및 최초 1회 확정 API.
// 변경 방지는 화면뿐 아니라 서버에서도 이미 확정된 계정의 PUT을 409로 거부해야 한다.
export const uiIntegrationApi = {
  get() {
    return http.get('/user/ui-settings', authConfig());
  },

  update(uiType) {
    return http.put('/user/ui-settings', { ui_type: uiType }, authConfig());
  },
};
