# AI 플래너

[README](../README.md) · [현재 아키텍처](architecture.md)

## 서비스 안에서 코스 작성

데이트 플랜 목록의 **AI 플래너**를 열고 전송 동의를 선택합니다. 날짜·지역·원하는 활동을 입력하면 한국어로 대화하며 코스를 제안합니다. **초안 저장**을 누르면 기존 플랜 목록에 저장됩니다. 저장한 초안을 열어 장소를 검색하고, 내용을 확인한 후 별도로 확정하면 달력에 반영됩니다.

대화는 현재 화면 메모리에만 있습니다. 새 대화·새로고침·페이지 이동 전에 남길 코스를 저장하세요. AI는 기존 일정이나 계정·사진·개인 일정을 자동 조회하지 않습니다. 입력한 대화와 현재 제안만 Cloudflare로 전송합니다. 실제 장소·주소·영업정보는 편집 화면에서 직접 확인하세요. AI가 자동 저장·확정하거나 기존 일정을 변경하지 않습니다.

## 서버 설정

Supabase에 `supabase/migrations/202610260036_ai_planner_budget.sql`을 적용합니다. API 서버의 비밀 환경 파일에 다음 두 항목을 설정하고 API를 재시작합니다. 브라우저 공개 환경변수로 넣지 않습니다.

```dotenv
WE2DAY_CLOUDFLARE_ACCOUNT_ID=
WE2DAY_CLOUDFLARE_API_TOKEN=
```

Cloudflare Workers AI → Use REST API에서 현재 계정에만 Workers AI Read/Edit 권한을 가진 전용 토큰을 발급합니다. 고정 모델은 `@cf/qwen/qwen3-30b-a3b-fp8`입니다. 기존 FastAPI가 REST API로 호출하므로 별도 Worker·D1·R2나 서비스 이전은 필요 없습니다.

Workers Free는 제공량 소진 시 중단합니다. Workers Paid 사용 시 제공량 초과분이 청구될 수 있으므로 계정의 플랜 상태를 직접 확인하세요. 앱은 프로젝트 전체 하루 50회·호출 간격 5초로 제한하며 실패한 요청도 포함합니다. UTC 0시(한국 오전 9시) 초기화이고 서버 재시작 후에도 유지됩니다. 입력은 시스템 지침 포함 16KB, 출력은 최대 2,048토큰입니다. 다른 앱의 Cloudflare 사용량까지 통제하지는 않습니다. 공급자 한도·오류 때 자동 재시도나 다른 유료 모델로 전환하지 않습니다.

## 구성과 한계

브라우저 → 같은 출처의 인증 중계 → FastAPI → DB 사용량 예약 → Workers AI 순서입니다. 답변의 JSON·플랜 형식을 검증한 뒤 화면에 표시합니다. 프롬프트·답변·토큰 원문은 서버 로그/DB에 기록하지 않고 날짜별 호출 횟수만 보관합니다. 초안 저장은 기존 사용자 권한과 요청 재시도 계약을 사용합니다.

첫 버전은 최대 6턴으로 제한하며 완성된 답변을 검증 후 표시합니다. 토큰 스트리밍·대화 영구보관·장기 대화 요약·기존 플랜 자동 편집은 제공하지 않습니다. 향후 필요성과 데이터 정책을 정한 뒤 검토할 확장입니다.

외부 ChatGPT의 [일정·코스 관리 연결](agent-api.md)은 별도 기능입니다. 외부 연결 키나 OAuth 토큰을 내부 AI에 전달하지 않습니다.

공식 참고: [REST 설정](https://developers.cloudflare.com/workers-ai/get-started/rest-api/), [모델](https://developers.cloudflare.com/workers-ai/models/qwen3-30b-a3b-fp8/), [무료 한도](https://developers.cloudflare.com/workers-ai/platform/pricing/).
