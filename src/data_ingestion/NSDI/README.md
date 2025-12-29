# NSDI Data Ingestion

**NSDI Hazard Zone Data Ingestion Pipeline for DynamoDB and Pinecone**

---

## Overview

The NSDI Data Ingestion module downloads landslide hazard zone data from Sri Lanka's National Spatial Data Infrastructure (NSDI) ArcGIS REST API and ingests it into:

1. **DynamoDB** - For fast geospatial queries via GeoHashIndex
2. **Pinecone** - For semantic/RAG search with embeddings

This data enables the RAG Query Engine to provide geological context for sensor locations.

---

## Directory Structure

```
src/data_ingestion/NSDI/
├── rag_pipeline/
│   ├── ndis_rag_pipeline.py    # Main pipeline: download → process → ingest
│   ├── geo_processor.py        # Shared GeoJSON processing utilities
│   └── process_backup.py       # Process existing backup files
├── scripts/
│   ├── setup_pinecone_index.py # Create Pinecone index
│   ├── analyse_data.py         # Analyze data distribution
│   ├── check_hazard_levels.py  # Check hazard level counts
│   ├── check_pinecone_index.py # Verify Pinecone index stats
│   └── check-location-details.py # Inspect raw data attributes
├── tests/
├── requirements.txt
└── README.md
```

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                     NSDI RAG Ingestion Pipeline                        │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    NSDIDownloader                                │  │
│  │  - Fetches from ArcGIS REST API                                  │  │
│  │  - Paginated downloads (1000 records/batch)                      │  │
│  │  - Optional bounds filtering                                     │  │
│  │  - Saves raw backup to nsdi_raw_backup.json                      │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              ↓                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    GeoJSONProcessor                              │  │
│  │  - Extract centroid from polygon rings                           │  │
│  │  - Compute geohash (precision 4 and 6)                           │  │
│  │  - Normalize hazard levels                                       │  │
│  │  - Calculate bounding box                                        │  │
│  │  - Convert floats to Decimal (DynamoDB)                          │  │
│  │  - Generate embedding text                                       │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              ↓                                         │
│  ┌─────────────────────────┐    ┌───────────────────────────────────┐  │
│  │   DynamoDBIngester      │    │   EmbeddingGenerator              │  │
│  │   - Batch write (25)    │    │   - sentence-transformers         │  │
│  │   - Size validation     │    │   - all-MiniLM-L6-v2 (384 dim)    │  │
│  │   - Error handling      │    │   - Batch encoding                │  │
│  └─────────────────────────┘    └───────────────────────────────────┘  │
│                              ↓                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    PineconeIngester                              │  │
│  │  - Upsert vectors with metadata                                  │  │
│  │  - Batch upsert (100 vectors)                                    │  │
│  │  - Namespace support                                             │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. NSDIDownloader

Downloads hazard zone features from the NSDI ArcGIS REST API:

```python
class NSDIDownloader:
    """Downloads GeoJSON data from NSDI ArcGIS API"""
    
    NSDI_BASE_URL = "https://gisapps.nsdi.gov.lk/server/rest/services/SLNSDI/Geo_Scientific_Information/MapServer/8"
    
    def download_all_features(self, batch_size: int = 1000, bounds: Optional[tuple] = None) -> List[Dict]:
        """
        Download all features from the NSDI layer.
        
        Args:
            batch_size: Number of records per batch (max 1000 for ArcGIS)
            bounds: Optional (min_lat, max_lat, min_lon, max_lon) for spatial filter
        """
```

### 2. GeoJSONProcessor

Shared module for consistent GeoJSON processing:

```python
class GeoJSONProcessor:
    """Processes NSDI GeoJSON features for DynamoDB/Pinecone storage."""
    
    @staticmethod
    def extract_centroid(geometry: Dict) -> Tuple[float, float]:
        """Extract centroid from polygon geometry (ArcGIS rings or GeoJSON)."""
    
    @staticmethod
    def calculate_bounding_box(geometry: Dict) -> Optional[Dict]:
        """Calculate bounding box (saves space vs full geometry)."""
    
    @staticmethod
    def normalize_hazard_level(raw: str) -> str:
        """Normalize hazard level to: Low, Moderate, High, Very High."""
    
    @classmethod
    def process_feature(cls, feature: Dict, version: int = 1, 
                        include_geometry: bool = False) -> Dict:
        """Process a single NSDI feature for DynamoDB storage."""
    
    @staticmethod
    def generate_embedding_text(item: Dict) -> str:
        """Generate text for embeddings with severity anchors."""
```

### 3. GeoHashCalculator

Handles geohash encoding with fallback:

```python
class GeoHashCalculator:
    """Handles geohash calculations with proper library support."""
    
    @staticmethod
    def encode(lat: float, lon: float, precision: int = 6) -> str:
        """Calculate geohash for spatial indexing."""
    
    @staticmethod
    def neighbors(geohash: str) -> List[str]:
        """Get neighboring geohashes for expanded spatial search."""
    
    @staticmethod
    def is_real_geohash() -> bool:
        """Check if pygeohash is available."""
```

