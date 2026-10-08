from pipeline import categories as c


def test_core_mappings():
    assert c.category_for({"amenity": "restaurant"}) == "food"
    assert c.category_for({"shop": "bakery"}) == "grocery"
    assert c.category_for({"shop": "florist"}) == "shopping"      # fallback for unlisted shop value
    assert c.category_for({"healthcare": "physiotherapist"}) == "health"
    assert c.category_for({"tourism": "hotel"}) == "lodging"
    assert c.category_for({"craft": "carpenter"}) == "services"
    assert c.category_for({"office": "company"}) == "office"


def test_non_businesses_are_not_mapped():
    assert c.category_for({"amenity": "bench"}) is None
    assert c.category_for({"shop": "vacant"}) is None
    assert c.category_for({"highway": "bus_stop"}) is None
    assert c.category_for({"tourism": "information"}) is None


def test_priority_and_multi_value():
    assert c.category_for({"amenity": "bench", "shop": "bakery"}) == "grocery"
    assert c.category_for({"amenity": "cafe;bar"}) == "food"


def test_every_category_has_icon_and_all_mapped_values_are_known():
    assert len(c.CATEGORIES) <= 20
    for cat in list(c.VALUE_MAP.values()) + [v for v in c.FALLBACK.values() if v]:
        assert c.icon_for(cat)
