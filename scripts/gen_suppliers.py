"""Generate data/suppliers.json: a fictional supplier catalog with realistic tradeoffs.

Run: uv run python scripts/gen_suppliers.py
All supplier names are invented. Certifications are listed only where a listing claims them,
so integrity checks can compare site claims against the chosen listing.
"""

import json
from pathlib import Path

# family: (products [(name, spec, base_cost_usd, unit_weight_kg, materials)], ...)
FAMILIES = {
    "ceramics_planters": [
        ("Self-watering ceramic planter, 15 cm", "15 cm dia x 14 cm h, inner reservoir 350 ml, cotton wick", 6.20, 1.1, "stoneware"),
        ("Self-watering ceramic planter, 20 cm", "20 cm dia x 18 cm h, inner reservoir 700 ml, cotton wick", 8.90, 1.8, "stoneware"),
        ("Ceramic planter trio set", "10/13/16 cm, drainage hole, bamboo saucers", 11.50, 2.4, "stoneware, bamboo"),
    ],
    "candles": [
        ("Soy candle, 8 oz tin", "8 oz soy wax, cotton wick, 40 h burn, custom label", 2.40, 0.32, "soy wax, tin"),
        ("Soy candle, 12 oz glass", "12 oz soy-coconut wax, wood wick, 60 h burn", 4.10, 0.65, "soy-coconut wax, glass"),
        ("Wax melts, 6-pack", "6 cubes, 2.5 oz total", 1.30, 0.1, "soy wax"),
    ],
    "apparel_basics": [
        ("Heavyweight cotton tee", "220 gsm, sizes XS-3XL, screen print up to 2 colors", 5.80, 0.25, "100% cotton"),
        ("Fleece hoodie", "320 gsm, sizes S-3XL, embroidery 1 location", 14.50, 0.65, "80% cotton 20% polyester"),
    ],
    "tote_bags": [
        ("Canvas tote, 12 oz", "38 x 42 cm, 60 cm handles, 1-color print", 1.90, 0.2, "cotton canvas"),
        ("Heavy canvas tote with gusset", "40 x 36 x 12 cm, inner pocket, 2-color print", 4.60, 0.38, "cotton canvas"),
    ],
    "coffee_beans": [
        ("Single-origin roasted beans, 250 g", "Kenya AA, roasted to order, valve bag", 4.80, 0.28, "arabica coffee"),
        ("House blend roasted beans, 1 kg", "Medium roast blend, valve bag", 13.50, 1.05, "arabica coffee"),
        ("Drip bags, 10-pack", "10 x 12 g single-serve drip bags", 3.90, 0.18, "arabica coffee"),
    ],
    "soap_skincare": [
        ("Cold-process soap bar, 110 g", "Olive/coconut base, essential-oil scent, paper wrap", 1.70, 0.13, "saponified oils"),
        ("Lip balm tube, 4.5 g", "Beeswax base, custom label", 0.60, 0.02, "beeswax, oils"),
        ("Body balm tin, 60 g", "Shea base, unscented or scented", 2.30, 0.1, "shea butter, oils"),
    ],
    "stationery": [
        ("A5 dot-grid notebook", "160 pages 100 gsm, lay-flat binding, custom cover", 2.60, 0.35, "paper, card"),
        ("Undated weekly planner", "A5, 128 pages, ribbon marker, custom layout", 3.90, 0.42, "paper, card"),
    ],
    "pet_accessories": [
        ("Nylon dog collar", "Sizes XS-L, quick-release buckle, custom color", 1.80, 0.06, "nylon webbing"),
        ("Matching dog leash, 1.5 m", "Padded handle, custom color", 2.70, 0.15, "nylon webbing"),
        ("Ceramic pet bowl", "16 cm, food-safe glaze", 3.40, 0.7, "stoneware"),
    ],
    "drinkware": [
        ("Insulated steel bottle, 600 ml", "Double-wall, powder coat, laser logo", 5.20, 0.38, "stainless steel"),
        ("Ceramic mug, 350 ml", "Custom glaze color, dishwasher safe", 2.10, 0.36, "stoneware"),
    ],
    "kitchen_textiles": [
        ("Cotton canvas apron", "Adjustable neck, 2 pockets, 1-color print", 4.20, 0.3, "cotton canvas"),
        ("Linen-blend tea towel, 2-pack", "50 x 70 cm, custom print", 2.80, 0.18, "linen-cotton"),
    ],
    "wooden_toys": [
        ("Wooden stacking rainbow", "7 arcs, water-based paint, 28 cm", 7.40, 0.9, "beech wood"),
        ("Wooden pull-along animal", "Hand-finished, 18 cm, cotton cord", 5.10, 0.4, "beech wood"),
    ],
}

