# NDIS RAG Ingestion Pipeline - Usage Guide

## 🎯 What This Does

This pipeline downloads hazard zone data from Sri Lanka's NDIS (National Spatial Data Infrastructure) and ingests it into your OpenLEWS system for:

1. **Spatial Queries** - Find hazard zones by location (via DynamoDB)
2. **Semantic Search** - Ask questions about geological data (via Pinecone RAG)
3. **Contextual Verification** - LLM validates sensor readings against official hazard zones

---

## 📦 Installation

```bash
# Navigate to data ingestion directory
cd ~/git/personal/openlews-prototype/src/data_ingestion/ndis

# Install dependencies
pip install -r requirements.txt

# Note: sentence-transformers is large (~500MB). 
# For faster start, you can skip embeddings initially:
pip install requests boto3 python-dotenv
```

---

## ⚙️ Configuration

### Option 1: Environment Variables (Recommended)

```bash
# Set AWS configuration
export AWS_REGION=ap-southeast-2
export DYNAMODB_TABLE_NAME=openlews-dev-hazard-zones

# Optional: Set Pinecone API key (if using Pinecone)
export PINECONE_API_KEY=your-pinecone-api-key-here
```

### Option 2: Get Pinecone API Key from Secrets Manager

```bash
# Retrieve from AWS Secrets Manager
SECRET_JSON=$(aws secretsmanager get-secret-value \
  --secret-id openlews-dev/pinecone/api-key \
  --region ap-southeast-2 \
  --query SecretString \
  --output text)

# Extract API key
export PINECONE_API_KEY=$(echo $SECRET_JSON | python3 -c "import sys, json; print(json.load(sys.stdin)['api_key'])")
```

---

## 🚀 Running the Pipeline

### Basic Run (DynamoDB only, no embeddings)

```bash
cd ~/git/personal/openlews-prototype/src/data_ingestion

# Run with default settings
python ndis_rag_pipeline.py
```

This will:
1. ✅ Download all NDIS hazard zones (~200-300 polygons)
2. ✅ Process and calculate centroids/geohashes
3. ✅ Insert into DynamoDB table
4. ⏭️ Skip embeddings (faster, no ML dependencies)

**Time**: ~2-3 minutes  
**Cost**: ~$0.02 (DynamoDB writes)

---

### Advanced Run (with Pinecone RAG)

First, sign up for Pinecone and create an index:

#### 1. Create Pinecone Index

Go to https://www.pinecone.io/ and:
- Sign up (free tier)
- Create index:
  - **Name**: `lews-geological-knowledge`
  - **Dimensions**: `384` (for all-MiniLM-L6-v2 model)
  - **Metric**: `cosine`
  - **Region**: `us-east-1`

#### 2. Install Embedding Dependencies

```bash
pip install sentence-transformers pinecone-client
```

#### 3. Run with Embeddings

```bash
# Set Pinecone API key
export PINECONE_API_KEY=your-key-here

# Run pipeline
python ndis_rag_pipeline.py
```

This will:
1. ✅ Download NDIS data
2. ✅ Generate embeddings for each hazard zone
3. ✅ Insert into DynamoDB
4. ✅ Upsert vectors into Pinecone

**Time**: ~10-15 minutes (first run downloads 500MB model)  
**Cost**: ~$0.02 (free Pinecone tier)

---

## 📊 Verify Data Ingestion

### Check DynamoDB

```bash
# Count total records
aws dynamodb describe-table \
  --table-name openlews-dev-hazard-zones \
  --region ap-southeast-2 \
  --query 'Table.ItemCount'

# View first 5 records
aws dynamodb scan \
  --table-name openlews-dev-hazard-zones \
  --max-items 5 \
  --region ap-southeast-2
```

### Check Pinecone (if enabled)

```python
import pinecone

pinecone.init(api_key="your-key")
index = pinecone.Index("lews-geological-knowledge")

# Check stats
print(index.describe_index_stats())

# Test query
results = index.query(
    vector=[0.1] * 384,  # Dummy vector
    top_k=5,
    include_metadata=True
)
print(results)
```

---

## 🔍 Query Examples

### Spatial Query (DynamoDB)

Find hazard zone at a specific location:

```python
import boto3
from decimal import Decimal

dynamodb = boto3.resource('dynamodb', region_name='ap-southeast-2')
table = dynamodb.Table('openlews-dev-hazard-zones')

# Calculate geohash for location (6.85, 80.93)
lat, lon = 6.85, 80.93
lat_bin = int((lat + 90) * 1000)
lon_bin = int((lon + 180) * 1000)
geohash = f"{lat_bin:06d}{lon_bin:07d}"[:6]

# Query by geohash
response = table.query(
    IndexName='GeoHashIndex',  # Assuming you add this GSI
    KeyConditionExpression='geohash = :gh',
    ExpressionAttributeValues={':gh': geohash}
)

for item in response['Items']:
    print(f"Zone: {item['zone_id']}, Level: {item['level']}")
```

### Semantic Query (Pinecone RAG)

Ask questions about hazard zones:

