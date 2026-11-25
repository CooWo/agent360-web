-- ═══════════════════════════════════════════════════════════════
-- 팀 구성(OPS TL) 데이터셋 (ROSTER_DATASET, 기본 `roster`)  — docs/roster/00-설계.md
-- 날짜 규칙 없음: 적용할 때마다 보드 전체가 버전으로 쌓인다.
-- ═══════════════════════════════════════════════════════════════
CREATE SCHEMA IF NOT EXISTS `${PROJECT}.roster` OPTIONS (location = 'asia-northeast3');

-- 기본정보 = Standard INFO TABLE 사본 (시트 → BigQuery 동기화)
CREATE TABLE IF NOT EXISTS `${PROJECT}.roster.agent_info` (
  emp_id    STRING NOT NULL OPTIONS (description = 'UBASE ID (사번)'),
  airbnb_id STRING,
  name      STRING NOT NULL,
  e_name    STRING,
  ldap      STRING,
  joined    STRING OPTIONS (description = '입사일 YYYY-MM-DD'),
  role      STRING OPTIONS (description = '직무'),
  market    STRING,
  `left`    STRING OPTIONS (description = '퇴사일 YYYY-MM-DD (없으면 빈 값)')
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
