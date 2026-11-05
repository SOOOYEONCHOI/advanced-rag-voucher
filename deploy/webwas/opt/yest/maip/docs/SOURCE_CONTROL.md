# 소스 관리

팀원이 각자 PC 의 로컬 브랜치에서 작업하고 main 에 합쳐 push 하는 규칙이다. **개발 DB 는 하나를 같이 쓴다** — 그래서
마이그레이션과 시드는 담당자 한 사람이 적용한다. 개발 환경과 테스트 명령은 [DEVELOPMENT.md](DEVELOPMENT.md),
코드 규칙은 [../AGENTS.md](../AGENTS.md) 에 있다.

## 1. 역할

| 역할 | 하는 일 |
|---|---|
| **담당자**(1명) | 공유 개발 DB 의 마이그레이션·시드 적용, 팀원 계정 발급 |
| **팀원** | 로컬 브랜치에서 작업하고 main 에 합쳐 push 한다. 마이그레이션은 담당자에게 보낸다(§4.1) |

main 은 Git 서버(Gitea)에서 force push 만 막혀 있다. 누구나 push 할 수 있으므로 push 전 확인(§5)을 각자 지킨다.

## 2. 처음 한 번

1. 저장소를 clone 하고 DEVELOPMENT.md §1.1·§1.2 대로 개발 환경을 준비한다.
   저장소 폴더에서 `git config pull.rebase false` 를 한 번 실행한다 — `git pull` 이 늘 merge 로 합친다(rebase 는
   `merge --no-ff` 로 남긴 병합 커밋을 푼다).
2. `.env` 의 DB 는 **공유 개발 DB** 를 가리킨다. 접속 정보는 담당자에게 받는다. `DB_CONN_MAX_AGE=0` 으로 둔다.
3. 로그인 계정은 담당자가 superuser 로 만들어 준다 — 메뉴가 아직 없는 새 화면을 주소로 열려면 superuser 여야 한다(§4.2).
   e2e·화면 검증 스크립트가 쓰는 `admin` 비밀번호도 받아 `.admin_pw` 에 적는다. **검증 도구 전용이다** — 화면 작업에
   쓰거나 바꾸지 않는다. 바꾸면 다른 사람의 e2e 가 모두 멈춘다.
4. `scripts/maipctl.py start` 로 띄우고 로그인해 본다.

공유 개발 DB 는 마이그레이션·시드가 끝나 있다. AGENTS [4] 의 금지 목록(`migrate`·`seed_*`)을 따른다 — 그 단계는 담당자 몫이다. `seed_demo` 는 현장 클라이언트 인증을 깨뜨린다.

## 3. 작업 한 건의 흐름

```bash
git switch main && git pull                  # 최신 main 에서 시작한다
git switch -c feat/<짧은-이름>                # 로컬 브랜치를 만든다
# ... 고치고, 고친 범위의 테스트·검증 스크립트를 돌리고, 커밋한다 ...
git switch main && git pull                  # 그 사이 들어온 main 을 받는다
git merge --no-ff feat/<짧은-이름>            # main 에 합친다. 충돌을 풀었으면 테스트를 다시 돌린다
git push                                     # 거절되면 다시 pull 해서 합친 뒤 push 한다
git branch -d feat/<짧은-이름>
```

| 브랜치 접두어 | 쓰임 |
|---|---|
| `feat/` | 기능 |
| `fix/` | 버그 |
| `docs/` | 문서만 |
| `chore/` | 설정·데이터 파일·정리 |
| `migration/` | 모델 변경과 마이그레이션만. 담당자에게 보낸다(§4.1) |

- 커밋 메시지는 Conventional Commits 다(AGENTS [4]).
- 한 커밋에는 한 가지 변경만 넣는다. `git add .` 대신 고친 파일만 올린다.
- `merge --no-ff` 가 남기는 병합 커밋 메시지는 `Merge: <무엇을>` 으로 쓴다(지금 main 이력과 같은 모양).
- 기능 브랜치(`feat/`·`fix/` 등)는 원격에 올리지 않아도 된다. 며칠 걸리는 작업을 백업하려면 올려도 된다.

## 4. 공유 개발 DB 규칙

### 4.1 마이그레이션은 담당자에게 보낸다

모델을 바꿔야 하면 **그 변경만 먼저** 담당자에게 보낸다. 담당자가 공유 DB 에 적용하고 main 에 넣은 뒤에 그 필드를 쓰는 기능을 개발한다.

1. 최신 main 에서 `migration/<이름>` 브랜치를 만든다.
2. 모델을 고치고 `python manage.py makemigrations` 만 돌린다. **`migrate` 는 돌리지 않는다.**
3. 모델 파일과 새 마이그레이션 파일만 커밋하고 `git push -u origin migration/<이름>` 으로 올린 뒤 담당자에게 알린다.
4. 담당자가 그 브랜치를 받아 공유 DB 에 적용하고(`migrate` → `makemigrations --check`) main 에 합쳐 push 한 뒤 원격 브랜치를 지운다.
5. 팀원은 main 을 받아 기능 브랜치에 합치고(`git merge main`) 이어서 개발한다.

