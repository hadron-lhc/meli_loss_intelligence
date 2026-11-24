from collections import defaultdict
from datetime import timedelta
from uuid import UUID

from loss_intelligence.synthetic.common import deterministic_uuid
from loss_intelligence.synthetic.config import SyntheticDataConfig
from loss_intelligence.synthetic.models import ReferenceData

ZONE_DEFS = [
    ("ZN-01", "Zona Metropolitana Norte", "AMBA"),
    ("ZN-02", "Zona Metropolitana Sur", "AMBA"),
    ("ZN-03", "Zona Centro", "CENTRO"),
    ("ZN-04", "Zona Litoral", "LITORAL"),
    ("ZN-05", "Zona Cuyo", "CUYO"),
    ("ZN-06", "Zona NOA", "NOA"),
    ("ZN-07", "Zona Patagonia Norte", "PATAGONIA"),
    ("ZN-08", "Zona Patagonia Sur", "PATAGONIA"),
    ("ZN-09", "Zona NEA", "NEA"),
    ("ZN-10", "Zona Pampa", "PAMPA"),
]

FACILITY_NAMES = [
    "Centro Logístico Norte",
    "Centro Logístico Sur",
    "Centro Logístico Centro",
    "Centro Logístico Litoral",
    "Centro Logístico Cuyo",
    "Centro Logístico NOA",
    "Centro Logístico Patagonia Norte",
    "Centro Logístico Patagonia Sur",
    "Centro Logístico NEA",
    "Centro Logístico Pampa",
]

FACILITY_TYPES = [
    "fulfillment",
    "last_mile_hub",
    "sortation",
    "cross_dock",
    "last_mile_hub",
    "fulfillment",
    "last_mile_hub",
    "cross_dock",
    "sortation",
    "last_mile_hub",
]

CARRIER_NAMES = [
    "Transporte Horizonte",
    "Red Logística Sur",
    "Correo del Plata",
    "Flota Propia Norte",
    "Transporte Cuyo",
    "Logística Litoral",
    "Mensajería Patagonia",
    "Red Nacional Postal",
]

CARRIER_TYPES = [
    "third_party",
    "third_party",
    "postal",
    "owned_fleet",
    "third_party",
    "third_party",
    "third_party",
    "postal",
]

CATEGORY_DEFS = [
    ("CAT-ELEC", "Electrónica pequeña", "high"),
    ("CAT-HOME", "Artículos para el hogar", "medium"),
    ("CAT-TOOLS", "Herramientas", "medium"),
    ("CAT-GLASS", "Cristalería", "high"),
    ("CAT-FASHION", "Indumentaria", "low"),
    ("CAT-BOOKS", "Libros y papelería", "low"),
    ("CAT-BEAUTY", "Belleza y cuidado personal", "medium"),
    ("CAT-SPORTS", "Deportes", "medium"),
    ("CAT-TOYS", "Juguetes", "low"),
    ("CAT-AUTO", "Accesorios automotor", "medium"),
    ("CAT-FURNITURE", "Muebles pequeños", "high"),
    ("CAT-PET", "Productos para mascotas", "low"),
]

PACKAGING_DEFS = [
    ("PKG-BOX", "Caja corrugada", "medium"),
    ("PKG-MAILER", "Sobre acolchado", "low"),
    ("PKG-WRAP", "Film protector", "low"),
    ("PKG-RIGID", "Contenedor rígido", "high"),
    ("PKG-PADDED", "Caja con relleno", "high"),
    ("PKG-REUSED", "Empaque reutilizado", "unknown"),
]

CARRIER_EFFECTS = [0.85, 0.95, 1.0, 1.05, 1.15, 1.0, 0.9, 1.1]
FACILITY_EFFECTS = [0.9, 1.0, 1.1, 0.85, 1.2, 1.0, 0.95, 1.05, 1.0, 0.9]
ZONE_EFFECTS = [0.9, 1.0, 1.1, 1.0, 0.95, 1.05, 0.85, 1.15, 1.0, 1.0]


def build_reference_data(config: SyntheticDataConfig) -> ReferenceData:
    zones: list[dict] = []
    for index in range(config.zone_count):
        code, name, region = ZONE_DEFS[index]
        zones.append(
            {
                "zone_id": deterministic_uuid(config.seed, "zone", code),
                "zone_code": code,
                "zone_name": name,
                "region": region,
                "country_code": "AR",
            }
        )

    zone_ids = [zone["zone_id"] for zone in zones]
    facilities: list[dict] = []
    facilities_by_zone: dict[UUID, list[UUID]] = defaultdict(list)
    zone_by_facility: dict[UUID, UUID] = {}
    for index in range(config.facility_count):
        zone_id = zone_ids[index % len(zone_ids)]
        facility_id = deterministic_uuid(config.seed, "facility", f"FC-{index + 1:02d}")
        facilities.append(
            {
                "facility_id": facility_id,
                "facility_code": f"FC-{index + 1:02d}",
                "facility_name": FACILITY_NAMES[index],
                "facility_type": FACILITY_TYPES[index],
                "zone_id": zone_id,
                "active_from": config.start_date - timedelta(days=365),
                "active_to": None,
                "is_active": True,
            }
        )
        facilities_by_zone[zone_id].append(facility_id)
        zone_by_facility[facility_id] = zone_id

    carriers: list[dict] = []
    carrier_effect: dict[UUID, float] = {}
    for index in range(config.carrier_count):
        carrier_id = deterministic_uuid(config.seed, "carrier", f"CR-{index + 1:02d}")
        carriers.append(
            {
                "carrier_id": carrier_id,
                "carrier_code": f"CR-{index + 1:02d}",
                "carrier_name": CARRIER_NAMES[index],
                "carrier_type": CARRIER_TYPES[index],
                "active_from": config.start_date - timedelta(days=365),
                "active_to": None,
            }
        )
        carrier_effect[carrier_id] = CARRIER_EFFECTS[index]

    product_categories: list[dict] = []
    for index in range(config.product_category_count):
        code, name, fragility = CATEGORY_DEFS[index]
        product_categories.append(
            {
                "product_category_id": deterministic_uuid(config.seed, "category", code),
                "category_code": code,
                "category_name": name,
                "fragility_class": fragility,
            }
        )

    packaging_types: list[dict] = []
    for index in range(config.packaging_type_count):
        code, name, protection = PACKAGING_DEFS[index]
        packaging_types.append(
            {
                "packaging_type_id": deterministic_uuid(config.seed, "packaging", code),
                "packaging_code": code,
                "packaging_name": name,
                "protection_level": protection,
            }
        )

    return ReferenceData(
        zones=zones,
        facilities=facilities,
        carriers=carriers,
        product_categories=product_categories,
        packaging_types=packaging_types,
        facilities_by_zone=dict(facilities_by_zone),
        zone_by_facility=zone_by_facility,
        zone_by_id={zone["zone_id"]: zone for zone in zones},
        carrier_by_id={carrier["carrier_id"]: carrier for carrier in carriers},
        category_by_id={
            category["product_category_id"]: category for category in product_categories
        },
        packaging_by_id={
            packaging["packaging_type_id"]: packaging for packaging in packaging_types
        },
        carrier_effect=carrier_effect,
        facility_effect={
            facility["facility_id"]: FACILITY_EFFECTS[index]
            for index, facility in enumerate(facilities)
        },
        zone_effect={zone["zone_id"]: ZONE_EFFECTS[index] for index, zone in enumerate(zones)},
    )
