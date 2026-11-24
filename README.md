# 상담사 360 (Agent 360) — 웹 베이스

SV가 매일 "오늘 누구를 봐야 하는지"를 바로 알 수 있도록, 상담사별 KPI·근태·QA·코칭·교육·인센티브를
한 화면에 모으는 웹입니다. Python(FastAPI) 하나로 만들고, 다른 플랫폼은 쓰지 않습니다.
같은 베이스 위에 Capacity Web 같은 다른 모듈을 폴더 단위로 붙일 수 있습니다.

## 1. 내 PC에서 실행 (샘플 데이터)

```bash
python -m venv .venv
source .venv/bin/activate            
pip install -r requirements-dev.txt
cp .env.example .env                
uvicorn app.main:app --reload
```

| 주소 | 내용 |
|---|---|
| http://localhost:8000/agent360 | 오늘 볼 상담사 (홈) |
| http://localhost:8000/agent360/agents | 상담사 목록 → 상세 |
| http://localhost:8000/agent360/coaching | 코칭 기록 |
| http://localhost:8000/agent360/admin | 관리 (admin만) |
| http://localhost:8000/api/docs | API 문서 (자동 생성) |

화면 오른쪽 위 **사용자 전환** 선택창으로 SV / 매니저 / 뷰어 / 관리자 화면을 바꿔 볼 수 있습니다
(`ENV=local` 일 때만 보이고, 운영(`ENV=prod`)에서는 IAP 로그인만 씁니다).

샘플 데이터에서 코칭 저장·신호 상태 변경을 하면 `sample_data/runtime/` 에 쌓입니다.
처음 상태로 돌리려면 이 폴더를 지우세요. 샘플을 새로 만들려면 `python sample_data/generate.py`.

## 2. 테스트

```bash
pytest -q
```

- `test_permissions_auth.py` 권한 범위·민감 정보·로그인(IAP 헤더/개발 쿠키)
- `test_services.py` 주간 KPI 계산(합÷합), 신호 점수·상태, 코칭 저장·검증·후속
- `test_render.py` 역할별 모든 화면이 오류 없이 그려지는지, screens.json 으로 섹션 조절
- `test_app.py` 실제 웹 경로(HTTP 상태 코드, API, 폼 저장 후 이동)

## 3. 서버 없이 화면 미리보기

```bash
python scripts/preview.py         
```

## 4. BigQuery 연결 (2단계)

자세한 순서는 [docs/2단계-BigQuery연결가이드.md](docs/2단계-BigQuery연결가이드.md).

```powershell
gcloud auth application-default login
python scripts\bq_setup.py ddl    
python scripts\bq_setup.py sample 
python scripts\bq_setup.py check  
# .env: DATA_BACKEND=bigquery, GCP_PROJECT=v12-2027
```

## 5. 배포 (Cloud Run + IAP, 3단계)

```bat
python scripts\deploy.py setup  --project v12-2027     
python scripts\deploy.py deploy --project v12-2027     
python scripts\deploy.py grant  --project v12-2027 
python scripts\bq_setup.py user --project v12-2027
```

접속 허용(IAP)과 앱 안 역할(`agent360.user_roles`)은 따로입니다. 자세한 순서는 [docs/3단계-배포가이드.md](docs/3단계-배포가이드.md).

## 6. 폴더 구조

```
app/
  main.py                  앱 시작점 (모듈 자동 등록, 오류 화면)
  core/                    모든 모듈이 같이 쓰는 기반 — 로그인, 권한, 데이터, 감사 로그, 차트, 템플릿
  modules/agent360/        상담사 360 모듈 (이 폴더만 옮기면 다른 앱에 붙음)
    screens.json           메뉴·화면 구성 (코드 수정 없이 조절)
    services/              계산·규칙 (웹과 무관한 순수 Python)
    views.py               화면에 넘길 데이터 조립
    pages.py / api.py      웹 경로 (화면 / JSON API)
    templates/agent360/    화면 HTML (sections/ = 상세 화면 블록)
  modules/assistant/       AI 질문 (기존 BigQuery 데이터 에이전트 연결) — /assistant
  core/ai/                 데이터 에이전트 호출·응답 해석·안전한 HTML 변환
  static/                  CSS(디자인 토큰), JS
sample_data/               샘플 데이터 + 생성기
sql/ddl/                   BigQuery 테이블 정의
sql/discovery/             실제 데이터(v11-2026) 열 확인 쿼리
scripts/bq_setup.py        BigQuery 테이블·샘플·점검·사용자 등록
scripts/deploy.py          Cloud Run 배포·IAP·접속 허용
tests/                     자동 테스트
docs/개발가이드.md          규칙·화면/모듈 추가 방법
docs/Info테이블-설계.md     상담사 마스터(사번 기준, LDAP 연결) 열 구성·새 Info 시트 형식
```

AI 질문 연결은 [docs/AI연결가이드.md](docs/AI연결가이드.md). 처음 실행은 [docs/1단계-로컬실행가이드.md](docs/1단계-로컬실행가이드.md), 개발 규칙은 [docs/개발가이드.md](docs/개발가이드.md)를 보세요.

## 다음 작업: Capacity Web & AI (기획안 1)

Claude Code 로 진행합니다. `CLAUDE.md` → `docs/capacity/00-분석.md` → `01-설계.md` → `02-작업목록.md` 순서로 읽고, 작업목록의 C-01 부터 하나씩 진행합니다. 원본 기획안은 `docs/plans/기획안1-capacity-web-ai.md`.
