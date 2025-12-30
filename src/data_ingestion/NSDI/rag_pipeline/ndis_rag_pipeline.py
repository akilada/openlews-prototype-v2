"""
NSDI GeoJSON RAG Ingestion Pipeline
Downloads hazard zone data from NSDI API and ingests into:
1. DynamoDB (openlews-dev-hazard-zones) - for spatial queries
2. Pinecone (lews-geological-knowledge) - for RAG/semantic search

Uses shared GeoJSONProcessor for consistent geohash handling.

Usage:
    # Download and process all records
    python ndis_rag_pipeline.py
    
    # Filter by bounds (for testing with smaller dataset)
    python ndis_rag_pipeline.py --filter-bounds 6.8,7.2,80.8,81.2
    
    # Limit records (for testing)
    python ndis_rag_pipeline.py --limit 1000
    
    # Skip Pinecone upload
    python ndis_rag_pipeline.py --skip-pinecone
    
    # Dry run (don't upload, just process)
    python ndis_rag_pipeline.py --dry-run
"""

import requests
import json
import time
import os
import sys
import argparse
from typing import List, Dict, Optional
import boto3

# Optional imports
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Import shared processor
from geo_processor import GeoJSONProcessor, GeoHashCalculator, estimate_item_size

# CONFIGURATION
NSDI_BASE_URL = "https://gisapps.nsdi.gov.lk/server/rest/services/SLNSDI/Geo_Scientific_Information/MapServer/8"
NSDI_QUERY_URL = f"{NSDI_BASE_URL}/query"

# AWS Configuration
AWS_REGION = os.getenv("AWS_REGION", "")
DYNAMODB_TABLE_NAME = os.getenv("DYNAMODB_TABLE_NAME", "")

# Pinecone Configuration
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", None)
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "")
PINECONE_NAMESPACE = os.getenv("PINECONE_NAMESPACE", "")

# Embedding Configuration
EMBEDDING_METHOD = os.getenv("EMBEDDING_METHOD", "local")  # "openai", "local", "none"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)


class NSDIDownloader:
    """Downloads GeoJSON data from NSDI ArcGIS API"""
    
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.query_url = f"{base_url}/query"
        
    def download_all_features(self, batch_size: int = 1000, bounds: Optional[tuple] = None) -> List[Dict]:
        """
        Download all features from the NSDI layer.
        
        Args:
            batch_size: Number of records per batch (max 1000 for ArcGIS)
            bounds: Optional (min_lat, max_lat, min_lon, max_lon) for spatial filter
            
        Returns:
            List of GeoJSON feature dictionaries
        """
        print(f"🌍 Downloading from NSDI: {self.base_url}")
        
        all_features = []
        offset = 0
        
        # Build spatial filter if bounds provided
        where_clause = "1=1"
        if bounds:
            min_lat, max_lat, min_lon, max_lon = bounds
            print(f"  🗺️  Applying bounds filter: lat [{min_lat}, {max_lat}], lon [{min_lon}, {max_lon}]")
        
        while True:
            params = {
                "where": where_clause,
                "outFields": "*",
                "f": "json",
                "returnGeometry": "true",
                "resultOffset": offset,
                "resultRecordCount": batch_size
            }
            
            try:
                print(f"  Fetching records {offset:,} to {offset + batch_size:,}...")
                resp = requests.get(self.query_url, params=params, timeout=60)
                
                if resp.status_code != 200:
                    print(f"  ❌ Error: Server returned {resp.status_code}")
                    break
                    
                data = resp.json()
                
                if "error" in data:
                    print(f"  ❌ ArcGIS Error: {data['error']}")
                    break
                    
                features = data.get("features", [])
                
                if not features:
                    print(f"  ✅ Download complete: {len(all_features):,} total records")
                    break
                
                # Apply bounds filter locally if specified
                if bounds:
                    min_lat, max_lat, min_lon, max_lon = bounds
                    filtered = []
                    for feature in features:
                        centroid_lat, centroid_lon = GeoJSONProcessor.extract_centroid(
                            feature.get("geometry", {})
                        )
                        if min_lat <= centroid_lat <= max_lat and min_lon <= centroid_lon <= max_lon:
                            filtered.append(feature)
                    features = filtered
                
                all_features.extend(features)
                offset += batch_size
                
                # Progress update
                if offset % 10000 == 0:
                    print(f"  📊 Progress: {len(all_features):,} features downloaded...")
                
                # Be polite to government servers
                time.sleep(0.3)
                
            except requests.exceptions.Timeout:
                print(f"  ⚠️  Timeout at offset {offset}, retrying...")
                time.sleep(2)
                continue
            except Exception as e:
                print(f"  ❌ Connection Failed: {e}")
                break
                
        return all_features


