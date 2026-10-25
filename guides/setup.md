# 설치와 처음 사용하기

[README](../README.md) · [배포](deployment.md) · [아키텍처](architecture.md)

처음 설치한다면 **예시 화면 확인 → Supabase 설정 → SQL 실행 → 계정 두 개 생성 → 초대로 연결** 순서로 진행하세요. 지도·소셜 로그인·알림은 필요할 때 추가할 수 있습니다. 아래 예제의 프로젝트 ID와 키는 자신의 값으로 바꿔야 합니다.

## 로컬 실행

Node.js 24.15 이상 24.x, npm 11, Python 3.13, uv가 필요합니다.

```sh
npm ci
uv sync --project apps/api --locked
```

서로 다른 터미널에서 실행합니다.

```sh
npm run dev
```

```sh
npm run dev:api
```

웹은 `http://127.0.0.1:3000`, API 생존 확인은 `http://127.0.0.1:8000/health/live`에서 확인합니다. `/preview`는 저장되지 않는 가상 일정과 생성 예시 사진을 사용하는 화면 미리보기입니다. 사용자 기록으로 사용하지 않습니다.

설정에서 화이트 또는 웜 클린 테마를 고를 수 있습니다. 선택한 테마는 해당 브라우저의 쿠키에 1년간 저장되며 기본 테마는 웜 클린입니다. HTTPS로 운영할 때는 Secure 속성을 사용합니다.

주요 버튼은 색을 채우고 보조 버튼은 테두리를 표시해 일반 텍스트와 구분합니다. 링크에는 밑줄을 표시하며, 펼칠 수 있는 항목에는 화살표를 사용합니다. 아이콘 버튼은 최소 44px의 터치 영역을 확보합니다. 키보드 포커스와 선택된 날짜·메뉴, 처리 중인 상태도 구분해 표시합니다.

Supabase 인증은 아래 설정을 마친 뒤 사용할 수 있습니다.

## 연결 후 사용하기

- **일정**에서 날짜를 고르고 약속을 추가합니다. 코스는 플랜에 활동 순서와 장소를 적어 저장한 뒤, 내용을 확인하고 확정합니다. 확정에 성공하면 해당 날짜가 선택된 일정 화면으로 돌아갑니다.
- **설정 → 자주 가는 곳**에 장소를 저장하면 약속·코스에서 다시 선택할 수 있습니다. 추가·수정 창의 검색 아이콘으로 장소명·주소를 찾아 선택하거나 직접 입력합니다. 장소 선택과 저장은 별도입니다. 휴지통 아이콘으로 삭제한 장소는 휴지통에서 복원할 수 있으며, 기존 약속·코스는 바뀌지 않습니다.
- **기록**의 앨범 상단에서 검색·사진 업로드를 열고, 사진 도구(⋯)에서 새로고침·사진 내보내기를 선택합니다. 내보내기는 사진을 고른 뒤 내려받습니다. 앨범은 가로로 넘겨 보고, 날짜 옆 달력 아이콘으로 사진이 있는 날짜를 선택합니다.
- **기록 → 검색**에서 사진·기록·동선·월간 추억을 선택합니다. 동선을 조회하면 불러온 두 점 기록을 날짜순으로 재생할 수 있습니다. 영상 파일은 만들지 않습니다.
- **설정 → 기록 내보내기**에서 사본을 내려받습니다. **사진 휴지통**에서는 복구와 보관 기간이 지난 사진의 영구 삭제를 확인합니다.
- **설정 → 화면 테마**에서 웜 클린·화이트 또는 네 캐릭터 테마를 선택합니다. 선택은 해당 브라우저에 저장됩니다.

## 로그인 설정

### 1. Supabase 프로젝트

