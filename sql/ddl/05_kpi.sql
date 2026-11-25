-- KPI 데이터세트 (v12) — 원천: v11-2026.Dynamic 의 BA 에이전트 뷰 4개 (AI BA CHAT 과 같은 정의)
--   final_view_case        → specialist_case_daily  (상담사 × 일자: NPS · Throughput · Reopen · Time to Response · Work/Handle …)
--   final_view             → specialist_time_daily  (상담사 × 일자: SPD · Interactivity · Occupancy · Adherence + 목표값)
--   final_view_kpi_case    → case_kpi_weekly        (주차 × LS · 섹터 · 테뉴어 · 언어: NPS · Resolution · Expense …, 사람 열 없음)
--   final_view_kpi_Survey  → survey_weekly          (주차 × LS · 섹터 · 테뉴어 · 언어: AQS, 사람 열 없음)
-- 표에는 분자·분모 합만 저장한다. 비율은 항상 SUM(분자)/SUM(분모) 로 앱·SQL 에서 계산 (행 비율 평균 금지).
-- 매일 sql/pipeline/kpi_refresh.sql 이 최근 N일(주차 표는 그 기간에 걸린 주차)을 지우고 다시 넣는다.

CREATE SCHEMA IF NOT EXISTS `${PROJECT}.kpi`
OPTIONS (location = 'asia-northeast3', description = 'KPI 마트 — v11-2026.Dynamic 에서 매일 갱신');

CREATE TABLE IF NOT EXISTS `${PROJECT}.kpi.specialist_case_daily` (
  date                DATE   NOT NULL OPTIONS (description = 'ds_metric'),
  week_ending         DATE            OPTIONS (description = 'dim_week_ending (토요일 마감)'),
  ldap                STRING NOT NULL OPTIONS (description = 'dim_specialist_ldap_id (소문자)'),
  lead_ldap           STRING,
  sector              STRING          OPTIONS (description = 'clean_specialist_sector'),
  tenure_group        STRING,
  last_service_group  STRING          OPTIONS (description = 'Clean_Last_Service_Group'),
  excluded            BOOL            OPTIONS (description = 'dim_specialist_is_exclude_from_performance (NULL 은 TRUE 로)'),
  nps_net             FLOAT64, nps_responses FLOAT64,
  solved_volume       FLOAT64 OPTIONS (description = 'Throughput 분자 Cases_Solved_Volume'),
  assignments         FLOAT64 OPTIONS (description = 'cs_specialist_case_assignments_completed — 처리 건수, 여러 지표의 분모'),
  reopens             FLOAT64, case_solves FLOAT64,
  ttresp_min          FLOAT64 OPTIONS (description = 'Time to Response 메시지 인바운드 분 합'),
  msg_sessions        FLOAT64 OPTIONS (description = '메시지 인바운드 세션 수'),
  handle_sec          FLOAT64, work_sec FLOAT64,
  pend_events FLOAT64, recontacts FLOAT64, handoffs FLOAT64, escalations FLOAT64, touches FLOAT64,
  obc_sessions FLOAT64, ownership_changes FLOAT64,
  ttr_days FLOAT64, solved_excl_bot FLOAT64, fcr FLOAT64, closed_excl_claims FLOAT64,
  contacts_no_survey FLOAT64, closed_contacts FLOAT64,
  refreshed_at        TIMESTAMP
)
PARTITION BY date
CLUSTER BY ldap;

CREATE TABLE IF NOT EXISTS `${PROJECT}.kpi.specialist_time_daily` (
  date               DATE   NOT NULL OPTIONS (description = 'ds_specialist_metrics'),
  week_ending        DATE,
  ldap               STRING NOT NULL,
  lead_ldap          STRING,
  sector             STRING,
  tenure_group       STRING,
  excluded           BOOL,
  cases_solved       FLOAT64 OPTIONS (description = 'SPD 분자: cs_specialist_cases_solved'),
  logged_min         FLOAT64 OPTIONS (description = 'Cs_Specialist_Logged_Productive_Minutes'),
  interactive_sec    FLOAT64, work_sec FLOAT64,
  adherence_in_min   FLOAT64, adherence_total_min FLOAT64,
  target_spd         FLOAT64, target_throughput FLOAT64, target_reopen FLOAT64,
  target_ttresp      FLOAT64, target_worktime FLOAT64,
  refreshed_at       TIMESTAMP
)
PARTITION BY date
CLUSTER BY ldap;

CREATE TABLE IF NOT EXISTS `${PROJECT}.kpi.case_kpi_weekly` (
  week_ending DATE NOT NULL, last_service_group STRING, sector STRING, tenure_group STRING, case_language STRING,
  excluded BOOL,
  nps_net FLOAT64, nps_responses FLOAT64, resolved_scores FLOAT64, resolved_responses FLOAT64,
  coupon_usd FLOAT64, loss_usd FLOAT64, issues_closed FLOAT64, mg_expense_issued FLOAT64, mg_expense_usd FLOAT64,
  cases FLOAT64, ownership_changes FLOAT64,
  refreshed_at TIMESTAMP
)
PARTITION BY week_ending;

