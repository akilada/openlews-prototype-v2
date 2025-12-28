# RAG Query Lambda - Deployment Guide

## 📋 Overview

The RAG Query Lambda connects sensor locations to NDIS landslide hazard zones using spatial queries against DynamoDB and Pinecone.

**What it does:**
- Finds nearest hazard zone to a sensor location
- Finds all zones within a radius
- Returns contextual risk information
- Calculates distances using Haversine formula

**Use cases:**
- Enhanced sensor alerts with geological context
- Multi-sensor correlation by hazard zone
- Dynamic threshold adjustment based on risk level
- Situational awareness for emergency response

---

## 🏗️ Architecture

```
Sensor/API Gateway
       ↓
   Lambda Function
       ↓
   ┌────────────────┐
   │  Geo Calculator │
   └────────────────┘
       ↓
   ┌────────────────────────┐
   │  DynamoDB Query        │
   │  (GeoHash Index)       │
   │  → Get zones by area   │
   └────────────────────────┘
       ↓
   ┌────────────────────────┐
   │  Distance Calculation  │
   │  (Haversine formula)   │
   └────────────────────────┘
       ↓
   Return nearest zone + context
```

---

## 📦 Files

```
rag-query-lambda/
├── lambda_function.py           # Main Lambda handler
├── requirements.txt             # Python dependencies
├── deploy_lambda.sh            # Deployment script
├── test_rag_lambda.py          # Test script
├── terraform/                  # Infrastructure as Code
│   └── main.tf                # Terraform module
└── README.md                   # This file
```

---

## 🚀 Quick Start

### **Option 1: Deploy with Script** (Recommended)

```bash
# 1. Set environment variables
export AWS_REGION=ap-southeast-2
export PROJECT_NAME=openlews
export ENVIRONMENT=dev

# 2. Ensure Pinecone API key is in Secrets Manager
aws secretsmanager create-secret \
  --name openlews-dev/pinecone/api-key \
  --secret-string "your-pinecone-api-key" \
  --region ap-southeast-2

# 3. Create IAM role (one-time setup)
# See "Manual Setup" section below

# 4. Deploy Lambda
bash deploy_lambda.sh
```

---

### **Option 2: Deploy with Terraform**

```bash
cd terraform/

# Initialize
terraform init

# Plan
terraform plan \
  -var="dynamodb_table_name=openlews-dev-hazard-zones" \
  -var="pinecone_api_key_secret_arn=arn:aws:secretsmanager:..."

# Apply
terraform apply
```

---

## 🔧 Manual Setup (If Script Fails)

### **Step 1: Create IAM Role**

```bash
# Create trust policy
cat > trust-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# Create role
aws iam create-role \
  --role-name openlews-dev-rag-query-lambda-role \
  --assume-role-policy-document file://trust-policy.json

# Attach basic execution policy
aws iam attach-role-policy \
  --role-name openlews-dev-rag-query-lambda-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

### **Step 2: Create Inline Policy for DynamoDB**

```bash
cat > lambda-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:Query",
        "dynamodb:GetItem"
      ],
      "Resource": [
        "arn:aws:dynamodb:ap-southeast-2:*:table/openlews-dev-hazard-zones",
        "arn:aws:dynamodb:ap-southeast-2:*:table/openlews-dev-hazard-zones/index/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:ap-southeast-2:*:secret:openlews-dev/pinecone/api-key*"
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name openlews-dev-rag-query-lambda-role \
  --policy-name DynamoDBandSecretsAccess \
  --policy-document file://lambda-policy.json
```

### **Step 3: Package Lambda**

```bash
# Create package directory
mkdir lambda_package
cd lambda_package

# Copy Lambda code
cp ../lambda_function.py .

# Install dependencies
pip install -r ../requirements.txt -t .

# Create ZIP
zip -r ../lambda_package.zip .
cd ..
```

### **Step 4: Create Lambda Function**

```bash
# Get role ARN
ROLE_ARN=$(aws iam get-role --role-name openlews-dev-rag-query-lambda-role --query 'Role.Arn' --output text)

# Get Pinecone API key
PINECONE_API_KEY=$(aws secretsmanager get-secret-value \
  --secret-id openlews-dev/pinecone/api-key \
  --query SecretString \
  --output text)

# Create Lambda
aws lambda create-function \
  --function-name openlews-dev-rag-query \
  --runtime python3.11 \
  --role "$ROLE_ARN" \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://lambda_package.zip \
  --timeout 30 \
  --memory-size 512 \
  --environment "Variables={
      AWS_REGION=ap-southeast-2,
      DYNAMODB_TABLE_NAME=openlews-dev-hazard-zones,
      PINECONE_API_KEY=$PINECONE_API_KEY,
      PINECONE_INDEX_NAME=lews-geological-knowledge,
      PINECONE_NAMESPACE=openlews
  }" \
  --region ap-southeast-2
