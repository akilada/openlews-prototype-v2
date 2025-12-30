#!/usr/bin/env python3
"""
Process Existing NSDI Backup and Upload to DynamoDB/Pinecone

Reads an existing nsdi_raw_backup.json file and processes it for DynamoDB and
optionally Pinecone. Does not re-download from NSDI API.

Usage:
    # Process ALL records (default - no filtering)
    python process_backup.py

    # With embeddings + Pinecone upsert
    python process_backup.py --embeddings --pinecone

    # Test run
    python process_backup.py --limit 500 --dry-run --embeddings --pinecone

    # Filter by bounds: min_lat,max_lat,min_lon,max_lon
    python process_backup.py --filter-bounds 6.8,7.2,80.8,81.2 --embeddings --pinecone

Requirements:
    pip install boto3 python-dotenv pygeohash

Optional for embeddings:
    pip install sentence-transformers

Pinecone (Python 3.9 safe):
    pip install "pinecone<8"
"""

import json
import os
import sys
import time
import argparse
from typing import List, Dict, Optional, Tuple

import boto3
from dotenv import load_dotenv

# Import shared processor
from geo_processor import (
    GeoJSONProcessor,
    estimate_item_size,
    GEOHASH_AVAILABLE
)

load_dotenv()

# Configuration
AWS_REGION = os.getenv("AWS_REGION", "")
DYNAMODB_TABLE_NAME = os.getenv("DYNAMODB_TABLE_NAME", "")

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "")
PINECONE_NAMESPACE = os.getenv("PINECONE_NAMESPACE", "")

EMBEDDING_METHOD = os.getenv("EMBEDDING_METHOD", "none").lower()
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

BACKUP_FILE = "nsdi_raw_backup.json"
DYNAMODB_ITEM_LIMIT_BYTES = 400 * 1024


class EmbeddingGenerator:
    """Generate embeddings for semantic search."""

    def __init__(self, method: str = "local", model: str = "all-MiniLM-L6-v2"):
        self.method = method
        self.model_name = model
        self.model = None

        if self.method == "local":
            try:
                from sentence_transformers import SentenceTransformer
                print(f"  Loading embedding model: {model}...")
                self.model = SentenceTransformer(model)
                print("  ✓ Model loaded")
            except ImportError:
                print("  ❌ sentence-transformers not installed.")
                print("     Install with: pip install sentence-transformers")
                self.method = "none"

    def batch_generate(self, items: List[Dict]) -> List[Optional[List[float]]]:
        if self.method == "none" or not self.model:
            return [None] * len(items)

        texts = [GeoJSONProcessor.generate_embedding_text(item) for item in items]

        try:
            embeddings = self.model.encode(texts, show_progress_bar=True)
            return [emb.tolist() for emb in embeddings]
        except Exception as e:
            print(f"  ⚠️  Batch embedding failed: {e}")
            return [None] * len(items)


def load_backup_file(filepath: str,
                     limit: Optional[int] = None,
                     bounds: Optional[Tuple[float, float, float, float]] = None) -> List[Dict]:
    print(f"\n📂 Loading backup file: {filepath}")

    if not os.path.exists(filepath):
        print(f"  ❌ File not found: {filepath}")
        sys.exit(1)

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    print(f"  ✓ Loaded {len(features):,} features from backup")

    if bounds:
        min_lat, max_lat, min_lon, max_lon = bounds
        print(f"  🗺️  Filtering by bounds: lat [{min_lat}, {max_lat}], lon [{min_lon}, {max_lon}]")
        filtered = []
        for feature in features:
            centroid_lat, centroid_lon = GeoJSONProcessor.extract_centroid(feature.get("geometry", {}))
            if min_lat <= centroid_lat <= max_lat and min_lon <= centroid_lon <= max_lon:
                filtered.append(feature)

        print(f"  ✓ Filtered to {len(filtered):,} features within bounds")
        features = filtered

    if limit:
        features = features[:limit]
        print(f"  📊 Limited to first {len(features):,} features")

    return features