### 4. EmbeddingGenerator

Generates embeddings for semantic search:

```python
class EmbeddingGenerator:
    """Generates embeddings for semantic search."""
    
    def __init__(self, method: str = "local", model: str = "all-MiniLM-L6-v2"):
        """Initialize with local sentence-transformers model."""
    
    def batch_generate(self, items: List[Dict]) -> List[Optional[List[float]]]:
        """Generate embeddings for a batch of items."""
```

---

## Data Schema

### Input: NSDI ArcGIS Feature

```json
{
  "attributes": {
    "objectid": 12345,
    "level": "High",
    "district": "Badulla",
    "ds_division": "Haldummulla",
    "gn_division": "Meeriyabedda",
    "soil_type": "Colluvium",
    "land_use": "Tea",
    "st_area(shape)": 125000.5,
    "st_length(shape)": 1850.2
  },
  "geometry": {
    "rings": [[[80.93, 6.85], [80.94, 6.85], ...]]
  }
}
```

### Output: DynamoDB Item

```json
{
  "zone_id": "NSDI_12345",
  "version": 1,
  "level": "High",
  "hazard_level": "High",
  "centroid_lat": 6.855,
  "centroid_lon": 80.935,
  "geohash": "tc1x",
  "geohash4": "tc1x",
  "geohash6": "tc1xyz",
  "district": "Badulla",
  "ds_division": "Haldummulla",
  "gn_division": "Meeriyabedda",
  "soil_type": "Colluvium",
  "landslide_type": "Unknown",
  "land_use": "Tea",
  "bounding_box": {
    "min_lat": 6.84,
    "max_lat": 6.87,
    "min_lon": 80.92,
    "max_lon": 80.95
  },
  "metadata": {
    "objectid": 12345,
    "shape_area": 125000.5,
    "shape_length": 1850.2,
    "geometry_points": 42
  },
  "created_at": 1735430400000,
  "source": "NSDI_API",
  "source_url": "https://gisapps.nsdi.gov.lk/..."
}
```

### Output: Pinecone Vector

```json
{
  "id": "NSDI_12345",
  "values": [0.123, -0.456, ...],
  "metadata": {
    "zone_id": "NSDI_12345",
    "level": "High",
    "hazard_level": "High",
    "centroid_lat": 6.855,
    "centroid_lon": 80.935,
    "geohash": "tc1x",
    "district": "Badulla",
    "ds_division": "Haldummulla",
    "soil_type": "Colluvium",
    "area_sqm": 125000.5,
    "source": "NSDI"
  }
}
```

---

## Embedding Text Generation

The embedding text is structured to anchor hazard severity for semantic queries:

```python
def generate_embedding_text(item: Dict) -> str:
    """Generate text with severity anchors for better semantic matching."""
    level = item.get("hazard_level", "Unknown")
    
    # Severity anchors for semantic matching
    severity_anchors = [
        f"landslide hazard level: {level}",
        f"{level} landslide risk",
        f"risk severity {level}",
    ]
    
    parts = [
        f"NSDI landslide hazard zone {item.get('zone_id', 'Unknown')}.",
        *severity_anchors,
        f"geohash {item.get('geohash', 'unknown')}",
        f"location latitude {float(item.get('centroid_lat', 0.0)):.4f} longitude {float(item.get('centroid_lon', 0.0)):.4f}",
        f"district {item.get('district', 'Unknown')}",
        f"ds division {item.get('ds_division', 'Unknown')}",
        f"gn division {item.get('gn_division', 'Unknown')}",
        f"soil type {item.get('soil_type', 'Unknown')}",
        f"landslide type {item.get('landslide_type', 'Unknown')}",
        f"land use {item.get('land_use', 'Unknown')}",
    ]
    
    return " | ".join(parts)
```

---

## Usage

### Initial Setup

```bash
# Install dependencies
cd src/data_ingestion/NSDI
pip install -r requirements.txt

# Create .env file
cat > .env << EOF
AWS_REGION=ap-south-1
DYNAMODB_TABLE_NAME=openlews-dev-hazard-zones
PINECONE_API_KEY=your-api-key
PINECONE_INDEX_NAME=lews-geological-knowledge
PINECONE_NAMESPACE=
EMBEDDING_METHOD=local
EMBEDDING_MODEL=all-MiniLM-L6-v2
EOF

# Setup Pinecone index (384 dimensions for all-MiniLM-L6-v2)
python scripts/setup_pinecone_index.py
```

### Main Pipeline

```bash
# Download and ingest ALL records
python rag_pipeline/ndis_rag_pipeline.py

# Filter by geographic bounds (for testing)
python rag_pipeline/ndis_rag_pipeline.py --filter-bounds 6.8,7.2,80.8,81.2

# Limit number of records
python rag_pipeline/ndis_rag_pipeline.py --limit 1000

# Skip Pinecone upload (DynamoDB only)
python rag_pipeline/ndis_rag_pipeline.py --skip-pinecone

# Dry run (process but don't upload)
python rag_pipeline/ndis_rag_pipeline.py --dry-run
```

