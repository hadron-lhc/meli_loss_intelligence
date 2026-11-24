-- MELI Loss Intelligence — initial proposed PostgreSQL schema
-- All identifiers and event codes are synthetic project constructs.
-- Apply to an empty database. Evaluation truth is isolated in schema `evaluation`.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE zones (
    zone_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    zone_code TEXT NOT NULL UNIQUE,
    zone_name TEXT NOT NULL,
    region TEXT NOT NULL,
    country_code CHAR(2) NOT NULL
);

CREATE TABLE facilities (
    facility_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    facility_code TEXT NOT NULL UNIQUE,
    facility_name TEXT NOT NULL,
    facility_type TEXT NOT NULL CHECK (facility_type IN
        ('fulfillment','cross_dock','sortation','last_mile_hub','pickup_point','other')),
    zone_id UUID REFERENCES zones(zone_id),
    active_from DATE NOT NULL,
    active_to DATE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (active_to IS NULL OR active_to >= active_from)
);

CREATE TABLE carriers (
    carrier_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    carrier_code TEXT NOT NULL UNIQUE,
    carrier_name TEXT NOT NULL,
    carrier_type TEXT NOT NULL CHECK (carrier_type IN
        ('third_party','owned_fleet','postal','other')),
    active_from DATE NOT NULL,
    active_to DATE,
    CHECK (active_to IS NULL OR active_to >= active_from)
);

CREATE TABLE product_categories (
    product_category_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category_code TEXT NOT NULL UNIQUE,
    category_name TEXT NOT NULL,
    fragility_class TEXT NOT NULL CHECK (fragility_class IN ('low','medium','high','unknown'))
);

CREATE TABLE packaging_types (
    packaging_type_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    packaging_code TEXT NOT NULL UNIQUE,
    packaging_name TEXT NOT NULL,
    protection_level TEXT NOT NULL CHECK (protection_level IN ('low','medium','high','unknown'))
);

CREATE TABLE shipments (
    shipment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shipment_code TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL,
    dispatched_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    origin_facility_id UUID REFERENCES facilities(facility_id),
    destination_zone_id UUID NOT NULL REFERENCES zones(zone_id),
    carrier_id UUID REFERENCES carriers(carrier_id),
    product_category_id UUID NOT NULL REFERENCES product_categories(product_category_id),
    packaging_type_id UUID NOT NULL REFERENCES packaging_types(packaging_type_id),
    weight_g INTEGER CHECK (weight_g IS NULL OR weight_g > 0),
    length_mm INTEGER CHECK (length_mm IS NULL OR length_mm > 0),
    width_mm INTEGER CHECK (width_mm IS NULL OR width_mm > 0),
    height_mm INTEGER CHECK (height_mm IS NULL OR height_mm > 0),
    declared_value NUMERIC(14,2) CHECK (declared_value IS NULL OR declared_value >= 0),
    currency_code CHAR(3),
    shipment_status TEXT NOT NULL CHECK (shipment_status IN
        ('created','in_transit','delivered','returned','cancelled','lost','unknown')),
    is_test_record BOOLEAN NOT NULL DEFAULT FALSE,
    created_record_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (delivered_at IS NULL OR dispatched_at IS NULL OR delivered_at >= dispatched_at),
    CHECK ((declared_value IS NULL AND currency_code IS NULL) OR
           (declared_value IS NOT NULL AND currency_code IS NOT NULL))
);

CREATE TABLE shipment_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shipment_id UUID NOT NULL REFERENCES shipments(shipment_id) ON DELETE CASCADE,
    event_code TEXT NOT NULL,
    event_name TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN
        ('origin_processing','linehaul','destination_processing','last_mile','delivery',
         'reverse_logistics','other')),
    event_status TEXT NOT NULL CHECK (event_status IN
        ('normal','exception','informational','unknown')),
    occurred_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    facility_id UUID REFERENCES facilities(facility_id),
    zone_id UUID REFERENCES zones(zone_id),
    carrier_id UUID REFERENCES carriers(carrier_id),
    sequence_number INTEGER NOT NULL CHECK (sequence_number > 0),
    source_system TEXT NOT NULL,
    event_metadata JSONB,
    UNIQUE (shipment_id, sequence_number)
);

CREATE TABLE incidents (
    incident_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shipment_id UUID NOT NULL REFERENCES shipments(shipment_id),
    related_event_id UUID REFERENCES shipment_events(event_id),
    incident_type TEXT NOT NULL CHECK (incident_type IN
        ('package_damage','package_loss','tampering','other')),
    damage_type TEXT CHECK (damage_type IS NULL OR damage_type IN
        ('crushed','torn','punctured','wet','broken_contents','deformed','other','unknown')),
    severity TEXT NOT NULL CHECK (severity IN ('low','medium','high','critical','unknown')),
    reported_at TIMESTAMPTZ NOT NULL,
    confirmed_at TIMESTAMPTZ,
    incident_status TEXT NOT NULL CHECK (incident_status IN
        ('reported','under_review','confirmed','rejected','closed')),
    estimated_loss_amount NUMERIC(14,2) CHECK
        (estimated_loss_amount IS NULL OR estimated_loss_amount >= 0),
    currency_code CHAR(3),
    evidence_type TEXT NOT NULL CHECK (evidence_type IN
        ('photo','inspection','customer_report','carrier_report','multiple','unknown')),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((estimated_loss_amount IS NULL AND currency_code IS NULL) OR
           (estimated_loss_amount IS NOT NULL AND currency_code IS NOT NULL)),
    CHECK (incident_status <> 'confirmed' OR confirmed_at IS NOT NULL),
    CHECK (incident_type <> 'package_damage' OR damage_type IS NOT NULL)
);

