-- 2-5. v11-2026 에서 상담사 360 에 쓸 열 찾기 (읽기만 함, 비용 거의 없음)
-- BigQuery 콘솔에서 실행 → 결과 전체를 복사(또는 CSV 저장)해서 보내 주세요.
SELECT
  table_name,
  column_name,
  data_type
FROM `v11-2026.Dynamic.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name IN ('final_view', 'final_view_case', 'final_view_kpi_Survey')
  AND REGEXP_CONTAINS(LOWER(column_name),
      r'ldap|_name|team|supervisor|manager|lead|coach|sector|tenure|hire|start_date|cohort|nesting|ramp'
   || r'|ds_metric|ds_specialist|week_ending|exclude'
   || r'|handle|aht|work_time|talk|hold|solved|assignments_completed|throughput'
   || r'|nps_net|nps_responses|quality_score|quality_responses'
   || r'|schedul|adherence|absen|attend|leave|occupancy')
ORDER BY table_name, column_name;
