-- ═══════════════════════════════════════════════════════════════
-- 공통 데이터셋 (COMMON_DATASET, 기본 `common`)
-- 상담사 마스터 + 사실 데이터. Capacity Web 등 다른 모듈도 같이 읽는다.
-- 실행: python scripts/bq_setup.py ddl --project <프로젝트>
-- ═══════════════════════════════════════════════════════════════
CREATE SCHEMA IF NOT EXISTS `${PROJECT}.common` OPTIONS (location = 'asia-northeast3');

-- 상담사 마스터 (Info 테이블): 사번 1명 1행. 화면 조회·연결 키는 사번(agent_id),
-- LDAP 는 상담 데이터(v11 final_view 등, ldap 기준)를 사번으로 바꿔 붙일 때 쓰는 연결 열.
-- 원천: 별도 Info 시트 → (외부 테이블) → 이 표로 매일 갱신. 열 구성은 docs/Info테이블-설계.md
CREATE TABLE IF NOT EXISTS `${PROJECT}.common.dim_agent` (
  agent_id     STRING NOT NULL OPTIONS (description = '사번 (기본 키, 상담사 찾기·조회 기준)'),
  ldap         STRING NOT NULL OPTIONS (description = 'LDAP (예: ub_gildong_hong). 상담 데이터 연결 키, 중복 금지'),
  name         STRING          OPTIONS (description = '한글 이름'),
  name_en      STRING          OPTIONS (description = '영문 이름'),
  email        STRING          OPTIONS (description = '회사 이메일 (@ubase.co.kr)'),
  team         STRING NOT NULL OPTIONS (description = '팀 (SV 권한 범위 단위)'),
  sector       STRING          OPTIONS (description = '큰 묶음 (예: R1, R2, US)'),
  channel      STRING          OPTIONS (description = '채널 (Voice | Async | …)'),
  sv_ldap      STRING          OPTIONS (description = '담당 SV(TL) LDAP'),
  sv_email     STRING          OPTIONS (description = '담당 SV 로그인 이메일'),
  hire_date    DATE            OPTIONS (description = '입사일'),
  onboard_date DATE            OPTIONS (description = '온보딩(현장 투입) 날짜'),
  cohort       STRING          OPTIONS (description = '입사 기수 / Batch'),
  nesting_end  DATE            OPTIONS (description = '네스팅 종료일'),
  shift_type   STRING          OPTIONS (description = 'Flex | Fixed | 단축 …'),
  location     STRING          OPTIONS (description = 'WFH | WFO'),
  skill_tags   ARRAY<STRING>,
  status       STRING          OPTIONS (description = '재직 | 휴직 | 퇴사 | 확인필요'),
  updated_at   TIMESTAMP
)
CLUSTER BY team, agent_id;

CREATE TABLE IF NOT EXISTS `${PROJECT}.common.fact_kpi_daily` (
  agent_id       STRING NOT NULL,
  date           DATE   NOT NULL,
  handled        INT64   OPTIONS (description = '처리 건수'),
  aht_sec        FLOAT64 OPTIONS (description = '평균 처리 시간(초). 주간은 handled 가중 평균'),
  nps_responses  INT64,
  nps_net        INT64   OPTIONS (description = '추천-비추천 수. NPS = SUM(nps_net)/SUM(nps_responses)*100'),
  productivity   FLOAT64
)
PARTITION BY date
CLUSTER BY agent_id;

CREATE TABLE IF NOT EXISTS `${PROJECT}.common.fact_attendance` (
  agent_id STRING NOT NULL,
  date     DATE   NOT NULL,
  status   STRING OPTIONS (description = '정상 | 지각 | 조퇴 | 결근 | 휴가')
)
PARTITION BY date
CLUSTER BY agent_id;

CREATE TABLE IF NOT EXISTS `${PROJECT}.common.fact_qa` (
  qa_id       STRING NOT NULL,
  agent_id    STRING NOT NULL,
  date        DATE   NOT NULL,
  score       FLOAT64,
  error_types ARRAY<STRING>
)
PARTITION BY date
CLUSTER BY agent_id;

CREATE TABLE IF NOT EXISTS `${PROJECT}.common.fact_training` (
  agent_id     STRING NOT NULL,
  course       STRING,
  kind         STRING OPTIONS (description = '필수 | 선택 | 재교육'),
  completed_on DATE
)
CLUSTER BY agent_id;

-- 민감 정보: 화면에서 담당 SV/매니저만 보이고, 열람 시 audit_log 에 남는다.
CREATE TABLE IF NOT EXISTS `${PROJECT}.common.fact_incentive` (
  agent_id STRING NOT NULL,
  month    STRING NOT NULL OPTIONS (description = 'YYYY-MM'),
  grade    STRING,
  note     STRING
)
CLUSTER BY agent_id;
