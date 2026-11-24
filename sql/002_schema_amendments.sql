-- 002 — Phase 1 schema amendments
-- 001_schema.sql remains the immutable baseline.
-- This migration adds reproducibility metadata, integrity constraints and
-- drill-down/audit support without changing the documented operational grains.

CREATE SCHEMA IF NOT EXISTS meta;

CREATE TABLE IF NOT EXISTS meta.generation_runs (
    generation_run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    generator_version TEXT NOT NULL,
    seed BIGINT NOT NULL CHECK (seed >= 0),
    config JSONB NOT NULL,
    config_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    row_counts JSONB,
    CHECK (completed_at IS NULL OR completed_at >= started_at)
);

CREATE TABLE IF NOT EXISTS meta.detection_runs (
    detection_run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_generation_run_id UUID REFERENCES meta.generation_runs(generation_run_id),
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    config JSONB NOT NULL,
    config_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    CHECK (completed_at IS NULL OR completed_at >= started_at)
);

ALTER TABLE anomaly_alerts
    ADD COLUMN IF NOT EXISTS detection_run_id UUID
        REFERENCES meta.detection_runs(detection_run_id);

-- Canonical event taxonomy is enforced by the database, not only by application code.
CREATE TABLE IF NOT EXISTS event_types (
    event_code TEXT PRIMARY KEY,
    event_name TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN
        ('origin_processing','linehaul','destination_processing','last_mile','delivery',
         'reverse_logistics','other')),
    event_status TEXT NOT NULL CHECK (event_status IN
        ('normal','exception','informational','unknown')),
    expected_in_normal_journey BOOLEAN NOT NULL,
    notes TEXT
);

INSERT INTO event_types
    (event_code, event_name, stage, event_status, expected_in_normal_journey, notes)
VALUES
    ('SHP_CREATED', 'Shipment created', 'origin_processing', 'informational', TRUE, NULL),
    ('PICKUP_SCHEDULED', 'Pickup scheduled', 'origin_processing', 'informational', TRUE, NULL),
    ('PICKED_UP', 'Picked up', 'origin_processing', 'normal', TRUE, NULL),
    ('ORIGIN_RECEIVED', 'Received at origin facility', 'origin_processing', 'normal', TRUE, NULL),
    ('ORIGIN_SORTED', 'Sorted at origin facility', 'origin_processing', 'normal', TRUE, NULL),
    ('DISPATCHED_LINEHAUL', 'Dispatched to linehaul', 'linehaul', 'normal', TRUE, NULL),
    ('LINEHAUL_IN_TRANSIT', 'In linehaul transit', 'linehaul', 'normal', TRUE, NULL),
    ('ARRIVED_DESTINATION', 'Arrived at destination facility',
        'destination_processing', 'normal', TRUE, NULL),
    ('DESTINATION_SORTED', 'Sorted at destination facility',
        'destination_processing', 'normal', TRUE, NULL),
    ('TRANSFERRED_LAST_MILE', 'Transferred to last-mile operation',
        'last_mile', 'normal', TRUE, NULL),
    ('OUT_FOR_DELIVERY', 'Out for delivery', 'delivery', 'normal', TRUE, NULL),
    ('DELIVERY_ATTEMPTED', 'Delivery attempted', 'delivery', 'exception', FALSE, NULL),
    ('DELIVERED', 'Delivered', 'delivery', 'normal', TRUE, NULL),
    ('DELIVERY_EXCEPTION', 'Delivery exception', 'delivery', 'exception', FALSE, NULL),
    ('DAMAGE_REPORTED', 'Damage reported', 'other', 'exception', FALSE, NULL),
    ('DAMAGE_CONFIRMED', 'Damage confirmed', 'other', 'exception', FALSE, NULL),
    ('INSPECTION_REQUIRED', 'Inspection required', 'other', 'exception', FALSE, NULL),
    ('PACKAGE_MISSING', 'Package missing', 'other', 'exception', FALSE, NULL),
    ('RETURN_INITIATED', 'Return initiated', 'reverse_logistics', 'informational', FALSE, NULL),
    ('RETURN_IN_TRANSIT', 'Return in transit', 'reverse_logistics', 'normal', FALSE, NULL),
    ('RETURN_RECEIVED', 'Return received', 'reverse_logistics', 'normal', FALSE, NULL),
    ('RETURN_INSPECTED', 'Return inspected', 'reverse_logistics', 'normal', FALSE, NULL),
    ('STATUS_CORRECTED', 'Status corrected', 'other', 'informational', FALSE, NULL),
    ('DATA_GAP_DETECTED', 'Tracking data gap detected', 'other', 'unknown', FALSE, NULL)
ON CONFLICT (event_code) DO NOTHING;

ALTER TABLE shipment_events
    ADD CONSTRAINT fk_shipment_events_event_type
    FOREIGN KEY (event_code) REFERENCES event_types(event_code);

-- An incident's related event must belong to the same shipment.
ALTER TABLE shipment_events
    ADD CONSTRAINT uq_shipment_events_shipment_event UNIQUE (shipment_id, event_id);

