import json
from collections import Counter

"""
Check location attributes such as district, ds_division an gn_division  in downloaded NSDI RAW JSON.

Usage:
  python scripts/check_hazard_levels.py

Env vars (optional):
  AWS_REGION
  HAZARD_TABLE_NAME
"""

path = "nsdi_raw_backup.json"
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

features = data.get("features") or data.get("Features") or []
print(f"Features: {len(features)}")

# Count property keys across all features (case-insensitive)
key_counts = Counter()
missing = Counter()


def pick(props, *candidates):
    lower = {k.lower(): k for k in props.keys()}
    for c in candidates:
        k = lower.get(c.lower())
        if k is not None:
            return k, props.get(k)
    return None, None


for feat in features:
    props = feat.get("properties") or feat.get("Properties") or {}
    for k in props.keys():
        key_counts[k.lower()] += 1

    _, district = pick(props, "district", "district_name", "admin_district")
    _, ds = pick(props, "ds_division", "ds", "dsdivision", "ds_name")
    _, gn = pick(props, "gn_division", "gn", "gndivision", "gn_name")

    if district in (None, "", "Unknown"):
        missing["district"] += 1

    if ds in (None, "", "Unknown"):
        missing["ds"] += 1

    if gn in (None, "", "Unknown"):
        missing["gn"] += 1

print("\nTop candidate keys (you can eyeball what’s available):")
for k, c in key_counts.most_common(30):
    print(f"  {k}: {c}")

print("\nMissing counts (per feature):")
for k in ("district", "ds", "gn"):
    print(f"  {k}: {missing[k]} / {len(features)}")
