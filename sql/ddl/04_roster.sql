-- ═══════════════════════════════════════════════════════════════
-- 팀 구성(OPS TL) 데이터셋 (ROSTER_DATASET, 기본 `roster`)  — docs/roster/00-설계.md
-- 날짜 규칙 없음: 적용할 때마다 보드 전체가 버전으로 쌓인다.
-- ═══════════════════════════════════════════════════════════════
CREATE SCHEMA IF NOT EXISTS `${PROJECT}.roster` OPTIONS (location = 'asia-northeast3');

-- ── INFO (기본정보) ── 시트 'INFO 자동화 시트' → info_raw(받은 그대로, 쌓음) → mart_agent_info(정리, 사번당 한 줄)
-- 불러오기: python scripts/info_sync.py --project v12-2027   (정리 규칙: app/modules/roster/services/info.py)

-- 받은 그대로 (불러올 때마다 load_id 로 한 묶음씩 쌓임, 3년 보관)
CREATE TABLE IF NOT EXISTS `${PROJECT}.roster.info_raw` (
  load_id               STRING    NOT NULL,
  loaded_at             TIMESTAMP NOT NULL,
  row_no                INT64     NOT NULL OPTIONS (description = '데이터 순서 (머리글 아래 1부터)'),
  emp_id                STRING,
  name                  STRING,
  e_name                STRING,
  email                 STRING,
  airbnb_id             STRING,
  batch                 STRING,
  shift_type            STRING,
  location              STRING,
  tl_ldap               STRING,
  type                  STRING,
  tier                  STRING,
  ldap                  STRING,
  fte                   STRING,
  onboarding            STRING,
  r2_onboarding         STRING,
  universal             STRING,
  incentive_date        STRING,
  joined                STRING,
  status                STRING,
  tier_before_universal STRING,
  note                  STRING,
  raw_json              STRING    OPTIONS (description = '원래 행 전체 (A열~Y열)')
)
PARTITION BY DATE(loaded_at)
OPTIONS (partition_expiration_days = 1095);

-- 정리된 지금 상태 (불러올 때마다 통째로 바뀜)
CREATE TABLE IF NOT EXISTS `${PROJECT}.roster.mart_agent_info` (
  emp_id                STRING NOT NULL OPTIONS (description = '사번 (OPS)'),
  name                  STRING OPTIONS (description = '한글명 (OPS)'),
  e_name                STRING OPTIONS (description = 'Name (OPS)'),
  email                 STRING,
  airbnb_id             STRING,
  batch                 STRING OPTIONS (description = 'CE/SR1 Batch (OPS)'),
  shift_type            STRING,
  location              STRING,
  tl_ldap               STRING OPTIONS (description = 'TL LDAP (BA: OPS 시트 자동반영 + 팀장 수정)'),
  type                  STRING,
  tier                  STRING,
  ldap                  STRING,
  fte                   STRING,
  onboarding            DATE OPTIONS (description = '온보딩 날짜'),
  r2_onboarding         DATE OPTIONS (description = 'R2 온보딩'),
  universal             STRING OPTIONS (description = 'WFM 입력'),
  incentive_date        DATE OPTIONS (description = '근속 인센티브'),
  joined                DATE OPTIONS (description = '입사일(UHR)'),
  status                STRING OPTIONS (description = '재직정보: 재직자 | 퇴직자'),
  tier_before_universal STRING OPTIONS (description = 'Universal 전 Tier (WFM)'),
  note                  STRING OPTIONS (description = '비고'),
  dates_ok              BOOL      OPTIONS (description = '날짜 칸이 모두 날짜로 읽혔거나 비었으면 TRUE'),
  load_id               STRING    OPTIONS (description = '어느 불러오기에서 왔는지 (info_raw.load_id)'),
  loaded_at             TIMESTAMP
);

-- 불러오기 기록
CREATE TABLE IF NOT EXISTS `${PROJECT}.roster.info_loads` (
  load_id       STRING    NOT NULL,
  loaded_at     TIMESTAMP NOT NULL,
  loaded_by     STRING,
  source        STRING    OPTIONS (description = '시트 ID / 탭'),
  rows_read     INT64,
  rows_mart     INT64,
  dropped_no_id INT64     OPTIONS (description = '사번 없어서 뺀 행'),
  duplicates    INT64     OPTIONS (description = '같은 사번 중복 행'),
  issues        INT64     OPTIONS (description = '날짜를 읽지 못한 칸 등'),
  issue_json    STRING
);

