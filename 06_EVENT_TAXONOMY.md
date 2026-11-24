# 06 — Canonical Event Taxonomy

## Important disclaimer

The event codes below are **project-defined canonical codes for the synthetic PoC**. They are not official Mercado Libre or Mercado Envíos event codes. Do not reuse or imply equivalence with private or public carrier codes.

Each event has:
- canonical code,
- display name,
- stage,
- status class,
- whether it is expected in a normal journey,
- optional notes.

## Event catalogue

| Code | Event name | Stage | Status | Meaning |
|---|---|---|---|---|
| `SHP_CREATED` | Shipment created | `origin_processing` | informational | Shipment record created. |
| `PICKUP_SCHEDULED` | Pickup scheduled | `origin_processing` | informational | Collection planned. |
| `PICKED_UP` | Picked up | `origin_processing` | normal | Shipment collected. |
| `ORIGIN_RECEIVED` | Received at origin facility | `origin_processing` | normal | Arrival at origin node. |
| `ORIGIN_SORTED` | Sorted at origin facility | `origin_processing` | normal | Origin sorting completed. |
| `DISPATCHED_LINEHAUL` | Dispatched to linehaul | `linehaul` | normal | Shipment leaves origin node. |
| `LINEHAUL_IN_TRANSIT` | In linehaul transit | `linehaul` | normal | In transit between nodes. |
| `ARRIVED_DESTINATION` | Arrived at destination facility | `destination_processing` | normal | Arrival at destination node. |
| `DESTINATION_SORTED` | Sorted at destination facility | `destination_processing` | normal | Destination sorting completed. |
| `TRANSFERRED_LAST_MILE` | Transferred to last-mile operation | `last_mile` | normal | Handover to delivery operation. |
| `OUT_FOR_DELIVERY` | Out for delivery | `delivery` | normal | Delivery route started. |
| `DELIVERY_ATTEMPTED` | Delivery attempted | `delivery` | exception | Attempt recorded but not completed. |
| `DELIVERED` | Delivered | `delivery` | normal | Delivery completed. |
| `DELIVERY_EXCEPTION` | Delivery exception | `delivery` | exception | Delivery could not be completed. |
| `DAMAGE_REPORTED` | Damage reported | `other` | exception | Damage claim/report received; not yet confirmed. |
| `DAMAGE_CONFIRMED` | Damage confirmed | `other` | exception | Damage confirmed by review; should align with an `incidents` row. |
| `INSPECTION_REQUIRED` | Inspection required | `other` | exception | Manual inspection requested; not itself proof of damage. |
| `PACKAGE_MISSING` | Package missing | `other` | exception | Package not located at expected point; not automatically confirmed loss. |
| `RETURN_INITIATED` | Return initiated | `reverse_logistics` | informational | Return process started. |
| `RETURN_IN_TRANSIT` | Return in transit | `reverse_logistics` | normal | Return shipment moving. |
| `RETURN_RECEIVED` | Return received | `reverse_logistics` | normal | Return received at node. |
| `RETURN_INSPECTED` | Return inspected | `reverse_logistics` | normal | Inspection completed. |
| `STATUS_CORRECTED` | Status corrected | `other` | informational | Previous status corrected; preserve both events. |
| `DATA_GAP_DETECTED` | Tracking data gap detected | `other` | unknown | Missing expected event or telemetry gap. |

## Sequence and data-quality rules

- Not every shipment must have every event.
- A journey can branch (e.g. failed delivery followed by another attempt).
- Event order must be plausible but should not be perfectly identical across all shipments.
- A missing event is not proof of mishandling.
- `DAMAGE_REPORTED` and `DAMAGE_CONFIRMED` must remain distinct.
- `DAMAGE_CONFIRMED` is a canonical synthetic event and must not be treated as an official external event code.
- Event timestamps and recording timestamps should be generated separately so realistic reporting delay can be analysed.
- Include a small number of explicit data-quality scenarios, but keep them separate from damage scenarios.