PROFILES = [
    # code, region, country, cost x, moq, lead days, freight/kg by dest, rating, defect %, sample cost, sample days, certs, note
    ("value", "Shenzhen area", "CN", 0.72, 1000, 45, {"US": 2.9, "EU": 3.1, "UK": 3.2, "AU": 2.6, "other": 3.6}, 3.9, 4.0, 45, 14, [], "Lowest unit cost; sea freight; quality varies by batch."),
    ("mid", "Ho Chi Minh City area", "VN", 1.0, 300, 30, {"US": 3.6, "EU": 3.7, "UK": 3.8, "AU": 3.0, "other": 4.0}, 4.4, 2.0, 30, 10, ["ISO 9001"], "Balanced cost and quality; air or sea options."),
    ("craft", "Domestic workshop", "LOCAL", 1.85, 50, 14, {"US": 1.2, "EU": 1.2, "UK": 1.2, "AU": 1.2, "other": 2.5}, 4.8, 0.8, 20, 5, [], "Small-batch, ships from the launch country; highest unit cost."),
]

NAMES = {
    "ceramics_planters": ["Kilnworks Trading", "Saigon Clay Co.", "Hearth & Glaze Studio"],
    "candles": ["Brightwick Manufacturing", "Mekong Candle Works", "Little Flame Pour House"],
    "apparel_basics": ["Pearl River Garments", "Lotus Textile Group", "Cutline Sewing Collective"],
    "tote_bags": ["Canton Canvas Supply", "Delta Bag Makers", "Fieldstitch Bags"],
    "coffee_beans": ["Rift Valley Green Exports", "Highland Roast Partners", "Small Lot Roasting Co."],
    "soap_skincare": ["Guangdong Personal Care OEM", "Lotus Botanicals Lab", "Saltmeadow Soapery"],
    "stationery": ["Dongguan Paper Goods", "Hanoi Bindery", "Quire & Thread Press"],
    "pet_accessories": ["Pawline Industrial", "Mekong Pet Supply", "Good Leash Workshop"],
    "drinkware": ["Yongkang Steelware", "Bien Hoa Ceramics", "Kiln & Keel Mugs"],
    "kitchen_textiles": ["Ningbo Home Textiles", "Saigon Linen House", "Apron Row Studio"],
    "wooden_toys": ["Zhejiang Wood Toy Factory", "Binh Duong Timber Crafts", "Treehouse Joinery"],
}

CERTS = {  # only some listings may truthfully claim these
    ("candles", "mid"): ["ISO 9001", "Phthalate-free fragrance oils"],
    ("soap_skincare", "craft"): ["Cosmetic GMP"],
    ("wooden_toys", "mid"): ["ISO 9001", "EN 71 tested", "ASTM F963 tested"],
    ("wooden_toys", "value"): ["EN 71 tested"],
    ("coffee_beans", "value"): ["Rainforest Alliance (farm level)"],
    ("coffee_beans", "craft"): ["Organic (certified)"],
    ("ceramics_planters", "mid"): ["ISO 9001", "Lead-free glaze"],
    ("apparel_basics", "mid"): ["ISO 9001", "OEKO-TEX Standard 100"],
    ("tote_bags", "craft"): ["GOTS organic cotton"],
}

out = []
for fam, products in FAMILIES.items():
    for (code, region, country, mult, moq, lead, freight, rating, defect, sample_cost, sample_days, base_certs, note), name in zip(PROFILES, NAMES[fam]):
        sid = f"sup-{fam.replace('_', '-')}-{code}"
        items = []
        for i, (pname, spec, cost, kg, mats) in enumerate(products):
            unit = round(cost * mult, 2)
            items.append({
                "sku": f"{sid}-{i + 1}",
                "name": pname,
                "spec": spec,
                "materials": mats,
                "price_breaks": [
                    {"min_qty": moq, "unit_cost": unit},
                    {"min_qty": moq * 3, "unit_cost": round(unit * 0.88, 2)},
                    {"min_qty": moq * 10, "unit_cost": round(unit * 0.78, 2)},
                ],
                "unit_weight_kg": kg,
                "packaging_cost": round(0.35 + kg * 0.25, 2),
                "customization": "custom branding/label included above MOQ",
            })
        out.append({
            "id": sid, "name": name, "family": fam, "profile": code,
            "region": region, "ships_from": country,
            "moq": moq, "lead_time_days": lead,
            "freight_per_kg_usd": freight,
            "rating": rating, "defect_rate_pct": defect,
            "sample_cost_usd": sample_cost, "sample_days": sample_days,
            "certifications": CERTS.get((fam, code), base_certs),
            "payment_terms": "50% deposit, 50% before shipment" if code != "craft" else "100% on order",
            "notes": note,
            "products": items,
        })

path = Path(__file__).resolve().parents[1] / "data" / "suppliers.json"
path.write_text(json.dumps(out, indent=2))
print(f"wrote {len(out)} suppliers, {sum(len(s['products']) for s in out)} SKUs to {path}")
