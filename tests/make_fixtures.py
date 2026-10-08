"""Regenerate the tiny committed fixtures: python tests/make_fixtures.py

The OSM file is plain .osm XML (pyosmium reads it like a .pbf). Everything here is hand-written test data;
the numbers are valid-format Spanish numbers that are not meant to be real.
"""
from pathlib import Path
from xml.sax.saxutils import quoteattr

OUT = Path(__file__).resolve().parent / "fixtures"

ELEMENTS = [
    ("node", 1, {"amenity": "restaurant", "name": "Café Central", "phone": "+34 912 345 678; +34 913 456 789",
                 "website": "https://example.org", "opening_hours": "Mo-Su 09:00-23:00"}),
    ("node", 2, {"shop": "bakery", "name": "Panadería Sol", "contact:phone": "913456789"}),
    ("way", 3, {"amenity": "pharmacy", "name": "Farmacia Luna", "phone": "915550123, 918765432"}),
    ("node", 4, {"shop": "supermarket", "brand": "SuperEjemplo", "phone": "+34 931 234 567"}),
    ("node", 5, {"amenity": "bench", "phone": "+34 955 123 456"}),
    ("node", 6, {"shop": "clothes", "name": "Moda X", "phone": "12345"}),
    ("node", 7, {"tourism": "hotel", "name": "Hotel Mar", "contact:mobile": "612345678"}),
    ("node", 8, {"shop": "florist", "name": "Flores Ana"}),
    ("node", 9, {"shop": "vacant", "name": "Closed", "phone": "+34 600 111 222"}),
    ("relation", 10, {"tourism": "museum", "name": "Museo Ejemplo", "phone": "+34 955 123 456"}),
    ("node", 11, {"office": "lawyer", "phone": "+34 600 111 222"}),
    ("node", 12, {"name": "Just a node", "highway": "bus_stop"}),
]


def osm_xml() -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<osm version="0.6" generator="make_fixtures.py">']
    for kind, i, tags in ELEMENTS:
        attrs = f'id="{i}" version="1" timestamp="2026-01-01T00:00:00Z" uid="1" user="t" changeset="1"'
        if kind == "node":
            attrs += ' lat="40.0" lon="-3.0"'
        lines.append(f"  <{kind} {attrs}>")
        if kind == "way":
            lines += ['    <nd ref="1"/>', '    <nd ref="2"/>']
        if kind == "relation":
            lines.append('    <member type="node" ref="1" role=""/>')
        for k, v in tags.items():
            lines.append(f"    <tag k={quoteattr(k)} v={quoteattr(v)}/>")
        lines.append(f"  </{kind}>")
    lines.append("</osm>")
    return "\n".join(lines) + "\n"


SPAM_TXT = """# sample list
+34 600 111 222\tFake survey calls
+34 931 234 567
+49 30 12345678 # Test entry
not-a-number
+49900*
"""

SPAM_CSV = """number,reason,type
+34600111222,Fake survey,survey
+34931234567,,
bad,x,y
"""

SPAM_JSONL = """{"number": "+34600111222", "label": "Fake survey", "category": "survey"}
{"number": "931234567", "label": "Local"}
{"number": "oops"}
"""

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    (OUT / "sample.osm").write_text(osm_xml(), encoding="utf-8")
    (OUT / "spam.txt").write_text(SPAM_TXT, encoding="utf-8")
    (OUT / "spam.csv").write_text(SPAM_CSV, encoding="utf-8")
    (OUT / "spam.jsonl").write_text(SPAM_JSONL, encoding="utf-8")