### Process Existing Backup

```bash
# Process ALL records from backup file
python rag_pipeline/process_backup.py

# With embeddings and Pinecone upsert
python rag_pipeline/process_backup.py --embeddings --pinecone

# Filter by bounds
python rag_pipeline/process_backup.py --filter-bounds 6.8,7.2,80.8,81.2 --embeddings --pinecone

# Dry run test
python rag_pipeline/process_backup.py --limit 500 --dry-run --embeddings --pinecone
```

### Analysis Scripts

```bash
# Analyze hazard level distribution
python scripts/analyse_data.py

# Check DynamoDB hazard levels
python scripts/check_hazard_levels.py

# Check Pinecone index stats
python scripts/check_pinecone_index.py

# Inspect raw data attributes
python scripts/check-location-details.py
```

---

## Configuration

### Environment Variables

```bash
# AWS
AWS_REGION=ap-south-1
DYNAMODB_TABLE_NAME=openlews-dev-hazard-zones

# Pinecone
PINECONE_API_KEY=your-api-key
PINECONE_INDEX_NAME=lews-geological-knowledge
PINECONE_NAMESPACE=            # Optional namespace

# Embeddings
EMBEDDING_METHOD=local         # local, openai, or none
EMBEDDING_MODEL=all-MiniLM-L6-v2

# For setup_pinecone_index.py
PINECONE_DIMENSION=384         # Must match embedding model
PINECONE_METRIC=cosine
PINECONE_CLOUD=aws
PINECONE_REGION=us-east-1
```

### Pinecone Index Configuration

The `setup_pinecone_index.py` script creates a serverless index:

| Setting | Value | Notes |
|---------|-------|-------|
| Dimension | 384 | Matches all-MiniLM-L6-v2 |
| Metric | cosine | Similarity metric |
| Cloud | aws | Cloud provider |
| Region | us-east-1 | Pinecone region |

---

## Data Statistics

After running the pipeline `--filter-bounds 6.8,7.2,80.8,81.2`:

| Metric | Value |
|--------|-------|
| Total NSDI Features | ~19,000+ |
| DynamoDB Items | ~19,000+ |
| Pinecone Vectors | ~19,000+ |
| Average Item Size | ~2-3 KB |
| Max Item Size | <400 KB |

### Hazard Level Distribution (Example)

```
Hazard Level Distribution:
----------------------------------------
High            8,234 ( 42.8%) ████████████████████
Moderate        6,891 ( 35.8%) █████████████████
Low             2,456 ( 12.8%) ██████
Very High       1,666 (  8.6%) ████
```

---

## DynamoDB Size Handling

The pipeline avoids the 400KB DynamoDB item limit:

```python
DYNAMODB_ITEM_LIMIT_BYTES = 400 * 1024

def estimate_item_size(item: Dict) -> int:
    """Estimate size in bytes for DynamoDB 400KB limit checks."""
    import json
    return len(json.dumps(item, default=str).encode("utf-8"))

# By default, full geometry is NOT included (use bounding_box instead)
# Use --include-geometry flag only if needed (warning: may exceed limit)
```

---

## Error Handling

| Error | Handling |
|-------|----------|
| NSDI API timeout | Retry with 2-second delay |
| Invalid geometry | Skip feature, log warning |
| DynamoDB throttle | Automatic retry (batch_writer) |
| Pinecone rate limit | 0.1s delay between batches |
| Item >400KB | Skip and log warning |
| Missing pygeohash | Fall back to simple coordinate hash |

---

## Dependencies

```
# Core
boto3>=1.34.0,<2.0.0
python-dotenv>=1.0.0,<2.0.0
requests>=2.31.0,<3.0.0

# Geospatial
pygeohash>=1.2.0,<2.0.0

# Embeddings
sentence-transformers>=2.2.0,<3.0.0

# Pinecone (Python 3.9 compatible)
pinecone>=7.3.0,<8.0.0
```

---

## Verification

### Check DynamoDB

```bash
# Scan first 5 items
aws dynamodb scan \
  --table-name openlews-dev-hazard-zones \
  --max-items 5 \
  --region ap-south-1

# Query by geohash
aws dynamodb query \
  --table-name openlews-dev-hazard-zones \
  --index-name GeoHashIndex \
  --key-condition-expression "geohash = :gh" \
  --expression-attribute-values '{":gh": {"S": "tc1x"}}' \
  --max-items 5
```

### Check Pinecone

```python
from pinecone import Pinecone
import os

pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index = pc.Index("lews-geological-knowledge")
print(index.describe_index_stats())
```

---

## Related Components

- [RAG Query Engine](../../lambdas/rag/README.md) - Consumes hazard zone data
- [Detection Engine](../../lambdas/detector/README.md) - Uses RAG for context
- [Infrastructure](../../infrastructure/README.md) - DynamoDB table setup