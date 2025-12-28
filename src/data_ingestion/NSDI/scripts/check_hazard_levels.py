#!/usr/bin/env python3
"""
Check hazard level distribution in DynamoDB hazard zones table.

Usage:
  python scripts/check_hazard_levels.py

Env vars (optional):
  AWS_REGION
  HAZARD_TABLE_NAME
"""

import os
from collections import Counter

import boto3

AWS_REGION = os.getenv("AWS_REGION", " ")
TABLE_NAME = os.getenv("HAZARD_TABLE_NAME", " ")


def main() -> None:
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    table = dynamodb.Table(TABLE_NAME)

    print(f"Scanning hazard table: {TABLE_NAME} (region: {AWS_REGION})")
    counts = Counter()
    total = 0

    last_key = None
    while True:
        kwargs = {
            "ProjectionExpression": "#hl",
            "ExpressionAttributeNames": {"#hl": "hazard_level"},
        }
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key

        resp = table.scan(**kwargs)
        items = resp.get("Items", [])
        for it in items:
            lvl = it.get("hazard_level", "Unknown") or "Unknown"
            counts[str(lvl)] += 1
            total += 1

        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break

    print("\nHazard level distribution:")
    for k, v in counts.most_common():
        pct = (v / total * 100) if total else 0
        print(f"  - {k:10s}: {v:6d}  ({pct:5.1f}%)")

    print(f"\nTotal items scanned: {total}")


if __name__ == "__main__":
    main()
