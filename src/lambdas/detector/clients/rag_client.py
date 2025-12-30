"""
RAG Query Client

Invokes the RAG Query Lambda to retrieve geological context
from NSDI hazard zones for sensor locations.
"""

import json
from typing import Dict
from aws_lambda_powertools import Logger

logger = Logger(child=True)


class RAGClient:
    """
    Client for RAG Query Lambda invocation.
    """
    
    def __init__(self, lambda_client, rag_lambda_arn: str):
        """
        Initialize RAG client.
        
        Args:
            lambda_client: boto3 Lambda client
            rag_lambda_arn: ARN of RAG Query Lambda
        """
        self.lambda_client = lambda_client
        self.rag_lambda_arn = rag_lambda_arn
        
        logger.info(f"Initialized RAGClient for Lambda: {rag_lambda_arn}")
    
    async def query_nearest(self, latitude: float, longitude: float) -> Dict:
        """
        Query nearest NSDI hazard zone for geological context.
        
        Args:
            latitude: Sensor latitude
            longitude: Sensor longitude
            
        Returns:
            Geological context dictionary
        """
        logger.info(f"Querying RAG for location ({latitude:.4f}, {longitude:.4f})")
        
        payload = {
            "action": "nearest",
            "latitude": latitude,
            "longitude": longitude
        }
        
        try:
            response = self.lambda_client.invoke(
                FunctionName=self.rag_lambda_arn,
                InvocationType='RequestResponse',
                Payload=json.dumps(payload)
            )
            
            response_payload = json.loads(response['Payload'].read())
            
            if response.get('FunctionError'):
                logger.error(f"RAG Lambda error: {response_payload}")
                return self._get_default_context()
            
            if 'body' in response_payload:
                body = json.loads(response_payload['body'])
            else:
                body = response_payload
            
            if 'nearest_zone' in body:
                zone = body['nearest_zone']
                context = {
                    'hazard_level': zone.get('hazard_level', 'Unknown'),
                    'soil_type': zone.get('soil_type', 'Unknown'),
                    'slope_angle': zone.get('slope_angle', 0),
                    'land_use': zone.get('land_use', 'Unknown'),
                    'distance_m': zone.get('distance_m', 0),
                    "district": zone.get("district", "Unknown"),
                    "ds_division": zone.get("ds_division", "Unknown"),
                    "gn_division": zone.get("gn_division", "Unknown"),
                    'critical_moisture_percent': self._estimate_critical_moisture(
                        zone.get('hazard_level', 'Unknown'),
                        zone.get('soil_type', 'Unknown')
                    ),
                    'zone_id': zone.get('zone_id', 'Unknown')
                }
                
                logger.info(f"RAG context retrieved: {context['hazard_level']} zone")
                return context
            else:
                logger.warning("No hazard zone found in RAG response")
                return self._get_default_context()
                
        except Exception:
            logger.exception("Failed to query RAG Lambda")
            return self._get_default_context()
    
    def _estimate_critical_moisture(self, hazard_level: str, soil_type: str) -> float:
        """
        Estimate critical moisture threshold based on hazard level and soil type.
        
        This is a simplified heuristic. In production, this would come from
        soil water characteristic curves (SWCC) in the RAG database.
        
        Args:
            hazard_level: NSDI hazard level
            soil_type: Soil classification
            
        Returns:
            Estimated critical moisture (%)
        """
        base_thresholds = {
            'Colluvium': 35,  # Loose, unstable
            'Residual': 45,    # More stable
            'Fill': 30,        # Very unstable
            'Bedrock': 60      # Very stable
        }
        
        base = base_thresholds.get(soil_type, 40)
        
        # Adjust by hazard level
        adjustments = {
            'Very High': -5,  # Lower threshold (more sensitive)
            'High': -2,
            'Moderate': 0,
            'Low': +5,
            'Very Low': +10
        }
        
        adjustment = adjustments.get(hazard_level, 0)
        
        critical = max(25, min(65, base + adjustment))  # Clamp to 25-65%
        
        return float(critical)
    
    def _get_default_context(self) -> Dict:
        """
        Return default geological context when RAG query fails.
        
        Returns:
            Conservative default context
        """
        return {
            'hazard_level': 'Unknown',
            'soil_type': 'Unknown',
            'slope_angle': 0,
            'land_use': 'Unknown',
            'distance_m': 0,
            'critical_moisture_percent': 40.0,  # Conservative default
            'zone_id': 'DEFAULT'
        }