-- 적용된 보드 버전. doc = [{"tl","shift","emp_id","name","e_name","display_name","date","note"}, ...]
CREATE TABLE IF NOT EXISTS `${PROJECT}.roster.board_versions` (
  version_id STRING    NOT NULL,
  saved_at   TIMESTAMP NOT NULL,
  saved_by   STRING    NOT NULL,
  row_count  INT64,
  doc        STRING    NOT NULL
);

-- 사용자별 작업 중 초안
CREATE TABLE IF NOT EXISTS `${PROJECT}.roster.board_drafts` (
  email    STRING    NOT NULL,
  saved_at TIMESTAMP NOT NULL,
  doc      STRING    NOT NULL
);

-- 이미 만든 표에 열 추가 (CREATE IF NOT EXISTS 는 열을 더하지 않음)
ALTER TABLE `${PROJECT}.roster.mart_agent_info` ADD COLUMN IF NOT EXISTS dates_ok BOOL;

-- 웹에서 고친 칸 (상담사 INFO 화면 → 미리보기 → 저장). 시트를 다시 불러와도 남는다. 되돌리면 active = FALSE.
CREATE TABLE IF NOT EXISTS `${PROJECT}.roster.info_edits` (
  edit_id     STRING    NOT NULL,
  change_id   STRING    NOT NULL OPTIONS (description = 'agent360.change_log 의 변경 묶음'),
  emp_id      STRING    NOT NULL,
  field       STRING    NOT NULL OPTIONS (description = 'mart_agent_info 의 열 이름'),
  value       STRING    OPTIONS (description = '저장 값 (날짜는 YYYY-MM-DD)'),
  is_new      BOOL      OPTIONS (description = '웹에서 새로 등록한 사람'),
  edited_at   TIMESTAMP NOT NULL,
  edited_by   STRING    NOT NULL,
  active      BOOL      NOT NULL,
  reverted_at TIMESTAMP,
  reverted_by STRING
);

-- 지금 상태 = 시트 마트 + 웹 수정분 (같은 칸은 가장 최근 수정). BI·다른 모듈은 이 뷰를 읽는다.
-- 팀 구성 (시트 'OPS TL') — 불러올 때마다 통째로 바꾼다. 상담사 360 의 팀(TL 한글 이름)·명단 기준.
CREATE TABLE IF NOT EXISTS `${PROJECT}.roster.team_roster` (
  tl_name      STRING NOT NULL OPTIONS (description = 'TL 한글 이름 (시트 블록 위 이름)'),
  sort_order   INT64           OPTIONS (description = '시트 왼쪽부터 TL 순서'),
  row_order    INT64           OPTIONS (description = '시트 위에서부터 줄 순서 (TL 안 순서 · 시트에 다시 쓸 때 그대로)'),
  shift        STRING,
  emp_id       STRING NOT NULL,
  name         STRING          OPTIONS (description = '한글 이름'),
  e_name       STRING,
  display_name STRING,
  load_id      STRING,
  loaded_at    TIMESTAMP,
  loaded_by    STRING,
  source       STRING
);

ALTER TABLE `${PROJECT}.roster.team_roster` ADD COLUMN IF NOT EXISTS row_order INT64;

