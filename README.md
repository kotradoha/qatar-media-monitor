# qatar-media-monitor (자동 뉴스 피드 사이트)

카타르·중동정세 언론을 **하루 2회 자동 갱신**하는 공개 페이지입니다.
- 갱신 주기(직전 갱신 → 이번 갱신) **창(window)** 안에 보도된 기사만 표시
- **카타르 관련** 기사는 상단에 필수 고정, 그 아래 **중동정세(해외/국내)**
- Google News RSS + 주요 매체 RSS를 GitHub Actions가 수집·게시(무료·완전자동)

## 설치 (약 5분, 브라우저만으로 가능)

1. GitHub(**kotradoha**)에서 **New repository** → 이름 `qatar-media-monitor`, **Public**, "Add a README" 체크 없이 생성.
2. **Add file → Upload files** 로 이 폴더의 파일을 그대로 올립니다:
   - `index.html` (초기 화면 · 예시)
   - `generate.py`
   - `.github/workflows/update.yml`  ← 폴더 경로 그대로 유지
   - (README.md는 선택)
   > 웹 업로드로 폴더가 안 되면 **Add file → Create new file** 에서 파일명에 `.github/workflows/update.yml` 처럼 경로를 직접 입력하면 폴더가 자동 생성됩니다.
3. **Settings → Pages** → Source: **Deploy from a branch**, Branch: **main / (root)** → Save.
4. **Settings → Actions → General** → 하단 *Workflow permissions* 를 **Read and write permissions** 로 설정(자동 커밋용).
5. **(무료 AI 요약)** 한국어 자동 요약을 켜려면 **구글 Gemini 무료 API 키**를 등록합니다:
   - https://aistudio.google.com/apikey 접속(구글 로그인) → **Create API key** 로 무료 키 발급.
   - 저장소 **Settings → Secrets and variables → Actions → New repository secret**
     → Name: `GEMINI_API_KEY`, Value: (발급받은 키) → 저장.
   - 키를 넣지 않아도 **요약만 빠지고** 헤드라인/링크는 정상 자동 생성됩니다.
   - 하루 2회 호출이라 무료 한도 내에서 충분합니다.
6. **Actions** 탭 → `Update monitor` → **Run workflow**(수동 1회 실행)로 첫 생성.
7. 1~2분 뒤 접속: **https://kotradoha.github.io/qatar-media-monitor/**

이후에는 매일 **카타르시간 07:00 / 15:30**(UTC 04:00 / 12:30)에 자동 갱신됩니다.

## 주제/매체 바꾸기
`generate.py` 상단 CONFIG의 `TITLE`, 검색 쿼리(`Q_QATAR_*`, `Q_MIDEAST_*`), 키워드(`QATAR_KW`, `MIDEAST_KW`), `QUICK_LINKS` 만 수정하면 다른 이슈/지역에도 재사용 가능합니다.

## 참고
- GitHub Actions 스케줄은 UTC 기준이며, 부하에 따라 몇 분 지연될 수 있습니다.
- 특정 매체의 직접 RSS를 추가하려면 `DIRECT_FEEDS` 에 (이름, RSS URL)을 넣으세요.
