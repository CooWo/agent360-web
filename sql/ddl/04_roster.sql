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