1. [Supabase Dashboard](https://supabase.com/dashboard)에서 Free 조직과 프로젝트를 만듭니다. DB 암호는 개인 암호 관리자에 보관하세요. 앱의 일반 로그인 환경 파일에는 DB 암호를 넣지 않습니다. 공동 기능에는 뒤의 SQL 마이그레이션 적용이 필요합니다.
2. 프로젝트의 Connect 또는 Settings → API Keys에서 **Project URL**과 **Publishable key**를 확인합니다. 공개 키는 `sb_publishable_...` 형태입니다. Secret/service_role 키는 필요하지 않습니다.
3. Authentication → URL Configuration에 Site URL `http://127.0.0.1:3000`, Redirect URLs `http://127.0.0.1:3000/auth/callback`을 등록합니다.
4. 첫 OAuth 로그인에서 계정을 만들 수 있도록 신규 가입을 허용합니다. 인증 계정 생성은 커플 공간 초대와 별개이며 로그인만으로 공동 데이터 접근을 허용하지 않습니다.

<a id="password-accounts"></a>

### 2. 지정 아이디·비밀번호 계정

아이디 로그인에는 실제 이메일 주소나 이메일 인증이 필요하지 않습니다. 앱에는 **아이디·비밀번호 입력만** 표시되며 회원가입 화면은 제공하지 않습니다. 운영자가 사용할 계정을 미리 생성합니다.

Supabase password API는 이메일/전화번호 식별자를 사용하므로 서버가 아이디를 내부 주소 `아이디@login.we2day.invalid`로 변환합니다. `.invalid`는 이메일 발송에 사용하지 않는 예약 도메인입니다. 비밀번호 검증/보관은 Supabase가 담당하며 별도의 비밀번호 DB나 앱 관리자 키는 사용하지 않습니다. 아이디 계정의 내부 주소는 계정 화면에 표시하지 않습니다.

1. Supabase → Authentication → Sign In / Providers → **Email** 공급자를 활성화합니다. 이는 내부 password 인증을 위한 설정이며 실제 이메일을 수집하거나 메일 로그인을 제공하는 것은 아닙니다.
2. Authentication → Users → Add user → Create new user에서 계정을 생성합니다.

   | 콘솔 항목 | 입력 예시 |
   | --- | --- |
   | Email | 아이디가 `partner_a`라면 `partner_a@login.we2day.invalid` |
   | Password | 사용할 비밀번호를 직접 지정. 길고 고유한 값 사용 권장 |
   | Auto Confirm User | 해당 사전 생성 계정에 체크 |

3. 다른 사용자도 별도 아이디/비밀번호로 생성합니다. 앱에서는 `partner_a`처럼 **주소 앞의 아이디만** 입력합니다. SMTP 설정·메일 수신/확인 링크는 필요하지 않습니다. 기존 소셜 계정의 이메일/비밀번호를 수정해 변환하지 마세요.
4. 아이디는 영문자로 시작하는 3~32자 영문·숫자·밑줄을 사용합니다. 로그인 입력의 앞뒤 공백은 제거하고 대소문자는 구분하지 않습니다. 콘솔의 내부 주소에는 **소문자 아이디**를 사용하세요. 비밀번호는 앞뒤 공백을 포함해 입력한 그대로 전달합니다.

아이디 로그인은 실제 이메일을 받지 않으므로 메일로 비밀번호를 찾는 기능은 제공하지 않습니다. 초기 비밀번호 재설정은 관리자가 Supabase 콘솔에서 처리합니다. 아이디 변경·소셜 계정 연결·복구 UI는 아직 제공하지 않습니다. 계정 생성과 커플 초대는 별도입니다.

지정 계정만 사용할 운영 환경에서는 Authentication의 사용자 가입 설정에서 **Allow new users to sign up**을 꺼 신규 가입도 제한하세요. 로그인 화면을 숨기는 것과 Supabase의 가입 허용 설정은 별개입니다. 소셜 로그인을 통한 신규 가입이 필요한 공개 설치는 해당 설정을 운영 정책에 맞게 선택합니다. [Supabase 일반 인증 설정](https://supabase.com/docs/guides/auth/general-configuration)을 참고하세요.

### 3. Google OAuth 앱 (선택)

1. [Google Cloud Console](https://console.cloud.google.com/)에서 프로젝트를 선택하고 Google Auth Platform을 설정합니다.
2. Branding에 앱 이름과 지원/연락 이메일을 입력합니다. Audience는 External, 개발 중에는 Testing으로 시작할 수 있습니다. 테스트 사용자 목록을 사용한다면 사용할 계정을 등록하세요. 기본 프로필 권한만 요청하는 앱에는 테스트 사용자 제한의 예외가 있을 수 있습니다. 따라서 이 목록만으로 앱 사용자를 제한할 수 있다고 가정하지 마세요.
3. Data Access → 범위 추가에서 다음 값을 선택하거나 **전체 문자열을 한 줄씩** 입력합니다.

   ```text
   openid
   https://www.googleapis.com/auth/userinfo.email
   https://www.googleapis.com/auth/userinfo.profile
   ```

4. Clients → Create client에서 아래처럼 입력합니다.

   | 항목 | 입력값 |
   | --- | --- |
   | 애플리케이션 유형 | 웹 애플리케이션 |
   | 이름 | `WE2DAY Local` 등 콘솔에서 구분할 이름 |
   | 승인된 JavaScript 원본 | `http://127.0.0.1:3000` |
   | 승인된 리디렉션 URI | Supabase Google 공급자 화면에서 복사한 `https://<project-ref>.supabase.co/auth/v1/callback` |
   | Use this client for an AI-powered agent | 선택하지 않음 |

5. 생성한 클라이언트를 열어 **클라이언트 ID**와 **클라이언트 보안 비밀번호(Client Secret)**를 복사합니다. Supabase → Authentication → Sign In / Providers → Google에서 각각 Client IDs·Client Secret에 입력하고 활성화·저장합니다.

   **Client IDs에는 앱 이름을 넣지 않습니다.** `숫자-문자열.apps.googleusercontent.com` 형태의 발급값을 넣으세요. 웹/PWA부터 시작하므로 현재는 웹 클라이언트 ID 하나면 됩니다. Google Client ID·Secret은 앱 `.env`에 추가하지 않습니다.

### 4. Kakao OAuth 앱 (선택)

1. [Kakao Developers](https://developers.kakao.com/)에서 앱을 만들고 콘솔의 필수 앱 정보를 입력합니다.
2. App Settings → App → Platform Key에서 **REST API key**를 확인합니다. 해당 키의 Kakao Login Redirect URI에 Supabase Kakao 공급자 화면에서 복사한 `https://<project-ref>.supabase.co/auth/v1/callback`을 등록합니다.
3. **Kakao Login Client Secret code**를 확인하고 활성화합니다. JavaScript 키나 Admin 키와 혼동하지 마세요.
4. Kakao Login 사용을 ON으로 설정하고 Consent Items에서 닉네임·프로필 사진 권한을 설정합니다. 현재 구성은 이메일 권한·OpenID Connect를 요구하지 않습니다.
5. Supabase Kakao 공급자의 Client ID에 REST API key, Client Secret에 위 secret을 입력합니다. **Allow users without an email을 ON**으로 설정하고 공급자를 활성화·저장합니다. 이메일이 없어도 Supabase 사용자 ID로 식별합니다.
6. 개발/테스트 앱으로 사용자 접근을 제한했다면 사용할 상대 계정도 팀 멤버/허용 사용자에 추가합니다.

콘솔 메뉴는 변경될 수 있습니다. [Supabase Google 설정](https://supabase.com/docs/guides/auth/social-login/auth-google)·[Supabase Kakao 설정](https://supabase.com/docs/guides/auth/social-login/auth-kakao)·[Google 범위 목록](https://developers.google.com/identity/protocols/oauth2/scopes)·[Kakao 설정](https://developers.kakao.com/docs/ko/kakaologin/prerequisite)을 함께 확인하세요.

### 5. 환경 변수와 로그인 방식 선택

`apps/web/.env.example`을 `apps/web/.env`, `apps/api/.env.example`을 `apps/api/.env`로 복사합니다. 기존 파일이 있으면 덮어쓰지 말고 필요한 값만 수정합니다.

웹 `apps/web/.env`:

```dotenv
WE2DAY_SITE_URL=http://127.0.0.1:3000
WE2DAY_SUPABASE_URL=https://<project-ref>.supabase.co
WE2DAY_SUPABASE_PUBLISHABLE_KEY=<publishable-key>
WE2DAY_AUTH_PROVIDERS=password
WE2DAY_API_URL=http://127.0.0.1:8000
```

API `apps/api/.env`:

```dotenv
WE2DAY_SUPABASE_URL=https://<project-ref>.supabase.co
WE2DAY_SUPABASE_PUBLISHABLE_KEY=<same-publishable-key>
WE2DAY_CORS_ORIGINS=["http://localhost:3000","http://127.0.0.1:3000"]
```

두 파일의 URL·Publishable key는 **같은 프로젝트 값**을 넣습니다. Google/Kakao의 Client Secret은 Supabase 콘솔에만 입력합니다. 실제 `.env`는 Git 추적과 Docker 이미지 빌드에서 제외되며 Compose가 런타임 환경으로 읽습니다.

웹의 `WE2DAY_SITE_URL`은 `http://127.0.0.1:3000`으로 맞추고 같은 호스트에서 로그인을 시작하고 완료하세요. `WE2DAY_AUTH_PROVIDERS`는 사용할 방식만 지정합니다. 미지정 기본값은 `password`, 빈 문자열로 지정하면 모든 로그인 방식을 숨깁니다. 사용하지 않는 방식은 화면과 서버 액션에서 모두 차단합니다.

| 사용할 구성 | WE2DAY_AUTH_PROVIDERS |
| --- | --- |
| 지정 아이디·비밀번호만 | `password` |
| 소셜만 | `google,kakao` (하나만 지정해도 됨) |
| 아이디와 소셜 함께 | `password,google,kakao` |

아이디 로그인만 사용할 때 Google/Kakao 콘솔 설정은 하지 않아도 됩니다. 소셜을 선택한 환경은 해당 공급자도 Supabase에서 활성화해야 합니다. 기존 환경 파일이 `google,kakao`라면 아이디 방식을 사용하려면 `password`를 추가하거나 교체하세요.

| 설정 위치 | 등록할 값 |
| --- | --- |
| Supabase Authentication → URL Configuration → Site URL | `http://127.0.0.1:3000` |
| Supabase Redirect URLs | `http://127.0.0.1:3000/auth/callback` |
| Google OAuth Web client → JavaScript origins | `http://127.0.0.1:3000` |
| Google/Kakao OAuth Redirect URI | Supabase 공급자 화면의 `https://<project-ref>.supabase.co/auth/v1/callback` |

API 환경 파일은 로그인 방식을 바꿀 때 변경할 필요가 없습니다. 실제 아이디/비밀번호·서비스 키는 README나 `.env.example`에 넣지 마세요.

### 6. 설정 반영과 확인

환경 변수만 바꿨다면 저장소 루트에서 다음 명령으로 컨테이너를 다시 생성합니다. `docker compose restart`만으로는 변경된 환경 변수가 반영되지 않습니다.

```sh
docker compose up --detach --wait
```

소스·의존성도 바꿨다면 `docker compose up --build --detach --wait`를 사용합니다. 로컬 개발 실행은 웹/API 서버를 재시작합니다. Compose에서는 웹→API 주소를 `http://api:8000`으로 자동 설정합니다.

1. `http://127.0.0.1:3000/login`에서 선택한 방식만 표시되는지 확인합니다. 아이디 방식은 미리 만든 아이디·비밀번호로 로그인합니다.
2. 소셜 방식을 선택했다면 Google/Kakao에서 사용할 계정과 공유 정보·동의 내용을 확인합니다. 카카오 계정에 로그인되지 않았다면 직접 계정을 입력하거나 **QR코드 로그인**을 선택해 카카오톡 → 더보기 → QR코드 스캔으로 인증할 수 있습니다. 계정 비밀번호나 QR 인증 정보를 채팅·공개 이슈에 공유하지 마세요.
3. 로그인 완료 후 `/account`에서 계정과 서버의 계정 확인 완료 표시를 확인합니다.
4. 새로고침·새 탭에서도 세션이 유지되고, 로그아웃 후 `/account`에 재접속하면 로그인으로 돌아오는지 확인합니다.
5. Supabase Authentication → Users에서도 계정 생성 여부를 확인할 수 있습니다.

공급자의 로그인/동의 화면이 열리는 것과 앱으로 복귀해 인증이 완료되는 것은 별도입니다. Google은 이메일·프로필 범위만 사용하며 Calendar·Drive 권한은 요청하지 않습니다. Kakao는 이메일 없는 계정을 지원하도록 요청 scope를 닉네임·프로필 사진으로 제한합니다. 실제 계정 정보·토큰·콜백 전체 URL은 로그나 공개 이슈에 올리지 마세요.

### 오류 해결

| 증상 | 확인/해결 |
| --- | --- |
| Google 범위가 잘못되었다는 오류 | `userinfo.email`·`userinfo.profile` 축약값 대신 위 전체 URI 입력 |
| Supabase Client IDs의 Invalid characters | `WE2DAY` 같은 이름 대신 Google이 발급한 `.apps.googleusercontent.com` ID 입력 |
| 로그인 버튼이 없음 | 웹 URL/키·공급자 목록 확인 후 `docker compose up --detach --wait` 실행 |
| 아이디 또는 비밀번호 오류 | 사전 생성 계정의 소문자 내부 주소·비밀번호·Auto Confirm 여부와 Email 공급자 활성화 확인. 내부 주소 전체가 아닌 아이디만 입력 |
| Google redirect_uri_mismatch / Kakao KOE006 | Google/Kakao 콘솔에 **Supabase 콜백**이 정확히 등록됐는지 확인 |
| Google 동의 후 Unable to exchange external code | Supabase Google의 Client Secret이 비어 있거나 다른 클라이언트 값인지 먼저 확인. 같은 웹 클라이언트의 ID·Secret을 짝지어 저장한 뒤 새 로그인 요청으로 재시도 |
| 동의 후 앱 복귀 실패 | Supabase에 **앱 콜백** 등록, 127.0.0.1/localhost 혼용 금지, 시작한 브라우저에서 완료 |
| Kakao KOE205·이메일 권한 오류 | 닉네임/프로필 사진 동의항목 설정과 Supabase Allow users without an email 확인 |
| 계정은 보이지만 서버 확인 실패 | 웹/API URL·키의 프로젝트 일치, API 실행 상태·Docker 내부 통신 확인 |

## 데이터베이스 설정

로그인 설정을 마친 뒤 같은 Supabase 프로젝트의 SQL Editor에서 마이그레이션 파일을 적용합니다.

- **처음 설치:** 아래 파일을 001부터 026까지 순서대로 열어 각각 전체 내용을 실행합니다. 매번 `Success`를 확인하고 다음 파일로 넘어갑니다.
- **기존 설치 업데이트:** 적용 이력을 확인하고 아직 실행하지 않은 파일만 순서대로 적용합니다. 이미 적용한 파일은 다시 실행하지 않습니다.

| 순서 | 실행할 파일 | 추가되는 기능 |
| --- | --- | --- |
| 001 | [`202610190001_shared_calendar.sql`](../supabase/migrations/202610190001_shared_calendar.sql) | 공간·초대·공동 일정 |
| 002 | [`202610190002_anniversaries.sql`](../supabase/migrations/202610190002_anniversaries.sql) | 기념일과 디데이 |
| 003 | [`202610190003_photos.sql`](../supabase/migrations/202610190003_photos.sql) | 사진 저장과 앨범 |
| 004 | [`202610190004_meeting_days.sql`](../supabase/migrations/202610190004_meeting_days.sql) | 만난 날 표시와 메모 |
| 005 | [`202610190005_photo_lifecycle.sql`](../supabase/migrations/202610190005_photo_lifecycle.sql) | 사진 휴지통·복구·영구 삭제 |
| 006 | [`202610190006_meeting_routes.sql`](../supabase/migrations/202610190006_meeting_routes.sql) | 날짜별 출발점·도착점 |
| 007 | [`202610190007_date_plans.sql`](../supabase/migrations/202610190007_date_plans.sql) | 데이트 플랜과 달력 연결 |
| 008 | [`202610190008_date_reports.sql`](../supabase/migrations/202610190008_date_reports.sql) | 개인 리포트와 공유 |
| 009 | [`202610190009_wishlist.sql`](../supabase/migrations/202610190009_wishlist.sql) | 위시리스트 |
| 010 | [`202610190010_monthly_memories.sql`](../supabase/migrations/202610190010_monthly_memories.sql) | 월간 추억 집계 |
| 011 | [`202610190011_shared_checklists.sql`](../supabase/migrations/202610190011_shared_checklists.sql) | 공동 준비 목록 |
| 012 | [`202610190012_shared_goals.sql`](../supabase/migrations/202610190012_shared_goals.sql) | 공동 목표와 달성 단계 |
| 013 | [`202610190013_direct_questions.sql`](../supabase/migrations/202610190013_direct_questions.sql) | 공동 질문과 개인 답변 |
| 014 | [`202610190014_timezones.sql`](../supabase/migrations/202610190014_timezones.sql) | 개인 시간대 설정 |
| 015 | [`202610190015_choice_roulette.sql`](../supabase/migrations/202610190015_choice_roulette.sql) | 선택 룰렛과 결과 기록 |
| 016 | [`202610200016_photo_search.sql`](../supabase/migrations/202610200016_photo_search.sql) | 사진 날짜·한마디 검색 |
| 017 | [`202610200017_photo_reference_search.sql`](../supabase/migrations/202610200017_photo_reference_search.sql) | 사진 원본 파일 정보·업로더 검색 |
| 018 | [`202610200018_question_search.sql`](../supabase/migrations/202610200018_question_search.sql) | 공동 질문 검색 |
| 019 | [`202610200019_visit_progress.sql`](../supabase/migrations/202610200019_visit_progress.sql) | 확정한 플랜의 방문 진행 기록 |
| 020 | [`202610210020_record_search.sql`](../supabase/migrations/202610210020_record_search.sql) | 일정·플랜·공유 리포트·위시 검색 |
| 021 | [`202610210021_next_appointment.sql`](../supabase/migrations/202610210021_next_appointment.sql) | 다음 약속 조회 |
| 022 | [`202610210022_record_snapshots.sql`](../supabase/migrations/202610210022_record_snapshots.sql) | 기록 다운로드 |
| 023 | [`202610210023_device_push.sql`](../supabase/migrations/202610210023_device_push.sql) | 기기별 푸시 알림 등록·해제 |
| 024 | [`202610220024_scheduled_anniversary_push.sql`](../supabase/migrations/202610220024_scheduled_anniversary_push.sql) | 기념일 자동 알림을 위한 발송 상태와 전용 DB 역할 |
| 025 | [`202610220025_user_profiles.sql`](../supabase/migrations/202610220025_user_profiles.sql) | 로그인 아이디와 별도로 사용하는 사용자 이름 |
| 026 | [`202610230026_favorite_places.sql`](../supabase/migrations/202610230026_favorite_places.sql) | 커플 공유 자주 가는 곳, 수정 충돌 확인과 보관·복원 |
| 027 | [`202610230027_plan_map_links.sql`](../supabase/migrations/202610230027_plan_map_links.sql) | 코스의 네이버 지도 공유 링크 |
| 028 | [`202610240028_agent_gateway.sql`](../supabase/migrations/202610240028_agent_gateway.sql) | 범위가 제한된 에이전트 연결 키와 초안 작성 |
| 029 | [`202610250029_read_projections.sql`](../supabase/migrations/202610250029_read_projections.sql) | 플랜 요약과 사진 있는 날짜 조회 |
| 030 | [`202610250030_photo_metadata.sql`](../supabase/migrations/202610250030_photo_metadata.sql) | 두 사람의 사진 날짜·설명 수정 |
| 031 | [`202610250031_photo_previews.sql`](../supabase/migrations/202610250031_photo_previews.sql) | 비공개 사진 미리보기와 파일 수명주기 |
| 032 | [`202610250032_personal_schedules.sql`](../supabase/migrations/202610250032_personal_schedules.sql) | 개인 일정과 작성자 수정·삭제 권한 |

024를 적용해도 자동 알림이 바로 켜지지는 않습니다. 새 예약 역할은 로그인할 수 없는 상태로 생성됩니다. 자동 알림을 사용하려면 [배포 가이드](deployment.md)의 worker 설정과 기기별 동의 절차도 완료해야 합니다.

### 두 계정 연결과 저장 확인

로그인 후 **설정 → 계정 관리 → 사용자 이름**에서 서비스에 표시할 이름을 저장합니다. 로그인 아이디·비밀번호는 그대로 사용하며, 표시 이름은 본인만 수정할 수 있습니다. 연결된 상대방은 이름을 볼 수 있고, 설정·계정·사진 업로더 표시에 사용됩니다. 이름을 등록하지 않았거나 프로필을 불러오지 못한 경우에는 아이디·이메일 대신 일반 안내를 표시합니다. 소셜 로그인 이름을 자동으로 복사하지 않으므로 로그인 방식에 관계없이 직접 설정하세요.

1. 한 계정으로 `/couple`에서 **새 공간 만들기 → 초대 코드 만들기**를 선택합니다.
2. 상대는 자신의 계정으로 로그인한 뒤 **받은 초대 코드 → 초대 수락하기**를 선택합니다. 초대를 받을 사람은 별도 공간을 만들지 않습니다. 이미 연결된 계정은 이 단계를 반복하지 않습니다.
3. 달력에서 약속·기념일·만난 날을 저장하고 상대 계정에서도 같은 기록이 보이는지 확인합니다.
4. `/memories`에서 테스트용 사진을 올려 공유·휴지통 이동·복구를 확인합니다. `/plans`에서는 초안 작성 → 확정 → 달력 등록을 확인합니다.

같은 PC에서 두 계정을 확인하려면 일반 창과 시크릿 창처럼 로그인 세션이 분리된 브라우저 창을 사용하세요.

약속에는 제목과 날짜가 필요하며 시간·장소·메모는 선택입니다. 제목은 100자, 장소는 200자, 메모는 2,000자까지 입력할 수 있습니다. 날짜는 2000~2100년, 시간은 한국 시간 기준으로 저장합니다. 커플 연결 해제와 약속 삭제는 아직 지원하지 않습니다.

### 데이터가 조회되지 않을 때

마이그레이션 적용 여부, Supabase Data API 활성화와 `public` 스키마 공개 설정, 웹과 API가 같은 프로젝트를 사용하는지 확인하세요. 앱 설정에 `service_role`이나 secret key를 추가할 필요는 없습니다.

기념일만 조회되지 않는다면 같은 프로젝트의 SQL Editor에서 다음 명령으로 테이블이 있는지 확인할 수 있습니다.

```sql
select to_regclass('public.anniversaries') as anniversary_table;
```

결과가 `NULL`이면 테이블이 없는 상태입니다. 002 파일 전체를 실행하고 `Success`를 확인하세요. 테이블이 이미 있다면 파일을 다시 실행하기 전에 기존 실행 오류와 Data API 설정을 확인합니다. API 로그에는 오류 분류와 HTTP 상태만 남기며 SQL 원문·응답 본문·키는 기록하지 않습니다.

## NAVER 장소 검색 설정 (선택)

약속 입력·상세와 데이트 플랜의 활동에서 **장소 검색**을 열고 지역·장소 이름을 입력한 뒤 **검색**을 누릅니다. 앱 안에 장소명·주소 등 최대 5건의 목록이 표시됩니다. 약속·활동 입력에서는 **장소 선택**으로 목적지를 입력란에 넣고 수정할 수 있습니다. 선택만으로 저장되지 않으며 기존 저장 버튼으로 반영합니다. 검색 버튼 또는 Enter를 눌렀을 때만 검색어를 네이버로 전송하며, 검색과 약속·플랜 저장은 별도 동작입니다.

1. [네이버 클라우드 콘솔](https://console.ncloud.com/)의 **Application Services → NAVER API HUB → Application**에서 검색 API의 지역 검색을 사용할 애플리케이션을 등록합니다. 현재 콘솔의 무료 제공량·호출 한도를 확인합니다.
2. 해당 애플리케이션의 **Client ID·Client Secret**을 `apps/api/.env`에 입력합니다. **Maps 지도 표시용 키와는 다릅니다.** 웹 환경 파일이나 `NEXT_PUBLIC_*` 변수에는 검색 키를 넣지 않습니다.

```dotenv
WE2DAY_NAVER_SEARCH_ENABLED=true
WE2DAY_NAVER_SEARCH_CLIENT_ID=your-api-hub-client-id
WE2DAY_NAVER_SEARCH_CLIENT_SECRET=your-api-hub-client-secret
```

3. Docker 환경은 API 이미지를 다시 빌드해 반영합니다. 로컬에서 API를 직접 실행한다면 해당 서버를 재시작합니다.

```powershell
docker compose up --detach --build --wait api
```

검색은 로그인 후 둘의 공간을 만든 상태에서 사용할 수 있습니다. 결과는 현재 화면에서만 잠시 표시하며 닫기·새 검색·화면 이동 시 제거합니다. 검색이 실패해도 작성 중인 약속·활동 내용은 유지됩니다. 키를 설정하지 않아도 장소를 직접 입력하고 플랜·약속을 저장할 수 있습니다. 기존 코스의 **네이버 지도** 버튼은 저장한 장소로 지도 앱을 열며, 운전 길찾기는 앱에서 선택합니다.

[공식 지역 검색 명세](https://api.ncloud-docs.com/docs/naver-api-hub-search-local) · [지도 앱 연결](https://guide.ncloud-docs.com/docs/maps-url-scheme). 검색 API HUB 키와 Dynamic Map Client ID의 용도·설정을 구분하세요.

## NAVER 지도 표시 설정

출발·도착 두 점을 찍는 지도 입력 기능은 제거했습니다. 새 설치에는 웹 Dynamic Map Client ID 설정이 필요하지 않습니다. 장소 검색과 저장한 코스의 네이버 지도 앱 연결은 위 절차대로 사용합니다. 기존 DB 마이그레이션은 과거 자료와 API 호환을 위해 유지합니다.

<a id="checks"></a>
## 검사

```sh
npm run lint
npm run typecheck
npm run build
npm run lint:api
npm run test:api
npm exec --workspace @we2day/web -- playwright install chromium
npm run test:web
npm run test:auth
npm run test:database
npm run test:calendar
npm run test:photos
npm run test:photo-sharing
npm run test:places
npm run test:plans
npm run test:map-loader
npm run test:journey
npm run test:organizer
npm run test:timeline
npm run test:pwa
```

브라우저 검사는 기본적으로 개발 서버를 시작하고 종료합니다. 이미 같은 주소에서 개발 서버를 실행했다면 해당 서버를 재사용합니다.

인증 검사는 별도 로컬 테스트용 인증 서버·실제 FastAPI·Next 서버를 54329/8100/3100 포트에 실행하고 종료합니다. 실제 공급자 로그인을 대체하지 않습니다. 실제 인증 세션을 검사 산출물로 저장하지 않습니다.

`test:database`와 `test:calendar`에는 Docker가 필요합니다. PostgreSQL 17 Alpine, 브라우저 종단 검사에는 PostgREST 14.10 이미지를 사용합니다. 최초 실행은 이미지를 내려받을 수 있습니다. 임시 DB·컨테이너는 검사 후 제거하며 실제 Supabase 프로젝트나 실제 계정을 사용하지 않습니다.

| 검사 | 확인하는 내용 |
| --- | --- |
| `test:api` | 인증·본문 검증·안전한 오류·사용자 JWT 전달. Docker DB 검사는 기본적으로 건너뜀 |
| `test:database` | 실제 SQL·RLS·직접 변경 우회 차단·초대 만료/재사용·동시 수락·수정 충돌 |
| `test:auth` | 테스트용 인증 서버와 실제 웹/API로 로그인·쿠키·갱신·로그아웃·방식별 노출 |
| `test:calendar` | 테스트 계정 + 실제 Next → FastAPI → PostgREST → PostgreSQL로 사용자 두 명 공유·권한·응답 유실 재시도·수정 충돌·입력 유지 |
| `test:web` | 테마·월 달력·예시 화면·모바일 레이아웃 회귀 |
| `test:photos` | 테스트 이미지/EXIF로 압축·다운로드·메타데이터 제외·파일 거부/취소·모바일 검사 |
| `test:photo-sharing` | 테스트 계정 두 개의 저장/공유·휴지통 이동·상대 계정에서 복구·30일/삭제 재시도·ZIP 다운로드·만남 메모/충돌. 실제 SQL + 사진 저장소를 대신하는 HTTP 테스트 서버 |
| `test:map-loader` | 외부 호출 없이 SDK 준비 콜백/로드 이벤트·실패 후 재시도 검사. 브라우저·Docker 불필요 |
| `test:plans` | 일회용 DB/테스트 계정 두 개의 플랜 저장→확정→충돌→재확정→보관/복원. 실제 Maps API 호출 없음 |
| `test:journey` | 테스트 계정 두 개의 위시→플랜 확정→투데이·미확정 변경 제외→개인 회고 차단/공유/철회→복제 시 달력 보존 |
| `test:organizer` | 테스트 계정의 다가오는 약속/기념일·날짜 직접 이동·ICS 실제 다운로드/메모 선택·월간 집계와 빈 월 |
| `test:timeline` | 미정 비용(null)과 입력한 0원, 일부 비용의 합계 구분. Docker 불필요 |
| `test:pwa` | 연결이 끊겼을 때 안내 화면 표시, API·인증·POST 응답 저장 제외, 사용자 선택에 따른 업데이트. Docker 불필요 |
| `test:places` | 합성 장소 목록·약속/활동 장소 선택·저장 후 재조회·초안 보존·순서 조작·모바일 정렬·안전 링크·오류/취소·중계 보안. 실제 검색 API 호출 없음 |

공동 일정·기념일 종단 검사는 웹/API/테스트용 인증의 위 포트와 임시 PostgREST의 54330 포트를 사용합니다. 날짜 계산은 첫날/100일·윤일/평년·한국 자정과 원본 보존을 검사하며, 브라우저에서는 사용자 두 명 기념일 공유·응답 유실 재시도·입력 오류/충돌·취소·두 테마를 확인합니다. 추적 파일은 남기지 않으며, 자동 검사와 별도로 실제 Supabase 프로젝트와 사용자 계정, 휴대폰에서도 동작을 확인해야 합니다.

`test:photos`는 Supabase 설정을 비운 별도 Next 서버를 3101 포트에 실행·종료합니다. 개인 사진·실제 계정 없이 테스트 이미지와 메타데이터만 검사하며 사진 업로드/공유 검증과 구분합니다.

`test:photo-sharing`은 공동 일정 검사와 같은 일회용 PostgreSQL/PostgREST·테스트용 인증·웹/API 포트를 재사용합니다. 파일은 메모리에 보관하는 사진 저장소를 대신하는 HTTP 테스트 서버이며 실제 PostgreSQL RLS를 호출합니다. 실제 Supabase Storage 서버·클라우드 적용 확인을 대신하지 않습니다. 수정한 기능에 맞는 검사를 선택해 실행하세요. 인증이나 공통 기반을 바꾸거나 배포를 준비할 때는 관련 전체 흐름도 함께 검사합니다.

### 전체 화면과 모바일 레이아웃 검사

`test:organizer`에는 모든 페이지를 자동으로 찾아 검사하는 화면 감사가 포함됩니다. 긴 제목·사진·편집 폼을 넣은 상태에서 좁은 모바일, 태블릿, 데스크톱과 두 테마의 가로 넘침, 입력칸 크기, 터치 영역, 키보드 포커스를 확인합니다. 화면 캡처는 `apps/web/test-results`에 생성되며 공개 커밋에는 포함하지 않습니다.

전체 화면 감사만 실행하려면 다음 명령을 사용하세요.

```bash
uv run --project apps/api python apps/web/tests/run_calendar_tests.py --organizer --grep "all page controls"
```

Safari 계열 렌더링에는 WebKit을 사용합니다. 개발 서버의 화면 갱신과 자동 이동이 겹치는 영향을 줄이려면 운영용 빌드로 검사하세요. 먼저 저장소 루트에서 다음을 실행합니다.

```bash
npx playwright install webkit
npm run build
node -e "const fs=require('node:fs');fs.cpSync('apps/web/.next/static','apps/web/.next/standalone/apps/web/.next/static',{recursive:true});fs.cpSync('apps/web/public','apps/web/.next/standalone/apps/web/public',{recursive:true})"
```

PowerShell에서는 아래 환경 변수를 지정한 뒤 같은 화면 감사 명령을 실행합니다.

```powershell
$env:WE2DAY_TEST_BROWSER='webkit'
$env:WE2DAY_TEST_WEB_ENGINE='standalone'
uv run --project apps/api python apps/web/tests/run_calendar_tests.py --organizer --grep "all page controls"
Remove-Item Env:WE2DAY_TEST_BROWSER, Env:WE2DAY_TEST_WEB_ENGINE
```

기본 브라우저 엔진은 Chromium입니다. 운영 빌드 검사도 실제 서비스 대신 테스트 계정·임시 DB를 사용합니다. 이 검사는 iPhone 실기기의 키보드·홈 화면 앱·알림 동작 확인을 대신하지 않습니다.

## Docker

Docker Engine과 Docker Compose가 실행 중인 환경에서 다음 명령을 사용합니다. 로컬 개발 서버와 포트가 겹치면 먼저 종료하세요. 의존성 설치에는 BuildKit의 npm 캐시와 제한된 네트워크 재시도를 사용하며 잠금 파일의 버전을 유지합니다.

```sh
docker compose up --build
```

종료 후 컨테이너를 정리합니다.

```sh
docker compose down
```

웹/API는 각각의 `.env`를 선택적으로 읽습니다. 설정이 없어도 화면 미리보기와 API 생존 확인은 사용할 수 있습니다. 웹→API 주소는 Compose 내부 `http://api:8000`으로 자동 설정합니다. 환경 변경 후 `docker compose up --build --detach --wait`로 반영합니다. 컨테이너는 기본적으로 로컬 호스트의 3000·8000 포트에 바인딩됩니다.

[README로 돌아가기](../README.md)

### 코스에 네이버 지도 공유 링크 넣기

PC 네이버 지도에서 공유 링크를 복사한 뒤 코스 활동의 지도 검색 옆 ‘네이버 지도 공유 링크’에 붙여 넣으세요. `https://naver.me/…` 형식만 지원합니다. 플랜을 저장하고 확정하면 해당 코스의 네이버 지도 버튼이 공유 링크를 열며, 링크가 없으면 기존 장소명 검색을 사용합니다. 장소 공유는 장소를, 경로 공유는 링크에 담긴 경로를 엽니다. 앱 실행 여부는 기기 설정에 따라 달라지며 운전 안내가 자동 시작되지는 않습니다. 기존 설치는 SQL027을 적용한 뒤 API와 웹을 함께 업데이트하세요.

### 사진 날짜·설명과 미리보기

정상 앨범의 사진 상단 연필 아이콘에서 두 사람 모두 앨범 날짜와 설명을 수정할 수 있습니다. 저장 후 새 날짜의 앨범으로 이동하며 검색·월간 추억에도 반영됩니다. 촬영 시각, 업로더, 업로드 시각과 사진 파일은 그대로 유지합니다. 동시에 바뀐 사진은 덮어쓰지 않으며, 최신 목록을 확인한 뒤 다시 수정하세요. 휴지통 사진은 복구한 뒤 수정합니다.

사진 목록에는 최대 640px의 작은 WebP를 사용합니다. 같은 비공개 `we2day-photos` 버킷에 `<공간 UUID>/<사진 UUID>.preview.webp`로 저장하며, 기존 사진은 처음 미리보기를 조회할 때 생성합니다. 이 파생본에는 EXIF·GPS·ICC·XMP를 넣지 않으며, 표시할 때 권한·해시·이미지 형식을 검사합니다. 생성에 실패하면 기존 압축본에서 미리보기를 만들어 표시합니다. 큰 사진 보기와 다운로드는 기존 압축본을 사용합니다.

미리보기에도 저장 용량이 추가됩니다. 휴지통·복원 정책은 두 파일에 함께 적용하며, 보관 기간 이후 명시적으로 영구 삭제하면 두 파일을 모두 지운 뒤 기록을 정리합니다. 전체 백업은 버킷의 두 파일을 모두 수집·검증·복원합니다. 기존 설치는 미적용 SQL029~031을 순서대로 적용한 뒤 웹·API와 백업/감사 이미지를 함께 업데이트하세요. 새 키나 공개 버킷 설정은 필요하지 않습니다.

### 개인 일정 적용

기존 설치는 미적용 SQL032 전체를 실행한 뒤 웹·API를 함께 업데이트합니다. 기존 공동 약속의 자료와 공동 편집 권한은 유지됩니다. 개인 일정은 두 사람이 조회하며 작성자만 수정·삭제할 수 있습니다. 장소·코스 없이 등록하며, 다음 공동 약속과 에이전트 조회에서 제외됩니다. 새 키나 계정 설정은 필요하지 않습니다. 기록 JSON에는 일정 유형이 포함되며 기존 유형 없는 JSON 사본의 로컬 검사도 지원합니다.
