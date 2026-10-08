"""Map OSM tags to a SHORT list of categories, each with an icon name.

The icon names are Material Symbols names; the app maps them to its own vector drawables.
Mapping rule: keys are tried in KEY_PRIORITY order; the first key whose value is mapped wins.
Values of a business key that are not listed fall back to the key's default category (`FALLBACK`),
except for `amenity`, which has no fallback (an unlisted amenity such as a bench is not a business).
"""
from __future__ import annotations

# category id -> icon name. Keep this list short: it is the app's filter chip row.
CATEGORIES: dict[str, str] = {
    "food": "restaurant",
    "grocery": "shopping_basket",
    "shopping": "shopping_bag",
    "health": "local_hospital",
    "lodging": "hotel",
    "automotive": "directions_car",
    "finance": "account_balance",
    "beauty": "content_cut",
    "services": "build",
    "office": "business_center",
    "education": "school",
    "government": "account_balance_wallet",
    "transport": "local_taxi",
    "leisure": "sports_tennis",
    "culture": "theater_comedy",
    "other": "storefront",
}

KEY_PRIORITY = ["healthcare", "shop", "amenity", "office", "craft", "tourism", "leisure"]

# (key, value) -> category. Checked first.
VALUE_MAP: dict[tuple[str, str], str] = {}


def _add(key: str, category: str, values: str) -> None:
    for v in values.split():
        VALUE_MAP[(key, v)] = category


_add("amenity", "food", "restaurant cafe bar pub fast_food ice_cream biergarten food_court")
_add("amenity", "health", "pharmacy clinic doctors dentist hospital veterinary")
_add("amenity", "finance", "bank bureau_de_change")
_add("amenity", "government", "townhall police fire_station post_office courthouse embassy public_building")
_add("amenity", "education", "school kindergarten college university driving_school language_school library")
_add("amenity", "transport", "taxi car_rental bicycle_rental car_sharing ferry_terminal bus_station")
_add("amenity", "automotive", "fuel car_wash charging_station car_repair vehicle_inspection")
_add("amenity", "leisure", "gym nightclub casino")
_add("amenity", "culture", "cinema theatre arts_centre community_centre events_venue")
_add("amenity", "lodging", "hostel")

_add("shop", "grocery", "supermarket convenience bakery butcher greengrocer deli pastry seafood "
                        "beverages alcohol cheese confectionery farm health_food")
_add("shop", "beauty", "hairdresser beauty cosmetics perfumery massage tattoo nails")
_add("shop", "automotive", "car car_repair car_parts tyres motorcycle bicycle")
_add("shop", "health", "chemist optician hearing_aids medical_supply")
_add("shop", "services", "laundry dry_cleaning copyshop travel_agency locksmith")
_add("shop", "finance", "pawnbroker")

_add("tourism", "lodging", "hotel motel hostel guest_house apartment chalet camp_site caravan_site")
_add("tourism", "culture", "museum gallery attraction zoo theme_park aquarium")

_add("office", "government", "government administrative diplomatic")
_add("office", "finance", "insurance financial accountant tax_advisor")
_add("office", "services", "estate_agent lawyer notary architect")

_add("leisure", "leisure", "fitness_centre sports_centre swimming_pool golf_course bowling_alley "
                           "dance sports_hall stadium")

# key -> default category for unlisted values (None = no fallback).
FALLBACK: dict[str, str | None] = {
    "healthcare": "health",
    "shop": "shopping",
    "amenity": None,
    "office": "office",
    "craft": "services",
    "tourism": "other",
    "leisure": "other",
}

# Values that mean "not a place a caller could be": never mapped, even through the fallback.
IGNORED: dict[str, set[str]] = {
    "shop": {"no", "vacant"},
    "office": {"no", "vacant"},
    "craft": {"no"},
    "healthcare": {"no"},
    "tourism": {"no", "information", "picnic_site", "viewpoint", "artwork"},
    "leisure": {"no", "park", "pitch", "picnic_table", "playground", "garden", "common", "track",
                "fitness_station", "slipway", "firepit", "bench", "nature_reserve"},
}


def category_for(tags: dict[str, str], business_keys: list[str] | None = None) -> str | None:
    """Return the category id for a tag set, or None when the element is not a business."""
    keys = [k for k in KEY_PRIORITY if business_keys is None or k in business_keys]
    for key in keys:
        value = tags.get(key)
        if not value or value in IGNORED.get(key, ()):
            continue
        for v in value.split(";"):
            v = v.strip()
            if (key, v) in VALUE_MAP:
                return VALUE_MAP[(key, v)]
        fb = FALLBACK.get(key)
        if fb:
            return fb
    return None


def icon_for(category: str) -> str:
    return CATEGORIES[category]