def ingest_to_dynamodb(items: List[Dict], table_name: str, batch_size: int = 25, dry_run: bool = False) -> int:
    print(f"\n📊 {'[DRY RUN] ' if dry_run else ''}Ingesting {len(items):,} items into DynamoDB: {table_name}")

    oversized = []
    for item in items:
        size = estimate_item_size(item)
        if size > DYNAMODB_ITEM_LIMIT_BYTES:
            oversized.append((item.get("zone_id", "unknown"), size))

    if dry_run:
        print("  ⚠️  Dry run mode - no data will be written")
        if oversized:
            print(f"  ⚠️  {len(oversized)} items exceed 400KB limit (showing up to 10):")
            for zone_id, size in oversized[:10]:
                print(f"      {zone_id}: {size / 1024:.1f}KB")
        return len(items) - len(oversized)

    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    table = dynamodb.Table(table_name)

    inserted_count = 0
    failed_items = []
    total_batches = (len(items) + batch_size - 1) // batch_size

    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        batch_num = i // batch_size + 1

        with table.batch_writer() as writer:
            for item in batch:
                try:
                    if estimate_item_size(item) > DYNAMODB_ITEM_LIMIT_BYTES:
                        continue
                    writer.put_item(Item=item)
                    inserted_count += 1
                except Exception as e:
                    failed_items.append((item.get("zone_id", "unknown"), str(e)))
                    if len(failed_items) <= 5:
                        print(f"  ❌ Failed to insert {item.get('zone_id')}: {e}")

        if batch_num % 100 == 0 or batch_num == total_batches:
            print(f"  ✓ Batch {batch_num:,}/{total_batches:,} ({inserted_count:,}/{len(items):,} items)")
        time.sleep(0.05)

    print(f"✅ DynamoDB ingestion complete: {inserted_count:,}/{len(items):,} items")

    if oversized:
        print(f"⚠️  Skipped {len(oversized)} oversized items (>400KB)")

    if failed_items:
        print(f"⚠️  Failed items: {len(failed_items)} (showing up to 5)")
        for zone_id, error in failed_items[:5]:
            print(f"   {zone_id}: {error[:120]}")

    return inserted_count


def _pinecone_client():
    """Create Pinecone client with clear errors."""
    try:
        from pinecone import Pinecone
        return Pinecone(api_key=PINECONE_API_KEY)
    except ImportError:
        print("❌ Pinecone SDK not installed.")
        print('   Install (Python 3.9 safe): pip install "pinecone<8"')
        return None


def _pinecone_index_dimension(pc, index_name: str) -> Optional[int]:
    """Try to read index dimension in a version-tolerant way."""
    try:
        desc = pc.describe_index(index_name)
        if isinstance(desc, dict):
            return int(desc.get("dimension"))
        return int(getattr(desc, "dimension"))
    except Exception:
        return None


def upsert_to_pinecone(items: List[Dict], embeddings: List[Optional[List[float]]], dry_run: bool = False) -> int:
    if not PINECONE_API_KEY:
        print("⚠️  PINECONE_API_KEY not set. Skipping Pinecone upload.")
        return 0

    pc = _pinecone_client()
    if pc is None:
        return 0

    print(f"\n🌲 {'[DRY RUN] ' if dry_run else ''}Upserting vectors to Pinecone: {PINECONE_INDEX_NAME}")

    # Dimension sanity check
    first_emb = next((e for e in embeddings if e is not None), None)
    if first_emb is None:
        print("⚠️  No embeddings available. Skipping Pinecone upload.")
        return 0

    expected_dim = len(first_emb)
    actual_dim = _pinecone_index_dimension(pc, PINECONE_INDEX_NAME)
    if actual_dim is not None and actual_dim != expected_dim:
        print("❌ Dimension mismatch!")
        print(f"   Embeddings dimension: {expected_dim}")
        print(f"   Pinecone index dimension: {actual_dim}")
        print("   Fix: recreate the index with the correct DIMENSION.")
        return 0

    if dry_run:
        valid = sum(1 for e in embeddings if e is not None)
        print(f"  ⚠️  Dry run mode - would upsert {valid:,} vectors")
        return valid

    index = pc.Index(PINECONE_INDEX_NAME)

    vectors = []
    for item, embedding in zip(items, embeddings):
        if embedding is None:
            continue

        metadata = {
            "zone_id": item["zone_id"],
            "level": item.get("level", "Unknown"),
            "hazard_level": item.get("hazard_level", item.get("level", "Unknown")),
            "centroid_lat": float(item["centroid_lat"]),
            "centroid_lon": float(item["centroid_lon"]),
            "geohash": item["geohash"],
            "district": item.get("district", "Unknown"),
            "ds_division": item.get("ds_division", "Unknown"),
            "soil_type": item.get("soil_type", "Unknown"),
            "shape_area": float(item.get("metadata", {}).get("shape_area", 0.0)),
        }

        vectors.append({
            "id": item["zone_id"],
            "values": embedding,
            "metadata": metadata
        })

    batch_size = 100
    upserted = 0
    total_batches = (len(vectors) + batch_size - 1) // batch_size

    for i in range(0, len(vectors), batch_size):
        batch = vectors[i:i + batch_size]
        batch_num = i // batch_size + 1

        index.upsert(vectors=batch, namespace=PINECONE_NAMESPACE)
        upserted += len(batch)

        if batch_num % 50 == 0 or batch_num == total_batches:
            print(f"  ✓ Batch {batch_num:,}/{total_batches:,} ({upserted:,}/{len(vectors):,} vectors)")

        time.sleep(0.1)

    print(f"✅ Pinecone upsert complete: {upserted:,} vectors")
    return upserted


