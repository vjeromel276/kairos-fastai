DROP TABLE IF EXISTS trading_calendar;

CREATE TABLE trading_calendar AS
SELECT DISTINCT
    CAST(date AS DATE) AS trading_date
FROM sep_base
WHERE date IS NOT NULL
ORDER BY trading_date;

CHECKPOINT;
