#!/usr/bin/env python3
"""
Test RAG Query Lambda Function

Tests the Lambda both locally and deployed to AWS
"""

import json
import os
import sys

# For local testing
sys.path.insert(0, os.path.dirname(__file__))


def test_local():
    """Test Lambda function locally"""
    print("="*60)
    print("🧪 Testing Lambda Locally")
    print("="*60)
    
    # Set environment variables for local testing
    os.environ['AWS_REGION'] = ''
    os.environ['DYNAMODB_TABLE_NAME'] = ''
    os.environ['PINECONE_INDEX_NAME'] = ''
    os.environ['PINECONE_NAMESPACE'] = ''
    
    # Load Pinecone API key from .env if available
    try:
        from dotenv import load_dotenv
        load_dotenv()
        os.environ['PINECONE_API_KEY'] = os.getenv('PINECONE_API_KEY', '')
    except:
        pass
    
    if not os.environ.get('PINECONE_API_KEY'):
        print("⚠️  Warning: PINECONE_API_KEY not set")
        print("Set it in .env or environment")
        return False
    
    try:
        from rag_query_lambda import lambda_handler
    except ImportError:
        print("❌ Could not import lambda_function")
        print("Make sure rag_query_lambda.py is in the current directory")
        return False
    
    test_cases = [
        {
            "name": "Find Nearest Zone",
            "event": {
                "action": "nearest",
                "latitude": 6.92,
                "longitude": 80.98
            }
        },
        {
            "name": "Find Zones in Radius",
            "event": {
                "action": "radius",
                "latitude": 6.92,
                "longitude": 80.98,
                "radius_km": 2.0
            }
        },
        {
            "name": "Find Nearest Zone (Badulla)",
            "event": {
                "action": "nearest",
                "latitude": 6.9889,
                "longitude": 81.0544
            }
        },
        {
            "name": "Find Nearest Zone (Haldummulla)",
            "event": {
                "action": "nearest",
                "latitude": 6.7833,
                "longitude": 80.9000
            }
        }
    ]
    
    print("\n")
    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest {i}: {test_case['name']}")
        print("-" * 60)
        print(f"Event: {json.dumps(test_case['event'], indent=2)}")
        
        try:
            result = lambda_handler(test_case['event'], None)
            
            status_code = result.get('statusCode', 500)
            body = json.loads(result.get('body', '{}'))
            
            if status_code == 200:
                print(f"✅ SUCCESS (Status: {status_code})")
                
                if 'nearest_zone' in body:
                    zone = body['nearest_zone']
                    print(f"   Zone ID: {zone['zone_id']}")
                    print(f"   Hazard Level: {zone['hazard_level']}")
                    print(f"   Distance: {zone['distance_meters']:.1f}m")
                    print(f"   Location: {zone['centroid']['lat']:.4f}, {zone['centroid']['lon']:.4f}")
                
                if 'zones' in body:
                    print(f"   Found {body['count']} zones")
                    print(f"   Risk Summary: {body.get('risk_summary', {})}")
                    print(f"   Context: {body.get('risk_context', '')}")
                
            else:
                print(f"❌ FAILED (Status: {status_code})")
                print(f"   Error: {body.get('error', 'Unknown error')}")
                
        except Exception as e:
            print(f"❌ EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "="*60)
    print("✅ Local Testing Complete")
    print("="*60)
    return True


def test_deployed(function_name: str = "openlews-dev-rag-query", region: str = "ap-southeast-2"):
    """Test deployed Lambda function via AWS"""
    print("="*60)
    print(f"☁️  Testing Deployed Lambda: {function_name}")
    print("="*60)
    
    import boto3
    
    lambda_client = boto3.client('lambda', region_name=region)
    
    test_cases = [
        {
            "name": "Find Nearest Zone (Badulla)",
            "payload": {
                "action": "nearest",
                "latitude": 6.92,
                "longitude": 80.98
            }
        },
        {
            "name": "Find Zones in 1km Radius",
            "payload": {
                "action": "radius",
                "latitude": 6.92,
                "longitude": 80.98,
                "radius_km": 1.0
            }
        }
    ]
    
    print("\n")
    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest {i}: {test_case['name']}")
        print("-" * 60)
        
        try:
            response = lambda_client.invoke(
                FunctionName=function_name,
                InvocationType='RequestResponse',
                Payload=json.dumps(test_case['payload'])
            )
            
            payload = json.loads(response['Payload'].read())
            status_code = payload.get('statusCode', 500)
            body = json.loads(payload.get('body', '{}'))
            
            if status_code == 200:
                print(f"✅ SUCCESS (Status: {status_code})")
                
                if 'nearest_zone' in body:
                    zone = body['nearest_zone']
                    print(f"   Zone: {zone['zone_id']} ({zone['hazard_level']})")
                    print(f"   Distance: {zone['distance_meters']:.1f}m")
                
                if 'zones' in body:
                    print(f"   Found {body['count']} zones")
                    print(f"   Context: {body.get('risk_context', '')}")
            else:
                print(f"❌ FAILED (Status: {status_code})")
                print(f"   Error: {body.get('error', 'Unknown')}")
                
        except Exception as e:
            print(f"❌ EXCEPTION: {e}")
    
    print("\n" + "="*60)
    print("✅ AWS Testing Complete")
    print("="*60)


def main():
    """Main test runner"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test RAG Query Lambda")
    parser.add_argument('--mode', choices=['local', 'aws', 'both'], default='local',
                       help='Test mode: local, aws, or both')
    parser.add_argument('--function-name', default='openlews-dev-rag-query',
                       help='AWS Lambda function name')
    parser.add_argument('--region', default='ap-southeast-2',
                       help='AWS region')
    
    args = parser.parse_args()
    
    if args.mode in ['local', 'both']:
        success = test_local()
        if not success and args.mode == 'local':
            sys.exit(1)
    
    if args.mode in ['aws', 'both']:
        print("\n\n")
        test_deployed(args.function_name, args.region)


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