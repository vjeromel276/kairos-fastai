-- Build fastai-first liquid common-stock universe v1.
--
-- Source tables:
--   sep_base
--   tickers
--
-- Output:
--   universe_fastai_v1
--
-- Contract:
--   one row per ticker/date
--   source data through latest sep_base date
--   no target dependency
--   no model/teacher dependency

DROP TABLE IF EXISTS universe_fastai_v1;

CREATE TEMP TABLE sep_dedup_fastai_v1 AS
SELECT
    *
FROM sep_base
WHERE ticker IS NOT NULL
  AND date IS NOT NULL
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY ticker, date
    ORDER BY TRY_CAST(lastupdated AS DATE) DESC NULLS LAST,
             closeadj DESC NULLS LAST,
             volume DESC NULLS LAST
) = 1;

CREATE TEMP TABLE ticker_meta_fastai_v1 AS
SELECT
    ticker,
    exchange,
    category,
    sector,
    industry,
    scalemarketcap,
    scalerevenue,
    relatedtickers,
    currency,
    location
FROM tickers
WHERE "table" = 'SEP'
  AND ticker IS NOT NULL
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY ticker
    ORDER BY lastupdated DESC NULLS LAST,
             lastpricedate DESC NULLS LAST,
             firstpricedate DESC NULLS LAST
) = 1;

CREATE TABLE universe_fastai_v1 AS
WITH base AS (
    SELECT
        s.ticker,
        CAST(s.date AS DATE) AS date,
        t.exchange,
        t.category,
        COALESCE(t.sector, 'UNKNOWN') AS sector,
        COALESCE(t.industry, 'UNKNOWN') AS industry,
        t.scalemarketcap,
        t.scalerevenue,
        t.currency,
        t.location,
        s.open,
        s.high,
        s.low,
        s.close,
        s.closeadj,
        s.volume,
        s.closeadj * s.volume AS dollar_volume
    FROM sep_dedup_fastai_v1 s
    LEFT JOIN ticker_meta_fastai_v1 t
      ON s.ticker = t.ticker
    WHERE s.closeadj IS NOT NULL
      AND s.closeadj > 0
      AND s.volume IS NOT NULL
      AND s.volume > 0
      AND t.exchange IN ('NASDAQ', 'NYSE', 'NYSEMKT')
      AND t.category IN (
          'Domestic Common Stock',
          'Domestic Common Stock Primary Class',
          'Domestic Common Stock Secondary Class'
      )
),
liquidity AS (
    SELECT
        *,
        AVG(dollar_volume) OVER (
            PARTITION BY ticker
            ORDER BY date
            ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
        ) AS adv_20,
        AVG(dollar_volume) OVER (
            PARTITION BY ticker
            ORDER BY date
            ROWS BETWEEN 59 PRECEDING AND CURRENT ROW
        ) AS adv_60,
        COUNT(*) OVER (
            PARTITION BY ticker
            ORDER BY date
            ROWS BETWEEN 59 PRECEDING AND CURRENT ROW
        ) AS obs_60
    FROM base
)
SELECT
    ticker,
    date,
    exchange,
    category,
    sector,
    industry,
    scalemarketcap,
    scalerevenue,
    currency,
    location,
    open,
    high,
    low,
    close,
    closeadj,
    volume,
    dollar_volume,
    adv_20,
    adv_60,
    COUNT(*) OVER (PARTITION BY date) AS n_raw_universe
FROM liquidity
WHERE closeadj >= 5
  AND adv_20 >= 1000000
  AND obs_60 >= 60;

DROP TABLE sep_dedup_fastai_v1;
DROP TABLE ticker_meta_fastai_v1;

CHECKPOINT;