# 설치와 처음 사용하기

[README](../README.md) · [배포](deployment.md) · [아키텍처](architecture.md)

새 설치는 **미리보기 → Supabase → SQL → 두 계정 → 공간 연결** 순서로 진행합니다. 지도·소셜 로그인·알림은 선택 기능입니다. 실제 키와 계정은 각 설치 환경에서 준비합니다. 설정한 기능만 화면에 노출하며, 아래 예제의 프로젝트 식별자와 키는 직접 교체합니다.

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

설정에서 화이트/웜 클린을 선택하면 이 브라우저의 쿠키에 1년간 저장합니다. 기본값은 웜 클린입니다. HTTPS 운영에서는 Secure 쿠키를 사용합니다.

주요 실행은 단색 채움, 보조 버튼과 이동은 윤곽·배경으로 구분합니다. 본문 링크는 밑줄, 펼치기는 화살표와 열린 상태, 클릭 가능한 카드는 이동 단서를 표시합니다. 아이콘 버튼은 최소44px 터치 영역을 유지하며 키보드 포커스·선택·처리 중 비활성 상태를 구분합니다. 달력 날짜와 주요 메뉴는 각 문맥의 선택 표시를 유지합니다.

Supabase 인증은 아래 설정을 마친 뒤 사용할 수 있습니다.

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

이메일 주소를 수집하지 않으므로 이메일 기반 비밀번호 찾기는 제공하지 않습니다. 초기 비밀번호 재설정은 관리자가 Supabase 콘솔에서 처리합니다. 아이디 변경·소셜 계정 연결·복구 UI는 아직 제공하지 않습니다. 계정 생성과 커플 초대는 별도입니다.

