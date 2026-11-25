-- ═══════════════════════════════════════════════════════════════
-- Capacity 데이터셋 (CAPACITY_DATASET, 기본 `capacity`)
-- 주 = 토요일 마감. 샘플: sample_data/capacity/*.json
-- ═══════════════════════════════════════════════════════════════
CREATE SCHEMA IF NOT EXISTS `${PROJECT}.capacity` OPTIONS (location = 'asia-northeast3');

-- 주간 물량 실적·포케스트 (확인 필요 Q2: 원천·갱신 주체)
CREATE TABLE IF NOT EXISTS `${PROJECT}.capacity.forecast_weekly` (
  week       DATE NOT NULL OPTIONS (description = '주 마감일(토)'),
  channel    STRING NOT NULL OPTIONS (description = 'Voice | Async'),
  volume     INT64 NOT NULL,
  aht_sec    INT64 NOT NULL,
  kind       STRING NOT NULL OPTIONS (description = 'actual | forecast')
);

-- 주간 인원 (현업·네스팅). C-08 에서 기수 흐름 계산값으로 바뀐다.
CREATE TABLE IF NOT EXISTS `${PROJECT}.capacity.headcount_weekly` (
  week          DATE NOT NULL,
  channel       STRING NOT NULL,
  hc_production INT64 NOT NULL,
  hc_nesting    INT64 NOT NULL
);

-- 채널별 계산 가정 (확인 필요 Q1·Q6)
CREATE TABLE IF NOT EXISTS `${PROJECT}.capacity.assumptions` (
  channel              STRING NOT NULL,
  work_hours_week      FLOAT64 NOT NULL,
  occupancy            FLOAT64 NOT NULL,
  shrinkage            FLOAT64 NOT NULL,
  nesting_productivity FLOAT64 NOT NULL,
  sl_target            STRING,
  source               STRING
);
