# distribution

`/api/v1` 로 내려주는 배포물을 두는 곳이다. 위치는 `DISTRIBUTION_ROOT` 로 바꾼다
(기본값은 이 폴더). `app/static/` 아래 두지 않는다 — whitenoise 가 같은 파일을 `/static/...` 으로
한 번 더 내보낸다(DECISIONS DEC-C6).

| 폴더 | 내용 | API |
|---|---|---|
| `client/` | Windows Client 배포 zip | `GET /api/v1/client-packages` |
| `licenses/` | Qt/PySide6 LGPL 대응 소스 | `GET /api/v1/licenses/sources` |

**이 폴더의 파일은 인증 없이 공개된다**(DEC-024). API Key·비밀번호·인증서·`.env` 가 든 zip,
공개할 수 없는 문서나 데이터를 넣지 않는다. LGPL 대응 소스는 **마지막 배포 후 3년간** 지우지 않는다.

## 저장소에 넣는 것과 넣지 않는 것

배포물(`*.zip`·`*.tar.xz`)은 넣지 않는다 — 루트 `.gitignore` 가 확장자로 제외한다.
**`SHA256SUMS.txt` 와 이 README 는 넣는다.** 어떤 파일이 어떤 해시로 있어야 하는지가
이력으로 남고, 운영에 반입한 파일이 맞는지 이 파일로 대조한다.

## 파일을 넣을 때

1. 파일명에 버전과 날짜를 넣는다. 예: `VisionInspectionClient-0.1.6-beta-20261006.zip`
2. 같은 폴더의 `SHA256SUMS.txt` 를 갱신한다.

   ```bash
   cd distribution/client
   sha256sum *.zip > SHA256SUMS.txt
   sha256sum -c SHA256SUMS.txt
   ```

3. `SHA256SUMS.txt` 변경만 커밋한다.

`SHA256SUMS.txt` 는 `<해시>  <파일명>` 또는 `<해시> *<파일명>` 을 한 줄에 하나씩
적는다. 형식이 틀린 줄은 버려지고 그 파일의 목록 응답 `sha256` 이 `null` 이 된다(`SHA256SUMS.txt` 가
없으면 폴더 전체가 `null`).
서버는 해시를 **계산하지 않고** 같은 폴더의 이 파일에서 읽는다 — 1GB 아카이브를 요청마다 해싱하면 목록 조회가
수 초씩 걸린다.

운영 반입 절차는 [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md) §8-1.