CREATE OR REPLACE VIEW `${PROJECT}.roster.v_agent_info` AS
WITH latest AS (
  SELECT * FROM `${PROJECT}.roster.info_edits` WHERE active
  QUALIFY ROW_NUMBER() OVER (PARTITION BY emp_id, field ORDER BY edited_at DESC, edit_id DESC) = 1
), w AS (
  SELECT e.emp_id,
    ANY_VALUE(IF(e.field = 'name', e.value, NULL)) AS name,
    ANY_VALUE(IF(e.field = 'e_name', e.value, NULL)) AS e_name,
    ANY_VALUE(IF(e.field = 'email', e.value, NULL)) AS email,
    ANY_VALUE(IF(e.field = 'airbnb_id', e.value, NULL)) AS airbnb_id,
    ANY_VALUE(IF(e.field = 'batch', e.value, NULL)) AS batch,
    ANY_VALUE(IF(e.field = 'shift_type', e.value, NULL)) AS shift_type,
    ANY_VALUE(IF(e.field = 'location', e.value, NULL)) AS location,
    ANY_VALUE(IF(e.field = 'tl_ldap', e.value, NULL)) AS tl_ldap,
    ANY_VALUE(IF(e.field = 'type', e.value, NULL)) AS type,
    ANY_VALUE(IF(e.field = 'tier', e.value, NULL)) AS tier,
    ANY_VALUE(IF(e.field = 'ldap', e.value, NULL)) AS ldap,
    ANY_VALUE(IF(e.field = 'fte', e.value, NULL)) AS fte,
    ANY_VALUE(IF(e.field = 'onboarding', e.value, NULL)) AS onboarding,
    ANY_VALUE(IF(e.field = 'r2_onboarding', e.value, NULL)) AS r2_onboarding,
    ANY_VALUE(IF(e.field = 'universal', e.value, NULL)) AS universal,
    ANY_VALUE(IF(e.field = 'incentive_date', e.value, NULL)) AS incentive_date,
    ANY_VALUE(IF(e.field = 'joined', e.value, NULL)) AS joined,
    ANY_VALUE(IF(e.field = 'status', e.value, NULL)) AS status,
    ANY_VALUE(IF(e.field = 'tier_before_universal', e.value, NULL)) AS tier_before_universal,
    ANY_VALUE(IF(e.field = 'note', e.value, NULL)) AS note,
    LOGICAL_OR(e.is_new) AS is_new
  FROM latest e GROUP BY e.emp_id
)
SELECT
  COALESCE(m.emp_id, w.emp_id) AS emp_id,
  COALESCE(w.name, m.name) AS name,
  COALESCE(w.e_name, m.e_name) AS e_name,
  COALESCE(w.email, m.email) AS email,
  COALESCE(w.airbnb_id, m.airbnb_id) AS airbnb_id,
  COALESCE(w.batch, m.batch) AS batch,
  COALESCE(w.shift_type, m.shift_type) AS shift_type,
  COALESCE(w.location, m.location) AS location,
  COALESCE(w.tl_ldap, m.tl_ldap) AS tl_ldap,
  COALESCE(w.type, m.type) AS type,
  COALESCE(w.tier, m.tier) AS tier,
  COALESCE(w.ldap, m.ldap) AS ldap,
  COALESCE(w.fte, m.fte) AS fte,
  IF(w.onboarding IS NOT NULL, SAFE.PARSE_DATE('%Y-%m-%d', NULLIF(w.onboarding, '')), m.onboarding) AS onboarding,
  IF(w.r2_onboarding IS NOT NULL, SAFE.PARSE_DATE('%Y-%m-%d', NULLIF(w.r2_onboarding, '')), m.r2_onboarding) AS r2_onboarding,
  COALESCE(w.universal, m.universal) AS universal,
  IF(w.incentive_date IS NOT NULL, SAFE.PARSE_DATE('%Y-%m-%d', NULLIF(w.incentive_date, '')), m.incentive_date) AS incentive_date,
  IF(w.joined IS NOT NULL, SAFE.PARSE_DATE('%Y-%m-%d', NULLIF(w.joined, '')), m.joined) AS joined,
  COALESCE(w.status, m.status) AS status,
  COALESCE(w.tier_before_universal, m.tier_before_universal) AS tier_before_universal,
  COALESCE(w.note, m.note) AS note,
  m.dates_ok,
  w.emp_id IS NOT NULL AS web_edited,
  m.emp_id IS NULL AS web_only
FROM `${PROJECT}.roster.mart_agent_info` m
FULL OUTER JOIN w ON w.emp_id = m.emp_id;

-- ── 근태 ── 원본 시트 'Schedule KR' → common.fact_attendance (바뀐 칸만 MERGE). 불러오기 기록:
-- 예약 실행: python -m app.modules.roster.attendance_job  (Cloud Run 작업 + Cloud Scheduler, deploy.py attendance-job)
CREATE TABLE IF NOT EXISTS `${PROJECT}.roster.attendance_loads` (
  load_id   STRING    NOT NULL,
  loaded_at TIMESTAMP NOT NULL,
  loaded_by STRING    OPTIONS (description = '누른 사람 이메일 또는 scheduler'),
  source    STRING    OPTIONS (description = '시트 ID / 탭'),
  since     DATE,
  until     DATE,
  agents    INT64     OPTIONS (description = '읽은 상담사 수'),
  cells     INT64     OPTIONS (description = '기간 안 근태 칸 수'),
  upserts   INT64     OPTIONS (description = '새로 넣거나 고친 칸'),
  deletes   INT64     OPTIONS (description = '시트에서 지워져 뺀 칸'),
  by_status STRING    OPTIONS (description = 'JSON {상태: 칸 수}'),
  unknown   STRING    OPTIONS (description = 'JSON [[모르는 값, 개수], ...] → 기타')
)
PARTITION BY DATE(loaded_at)
OPTIONS (partition_expiration_days = 1095);