CREATE TABLE IF NOT EXISTS `${PROJECT}.kpi.survey_weekly` (
  week_ending DATE NOT NULL, last_service_group STRING, sector STRING, tenure_group STRING, case_language STRING,
  excluded BOOL,
  aqs_score FLOAT64, aqs_responses FLOAT64, knowledge_score FLOAT64, knowledge_responses FLOAT64,
  follow_through_score FLOAT64, follow_through_responses FLOAT64, efficiency_score FLOAT64, efficiency_responses FLOAT64,
  refreshed_at TIMESTAMP
)
PARTITION BY week_ending;

CREATE TABLE IF NOT EXISTS `${PROJECT}.kpi.refresh_log` (
  refreshed_at TIMESTAMP NOT NULL, since DATE, case_rows INT64, time_rows INT64, kpi_case_rows INT64, survey_rows INT64,
  max_date DATE
);

-- 상담사 목록 = 상담사 INFO(시트 마트 + 웹 수정분)의 재직자 중 LDAP 있는 사람. 팀 = TL(LDAP), 담당 SV = TL 의 이메일.
CREATE OR REPLACE VIEW `${PROJECT}.kpi.v_agent` AS
WITH info AS (
  SELECT * FROM `${PROJECT}.roster.v_agent_info` WHERE IFNULL(ldap, '') != ''
), sec AS (
  SELECT ldap, ARRAY_AGG(sector ORDER BY date DESC LIMIT 1)[OFFSET(0)] AS sector
  FROM `${PROJECT}.kpi.specialist_time_daily` WHERE sector IS NOT NULL GROUP BY ldap
)
SELECT
  a.emp_id AS agent_id, LOWER(TRIM(a.ldap)) AS ldap, a.name, a.e_name AS name_en, a.email,
  IFNULL(NULLIF(LOWER(TRIM(a.tl_ldap)), ''), '(TL 없음)') AS team,
  IFNULL(tl.name, IFNULL(NULLIF(a.tl_ldap, ''), '(TL 없음)')) AS team_label,
  sec.sector, a.tl_ldap AS sv_ldap, tl.email AS sv_email,
  a.joined AS hire_date, a.onboarding AS onboard_date, a.batch AS cohort, CAST(NULL AS DATE) AS nesting_end,
  a.shift_type, a.location, a.tier, a.type, ARRAY<STRING>[] AS skill_tags,
  '재직' AS status
FROM info a
LEFT JOIN info tl ON LOWER(TRIM(tl.ldap)) = LOWER(TRIM(a.tl_ldap))
LEFT JOIN sec ON sec.ldap = LOWER(TRIM(a.ldap))
WHERE a.status = '재직자'
QUALIFY ROW_NUMBER() OVER (PARTITION BY a.emp_id ORDER BY tl.emp_id) = 1;

-- 상담사 × 일자 KPI (분자·분모 합). 성과 제외(excluded) 행은 뺀다 — BA 에이전트 기본 필터와 같음.
CREATE OR REPLACE VIEW `${PROJECT}.kpi.v_agent_kpi_daily` AS
WITH c AS (
  SELECT date, ldap, ANY_VALUE(tenure_group) tenure_group,
    SUM(nps_net) nps_net, SUM(nps_responses) nps_responses, SUM(solved_volume) solved_volume,
    SUM(assignments) assignments, SUM(reopens) reopens, SUM(case_solves) case_solves,
    SUM(ttresp_min) ttresp_min, SUM(msg_sessions) msg_sessions, SUM(handle_sec) handle_sec, SUM(work_sec) work_sec
  FROM `${PROJECT}.kpi.specialist_case_daily` WHERE excluded = FALSE GROUP BY date, ldap
), t AS (
  SELECT date, ldap, ANY_VALUE(tenure_group) tenure_group, SUM(cases_solved) cases_solved, SUM(logged_min) logged_min,
    MAX(target_spd) target_spd, MAX(target_throughput) target_throughput, MAX(target_reopen) target_reopen,
    MAX(target_ttresp) target_ttresp, MAX(target_worktime) target_worktime
  FROM `${PROJECT}.kpi.specialist_time_daily` WHERE excluded = FALSE GROUP BY date, ldap
)
SELECT a.agent_id, k.*
FROM (
  SELECT COALESCE(c.date, t.date) date, COALESCE(c.ldap, t.ldap) ldap, COALESCE(t.tenure_group, c.tenure_group) tenure_group,
    c.nps_net, c.nps_responses, c.solved_volume, c.assignments, c.reopens, c.case_solves,
    c.ttresp_min, c.msg_sessions, c.handle_sec, c.work_sec,
    t.cases_solved, t.logged_min, t.target_spd, t.target_throughput, t.target_reopen, t.target_ttresp, t.target_worktime
  FROM c FULL OUTER JOIN t ON c.date = t.date AND c.ldap = t.ldap
) k
JOIN `${PROJECT}.kpi.v_agent` a ON a.ldap = k.ldap;
