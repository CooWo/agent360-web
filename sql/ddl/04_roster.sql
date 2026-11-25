-- ═══════════════════════════════════════════════════════════════
-- 팀 구성(OPS TL) 데이터셋 (ROSTER_DATASET, 기본 `roster`)  — docs/roster/00-설계.md
-- 날짜 규칙 없음: 적용할 때마다 보드 전체가 버전으로 쌓인다.
-- ═══════════════════════════════════════════════════════════════
CREATE SCHEMA IF NOT EXISTS `${PROJECT}.roster` OPTIONS (location = 'asia-northeast3');

-- 기본정보 = 시트 'INFO 자동화 시트' 사본 (열 정의 app/modules/roster/services/info.py, 시트 → BigQuery 동기화)
-- BA용 계산 열(Tenure·퇴사 Tenure·R2 기준 Tenure)은 저장하지 않고 계산한다.
CREATE TABLE IF NOT EXISTS `${PROJECT}.roster.agent_info` (
  emp_id                STRING NOT NULL OPTIONS (description = '사번 (OPS)'),
  name                  STRING NOT NULL OPTIONS (description = '한글명 (OPS)'),
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
  onboarding            STRING OPTIONS (description = '온보딩 날짜'),
  r2_onboarding         STRING,
  universal             STRING OPTIONS (description = 'WFM 입력'),
  incentive_date        STRING OPTIONS (description = '근속 인센티브'),
  joined                STRING OPTIONS (description = '입사일(UHR)'),
  status                STRING OPTIONS (description = '재직정보: 재직자 | 퇴직자'),
  tier_before_universal STRING OPTIONS (description = 'Universal 전 Tier (WFM)'),
  note                  STRING OPTIONS (description = '비고')
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