CREATE TABLE returns (
    return_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shipment_id UUID NOT NULL REFERENCES shipments(shipment_id),
    initiated_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ,
    declared_reason TEXT NOT NULL CHECK (declared_reason IN
        ('damaged','wrong_item','not_as_described','changed_mind','size_fit',
         'missing_parts','other','unknown')),
    inspection_outcome TEXT NOT NULL CHECK (inspection_outcome IN
        ('not_inspected','matches_declaration','does_not_match_declaration','inconclusive','unknown')),
    return_status TEXT NOT NULL CHECK (return_status IN
        ('initiated','in_transit','received','inspected','closed','cancelled')),
    condition_on_return TEXT CHECK (condition_on_return IS NULL OR condition_on_return IN
        ('new','used','damaged','incomplete','unknown')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (received_at IS NULL OR received_at >= initiated_at)
);

CREATE TABLE anomaly_alerts (
    alert_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_type TEXT NOT NULL CHECK (alert_type IN
        ('damage_rate_spike','stage_concentration','carrier_deviation',
         'product_profile_deviation','event_sequence_outlier','return_pattern_outlier','data_quality')),
    scope_type TEXT NOT NULL CHECK (scope_type IN
        ('facility','carrier','zone','stage','product_category','shipment','return','global')),
    scope_id TEXT,
    observed_start TIMESTAMPTZ NOT NULL,
    observed_end TIMESTAMPTZ NOT NULL,
    baseline_start TIMESTAMPTZ,
    baseline_end TIMESTAMPTZ,
    observed_numerator INTEGER CHECK (observed_numerator IS NULL OR observed_numerator >= 0),
    observed_denominator INTEGER CHECK (observed_denominator IS NULL OR observed_denominator > 0),
    observed_rate NUMERIC(12,6),
    baseline_rate NUMERIC(12,6),
    anomaly_score NUMERIC(12,6),
    priority TEXT NOT NULL CHECK (priority IN ('low','medium','high','critical')),
    explanation TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN
        ('new','acknowledged','investigating','resolved','dismissed')),
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (observed_end > observed_start),
    CHECK (baseline_end IS NULL OR baseline_start IS NULL OR baseline_end > baseline_start)
);

CREATE TABLE investigations (
    investigation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id UUID REFERENCES anomaly_alerts(alert_id),
    incident_id UUID REFERENCES incidents(incident_id),
    status TEXT NOT NULL CHECK (status IN ('open','in_review','closed','dismissed')),
    outcome TEXT CHECK (outcome IS NULL OR outcome IN
        ('confirmed_issue','no_issue_found','data_quality_issue','needs_more_evidence','other')),
    reviewer_label TEXT NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ,
    notes TEXT,
    recommended_action TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (alert_id IS NOT NULL OR incident_id IS NOT NULL),
    CHECK (closed_at IS NULL OR closed_at >= opened_at),
    CHECK (status NOT IN ('closed','dismissed') OR
           (closed_at IS NOT NULL AND outcome IS NOT NULL))
);

CREATE INDEX idx_shipments_created_at ON shipments(created_at);
CREATE INDEX idx_shipments_facility_carrier ON shipments(origin_facility_id, carrier_id);
CREATE INDEX idx_events_shipment_time ON shipment_events(shipment_id, occurred_at, sequence_number);
CREATE INDEX idx_events_code_time ON shipment_events(event_code, occurred_at);
CREATE INDEX idx_incidents_status_reported ON incidents(incident_status, reported_at);
CREATE INDEX idx_returns_initiated ON returns(initiated_at);
CREATE INDEX idx_alerts_status_generated ON anomaly_alerts(status, generated_at);

-- Evaluation truth is deliberately isolated from operational tables.
CREATE SCHEMA IF NOT EXISTS evaluation;

CREATE TABLE evaluation.synthetic_scenarios (
    scenario_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_code TEXT NOT NULL UNIQUE,
    scenario_type TEXT NOT NULL,
    description TEXT NOT NULL,
    split TEXT NOT NULL CHECK (split IN ('train','validation','test')),
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    affected_entity_type TEXT NOT NULL,
    affected_entity_id TEXT NOT NULL,
    expected_detection BOOLEAN NOT NULL,
    CHECK (end_at > start_at)
);

CREATE TABLE evaluation.synthetic_truth_links (
    truth_link_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id UUID NOT NULL REFERENCES evaluation.synthetic_scenarios(scenario_id)
        ON DELETE CASCADE,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('shipment','event','incident','return')),
    entity_id UUID NOT NULL,
    truth_role TEXT NOT NULL CHECK (truth_role IN ('affected','control','background'))
);

CREATE INDEX idx_truth_scenario ON evaluation.synthetic_truth_links(scenario_id);
CREATE INDEX idx_truth_entity ON evaluation.synthetic_truth_links(entity_type, entity_id);