지정 계정만 사용할 운영 환경에서는 Authentication의 사용자 가입 설정에서 **Allow new users to sign up**을 꺼 신규 가입도 제한하세요. 로그인 화면을 숨기는 것과 Supabase의 가입 허용 설정은 별개입니다. 소셜 로그인을 통한 신규 가입이 필요한 공개 설치는 해당 설정을 운영 정책에 맞게 선택합니다. [Supabase 일반 인증 설정](https://supabase.com/docs/guides/auth/general-configuration)을 참고하세요.

### 3. Google OAuth 앱 (선택)

1. [Google Cloud Console](https://console.cloud.google.com/)에서 프로젝트를 선택하고 Google Auth Platform을 설정합니다.
2. Branding에 앱 이름과 지원/연락 이메일을 입력합니다. Audience는 External, 개발 중에는 Testing으로 시작할 수 있습니다. 테스트 사용자 목록을 사용한다면 사용할 계정을 등록하세요. 기본 identity 범위만 요청하는 앱에는 테스트 사용자 제한 예외가 있으므로 이 목록을 앱 접근 제어 수단으로 사용하지 않습니다.
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

웹의 `WE2DAY_SITE_URL`은 `http://127.0.0.1:3000`으로 맞추고 같은 호스트에서 로그인을 시작하고 완료하세요. `WE2DAY_AUTH_PROVIDERS`는 사용할 방식만 지정합니다. 미지정 기본값은 `password`, 명시적으로 빈 값이면 모든 로그인 방식을 숨깁니다. 사용하지 않는 방식은 화면과 서버 액션에서 모두 차단합니다.

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

## 공동 일정·기념일·사진·만남 DB 설정

로그인 설정과 별도로 한 번 적용합니다. **기존 프로젝트에 같은 마이그레이션을 다시 실행하지 마세요.** 배포 환경에서는 적용 이력을 관리하며 파일 이름 순서대로 적용합니다.

1. Supabase 프로젝트의 SQL Editor에서 새 쿼리를 엽니다.
2. [`202610190001_shared_calendar.sql`](../supabase/migrations/202610190001_shared_calendar.sql)의 전체 내용을 실행합니다. 테이블·인덱스·RLS·RPC를 한 트랜잭션으로 생성합니다.
3. [`202610190002_anniversaries.sql`](../supabase/migrations/202610190002_anniversaries.sql)의 전체 내용을 실행합니다. 기념일 테이블·제약·RLS·생성/수정 RPC를 추가합니다.
4. [`202610190003_photos.sql`](../supabase/migrations/202610190003_photos.sql)의 전체 내용을 실행합니다. 사진 테이블·예약/완료 RPC와 **private `we2day-photos` bucket(1MiB·image/webp)**·객체별 RLS를 만듭니다. 같은 이름의 버킷이 이미 있고 설정이 다르면 실행을 중단하므로 설정/적용 이력을 확인하세요. 공개 bucket으로 바꾸지 않습니다.
5. [`202610190004_meeting_days.sql`](../supabase/migrations/202610190004_meeting_days.sql)의 전체 내용을 실행합니다. 날짜별 만남 표시·메모·버전 비교 RPC/RLS를 만듭니다.
6. [`202610190005_photo_lifecycle.sql`](../supabase/migrations/202610190005_photo_lifecycle.sql)의 전체 내용을 실행합니다. 사진 휴지통/복구·최소30일·버전 검사와 삭제 준비/완료·Storage 삭제 권한을 추가합니다. **001~004 적용 환경은 005만 실행**합니다. 각 파일은 전체 Run과 Success 결과를 확인하며 추가 `.env`나 관리자 키는 필요하지 않습니다. 새 앱 코드를 실행하기 전에 필요한 SQL부터 적용합니다.
7. [`202610190006_meeting_routes.sql`](../supabase/migrations/202610190006_meeting_routes.sql) 전체를 실행합니다. 날짜별 두 점·좌표 범위·커플 RLS·수정 충돌/재시도 함수를 추가합니다.
8. [`202610190007_date_plans.sql`](../supabase/migrations/202610190007_date_plans.sql) 전체를 실행합니다. 플랜 저장·확정/달력 연결·보관/복원을 추가합니다. **001~005 적용 환경은 006 → 007만 순서대로 실행**합니다. 두 SQL 모두 Success 확인 후 사용하며 기존 SQL이나 계정을 다시 만들 필요는 없습니다.
9. [`202610190008_date_reports.sql`](../supabase/migrations/202610190008_date_reports.sql) 전체를 실행합니다. 작성자별 회고·개인 초안/명시적 공유·스냅샷과 RLS/RPC를 추가합니다.
10. [`202610190009_wishlist.sql`](../supabase/migrations/202610190009_wishlist.sql) 전체를 실행합니다. 수동 위시·공동 편집/완료·보관/복원과 RLS/RPC를 추가합니다. 각 Success를 확인합니다. 새 키나 계정 생성은 필요하지 않습니다.
11. [`202610190010_monthly_memories.sql`](../supabase/migrations/202610190010_monthly_memories.sql) 전체를 실행합니다. 기존 테이블의 RLS를 적용하는 읽기 전용 월간 집계 RPC를 추가하며 새 사진/기록 테이블을 만들지 않습니다.
12. [`202610190011_shared_checklists.sql`](../supabase/migrations/202610190011_shared_checklists.sql) 전체를 실행합니다. 공동 목록·체크·보관/복원의 테이블과 제한된 저장 RPC를 추가합니다.
13. [`202610190012_shared_goals.sql`](../supabase/migrations/202610190012_shared_goals.sql) 전체를 실행합니다. 공동 목표·희망 날짜·단계·수동 달성·보관/복원 테이블과 제한된 RPC를 추가합니다.
14. [`202610190013_direct_questions.sql`](../supabase/migrations/202610190013_direct_questions.sql) 전체를 실행합니다. 공동 질문·작성자 답변·공유/철회·건너뛰기의 RLS/RPC를 추가합니다.
15. [`202610190014_timezones.sql`](../supabase/migrations/202610190014_timezones.sql) 전체를 실행합니다. 본인 시간대 설정과 같은 공간 읽기를 추가합니다.
16. [`202610190015_choice_roulette.sql`](../supabase/migrations/202610190015_choice_roulette.sql) 전체를 실행합니다. 후보 룰렛·이력 보존·뽑기 재시도 RPC를 추가합니다.
17. [`202610200016_photo_search.sql`](../supabase/migrations/202610200016_photo_search.sql) 전체를 실행합니다. 기존 사진 RLS 아래에서 날짜·한마디를 검색하는 읽기 전용 RPC를 추가합니다. 이미 적용한 SQL은 반복하지 않습니다. 새 키/계정·추가 서비스는 필요하지 않습니다.
18. [`202610200017_photo_reference_search.sql`](../supabase/migrations/202610200017_photo_reference_search.sql) 전체를 실행합니다. 기존 사진 참고 정보·업로더 필터의 읽기 전용 RPC를 추가합니다.
19. [`202610200018_question_search.sql`](../supabase/migrations/202610200018_question_search.sql) 전체를 실행합니다. 답변을 조회하지 않는 공동 질문 문구 검색 RPC를 추가합니다. 각 SQL의 Success를 확인합니다.
20. [`202610200019_visit_progress.sql`](../supabase/migrations/202610200019_visit_progress.sql) 전체를 실행합니다. 기존 플랜의 확정차수와 공동 방문 진행·사본 보존을 추가합니다. 기존 확정안은1차수로 표시하며 방문 상태는 자동 생성하지 않습니다. **001~018 적용 환경은019만** 실행합니다.
21. [`202610210020_record_search.sql`](../supabase/migrations/202610210020_record_search.sql) 전체를 실행합니다. 기존 RLS의 가시성을 유지하는 종류별 기록 검색 함수를 추가합니다.
22. [`202610210021_next_appointment.sql`](../supabase/migrations/202610210021_next_appointment.sql) 전체를 실행합니다. 한국 시각 기준 다음 약속 읽기 함수를 추가합니다. **001~019 적용 환경은020→021만** 실행하고 각각 Success를 확인합니다. 새 키나 추가 서비스는 필요하지 않습니다.
23. [`202610210022_record_snapshots.sql`](../supabase/migrations/202610210022_record_snapshots.sql) 전체를 실행합니다. 기존 조회 권한의 종류별 읽기 전용 내보내기 함수를 추가합니다. **001~021 적용 환경은022만** 실행하고 Success를 확인합니다. 새 키/계정은 필요하지 않습니다.
24. [`202610210023_device_push.sql`](../supabase/migrations/202610210023_device_push.sql) 전체를 실행합니다. 본인 기기 구독과 등록/해지·테스트 제한 함수를 추가합니다. **001~022 적용 환경은023만** 실행합니다. 기존 기록 권한은 변경하지 않습니다.
25. 자동 기념일 알림을 사용하려면 [`202610220024_scheduled_anniversary_push.sql`](../supabase/migrations/202610220024_scheduled_anniversary_push.sql) 전체를 한 번 실행합니다. 별도 기기 동의·비공개 발송 상태·제한된 예약 역할을 추가하며, 역할은 처음에 로그인 불가입니다. **001~023 적용 환경은024만** 실행합니다. 비밀번호·worker 구성은 [배포 가이드](deployment.md)에서 따로 준비합니다.
26. SQL 실행 성공 후 `/couple`을 엽니다. 한 계정으로 **새 공간 만들기 → 초대 코드 만들기**, 다른 계정으로 **받은 초대 코드 → 초대 수락하기**를 진행합니다. 이미 연결된 두 계정은 반복하지 않습니다. 초대를 받을 사람은 새 공간을 따로 만들지 않습니다.
27. `/`에서 약속·기념일·만난 날 표시를 저장하고 상대 브라우저에서 같은 날짜/월을 확인합니다. `/memories`에서는 날짜와 합성/공유 가능한 사진을 골라 저장하고 상대가 같은 날짜의 앨범을 새로고침합니다. 휴지통 이동/상대 복구와 선택 압축본 내보내기도 확인합니다. `/plans`의 초안 저장→확정→달력 약속 연결, 달력의 동선 기록 저장·상대 조회도 확인합니다. 두 계정 확인에는 일반 창/시크릿 창 등 별도 쿠키 세션을 사용합니다.

약속은 제목·날짜가 필수이고 시간·장소·메모는 선택입니다. 제목은 100자, 장소는 200자, 메모는 2000자까지 저장합니다. 날짜는 2000–2100년, 시간은 한국 시간의 분 단위입니다. 연결 해제·약속 삭제는 아직 제공하지 않습니다.

인증 성공 후 공간 화면에서 연결 오류가 나면 마이그레이션 적용 여부, Supabase Data API 활성화·`public` 스키마 노출 여부, 웹/API가 같은 프로젝트를 사용하는지 확인하세요. `service_role`·secret key를 앱 설정에 추가할 필요는 없습니다.

기념일만 연결 오류가 나면 같은 프로젝트 SQL Editor에서 아래 읽기 전용 쿼리로 테이블 존재 여부를 먼저 확인합니다.

```sql
select to_regclass('public.anniversaries') as anniversary_table;
```

`NULL`이면 테이블이 생성되지 않은 상태입니다. 002 파일을 편집기에 열거나 붙여 넣는 단계에 이어 **전체 SQL 실행(Run)과 Success 결과**까지 확인하세요. 테이블이 이미 존재하면 전체 파일을 다시 실행하기 전에 기존 적용 이력·실행 오류·Data API 스키마 노출을 확인합니다. API는 연결 실패의 HTTP 상태와 고정 오류 분류만 로그에 기록하며 SQL 원문·응답 본문·키를 기록하지 않습니다.

## NAVER 장소 검색 설정 (선택)

설정하지 않아도 로그인·일정·기념일·사진 기능을 사용할 수 있습니다. 검색은 **NAVER API HUB → NAVER 검색 → 지역**을 사용합니다. Maps 지도 표시용 키·Google OAuth ID와 별개이며, Client Secret은 `apps/api/.env`에만 둡니다.

1. [네이버 클라우드 콘솔](https://console.ncloud.com/)에서 한국 리전의 **Application Services → NAVER API HUB → Subscription**을 엽니다. 현재 요금과 적용 약관을 확인하고 동의하는 경우 직접 이용 신청합니다.
2. **Application → Application 등록 → NAVER 검색의 지역**을 선택합니다. 이름은 `WE2DAY-Local`처럼 영문·숫자·하이픈으로 작성합니다.
3. **한도 및 알림**에서 일별/월별 한도를 설정합니다. 두 사람의 초기 사용이라면 일100회·월1,000회를 시작값으로 검토할 수 있습니다. 계정의 다른 Application 합산 사용량과 현재 무료 조건도 확인합니다.
4. Application의 **인증 정보**에서 Client ID와 Client Secret을 확인하고, 기존 Supabase 설정을 유지한 채 `apps/api/.env`에 다음을 추가합니다. 값은 채팅·README·Git에 남기지 않습니다.

```dotenv
WE2DAY_NAVER_SEARCH_ENABLED=true
WE2DAY_NAVER_SEARCH_CLIENT_ID=YOUR_API_HUB_CLIENT_ID
WE2DAY_NAVER_SEARCH_CLIENT_SECRET=YOUR_API_HUB_CLIENT_SECRET
```

5. Docker 사용 시 `docker compose up --detach --wait`로 변경한 환경 변수를 반영합니다. `uvicorn --reload`로 실행 중이라도 `.env` 변경 후에는 API 프로세스를 재시작합니다. 웹에는 NAVER 키를 추가하지 않습니다.
6. 로그인 후 **약속 추가하기 → 네이버 장소 검색 열기**에서 공개 장소 검색어로 확인합니다. 검색 결과는 열람용이며, 약속이나 장기 동선에 자동 저장되지 않습니다. 새 SQL 마이그레이션은 필요하지 않습니다.

검색 API와 Data Lab API의 무료 구간·기간·일/월 호출 제한은 상품별로 확인합니다. 이 앱은 지역 검색을 사용하며 검색어 트렌드·쇼핑 인사이트는 호출하지 않습니다. 키 설정 전에는 `WE2DAY_NAVER_SEARCH_ENABLED=false`를 유지합니다. [상품·요금 안내](https://www.ncloud.com/product/applicationService/NAVERAPIHUB), [콘솔 설정 안내](https://guide.ncloud-docs.com/docs/apihub-application).

현재 검색 약관에는 데이터 저장·파생물 이용·AI 입력 제한과 한정된 임시 캐시 예외가 있습니다. 이 구현은 검색 결과를 서버 DB/파일·브라우저 영구 저장소에 저장하거나 AI에 전달하지 않습니다. 장기 장소 기록·직선 좌표·타임랩스용 데이터는 적용 계약과 출처를 별도로 확인해야 합니다. [NAVER API 약관](https://developers.naver.com/products/terms/), [지역 검색 명세](https://api.ncloud-docs.com/docs/naver-api-hub-search-local).

## NAVER 지도 표시 설정 (선택)

장소 검색용 API HUB 키와 별도인 **NAVER Cloud Platform Maps → Dynamic Map**을 사용합니다. 지도 없이도 수동 플랜과 직접 좌표 기록은 사용할 수 있습니다.

1. [네이버 클라우드 콘솔](https://console.ncloud.com/)의 **Application Services → Maps → Application**에서 이용 신청/애플리케이션 등록을 진행합니다. 해당 계정의 적용 약관·대표 계정 무료 혜택/호출량을 확인한 뒤 신청합니다.
2. API는 **Dynamic Map**만 선택합니다. 이 구현에는 Directions 5·Geocoding·Reverse Geocoding이 필요하지 않습니다.
3. **Web 서비스 URL**에 `http://127.0.0.1:3000`을 등록합니다. localhost도 사용한다면 `http://localhost:3000`을 별도로 등록하고, 운영 도메인이 생기면 HTTPS 주소를 추가합니다. 로그인 사이트 URL과 같은 주소로 접속하세요.
4. 등록한 Maps 애플리케이션의 **Client ID**를 `apps/web/.env`에 추가합니다. API HUB의 검색 키를 재사용하지 않습니다.

```dotenv
WE2DAY_NAVER_MAPS_CLIENT_ID=YOUR_MAPS_CLIENT_ID
```

5. 브라우저용 Client ID는 공개 식별자입니다. **Maps Client Secret은 웹/API `.env`에 추가하지 않습니다.** 대표 계정의 여러 애플리케이션 사용량 합계가 무료 이용량 안에 들도록 일/월 한도를 설정하고 **한도 초과 사용은 허용하지 않음**으로 둡니다. 사용량 알림/호출량도 확인합니다.
6. Docker는 웹 서버가 실행 시 `.env`를 읽도록 `docker compose up --detach --wait web`로 다시 반영합니다. 직접 개발 서버를 사용한다면 웹 프로세스를 재시작합니다.
7. 로그인 후 달력의 오늘/지난 날짜 → **동선 기록 열기 → 지도에서 두 점 지정하기**에서 확인합니다. 출발/도착을 선택해 점을 찍고 직접 정한 장소 이름을 입력한 뒤 **동선 저장**을 누릅니다. SQL006이 필요하며 지도에서 점을 고르기만 해서는 저장되지 않습니다.

SDK는 현재 `ncpKeyId` 매개변수를 사용합니다. `ncpClientId` 기반의 예전 예제와 혼동하지 마세요. 지도 인증 오류는 Dynamic Map 선택·Client ID·허용 Web 서비스 URL을 확인합니다. 지도 로드/인증에 실패해도 작성한 이름·좌표는 유지하며, 지도를 닫았다 열어 다시 시도할 수 있습니다. [SDK 시작 안내](https://navermaps.github.io/maps.js.ncp/docs/tutorial-2-Getting-Started.html), [Maps 신청 안내](https://guide.ncloud-docs.com/docs/application-maps-app-vpc), [공식 무료 혜택 FAQ](https://www.ncloud.com/support/faq/prod/2828).

Maps와 API HUB 검색은 서로 다른 서비스이며 무료 제공·대표 계정 조건·호출 한도도 각각 확인해야 합니다. 사용 시점의 콘솔 조건을 확인하세요. 지도 SDK는 브라우저에서 NAVER 서비스로 직접 연결하며, 직접 지정한 두 점을 지도 위에 표시합니다. 공급자 응답의 저장/재사용 제한을 사용자 기록 저장 승인으로 대체하지 않습니다.

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

인증 검사는 별도 로컬 합성 Auth 서버·실제 FastAPI·Next 서버를 54329/8100/3100 포트에 실행하고 종료합니다. 실제 공급자 로그인을 대체하지 않습니다. 실제 인증 세션을 검사 산출물로 저장하지 않습니다.

`test:database`와 `test:calendar`에는 Docker가 필요합니다. PostgreSQL 17 Alpine, 브라우저 종단 검사에는 PostgREST 14.10 이미지를 사용합니다. 최초 실행은 이미지를 내려받을 수 있습니다. 임시 DB·컨테이너는 검사 후 제거하며 실제 Supabase 프로젝트나 실제 계정을 사용하지 않습니다.

| 검사 | 확인하는 경계 |
| --- | --- |
| `test:api` | 인증·본문 검증·안전한 오류·사용자 JWT 전달. Docker DB 검사는 기본적으로 건너뜀 |
| `test:database` | 실제 SQL·RLS·직접 변경 우회 차단·초대 만료/재사용·동시 수락·수정 충돌 |
| `test:auth` | 합성 인증 공급자와 실제 웹/API로 로그인·쿠키·갱신·로그아웃·방식별 노출 |
| `test:calendar` | 합성 신원 + 실제 Next → FastAPI → PostgREST → PostgreSQL로 두 사용자 공유·권한·응답 유실 재시도·수정 충돌·입력 유지 |
| `test:web` | 테마·월 달력·예시 화면·모바일 레이아웃 회귀 |
| `test:photos` | 합성 이미지/EXIF로 압축·다운로드·메타데이터 제외·파일 거부/취소·모바일 검사 |
| `test:photo-sharing` | 두 합성 계정의 저장/공유·휴지통/상대 복구·30일/삭제 재시도·ZIP 다운로드·만남 메모/충돌. 실제 SQL + Storage HTTP 모형 |
| `test:map-loader` | 외부 호출 없이 SDK 준비 콜백/로드 이벤트·실패 후 재시도 검사. 브라우저·Docker 불필요 |
| `test:plans` | 일회용 DB/합성 두 계정의 동선 저장·공유, SDK 대역의 지연 로드/두 점·직선, 플랜 저장→확정→충돌→재확정→보관/복원. 실제 Maps/API HUB 호출 없음 |
| `test:journey` | 합성 두 계정의 위시→플랜 확정→투데이·미확정 변경 제외→개인 회고 차단/공유/철회→복제 시 달력 보존 |
| `test:organizer` | 합성 계정의 다가오는 약속/기념일·날짜 직접 이동·ICS 실제 다운로드/메모 선택·월간 집계와 빈 월 |
| `test:timeline` | 비용 미정(null)과 명시적 0원·부분 비용 합계를 구분. Docker 불필요 |
| `test:pwa` | 서비스 워커의 문서 오프라인 안내·API/인증/POST 제외·응답 미보관·명시적 업데이트. Docker 불필요 |
| `test:places` | 합성 로그인/공간·실제 웹/API의 미설정·Origin/본문 한도, 직접 작성한 가상 결과로 검색 표시/빈 결과/실패·안전 링크·약속 입력 보존. 실제 NAVER 호출 없음 |

공동 일정·기념일 종단 검사는 웹/API/합성 Auth의 위 포트와 임시 PostgREST의 54330 포트를 사용합니다. 날짜 계산은 첫날/100일·윤일/평년·한국 자정과 원본 보존을 검사하며, 브라우저에서는 두 사용자 기념일 공유·응답 유실 재시도·입력 오류/충돌·취소·두 테마를 확인합니다. 추적 파일은 남기지 않으며, 실제 클라우드·실제 지정 계정·실제 휴대폰 검증은 별도로 진행해야 합니다.

`test:photos`는 Supabase 설정을 비운 별도 Next 서버를 3101 포트에 실행·종료합니다. 개인 사진·실제 계정 없이 합성 이미지와 메타데이터만 검사하며 사진 업로드/공유 검증과 구분합니다.

`test:photo-sharing`은 공동 일정 검사와 같은 일회용 PostgreSQL/PostgREST·합성 Auth·웹/API 포트를 재사용합니다. 파일은 메모리에 보관하는 Storage HTTP 모형이며 실제 PostgreSQL RLS를 호출합니다. 실제 Supabase Storage 서버·클라우드 적용 확인을 대신하지 않습니다. 변경한 기능에 필요한 검사를 선택하고 인증/전체 브라우저 회귀는 기반 변경이나 릴리스 시점에 묶어 실행합니다.

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
