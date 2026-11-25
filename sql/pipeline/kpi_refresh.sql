-- KPI 매일 갱신: v11-2026.Dynamic → ${PROJECT}.kpi  (BigQuery 예약 쿼리로 매일 실행, 수동: scripts/bq_setup.py kpi-refresh)
-- 최근 ${DAYS}일(주차 표는 그 기간에 걸린 주차 전체)을 지우고 다시 넣는다. 한 트랜잭션이라 중간 상태가 보이지 않는다.
-- 지표 정의는 AI BA CHAT 에이전트 안내문 5장과 같다 (여기서는 분자·분모 합만 만든다).
DECLARE since DATE DEFAULT DATE_SUB(CURRENT_DATE('Asia/Seoul'), INTERVAL ${DAYS} DAY);
DECLARE since_week DATE DEFAULT DATE_ADD(DATE_TRUNC(since, WEEK(SUNDAY)), INTERVAL 6 DAY);   -- since 가 속한 주의 토요일

BEGIN TRANSACTION;

DELETE FROM `${PROJECT}.kpi.specialist_case_daily` WHERE date >= since;
INSERT INTO `${PROJECT}.kpi.specialist_case_daily`
SELECT
  ds_metric, ANY_VALUE(dim_week_ending), LOWER(TRIM(dim_specialist_ldap_id)), ANY_VALUE(LOWER(dim_specialist_lead_ldap_id)),
  clean_specialist_sector, dim_specialist_tenure_group, Clean_Last_Service_Group,
  IFNULL(dim_specialist_is_exclude_from_performance, TRUE),
  SUM(cs_customer_nps_net_promoters), SUM(cs_customer_nps_responses),
  SUM(Cases_Solved_Volume), SUM(cs_specialist_case_assignments_completed),
  SUM(cs_case_reopen), SUM(cs_specialist_case_solves),
  SUM(cs_interaction_session_time_to_specialist_response_minutes_messaging_inbound),
  SUM(cs_interaction_specialist_sessions_messaging_inbound),
  SUM(Cs_Interaction_Session_Handle_Seconds), SUM(CS_Work_Time_For_Cases_in_Seconds),
  SUM(cs_specialist_pend_events), SUM(cs_interaction_specialist_recontacts), SUM(cs_specialist_transfer_handoffs),
  SUM(cs_specialist_transfer_escalations), SUM(cs_work_event_distinct_interactions),
  SUM(cs_interaction_specialist_sessions_phone_outbound), SUM(cs_specialist_ownership_changes),
  SUM(cs_specialist_cases_solved_days_to_resolution), SUM(cs_cases_solved_excluding_bot_only),
  SUM(cs_cases_closed_ops_first_contact_resolution), SUM(cs_cases_closed_excluding_claims),
  SUM(Cs_specialist_closed_case_contacts_no_survey), SUM(Cs_specialist_closed_case_contacts),
  CURRENT_TIMESTAMP()
FROM `v11-2026.Dynamic.final_view_case`
WHERE ds_metric >= since AND dim_specialist_ldap_id IS NOT NULL
GROUP BY ds_metric, LOWER(TRIM(dim_specialist_ldap_id)), clean_specialist_sector, dim_specialist_tenure_group,
         Clean_Last_Service_Group, IFNULL(dim_specialist_is_exclude_from_performance, TRUE);

DELETE FROM `${PROJECT}.kpi.specialist_time_daily` WHERE date >= since;
INSERT INTO `${PROJECT}.kpi.specialist_time_daily`
SELECT
  ds_specialist_metrics, ANY_VALUE(Dim_Week_Ending), LOWER(TRIM(dim_specialist_ldap_id)),
  ANY_VALUE(LOWER(dim_specialist_lead_ldap_id)), clean_specialist_sector, Dim_Specialist_Tenure_Group,
  IFNULL(dim_specialist_is_exclude_from_performance, TRUE),
  SUM(cs_specialist_cases_solved), SUM(Cs_Specialist_Logged_Productive_Minutes),
  SUM(cs_productive_hbat_plus_phone_seconds), SUM(CS_Work_Time_For_Cases_in_Seconds),
  SUM(Cs_Specialist_In_Adherence_Minutes), SUM(Cs_Specialist_Total_Adherence_Minutes),
  MAX(dim_spd_target_value_specialist_sector_specialist_tenure),
  MAX(dim_specialist_throughput_target_value_specialist_sector_specialist_lang),
  MAX(dim_reopen_rate_target_value_specialist_sector_specialist_lang),
  MAX(dim_time_to_response_specialist_async_target_value_specialist_sector),
  MAX(dim_worktime_per_handled_case_target_value_specialist_sector),
  CURRENT_TIMESTAMP()
