-- Migration 003: add MAD (median absolute deviation) to baselines so
-- flagging can use a robust z-score that one anomalous year cannot inflate.
ALTER TABLE baselines ADD COLUMN mad REAL;