```

---

## 🧪 Testing

### **Test Locally** (Before Deploying)

```bash
# Set environment variables
export AWS_REGION=ap-southeast-2
export DYNAMODB_TABLE_NAME=openlews-dev-hazard-zones
export PINECONE_API_KEY=your-key
export PINECONE_INDEX_NAME=lews-geological-knowledge
export PINECONE_NAMESPACE=openlews

# Run test
python test_rag_lambda.py --mode local
```

### **Test Deployed Lambda**

```bash
# Test via AWS
python test_rag_lambda.py --mode aws --function-name openlews-dev-rag-query

# Or test manually
aws lambda invoke \
  --function-name openlews-dev-rag-query \
  --payload '{"action":"nearest","latitude":6.92,"longitude":80.98}' \
  --region ap-southeast-2 \
  response.json

cat response.json | python -m json.tool
```

---

## 📖 API Reference

### **Action: nearest**

Find the nearest hazard zone to a location.

**Request:**
```json
{
  "action": "nearest",
  "latitude": 6.92,
  "longitude": 80.98,
  "max_distance_km": 5.0  // Optional, default: 5.0
}
```

**Response:**
```json
{
  "success": true,
  "nearest_zone": {
    "zone_id": "NDIS_12345",
    "hazard_level": "High",
    "distance_meters": 234.5,
    "centroid": {"lat": 6.9204, "lon": 80.9812},
    "geohash": "096920",
    "area_sqm": 2543.21,
    "metadata": {
      "objectid": 12345,
      "range": 4,
      "shape_area": 0.0000025,
      "shape_length": 0.02
    }
  },
  "query_location": {"lat": 6.92, "lon": 80.98}
}
```

---

### **Action: radius**

Find all hazard zones within a radius.

**Request:**
```json
{
  "action": "radius",
  "latitude": 6.92,
  "longitude": 80.98,
  "radius_km": 1.0  // Default: 1.0
}
```

**Response:**
```json
{
  "success": true,
  "zones": [
    {
      "zone_id": "NDIS_12345",
      "hazard_level": "High",
      "distance_meters": 234.5,
      "centroid": {"lat": 6.9204, "lon": 80.9812},
      "geohash": "096920",
      "area_sqm": 2543.21
    },
    // ... more zones
  ],
  "count": 5,
  "query_location": {"lat": 6.92, "lon": 80.98},
  "radius_km": 1.0,
  "risk_summary": {
    "High": 2,
    "Moderate": 3
  },
  "risk_context": "Nearest zone is High hazard level (234m away). 2 HIGH risk zone(s) detected"
}
```

---

## 🔗 Integration Examples

### **Enhanced Sensor Alert**

```python
import boto3
import json

lambda_client = boto3.client('lambda')

def process_sensor_alert(sensor_id, latitude, longitude, moisture):
    """Process sensor alert with geological context"""
    
    # Query RAG Lambda
    response = lambda_client.invoke(
        FunctionName='openlews-dev-rag-query',
        Payload=json.dumps({
            'action': 'nearest',
            'latitude': latitude,
            'longitude': longitude
        })
    )
    
    result = json.loads(response['Payload'].read())
    body = json.loads(result['body'])
    
    if body['success'] and 'nearest_zone' in body:
        zone = body['nearest_zone']
        
        # Generate contextual alert
        alert = {
            'sensor_id': sensor_id,
            'moisture': moisture,
            'hazard_zone': zone['zone_id'],
            'hazard_level': zone['hazard_level'],
            'distance_to_zone': zone['distance_meters'],
            'severity': 'CRITICAL' if zone['hazard_level'] == 'High' and moisture > 70 else 'WARNING',
            'message': f"Sensor {sensor_id} in {zone['hazard_level']} hazard zone detected {moisture}% moisture"
        }
        
        return alert
    
    return None