- **추가만 한다** — 새 테이블, 빈 값(`null=True`)이나 기본값이 있는 새 컬럼. 지우기·이름 바꾸기·NOT NULL 로 바꾸기는
  공유 DB 를 쓰는 다른 사람의 화면을 바로 깨뜨리므로 담당자와 일정을 먼저 맞춘다.
- 모델과 마이그레이션은 함께 보낸다. 마이그레이션만 main 에 들어가면 `makemigrations --check` 가 깨진다.
- **팀원은 모델·마이그레이션 변경을 main 에 직접 push 하지 않는다.**
- 번호는 최신 main 기준이다. 그 사이 다른 마이그레이션이 main 에 들어갔으면 파일을 지우고 `makemigrations` 를 다시 돌려 보낸다.
- 마이그레이션 작성 규칙(PostgreSQL 전용 SQL, `migrate --fake` 금지 등)은 DATA_MODEL.md·AGENTS.md 를 따른다.

### 4.2 메뉴와 시드는 담당자가 넣는다

- **`seed_initial` 은 담당자만 최신 main 에서 돌린다.** 메뉴 트리에 없는 메뉴를 지우는 명령이라, 예전 코드에서 돌리면 다른 사람이 만든 메뉴와 그 권한이 사라진다.
- 새 화면은 `domain/gui.py` 에 정의하고 superuser 로 `/gui/<화면코드>/` 를 열어 확인한다. 메뉴 트리를 바꿔 push 했으면 담당자에게 알린다 —
  담당자가 `seed_initial` 로 메뉴 행을 넣는다. 그 전까지 `verify_menu` 가 "gui.py 에만 있음"으로 FAIL 하는 것은 정상이다.
- 중분류에 매핑된 고객 양식을 화면에서 고쳤으면 담당자에게 알린다. 담당자가 공유 개발 DB 에서 `seed_dig_form` 데이터 파일
  (`domain/management/samples/dig_form_forms.json`·`dig_form_images/`)을 다시 뽑아 main 에 넣는다. 팀원은 이 파일을 손으로 고치지 않는다.

### 4.3 데이터와 커넥션

- 시험 데이터는 `E2E-`·`e2e-` 로 시작하게 만들고 끝나면 지운다. 다른 사람이 만든 데이터와 시드 데이터는 고치지 않는다.
- 이 PostgreSQL 은 다른 프로젝트와도 같이 쓰고 커넥션 수가 정해져 있다. 쓰지 않는 서버는 `maipctl.py stop` 으로 끈다.

## 5. push 전 확인

main 에 합친 뒤, push 하기 전에 본다.

- [ ] `python manage.py makemigrations --check` 가 변경 없음이고, `domain/migrations/` 에 내가 더한 파일이 없다(§4.1)
- [ ] 고친 범위의 단위 테스트(`--settings=configurations.test_settings`)
- [ ] 화면·화면 JS·화면이 부르는 API 를 고쳤으면 그 화면의 e2e
- [ ] 검증 스크립트(AGENTS.md [5])
- [ ] 문서: 메뉴·화면 → FEATURES, 테이블 → DATA_MODEL, 남은 일 → STATUS
- [ ] `/api/v1`·`/api/v1/datasets` 응답을 바꿨으면 계약 문서도 고쳤다
- [ ] `.env`·비밀번호·키·배포 zip 이 커밋에 없다(`git show --stat`)

## 6. main 을 받은 뒤

```bash
git switch main && git pull
.venv/bin/pip install -r requirements-dev.txt       # requirements 가 바뀌었을 때
.venv/bin/python scripts/maipctl.py restart
```

마이그레이션은 담당자가 이미 적용했으므로 돌리지 않는다.

## 7. 충돌이 잦은 곳

main 에 합칠 때 충돌이 나면 아래처럼 푼다. 풀고 나면 테스트를 다시 돌린다.

| 파일 | 맞추는 법 |
|---|---|
| `domain/gui.py` | 양쪽 화면 정의와 API 매핑을 모두 남긴다. `verify_permission_map` 으로 확인한다 |
| `domain/management/commands/seed_initial.py` 메뉴 트리 | 양쪽 메뉴를 모두 남긴다 |
| 공용 JS·CSS(`app/static/assets/js/common.js` 등) | 양쪽 변경을 합친 뒤 그 코드를 쓰는 화면의 e2e 를 돌린다 |
| `docs/STATUS.md` 등 문서의 표 | 양쪽 행을 모두 남기고 순번을 다시 맞춘다 |
| `domain/migrations/` | 여기서 충돌하면 안 된다 — §4.1 을 따랐는지 본다 |

## 8. 하지 않는 것

- force push, `git rebase` 등으로 이미 push 한 이력을 고쳐 쓰기
- 테스트하지 않고 push, 충돌을 풀고 다시 테스트하지 않고 push
- 모델·마이그레이션 변경을 main 에 직접 push
- 공유 개발 DB 에 `migrate`·`seed_*`·`migrate --fake`
- SQL 로 DB 의 테이블·데이터를 직접 고치기 — 테이블은 마이그레이션(§4.1)으로만 바꾼다
- `.env`·비밀번호·키·배포 zip 커밋, 문서에 저장소 주소·접속 정보 적기
