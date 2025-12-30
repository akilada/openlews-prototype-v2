"""
Multi-Modal Fusion Algorithm for Landslide Detection

Implements spatial correlation, cluster detection, and composite risk scoring
based on the Neuro-Symbolic AI framework described in the OpenLEWS research.

References:
- Aranayake 2016 forensic analysis
- NBRO hazard zonation methodology
- Strategy B: Multi-Sensor "Neighbourhood Watch"
"""

import math
from typing import Dict, List
from aws_lambda_powertools import Logger

logger = Logger(child=True)


class FusionAlgorithm:
    """
    Implements multi-sensor fusion and spatial correlation analysis.
    """
    
    # Quincunx grid spacing (meters)
    SENSOR_SPACING_M = 20.0
    
    # Neighbourhood radius for correlation (2.5x spacing)
    CORRELATION_RADIUS_M = 50.0
    
    # Cluster detection parameters
    MIN_CLUSTER_SIZE = 3  # Minimum sensors for cluster
    CLUSTER_RADIUS_M = 50.0
    
    def __init__(self):
        logger.info("Initializing FusionAlgorithm", extra={
            'sensor_spacing': self.SENSOR_SPACING_M,
            'correlation_radius': self.CORRELATION_RADIUS_M
        })
    
    def calculate_spatial_correlation(
        self,
        sensor_id: str,
        sensor_risks: Dict[str, Dict],
        telemetry_data: Dict[str, List[Dict]]
    ) -> float:
        """
        Calculate spatial correlation: do nearby sensors agree on risk?
        
        This implements Strategy B ("Neighbourhood Watch") from research:
        - Find sensors within correlation radius
        - Count how many show similar risk levels
        - Return agreement ratio
        
        Args:
            sensor_id: Target sensor
            sensor_risks: Risk scores for all sensors
            telemetry_data: Full telemetry dataset
            
        Returns:
            Correlation score (0.0 to 1.0)
        """
        if sensor_id not in telemetry_data or not telemetry_data[sensor_id]:
            logger.warning(f"No telemetry for sensor {sensor_id}")
            return 0.0
        
        # Get sensor location
        sensor_location = telemetry_data[sensor_id][-1]  # Latest reading
        sensor_lat = sensor_location['latitude']
        sensor_lon = sensor_location['longitude']
        sensor_risk = sensor_risks[sensor_id]['risk_score']
        
        # Find neighbours
        neighbours = self._find_neighbours(
            sensor_lat,
            sensor_lon,
            sensor_id,
            telemetry_data,
            self.CORRELATION_RADIUS_M
        )
        
        if len(neighbours) < 2:
            logger.debug(f"Sensor {sensor_id} has insufficient neighbours")
            return 0.0
        
        # Count agreement
        agreeing_count = 0
        for neighbour_id in neighbours:
            if neighbour_id not in sensor_risks:
                continue
                
            neighbour_risk = sensor_risks[neighbour_id]['risk_score']
            
            # Agreement definition: both high OR both low
            if (sensor_risk > 0.5 and neighbour_risk > 0.5) or \
               (sensor_risk < 0.3 and neighbour_risk < 0.3):
                agreeing_count += 1
        
        correlation = agreeing_count / len(neighbours)
        
        logger.debug(f"Sensor {sensor_id} correlation", extra={
            'neighbours': len(neighbours),
            'agreeing': agreeing_count,
            'correlation': correlation
        })
        
        return correlation
    
    def calculate_composite_risk(
        self,
        individual_risk: float,
        spatial_correlation: float
    ) -> float:
        """
        Combine individual risk with spatial correlation.
        
        Logic:
        - High correlation (>0.6): Boost risk (neighbours agree = high confidence)
        - Low correlation (<0.3): Reduce risk (likely sensor fault)
        - Medium correlation: No adjustment
        
        Args:
            individual_risk: Sensor's own risk score
            spatial_correlation: Agreement with neighbours
            
        Returns:
            Composite risk score (0.0 to 1.0)
        """
        if spatial_correlation > 0.6:
            # Multiple sensors agree = high confidence
            composite = min(1.0, individual_risk * 1.3)
            logger.debug("High correlation - boosting risk", extra={
                'individual': individual_risk,
                'composite': composite
            })
        elif spatial_correlation < 0.3:
            # Isolated anomaly = likely sensor fault
            composite = individual_risk * 0.5
            logger.debug("Low correlation - reducing risk (possible fault)", extra={
                'individual': individual_risk,
                'composite': composite
            })
        else:
            # Moderate agreement
            composite = individual_risk
        
        return composite
    
    def detect_clusters(
        self,
        sensor_risks: Dict[str, Dict],
        telemetry_data: Dict[str, List[Dict]]
    ) -> List[Dict]:
        """
        Detect clusters of 3+ sensors showing high risk.
        
        This detects "complex translational" failures like Aranayake 2016,
        where multiple adjacent sensors fail together.
        
        Args:
            sensor_risks: Risk scores for all sensors
            telemetry_data: Full telemetry dataset
            
        Returns:
            List of cluster descriptions
        """
        clusters = []
        processed_sensors = set()
        
        # Sort sensors by composite risk (highest first)
        sorted_sensors = sorted(
            sensor_risks.items(),
            key=lambda x: x[1].get('composite_risk', 0),
            reverse=True
        )
        
        for sensor_id, data in sorted_sensors:
            # Skip if already in a cluster
            if sensor_id in processed_sensors:
                continue
            
            # Only consider high-risk sensors
            if data.get('composite_risk', 0) < 0.6:
                continue
            
            # Skip if no location data
            if sensor_id not in telemetry_data or not telemetry_data[sensor_id]:
                continue
            
            # Get sensor location
            sensor_location = telemetry_data[sensor_id][-1]
            sensor_lat = sensor_location['latitude']
            sensor_lon = sensor_location['longitude']
            
            # Find high-risk neighbours
            high_risk_neighbours = self._find_high_risk_neighbours(
                sensor_lat,
                sensor_lon,
                sensor_id,
                sensor_risks,
                telemetry_data,
                self.CLUSTER_RADIUS_M,
                risk_threshold=0.6
            )
            
            # Cluster needs at least 3 sensors total (center + 2 neighbours)
            if len(high_risk_neighbours) >= 2:
                cluster_members = [sensor_id] + high_risk_neighbours
                
                # Calculate cluster statistics
                cluster_risks = [
                    sensor_risks[sid].get('composite_risk', 0)
                    for sid in cluster_members
                ]
                
                avg_risk = sum(cluster_risks) / len(cluster_risks)
                max_risk = max(cluster_risks)
                
                cluster = {
                    'center_sensor': sensor_id,
                    'center_location': {
                        'lat': sensor_lat,
                        'lon': sensor_lon
                    },
                    'members': cluster_members,
                    'size': len(cluster_members),
                    'avg_risk': avg_risk,
                    'max_risk': max_risk,
                    'correlation': data.get('spatial_correlation', 0.0)
                }
                
                clusters.append(cluster)
                
                # Mark all members as processed
                processed_sensors.update(cluster_members)
                
                logger.info(f"Cluster detected: {sensor_id}", extra={
                    'size': len(cluster_members),
                    'avg_risk': avg_risk
                })
        
        return clusters
    
    def _find_neighbours(
        self,
        lat: float,
        lon: float,
        exclude_sensor: str,
        telemetry_data: Dict[str, List[Dict]],
        radius_m: float
    ) -> List[str]:
        """
        Find all sensors within radius of a point.
        
        Args:
            lat: Target latitude
            lon: Target longitude
            exclude_sensor: Sensor ID to exclude (usually self)
            telemetry_data: Full telemetry dataset
            radius_m: Search radius in meters
            
        Returns:
            List of sensor IDs within radius
        """
        neighbours = []
        
        for sensor_id, records in telemetry_data.items():
            if sensor_id == exclude_sensor or not records:
                continue
            
            # Get latest location
            sensor_lat = records[-1]['latitude']
            sensor_lon = records[-1]['longitude']
            
            # Calculate distance
            distance = self._haversine_distance(lat, lon, sensor_lat, sensor_lon)
            
            if distance <= radius_m:
                neighbours.append(sensor_id)
        
        return neighbours
    
    def _find_high_risk_neighbours(
        self,
        lat: float,
        lon: float,
        exclude_sensor: str,
        sensor_risks: Dict[str, Dict],
        telemetry_data: Dict[str, List[Dict]],
        radius_m: float,
        risk_threshold: float = 0.6
    ) -> List[str]:
        """
        Find high-risk sensors within radius.
        
        Args:
            lat: Target latitude
            lon: Target longitude
            exclude_sensor: Sensor ID to exclude
            sensor_risks: Risk scores for all sensors
            telemetry_data: Full telemetry dataset
            radius_m: Search radius in meters
            risk_threshold: Minimum risk to include
            
        Returns:
            List of high-risk sensor IDs within radius
        """
        neighbours = self._find_neighbours(
            lat, lon, exclude_sensor, telemetry_data, radius_m
        )
        
        high_risk_neighbours = [
            sid for sid in neighbours
            if sid in sensor_risks and 
            sensor_risks[sid].get('composite_risk', 0) >= risk_threshold
        ]
        
        return high_risk_neighbours
    
    @staticmethod
    def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate distance between two points using Haversine formula.
        
        Args:
            lat1, lon1: First point
            lat2, lon2: Second point
            
        Returns:
            Distance in meters
        """
        R = 6371000  # Earth radius in meters
        
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        
        a = math.sin(delta_phi / 2) ** 2 + \
            math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        distance = R * c
        return distance
