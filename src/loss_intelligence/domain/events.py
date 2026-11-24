from dataclasses import dataclass


@dataclass(frozen=True)
class EventType:
    code: str
    name: str
    stage: str
    status: str
    expected_in_normal_journey: bool


EVENT_TAXONOMY: dict[str, EventType] = {
    event.code: event
    for event in (
        EventType("SHP_CREATED", "Shipment created", "origin_processing", "informational", True),
        EventType(
            "PICKUP_SCHEDULED", "Pickup scheduled", "origin_processing", "informational", True
        ),
        EventType("PICKED_UP", "Picked up", "origin_processing", "normal", True),
        EventType(
            "ORIGIN_RECEIVED", "Received at origin facility", "origin_processing", "normal", True
        ),
        EventType(
            "ORIGIN_SORTED", "Sorted at origin facility", "origin_processing", "normal", True
        ),
        EventType("DISPATCHED_LINEHAUL", "Dispatched to linehaul", "linehaul", "normal", True),
        EventType("LINEHAUL_IN_TRANSIT", "In linehaul transit", "linehaul", "normal", True),
        EventType(
            "ARRIVED_DESTINATION",
            "Arrived at destination facility",
            "destination_processing",
            "normal",
            True,
        ),
        EventType(
            "DESTINATION_SORTED",
            "Sorted at destination facility",
            "destination_processing",
            "normal",
            True,
        ),
        EventType(
            "TRANSFERRED_LAST_MILE",
            "Transferred to last-mile operation",
            "last_mile",
            "normal",
            True,
        ),
        EventType("OUT_FOR_DELIVERY", "Out for delivery", "delivery", "normal", True),
        EventType("DELIVERY_ATTEMPTED", "Delivery attempted", "delivery", "exception", False),
        EventType("DELIVERED", "Delivered", "delivery", "normal", True),
        EventType("DELIVERY_EXCEPTION", "Delivery exception", "delivery", "exception", False),
        EventType("DAMAGE_REPORTED", "Damage reported", "other", "exception", False),
        EventType("DAMAGE_CONFIRMED", "Damage confirmed", "other", "exception", False),
        EventType("INSPECTION_REQUIRED", "Inspection required", "other", "exception", False),
        EventType("PACKAGE_MISSING", "Package missing", "other", "exception", False),
        EventType(
            "RETURN_INITIATED", "Return initiated", "reverse_logistics", "informational", False
        ),
        EventType("RETURN_IN_TRANSIT", "Return in transit", "reverse_logistics", "normal", False),
        EventType("RETURN_RECEIVED", "Return received", "reverse_logistics", "normal", False),
        EventType("RETURN_INSPECTED", "Return inspected", "reverse_logistics", "normal", False),
        EventType("STATUS_CORRECTED", "Status corrected", "other", "informational", False),
        EventType("DATA_GAP_DETECTED", "Tracking data gap detected", "other", "unknown", False),
    )
}

DAMAGE_EVENT_CODES = frozenset({"DAMAGE_REPORTED", "DAMAGE_CONFIRMED"})
RETURN_EVENT_CODES = frozenset(
    {"RETURN_INITIATED", "RETURN_IN_TRANSIT", "RETURN_RECEIVED", "RETURN_INSPECTED"}
)
