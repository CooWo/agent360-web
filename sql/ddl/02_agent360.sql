-- ═══════════════════════════════════════════════════════════════
-- 모듈 데이터셋 (MODULE_DATASET, 기본 `agent360`)
-- 앱이 쓰는 테이블(코칭, 신호 상태, 권한, 감사 로그)과 기준값.
-- ═══════════════════════════════════════════════════════════════
CREATE SCHEMA IF NOT EXISTS `${PROJECT}.agent360` OPTIONS (location = 'asia-northeast3');

-- 화면 권한: IAP 로그인 이메일 → 역할·담당 팀. 여기 없는 사용자는 '등록되지 않은 사용자' 화면.
CREATE TABLE IF NOT EXISTS `${PROJECT}.agent360.user_roles` (
  email      STRING NOT NULL,
  name       STRING,
  ldap       STRING OPTIONS (description = '본인 LDAP (선택, dim_agent.sv_ldap 과 연결)'),
  role       STRING NOT NULL OPTIONS (description = 'admin | manager | wfm | sv | viewer'),
  teams      ARRAY<STRING>   OPTIONS (description = 'sv/viewer 가 볼 팀. manager/admin 은 비워도 전체'),
  active     BOOL   NOT NULL,
  updated_at TIMESTAMP,
  updated_by STRING
);

CREATE TABLE IF NOT EXISTS `${PROJECT}.agent360.fact_coaching` (
  coaching_id    STRING NOT NULL,
  agent_id       STRING NOT NULL,
  sv_email       STRING NOT NULL,
  date           DATE   NOT NULL,
  issue_type     STRING NOT NULL,
  summary        STRING,
  agreed_action  STRING,
  follow_up_date DATE,
  done           BOOL   NOT NULL,
  done_at        DATE,
  done_by        STRING,
  raw_note       STRING OPTIONS (description = '원문 메모 (민감)'),
  created_at     TIMESTAMP
)
PARTITION BY date
CLUSTER BY agent_id;

-- 코칭 폼 (기존 Coaching Form 양식) 항목 — 있으면 통과
ALTER TABLE `${PROJECT}.agent360.fact_coaching`
  ADD COLUMN IF NOT EXISTS priority STRING OPTIONS (description = 'P0~P3 (카테고리로 정해짐)'),
  ADD COLUMN IF NOT EXISTS area_detail STRING OPTIONS (description = 'Areas Where Coaching is needed — 세부'),
  ADD COLUMN IF NOT EXISTS desired_outcome STRING OPTIONS (description = 'Desired Outcomes of Coaching'),
  ADD COLUMN IF NOT EXISTS case_number STRING OPTIONS (description = 'Case Number'),
  ADD COLUMN IF NOT EXISTS root_cause STRING OPTIONS (description = 'Root cause (근본 원인)'),
  ADD COLUMN IF NOT EXISTS agent_comment STRING OPTIONS (description = "Agent's Comments"),
  ADD COLUMN IF NOT EXISTS agent_ack BOOL OPTIONS (description = "Agent's Signature (상담사 확인)");

-- 매일 배치(스케줄 쿼리/프로시저)가 as_of 날짜로 채우고, 앱은 status 만 바꾼다.
CREATE TABLE IF NOT EXISTS `${PROJECT}.agent360.mart_signals` (
  signal_id  STRING NOT NULL,
  as_of      DATE   NOT NULL,
  agent_id   STRING NOT NULL,
  type       STRING NOT NULL OPTIONS (description = 'signal_rules.rule'),
  label      STRING,
  severity   STRING OPTIONS (description = '상 | 중 | 하'),
  score      INT64  OPTIONS (description = '상 3 / 중 2 / 하 1'),
  evidence   STRING OPTIONS (description = '근거 문장 (예: 최근 2주 AHT 팀 평균 대비 +18%)'),
  status     STRING OPTIONS (description = '미확인 | 확인 | 코칭 예정 | 해당 없음'),
  status_by  STRING,
  status_at  TIMESTAMP
)
PARTITION BY as_of
CLUSTER BY agent_id;

CREATE TABLE IF NOT EXISTS `${PROJECT}.agent360.signal_rules` (
  rule        STRING NOT NULL,
  label       STRING,
  severity    STRING,
  description STRING,
  params      JSON   OPTIONS (description = '기준값. 예: {"weeks": 2, "pct": 15}'),
  updated_at  TIMESTAMP,
  updated_by  STRING
);

CREATE TABLE IF NOT EXISTS `${PROJECT}.agent360.issue_types` (
  issue_type STRING NOT NULL,
  sort_order INT64,
  active     BOOL NOT NULL
);

CREATE TABLE IF NOT EXISTS `${PROJECT}.agent360.audit_log` (
  ts          TIMESTAMP NOT NULL,
  actor       STRING    NOT NULL,
  role        STRING,
  action      STRING    NOT NULL OPTIONS (description = 'view_sensitive | coaching_create | coaching_complete | signal_status | rule_update'),
  target_type STRING,
  target_id   STRING,
  detail      JSON
)
PARTITION BY DATE(ts)
OPTIONS (partition_expiration_days = 1095);

-- 데이터 변경 묶음 (미리보기 → 승인 → 되돌리기, app/core/changes.py). doc = ChangeSet 전체 JSON.
CREATE TABLE IF NOT EXISTS `${PROJECT}.agent360.change_log` (
  change_id  STRING    NOT NULL,
  kind       STRING    NOT NULL OPTIONS (description = '예: capacity.assumptions'),
  status     STRING    NOT NULL OPTIONS (description = 'preview | applied | reverted | discarded'),
  actor      STRING    NOT NULL,
  created_at TIMESTAMP NOT NULL,
  doc        STRING    NOT NULL,
  updated_at TIMESTAMP
);

-- QA · 코칭 (코칭 대시보드 내보내기 zip 을 웹에서 올림). 올릴 때마다 새 묶음(change_id), 화면은 가장 최근 묶음.
CREATE TABLE IF NOT EXISTS `${PROJECT}.agent360.qa_coaching` (
  row_id            STRING NOT NULL,
  change_id         STRING NOT NULL OPTIONS (description = '올리기 한 번 = 변경 하나 (change_log)'),
  agent_id          STRING NOT NULL OPTIONS (description = '영문 이름으로 찾은 사번'),
  full_name         STRING          OPTIONS (description = '내보내기의 영문 이름'),
  evaluations       INT64, qa_avg FLOAT64, coaching_sessions INT64, coach STRING,
  grade_bad INT64, grade_ni INT64, grade_good INT64, grade_very_good INT64,
  source_file       STRING,
  uploaded_at       TIMESTAMP,
  uploaded_by       STRING,
  active            BOOL
);