```python
from sentence_transformers import SentenceTransformer
import pinecone

# Initialize
model = SentenceTransformer('all-MiniLM-L6-v2')
pinecone.init(api_key="your-key")
index = pinecone.Index("lews-geological-knowledge")

# Ask a question
query_text = "Find high hazard zones near Badulla district"
query_vector = model.encode(query_text).tolist()

# Search
results = index.query(
    vector=query_vector,
    top_k=5,
    include_metadata=True,
    filter={"level": "High"}  # Filter by hazard level
)

for match in results['matches']:
    print(f"Zone: {match['metadata']['zone_id']}")
    print(f"  Level: {match['metadata']['level']}")
    print(f"  Location: ({match['metadata']['centroid_lat']}, {match['metadata']['centroid_lon']})")
    print(f"  Score: {match['score']}")
```

---

## 🔧 Customization

### Change Embedding Model

Edit `ndis_rag_pipeline.py`:

```python
# Line ~26
EMBEDDING_METHOD = "local"
EMBEDDING_MODEL = "all-mpnet-base-v2"  # Higher quality, 768 dimensions

# Or use OpenAI
EMBEDDING_METHOD = "openai"
EMBEDDING_MODEL = "text-embedding-ada-002"  # 1536 dimensions
```

**Note**: If changing model, update Pinecone index dimensions accordingly!

### Add Custom Metadata

Edit the `process_feature()` method to extract more NDIS fields:

```python
# In GeoJSONProcessor.process_feature() around line 150
item = {
    "zone_id": zone_id,
    "version": version,
    "level": level,
    # ... existing fields ...
    "metadata": {
        # Add more NDIS fields here
        "district": attributes.get("District", "Unknown"),
        "ds_division": attributes.get("DS_Division", "Unknown"),
        "gn_division": attributes.get("GN_Division", "Unknown"),
        # etc.
    }
}
```

---

## 🐛 Troubleshooting

### Error: `DynamoDB table not found`

**Solution**: Verify your table name:
```bash
aws dynamodb list-tables --region ap-southeast-2 | grep hazard
```

### Error: `Pinecone index not found`

**Solution**: Create the index first (see Advanced Run section above)

### Error: `sentence-transformers not installed`

**Solution**: 
```bash
pip install sentence-transformers
# Or skip embeddings by setting EMBEDDING_METHOD = "none"
```

### NDIS API returns 0 records

**Solution**: Check if NDIS is accessible:
```bash
curl "https://gisapps.nsdi.gov.lk/server/rest/services/SLNSDI/Geo_Scientific_Information/MapServer/8/query?where=1=1&f=json&returnCountOnly=true"
```

If it returns an error, the API might be down. Try again later.

---

## 📈 Performance Optimization

### Batch Size Tuning

```python
# For faster download (if NDIS allows)
features = downloader.download_all_features(batch_size=2000)

# For faster DynamoDB ingestion
dynamodb_ingester.ingest_items(processed_items, batch_size=25)
```

### Skip Embedding Generation

For quick testing without Pinecone:

```python
# Edit line ~26
EMBEDDING_METHOD = "none"
```

This skips the slow embedding step and only ingests into DynamoDB.

---

## 🔄 Re-running the Pipeline

### Full Re-ingestion

```bash
# Delete all existing records (careful!)
aws dynamodb scan \
  --table-name openlews-dev-hazard-zones \
  --region ap-southeast-2 \
  | jq -r '.Items[] | [.zone_id.S, .version.N] | @tsv' \
  | while read zone_id version; do
      aws dynamodb delete-item \
        --table-name openlews-dev-hazard-zones \
        --key "{\"zone_id\":{\"S\":\"$zone_id\"},\"version\":{\"N\":\"$version\"}}"
    done

# Re-run pipeline
python ndis_rag_pipeline.py
```

### Incremental Updates

The pipeline uses `version` numbers. To update:

```python
# Edit process_feature() to increment version
item = processor.process_feature(feature, version=2)
```

---

## 💰 Cost Estimate

| Component | Usage | Cost |
|-----------|-------|------|
| NDIS API | Free | $0 |
| DynamoDB Writes | ~300 items | $0.02 |
| DynamoDB Storage | ~1 MB | $0.0003/month |
| Pinecone | Free tier | $0 |
| sentence-transformers | Local | $0 |
| **Total** | One-time | **~$0.02** |

**Monthly recurring**: <$0.01 (just DynamoDB storage)

---

## 🎯 Next Steps After Ingestion

1. **Build RAG Query Lambda** - Lambda that queries Pinecone when sensor anomaly detected
2. **Add to Detection Algorithm** - Contextual verification (Strategy A from research)
3. **Test with Simulator** - Verify sensor at (6.85, 80.93) gets correct hazard level
4. **Add More Data Sources**:
   - NBRO landslide inventory
   - DMC rainfall archives
   - Soil mechanics papers

---

## 📞 Support

If you encounter issues:
1. Check AWS CloudWatch Logs for errors
2. Verify AWS credentials: `aws sts get-caller-identity`
3. Test NDIS API manually: See troubleshooting section

---

**Happy ingesting! 🚀**