FROM `v11-2026.Dynamic.final_view`
WHERE ds_specialist_metrics >= since AND dim_specialist_ldap_id IS NOT NULL
GROUP BY ds_specialist_metrics, LOWER(TRIM(dim_specialist_ldap_id)), clean_specialist_sector,
         Dim_Specialist_Tenure_Group, IFNULL(dim_specialist_is_exclude_from_performance, TRUE);

DELETE FROM `${PROJECT}.kpi.case_kpi_weekly` WHERE week_ending >= since_week;
INSERT INTO `${PROJECT}.kpi.case_kpi_weekly`
SELECT
  Dim_Week_Ending, Clean_Last_Service_Group, clean_specialist_sector, Specialist_Tenure_Group, Case_Language,
  IFNULL(Is_Excluded_from_Performance_, TRUE),
  SUM(cs_customer_nps_net_promoters), SUM(cs_customer_nps_responses),
  SUM(cs_customer_nps_issue_resolved_scores), SUM(cs_customer_nps_responses_resolved),
  SUM(cs_specialist_expense_coupon_issued_usd), SUM(Cs_Specialist_Expense_Loss_Issued_Usd), SUM(cs_specialist_issues_closed),
  SUM(cs_issuing_specialist_nonhc_mg_expense_is_issued), SUM(cs_issuing_specialist_nonhc_mg_expense_issued_usd),
  SUM(cs_specialist_cases), SUM(cs_specialist_ownership_changes),
  CURRENT_TIMESTAMP()
FROM `v11-2026.Dynamic.final_view_kpi_case`
WHERE Dim_Week_Ending >= since_week
GROUP BY 1, 2, 3, 4, 5, 6;

DELETE FROM `${PROJECT}.kpi.survey_weekly` WHERE week_ending >= since_week;
INSERT INTO `${PROJECT}.kpi.survey_weekly`
SELECT
  dim_week_ending, dim_cs_case_last_service_group_standardized, clean_specialist_sector, dim_specialist_tenure_group,
  Case_Language, IFNULL(dim_specialist_is_exclude_from_performance, TRUE),
  SUM(cs_sum_specialist_quality_score), SUM(cs_sum_specialist_quality_responses),
  SUM(cs_survey_knowledge_score), SUM(cs_survey_knowledge_responses),
  SUM(cs_survey_follow_through_score), SUM(cs_survey_follow_through_responses),
  SUM(cs_survey_efficiency_score), SUM(cs_survey_efficiency_responses),
  CURRENT_TIMESTAMP()
FROM `v11-2026.Dynamic.final_view_kpi_Survey`
WHERE dim_week_ending >= since_week
GROUP BY 1, 2, 3, 4, 5, 6;

DELETE FROM `${PROJECT}.kpi.specialist_profile` WHERE TRUE;
INSERT INTO `${PROJECT}.kpi.specialist_profile`
SELECT LOWER(TRIM(dim_specialist_ldap_id)), dim_specialist_ccpam_title, clean_specialist_sector, Dim_Specialist_Tenure_Group,
  LOWER(dim_specialist_lead_ldap_id), ds_specialist_metrics, CURRENT_TIMESTAMP()
FROM `v11-2026.Dynamic.final_view`
WHERE dim_specialist_ldap_id IS NOT NULL AND ds_specialist_metrics >= DATE_SUB(CURRENT_DATE('Asia/Seoul'), INTERVAL 400 DAY)
QUALIFY ROW_NUMBER() OVER (PARTITION BY LOWER(TRIM(dim_specialist_ldap_id)) ORDER BY ds_specialist_metrics DESC) = 1;

INSERT INTO `${PROJECT}.kpi.refresh_log`
SELECT CURRENT_TIMESTAMP(), since,
  (SELECT COUNT(*) FROM `${PROJECT}.kpi.specialist_case_daily` WHERE date >= since),
  (SELECT COUNT(*) FROM `${PROJECT}.kpi.specialist_time_daily` WHERE date >= since),
  (SELECT COUNT(*) FROM `${PROJECT}.kpi.case_kpi_weekly` WHERE week_ending >= since_week),
  (SELECT COUNT(*) FROM `${PROJECT}.kpi.survey_weekly` WHERE week_ending >= since_week),
  (SELECT MAX(date) FROM `${PROJECT}.kpi.specialist_case_daily`);

COMMIT TRANSACTION;
