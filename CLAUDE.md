# CLAUDE.md — 작업 안내 (Claude Code 용)

이 저장소는 유베이스 운영용 사내 웹입니다. FastAPI 하나에 **모듈**을 붙이는 구조입니다.
- `agent360` — 상담사 360 (운영 중, 샘플 데이터)
- `assistant` — AI 질문 (기존 BigQuery 데이터 에이전트 연결, 운영 중)
- `capacity` — **Capacity Web & AI (지금 만드는 것)** → `docs/capacity/` 를 먼저 읽을 것

## 지금 할 일

1. `docs/plans/기획안1-capacity-web-ai.md` (원본 기획안) 훑어보기
2. `docs/capacity/00-분석.md` → `01-설계.md` → `02-작업목록.md` 순서로 읽기
3. `02-작업목록.md` 의 **다음 미완료 작업(C-xx) 하나만** 진행 → 완료 기준 확인 → 커밋
4. 막히는 결정(데이터 원천, 계산식, 역할)은 추측하지 말고 `00-분석.md` 의 "확인 필요"에 적고 사용자에게 묻기

## 명령 (Windows PowerShell 기준, 사용자는 Windows)

```powershell
cd C:\dev\agent360-web
.\.venv\Scripts\Activate.ps1          # cmd 라면 .venv\Scripts\activate.bat
pip install -r requirements-dev.txt
pytest -q                              # 반드시 전부 통과 후 커밋
uvicorn app.main:app --reload          # http://localhost:8000 , 오른쪽 위 사용자 전환(ENV=local)
python scripts/preview.py              # 서버 없이 역할별 화면 HTML → preview/
python scripts/bq_setup.py ddl|sample|check|user --project v12-2027
python scripts/deploy.py deploy --project v12-2027   # 배포는 사용자가 요청할 때만
```
- `.env` 는 커밋 금지 (`.env.example` 에 키만). 사용자 PC 의 `.env` 는 `DATA_BACKEND=bigquery` 일 수 있음 → 테스트는 conftest 가 sample 로 고정.
- PowerShell 은 `cd /d` 불가, 스크립트 실행은 `.\` 접두어 필요.

## 구조 규칙 (자세한 것은 `docs/개발가이드.md`)

| 층 | 위치 | 하는 일 | 하지 않는 일 |
|---|---|---|---|
| 데이터 | `app/core/data/`, `app/modules/<m>/data/` | 읽기·쓰기, 팀/계정 범위 필터 | 계산, 권한 판단 |
| 서비스 | `app/modules/<m>/services/` | 계산·규칙·검증·권한·감사 로그 (순수 Python) | HTTP, HTML |
| 뷰 | `app/modules/<m>/views.py` | 화면 하나의 데이터를 dict 로 조립 | HTTP, SQL |
| 라우터 | `pages.py`(화면), `api.py`(JSON) | 요청 → 뷰/서비스 → 응답 | 계산, SQL |
| 템플릿 | `app/modules/<m>/templates/<m>/` | 그리기 | 계산 |
| 설정 | `screens.json`, `.env` | 메뉴·화면·기준값 | — |

- 새 모듈 = `app/modules/<이름>/` 폴더 + `module.py` 의 `build(with_routers)`. `main.py` 는 고치지 않는다 (자동 등록).
- `pages.py`/`api.py` 만 FastAPI 를 import. 서비스·뷰·템플릿은 FastAPI 없이 테스트 가능해야 한다.
- 데이터 백엔드는 **sample(JSON) 과 bigquery 두 구현**을 항상 같이 만든다. 테스트는 sample 로.
- BigQuery SQL 은 **매개변수(@name)만**. 문자열로 값 끼워 넣기 금지. 쓰기는 DML (streaming insert 금지).
- 화면: 외부 JS/CSS 라이브러리 금지. 차트는 `app/core/charts.py` 처럼 서버에서 SVG. 색·간격은 `static/css/tokens.css` 변수만.
- 화면 문구는 쉬운 한국어. 숫자는 단위와 비교 대상을 같이 ("팀 평균 대비 +18%").
- 권한: `app/core/permissions.py` 의 `User` 로만 판단. 메뉴 숨김은 편의일 뿐, 서비스에서 막는다.
- 쓰기·민감 조회는 `app/core/audit.py` 의 `audit()` 로 기록.
- AI 가 데이터를 바꾸는 기능은 **미리보기 → 사용자 승인 → 저장 → 되돌리기** 순서를 지킨다 (기획안 설계 원칙 2).
- 숫자는 항상 SQL/계산 엔진 결과에서. LLM 이 숫자를 만들지 않게 한다.

## 테스트·완료 기준

- 작업마다 `tests/test_<모듈>_*.py` 추가. 계산은 손으로 검산한 예제로 단위 테스트.
- 화면은 `tests/test_render.py` 방식(뷰 + 템플릿 렌더)으로 역할별 렌더 테스트.
- BigQuery 쪽은 `tests/test_bigquery_contract.py` 처럼 가짜 클라이언트로 SQL 매개변수·DDL 열 일치 확인.
- `pytest -q` 전부 통과, `python scripts/preview.py` 오류 없음 → 커밋.

## 커밋·브랜치

- 저장소: GitHub `CooWo/agent360-web` (비공개), 기본 브랜치 `main`.
- 작업 하나 = 커밋 하나 이상, 메시지 첫 줄에 작업 번호: `C-05 계산 엔진: 가용 FTE·기수 흐름`.
- `02-작업목록.md` 의 해당 작업 상태를 `[x]` 로 바꾸고 같은 커밋에 포함.
- push·배포·GCP 권한 변경·BigQuery 테이블 재생성(`--recreate`)은 사용자에게 먼저 묻는다.

## 하지 말 것

- 비밀값(키·토큰·.env) 커밋, 실제 개인정보를 샘플 데이터에 넣기
- 기존 `agent360` 동작 깨기 (테스트로 확인)
- 기획안 범위 밖 기능 추가, UI 레벨 3(코드 자체 수정) 구현