class EmbeddingGenerator:
    """Generates embeddings for semantic search"""
    
    def __init__(self, method: str = "local", model: str = "all-MiniLM-L6-v2"):
        self.method = method
        self.model = model
        self.encoder = None
        
        if method == "local":
            try:
                from sentence_transformers import SentenceTransformer
                print(f"  Loading embedding model: {model}...")
                self.encoder = SentenceTransformer(model)
                print("  ✅ Loaded local embedding model")
            except ImportError:
                print("  ⚠️  sentence-transformers not installed. Run: pip install sentence-transformers")
                self.method = "none"
        
        elif method == "openai":
            print("  ⚠️  OpenAI embeddings not yet implemented")
            self.method = "none"
    
    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding vector from text"""
        if self.method == "none" or not self.encoder:
            return None
        
        try:
            embedding = self.encoder.encode(text)
            return embedding.tolist()
        except Exception as e:
            print(f"  ⚠️  Embedding error: {e}")
            return None
    
    def batch_generate(self, items: List[Dict]) -> List[Optional[List[float]]]:
        """Generate embeddings for a batch of items"""
        if self.method == "none" or not self.encoder:
            return [None] * len(items)
        
        # Use shared text generator
        texts = [GeoJSONProcessor.generate_embedding_text(item) for item in items]
        
        try:
            embeddings = self.encoder.encode(texts, show_progress_bar=True)
            return [emb.tolist() for emb in embeddings]
        except Exception as e:
            print(f"  ⚠️  Batch embedding error: {e}")
            return [None] * len(items)


class DynamoDBIngester:
    """Ingests processed features into DynamoDB"""
    
    def __init__(self, table_name: str):
        self.table = dynamodb.Table(table_name)
        self.table_name = table_name
        
    def ingest_items(self, items: List[Dict], batch_size: int = 25, dry_run: bool = False) -> int:
        """Batch insert items into DynamoDB"""
        print(f"\n📊 {'[DRY RUN] ' if dry_run else ''}Ingesting {len(items):,} items into DynamoDB: {self.table_name}")
        
        if dry_run:
            print("  ⚠️  Dry run mode - no data will be written")
            # Check for oversized items
            oversized = [(item['zone_id'], estimate_item_size(item)) 
                        for item in items if estimate_item_size(item) > 400 * 1024]
            if oversized:
                print(f"  ⚠️  {len(oversized)} items exceed 400KB limit")
            return len(items)
        
        inserted_count = 0
        failed_items = []
        oversized_items = []
        total_batches = (len(items) + batch_size - 1) // batch_size
        
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            batch_num = i // batch_size + 1
            
            with self.table.batch_writer() as writer:
                for item in batch:
                    try:
                        # Check item size before inserting
                        item_size = estimate_item_size(item)
                        if item_size > 400 * 1024:
                            oversized_items.append((item['zone_id'], item_size))
                            continue
                        
                        writer.put_item(Item=item)
                        inserted_count += 1
                    except Exception as e:
                        error_msg = str(e)
                        if "size has exceeded" in error_msg.lower():
                            oversized_items.append((item['zone_id'], estimate_item_size(item)))
                        else:
                            failed_items.append((item['zone_id'], str(e)))
                            if len(failed_items) <= 5:
                                print(f"  ❌ Failed to insert {item['zone_id']}: {e}")
            
            # Progress update
            if batch_num % 100 == 0 or batch_num == total_batches:
                print(f"  ✓ Batch {batch_num:,}/{total_batches:,} ({inserted_count:,}/{len(items):,})")
            
            time.sleep(0.05)
        
        print(f"✅ DynamoDB ingestion complete: {inserted_count:,}/{len(items):,} items")
        
        if oversized_items:
            print(f"⚠️  Skipped {len(oversized_items)} oversized items (>400KB)")
        if failed_items:
            print(f"⚠️  Failed items: {len(failed_items)}")
        
        return inserted_count


class PineconeIngester:
    """Ingests embeddings into Pinecone for RAG"""
    
    def __init__(self, api_key: Optional[str], index_name: str):
        self.api_key = api_key
        self.index_name = index_name
        self.index = None
        
        if api_key:
            try:
                from pinecone import Pinecone
                pc = Pinecone(api_key=api_key)
                self.index = pc.Index(index_name)
                print(f"  ✅ Connected to Pinecone index: {index_name}")
            except ImportError:
                print("  ⚠️  pinecone-client not installed. Run: pip install pinecone-client")
            except Exception as e:
                print(f"  ⚠️  Pinecone initialization failed: {e}")
    
    def ingest_vectors(self, items: List[Dict], embeddings: List[List[float]], 
                       batch_size: int = 100, dry_run: bool = False) -> int:
        """Upsert vectors into Pinecone"""
        if not self.index:
            print("  ⚠️  Pinecone not available. Skipping vector ingestion.")
            return 0
        
        print(f"\n🔍 {'[DRY RUN] ' if dry_run else ''}Ingesting {len(embeddings):,} vectors into Pinecone")
        
        vectors = []
        for item, embedding in zip(items, embeddings):
            if embedding is None:
                continue
            
            vector_id = item["zone_id"]
            metadata = {
                "zone_id": item["zone_id"],
                "level": item["level"],
                "hazard_level": item["hazard_level"],
                "centroid_lat": float(item["centroid_lat"]),
                "centroid_lon": float(item["centroid_lon"]),
                "geohash": item["geohash"],
                "district": item.get("district", "Unknown"),
                "ds_division": item.get("ds_division", "Unknown"),
                "soil_type": item.get("soil_type", "Unknown"),
                "area_sqm": float(item["metadata"]["shape_area"]),
                "source": "NSDI"
            }
            
            vectors.append({
                "id": vector_id,
                "values": embedding,
                "metadata": metadata
            })
        
        if dry_run:
            print(f"  ⚠️  Dry run mode - would upsert {len(vectors):,} vectors")
            return len(vectors)
        
        # Upsert in batches
        upserted_count = 0
        total_batches = (len(vectors) + batch_size - 1) // batch_size
        
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i:i + batch_size]
            batch_num = i // batch_size + 1
            try:
                self.index.upsert(vectors=batch, namespace=PINECONE_NAMESPACE)
                upserted_count += len(batch)
                
                if batch_num % 50 == 0 or batch_num == total_batches:
                    print(f"  ✓ Batch {batch_num:,}/{total_batches:,} ({upserted_count:,}/{len(vectors):,})")
            except Exception as e:
                print(f"  ❌ Failed to upsert batch: {e}")
            
            time.sleep(0.1)
        
        print(f"✅ Pinecone ingestion complete: {upserted_count:,}/{len(vectors):,} vectors")
        return upserted_count


def main():
    """Main RAG ingestion pipeline"""
    
    parser = argparse.ArgumentParser(description="NSDI RAG Ingestion Pipeline")
    parser.add_argument("--limit", type=int, help="Limit number of records to process")
    parser.add_argument("--filter-bounds", type=str, help="Filter by bounds: min_lat,max_lat,min_lon,max_lon")
    parser.add_argument("--skip-pinecone", action="store_true", help="Skip Pinecone upload")
    parser.add_argument("--skip-dynamodb", action="store_true", help="Skip DynamoDB upload")
    parser.add_argument("--skip-backup", action="store_true", help="Skip saving backup file")
    parser.add_argument("--dry-run", action="store_true", help="Process but don't upload")
    parser.add_argument("--embedding-method", type=str, default=EMBEDDING_METHOD, 
                        choices=["local", "openai", "none"], help="Embedding method")
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("🚀 NSDI GeoJSON RAG Ingestion Pipeline")
    print("=" * 70)
    print(f"  AWS Region: {AWS_REGION}")
    print(f"  DynamoDB Table: {DYNAMODB_TABLE_NAME}")
    print(f"  Embedding Method: {args.embedding_method}")
    print(f"  Geohash Library: {'pygeohash' if GeoHashCalculator.is_real_geohash() else 'simple fallback'}")
    if args.dry_run:
        print("  ⚠️  DRY RUN MODE - No data will be written")
    
    # Parse bounds if provided
    bounds = None
    if args.filter_bounds:
        try:
            parts = [p.strip() for p in args.filter_bounds.split(",")]
            bounds = tuple(float(p) for p in parts)
            if len(bounds) != 4:
                raise ValueError("Expected 4 comma-separated numbers")

            min_lat, max_lat, min_lon, max_lon = bounds
            if min_lat > max_lat or min_lon > max_lon:
                raise ValueError("Min values must be <= max values")

            print(f"  🗺️  Filtering by bounds: {bounds}")
        except ValueError as e:
            print("❌ Invalid bounds format. Use: min_lat,max_lat,min_lon,max_lon")
            print(f"   Details: {e}")
            sys.exit(1)
    
    downloader = NSDIDownloader(NSDI_BASE_URL)
    features = downloader.download_all_features(bounds=bounds)
    
    if not features:
        print("❌ No features downloaded. Exiting.")
        return
    
    if args.limit:
        features = features[:args.limit]
        print(f"  📊 Limited to {len(features):,} features")
    
    # Save raw data backup
    if not args.skip_backup:
        print("\n💾 Saving raw GeoJSON backup...")
        backup_filename = "ndis_raw_backup.json"
        with open(backup_filename, "w") as f:
            json.dump({"type": "FeatureCollection", "features": features}, f)
        print(f"  ✓ Saved to {backup_filename}")
    
    print(f"\n⚙️  Processing {len(features):,} features...")
    processed_items = []
    errors = []
    
    for idx, feature in enumerate(features):
        try:
            item = GeoJSONProcessor.process_feature(feature, source_url=NSDI_BASE_URL)
            processed_items.append(item)
        except Exception as e:
            errors.append(f"Feature {idx}: {e}")
            if len(errors) <= 5:
                print(f"  ⚠️  Failed to process feature: {e}")
    
    print(f"  ✓ Processed {len(processed_items):,} items")
    if errors:
        print(f"  ⚠️  {len(errors)} processing errors")
    
    if processed_items:
        sample = processed_items[0]
        print("\n📋 Sample processed item:")
        print(f"   zone_id: {sample['zone_id']}")
        print(f"   level: {sample['level']}")
        print(f"   hazard_level: {sample['hazard_level']}")
        print(f"   district: {sample.get('district', 'N/A')}")
        print(f"   geohash: {sample['geohash']}")
    
    embeddings = []
    if args.embedding_method != "none" and not args.skip_pinecone:
        print(f"\n🤖 Generating embeddings using method: {args.embedding_method}")
        embedding_gen = EmbeddingGenerator(method=args.embedding_method, model=EMBEDDING_MODEL)
        embeddings = embedding_gen.batch_generate(processed_items)
        valid_count = sum(1 for e in embeddings if e is not None)
        print(f"  ✓ Generated {valid_count:,} embeddings")
    
    if not args.skip_dynamodb:
        dynamodb_ingester = DynamoDBIngester(DYNAMODB_TABLE_NAME)
        dynamodb_ingester.ingest_items(processed_items, dry_run=args.dry_run)
    
    if not args.skip_pinecone and PINECONE_API_KEY and embeddings:
        pinecone_ingester = PineconeIngester(PINECONE_API_KEY, PINECONE_INDEX_NAME)
        pinecone_ingester.ingest_vectors(processed_items, embeddings, dry_run=args.dry_run)
    
    # Summary
    print("\n" + "=" * 70)
    print("✅ RAG Ingestion Pipeline Complete!")
    print("=" * 70)
    print(f"  📥 Downloaded: {len(features):,} features from NSDI")
    print(f"  ⚙️  Processed: {len(processed_items):,} items")
    if not args.skip_dynamodb:
        print(f"  📊 DynamoDB: {DYNAMODB_TABLE_NAME}")
    if embeddings:
        valid_count = sum(1 for e in embeddings if e is not None)
        print(f"  🔍 Embeddings: {valid_count:,} vectors")
    if args.dry_run:
        print("  ⚠️  DRY RUN - No data was written")
    
    print("\n📋 Next Steps:")
    print("  1. Verify data in DynamoDB:")
    print(f"     aws dynamodb scan --table-name {DYNAMODB_TABLE_NAME} --max-items 5 --region {AWS_REGION}")
    print("  2. Test spatial queries using geohash")
    print("  3. Rebuild and deploy Lambda functions")
    print("")


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
