-- 004 — Phase 4 detection scope types
-- Synthetic scenarios expose carrier-zone and packaging-profile signals, so alerts
-- must be able to store those scope types without widening any operational grain.

ALTER TABLE anomaly_alerts
    DROP CONSTRAINT IF EXISTS anomaly_alerts_scope_type_check;

ALTER TABLE anomaly_alerts
    ADD CONSTRAINT anomaly_alerts_scope_type_check CHECK (scope_type IN
        ('facility','carrier','zone','stage','product_category','packaging_type',
         'carrier_zone','shipment','return','global'));