def main():
    parser = argparse.ArgumentParser(description="Process NSDI backup and upload to DynamoDB/Pinecone")
    parser.add_argument("--limit", type=int, help="Limit number of records to process")
    parser.add_argument("--embeddings", action="store_true", help="Generate embeddings")
    parser.add_argument("--pinecone", action="store_true", help="Upload to Pinecone")
    parser.add_argument("--filter-bounds", type=str, help="Filter by bounds: min_lat,max_lat,min_lon,max_lon")
    parser.add_argument("--skip-dynamodb", action="store_true", help="Skip DynamoDB upload")
    parser.add_argument("--dry-run", action="store_true", help="Process but don't upload")
    parser.add_argument("--input", type=str, default=BACKUP_FILE, help="Input JSON file path")
    parser.add_argument("--include-geometry", action="store_true",
                        help="Include full geometry (WARNING: may exceed 400KB limit)")
    args = parser.parse_args()

    print("=" * 70)
    print("🚀 NSDI Backup Processor")
    print("=" * 70)
    print(f"  AWS Region: {AWS_REGION}")
    print(f"  DynamoDB Table: {DYNAMODB_TABLE_NAME}")
    print(f"  Input File: {args.input}")
    print(f"  Geohash Library: {'pygeohash' if GEOHASH_AVAILABLE else 'simple fallback'}")
    print(f"  Include Geometry: {args.include_geometry}")
    if args.dry_run:
        print("  ⚠️  DRY RUN MODE - No data will be written")

    if args.include_geometry:
        print("\n  ⚠️  WARNING: Including full geometry may exceed DynamoDB's 400KB limit.")

    bounds = None
    if args.filter_bounds:
        try:
            bounds = tuple(map(float, args.filter_bounds.split(",")))
            if len(bounds) != 4:
                raise ValueError()
        except Exception:
            print("❌ Invalid bounds format. Use: min_lat,max_lat,min_lon,max_lon")
            sys.exit(1)

    features = load_backup_file(args.input, limit=args.limit, bounds=bounds)
    if not features:
        print("❌ No features to process")
        sys.exit(1)

    print(f"\n⚙️  Processing {len(features):,} features...")
    processed_items = []
    errors = []

    for idx, feature in enumerate(features):
        try:
            item = GeoJSONProcessor.process_feature(feature, include_geometry=args.include_geometry)
            processed_items.append(item)
        except Exception as e:
            errors.append(f"Feature {idx}: {e}")
            if len(errors) <= 5:
                print(f"  ⚠️  Failed to process feature {idx}: {e}")

    print(f"  ✓ Processed {len(processed_items):,} items")
    if errors:
        print(f"  ⚠️  {len(errors)} processing errors")

    # Size stats
    sizes = [estimate_item_size(item) for item in processed_items]
    avg_size = sum(sizes) / len(sizes) if sizes else 0
    max_size = max(sizes) if sizes else 0
    oversized = sum(1 for s in sizes if s > DYNAMODB_ITEM_LIMIT_BYTES)

    print("\n📏 Item Size Statistics:")
    print(f"   Average: {avg_size / 1024:.1f}KB")
    print(f"   Maximum: {max_size / 1024:.1f}KB")
    print(f"   Oversized (>400KB): {oversized}" if oversized else "   ✓ All items within 400KB limit")

    # Embeddings
    embeddings: List[Optional[List[float]]] = [None] * len(processed_items)

    if args.embeddings or args.pinecone:
        method = EMBEDDING_METHOD if EMBEDDING_METHOD != "none" else "local"
        print(f"\n🤖 Generating embeddings using method: {method}")
        generator = EmbeddingGenerator(method=method, model=EMBEDDING_MODEL)
        embeddings = generator.batch_generate(processed_items)
        valid = sum(1 for e in embeddings if e is not None)
        print(f"  ✓ Generated {valid:,} embeddings")

    # DynamoDB
    if not args.skip_dynamodb:
        ingest_to_dynamodb(processed_items, DYNAMODB_TABLE_NAME, dry_run=args.dry_run)

    # Pinecone
    if args.pinecone:
        upsert_to_pinecone(processed_items, embeddings, dry_run=args.dry_run)

    print("\n" + "=" * 70)
    print("✅ Processing Complete!")
    print("=" * 70)
    print("\n📊 Summary:")
    print(f"  - Input features: {len(features):,}")
    print(f"  - Processed items: {len(processed_items):,}")
    print(f"  - Processing errors: {len(errors)}")
    if not args.skip_dynamodb:
        print(f"  - DynamoDB table: {DYNAMODB_TABLE_NAME}")
    if args.pinecone:
        print(f"  - Pinecone index: {PINECONE_INDEX_NAME} (ns: {PINECONE_NAMESPACE})")
    if args.dry_run:
        print("  ⚠️  DRY RUN - No data was written")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
