#!/usr/bin/env python3
"""
Analyze NDIS hazard zone distribution in DynamoDB and Pinecone
"""

import os
from collections import Counter
import boto3
from pinecone import Pinecone
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "")
DYNAMODB_TABLE_NAME = os.getenv("DYNAMODB_TABLE_NAME", "")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "")
PINECONE_NAMESPACE = os.getenv("PINECONE_NAMESPACE", "")


def analyze_dynamodb():
    """Analyze hazard levels in DynamoDB"""
    print("\n" + "="*60)
    print("📊 DynamoDB Analysis")
    print("="*60)
    
    dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    
    # Scan table
    print(f"\nScanning table: {DYNAMODB_TABLE_NAME}...")
    levels = []
    
    response = table.scan(
        ProjectionExpression='#lvl',
        ExpressionAttributeNames={'#lvl': 'level'}
    )
    levels.extend([item['level'] for item in response['Items']])
    
    # Handle pagination
    while 'LastEvaluatedKey' in response:
        response = table.scan(
            ProjectionExpression='#lvl',
            ExpressionAttributeNames={'#lvl': 'level'},
            ExclusiveStartKey=response['LastEvaluatedKey']
        )
        levels.extend([item['level'] for item in response['Items']])
    
    # Count
    counter = Counter(levels)
    total = sum(counter.values())
    
    print(f"\nTotal zones: {total:,}")
    print("\nHazard Level Distribution:")
    print("-" * 40)
    
    for level in sorted(counter.keys()):
        count = counter[level]
        pct = (count / total) * 100
        bar = "█" * int(pct / 2)
        print(f"{level:15} {count:6,} ({pct:5.1f}%) {bar}")
    
    return counter


def analyze_pinecone():
    """Analyze hazard levels in Pinecone metadata"""
    print("\n" + "="*60)
    print("🌲 Pinecone Analysis")
    print("="*60)
    
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    
    # Get stats
    stats = index.describe_index_stats()
    total = stats['total_vector_count']
    namespace_count = stats['namespaces'].get(PINECONE_NAMESPACE, {}).get('vector_count', 0)
    
    print(f"\nIndex: {PINECONE_INDEX_NAME}")
    print(f"Total vectors: {total:,}")
    print(f"Namespace '{PINECONE_NAMESPACE}': {namespace_count:,}")
    
    # Sample query to get metadata
    print("\nSampling metadata from 1000 random vectors...")
    
    # Query with random vector to get samples
    import numpy as np
    random_vector = np.random.rand(384).tolist()
    
    results = index.query(
        vector=random_vector,
        top_k=1000,
        include_metadata=True,
        namespace=PINECONE_NAMESPACE
    )
    
    levels = [match['metadata'].get('level', 'Unknown') for match in results['matches']]
    counter = Counter(levels)
    sample_total = len(levels)
    
    print(f"\nSample size: {sample_total:,}")
    print("\nHazard Level Distribution (sample):")
    print("-" * 40)
    
    for level in sorted(counter.keys()):
        count = counter[level]
        pct = (count / sample_total) * 100
        bar = "█" * int(pct / 2)
        print(f"{level:15} {count:6,} ({pct:5.1f}%) {bar}")
    
    return counter


def find_very_high_zones():
    """Find specific Very High hazard zones"""
    print("\n" + "="*60)
    print("🔍 Finding 'Very High' Hazard Zones")
    print("="*60)
    
    dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    
    # Scan for Very High zones
    response = table.scan(
        FilterExpression='#lvl = :level',
        ExpressionAttributeNames={'#lvl': 'level'},
        ExpressionAttributeValues={':level': 'Very High'},
        Limit=10
    )
    
    items = response['Items']
    
    if items:
        print(f"\nFound {len(items)} 'Very High' zones (showing first 10):")
        print("-" * 60)
        for item in items:
            print(f"Zone: {item['zone_id']}")
            print(f"  Level: {item['level']}")
            print(f"  Location: {item['centroid_lat']}, {item['centroid_lon']}")
            print(f"  Geohash: {item['geohash']}")
            print()
    else:
        print("\n⚠️  No 'Very High' hazard zones found in DynamoDB")
        print("\nPossible reasons:")
        print("1. Your filter region (6.8-7.2, 80.8-81.2) has no Very High zones")
        print("2. NDIS classifies this area as mostly Moderate/High risk")
        print("3. Very High zones might be in different regions (Ratnapura, Kegalle)")


def test_specific_queries():
    """Test different query types"""
    print("\n" + "="*60)
    print("🧪 Testing Different Query Types")
    print("="*60)
    
    from sentence_transformers import SentenceTransformer
    
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    model = SentenceTransformer('all-MiniLM-L6-v2')
    
    queries = [
        "Very High hazard",
        "High hazard", 
        "Moderate hazard",
        "Low hazard",
        "Critical landslide risk",
        "Safe zones"
    ]
    
    for query_text in queries:
        vector = model.encode(query_text).tolist()
        results = index.query(
            vector=vector,
            top_k=3,
            include_metadata=True,
            namespace=PINECONE_NAMESPACE
        )
        
        print(f"\n📍 Query: '{query_text}'")
        if results['matches']:
            top_match = results['matches'][0]
            print(f"   Top result: {top_match['metadata']['level']} (score: {top_match['score']:.4f})")
        else:
            print("   No results")


def main():
    print("="*60)
    print("🔬 NDIS Hazard Zone Data Analysis")
    print("="*60)
    
    # Analyze DynamoDB
    db_levels = analyze_dynamodb()
    
    # Analyze Pinecone
    pc_levels = analyze_pinecone()
    
    # Find Very High zones
    find_very_high_zones()
    
    # Test queries
    test_specific_queries()
    
    print("\n" + "="*60)
    print("✅ Analysis Complete")
    print("="*60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()