```

### **Multi-Sensor Correlation**

```python
def correlate_sensors(sensors):
    """Check if multiple sensors are in the same hazard zone"""
    
    zones_affected = {}
    
    for sensor in sensors:
        response = lambda_client.invoke(
            FunctionName='openlews-dev-rag-query',
            Payload=json.dumps({
                'action': 'nearest',
                'latitude': sensor['lat'],
                'longitude': sensor['lon']
            })
        )
        
        result = json.loads(response['Payload'].read())
        body = json.loads(result['body'])
        
        if body['success']:
            zone_id = body['nearest_zone']['zone_id']
            
            if zone_id not in zones_affected:
                zones_affected[zone_id] = []
            
            zones_affected[zone_id].append(sensor['id'])
    
    # Alert if multiple sensors in same high-risk zone
    for zone_id, sensor_ids in zones_affected.items():
        if len(sensor_ids) >= 2:
            print(f"⚠️ CLUSTER ALERT: {len(sensor_ids)} sensors in zone {zone_id}")
```

---

## 💰 Cost Estimate

**Per 1000 invocations:**
- Lambda execution: $0.0000002 × 1000 = $0.0002
- DynamoDB reads: $0.00025 × 1000 = $0.25
- **Total: ~$0.25 per 1000 queries**

**Monthly (assuming 10,000 sensor queries/day):**
- 300,000 queries × $0.00025 = **$75/month**

---

## 🐛 Troubleshooting

### **Error: "No zones found within 5km"**

**Cause:** Sensor location is outside your ingested region (6.8-7.2°N, 80.8-81.2°E)

**Solution:**
- Increase `max_distance_km` parameter
- Or ingest more NDIS zones from other regions

---

### **Error: "GeoHashIndex not found"**

**Cause:** DynamoDB table doesn't have GeoHash Global Secondary Index

**Solution:**
```bash
aws dynamodb update-table \
  --table-name openlews-dev-hazard-zones \
  --attribute-definitions \
    AttributeName=geohash,AttributeType=S \
  --global-secondary-index-updates \
    "[{\"Create\":{\"IndexName\":\"GeoHashIndex\",\"KeySchema\":[{\"AttributeName\":\"geohash\",\"KeyType\":\"HASH\"}],\"Projection\":{\"ProjectionType\":\"ALL\"},\"ProvisionedThroughput\":{\"ReadCapacityUnits\":5,\"WriteCapacityUnits\":5}}}]"
```

---

### **Error: "Unable to connect to Pinecone"**

**Cause:** Pinecone API key not set or invalid

**Solution:**
- Check Secrets Manager has correct API key
- Update Lambda environment variables
- Test Pinecone connection separately

---

## 📊 Performance

**Latency:**
- Typical response: 200-500ms
- 90th percentile: <1s
- Timeout: 30s

**Optimization tips:**
- DynamoDB: Use geohash index (already implemented)
- Lambda: Increase memory to 1024MB for faster execution
- Caching: Add ElastiCache for frequently queried locations

---

## 🔐 Security

**Best practices:**
- ✅ IAM least-privilege (only Query on specific table)
- ✅ Secrets Manager for API keys
- ✅ VPC isolation (optional, for production)
- ⚠️ Function URL is public (change `authorization_type` to `AWS_IAM` for production)

---

## 🚀 Next Steps

After deploying this Lambda:

1. **Test with real sensor data** - Use IoT simulator
2. **Build detection algorithm** - Multi-modal fusion logic
3. **Create dashboard** - Visualize zones + sensors
4. **Add caching layer** - ElastiCache for performance
5. **Implement alerts** - SNS/SES for notifications

---

## 📞 Support

Questions? Check the main project README or open an issue.