ALTER TABLE incidents
    ADD CONSTRAINT fk_incidents_related_event_same_shipment
    FOREIGN KEY (shipment_id, related_event_id)
    REFERENCES shipment_events(shipment_id, event_id);

-- Explicit alert evidence supports drill-down without embedding IDs in explanations.
CREATE TABLE IF NOT EXISTS anomaly_alert_evidence (
    evidence_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id UUID NOT NULL REFERENCES anomaly_alerts(alert_id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('shipment', 'incident', 'return', 'event')),
    entity_id UUID NOT NULL,
    evidence_role TEXT NOT NULL CHECK (evidence_role IN
        ('primary', 'supporting', 'control', 'background')),
    contribution NUMERIC(12,6),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (alert_id, entity_type, entity_id, evidence_role)
);

CREATE INDEX IF NOT EXISTS idx_alert_evidence_alert
    ON anomaly_alert_evidence(alert_id);
CREATE INDEX IF NOT EXISTS idx_alert_evidence_entity
    ON anomaly_alert_evidence(entity_type, entity_id);

-- Append-only audit trail for human review status and outcome changes.
CREATE TABLE IF NOT EXISTS investigation_audit (
    audit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    investigation_id UUID NOT NULL REFERENCES investigations(investigation_id) ON DELETE CASCADE,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    changed_by TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    outcome TEXT,
    note TEXT,
    CHECK (from_status IS NULL OR from_status IN ('open', 'in_review', 'closed', 'dismissed')),
    CHECK (to_status IN ('open', 'in_review', 'closed', 'dismissed')),
    CHECK (outcome IS NULL OR outcome IN
        ('confirmed_issue','no_issue_found','data_quality_issue','needs_more_evidence','other'))
);

CREATE INDEX IF NOT EXISTS idx_investigation_audit_investigation
    ON investigation_audit(investigation_id, changed_at);

CREATE OR REPLACE FUNCTION set_investigation_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_investigations_updated_at
BEFORE UPDATE ON investigations
FOR EACH ROW EXECUTE FUNCTION set_investigation_updated_at();

CREATE OR REPLACE FUNCTION log_investigation_audit() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO investigation_audit
            (investigation_id, changed_by, to_status, outcome, note)
        VALUES
            (NEW.investigation_id, NEW.reviewer_label, NEW.status, NEW.outcome,
             'investigation created');
    ELSIF TG_OP = 'UPDATE'
          AND (OLD.status IS DISTINCT FROM NEW.status
               OR OLD.outcome IS DISTINCT FROM NEW.outcome) THEN
        INSERT INTO investigation_audit
            (investigation_id, changed_by, from_status, to_status, outcome, note)
        VALUES
            (NEW.investigation_id, NEW.reviewer_label, OLD.status, NEW.status, NEW.outcome,
             'status or outcome changed');
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_investigation_audit
AFTER INSERT OR UPDATE ON investigations
FOR EACH ROW EXECUTE FUNCTION log_investigation_audit();

CREATE UNIQUE INDEX IF NOT EXISTS uq_investigations_one_active_per_alert
    ON investigations(alert_id)
    WHERE alert_id IS NOT NULL AND status IN ('open', 'in_review');

ALTER TABLE evaluation.synthetic_scenarios
    ADD COLUMN IF NOT EXISTS expected_signals JSONB;
ALTER TABLE evaluation.synthetic_scenarios
    ADD COLUMN IF NOT EXISTS difficulty TEXT
        CHECK (difficulty IS NULL OR difficulty IN ('easy', 'medium', 'hard'));

ALTER TABLE evaluation.synthetic_truth_links
    ADD CONSTRAINT uq_truth_scenario_entity
    UNIQUE (scenario_id, entity_type, entity_id);

CREATE INDEX IF NOT EXISTS idx_incidents_shipment
    ON incidents(shipment_id);
CREATE INDEX IF NOT EXISTS idx_incidents_reported_at
    ON incidents(reported_at);
CREATE INDEX IF NOT EXISTS idx_incidents_confirmed_at
    ON incidents(confirmed_at) WHERE incident_status = 'confirmed';
CREATE INDEX IF NOT EXISTS idx_returns_shipment
    ON returns(shipment_id);
CREATE INDEX IF NOT EXISTS idx_investigations_alert
    ON investigations(alert_id);
CREATE INDEX IF NOT EXISTS idx_alerts_scope_time
    ON anomaly_alerts(scope_type, scope_id, generated_at);
CREATE INDEX IF NOT EXISTS idx_alerts_detection_run
    ON anomaly_alerts(detection_run_id);
CREATE INDEX IF NOT EXISTS idx_events_facility_time
    ON shipment_events(facility_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_carrier_time
    ON shipment_events(carrier_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_shipments_destination_zone
    ON shipments(destination_zone_id);
CREATE INDEX IF NOT EXISTS idx_shipments_dispatched_at
    ON shipments(dispatched_at);
CREATE INDEX IF NOT EXISTS idx_shipments_category_packaging
    ON shipments(product_category_id, packaging_type_id);
