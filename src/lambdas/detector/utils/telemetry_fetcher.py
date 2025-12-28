"""
Telemetry Fetcher Utility
Fetches sensor telemetry data from DynamoDB for analysis.
"""

from __future__ import annotations

from typing import Dict, List, Optional
from boto3.dynamodb.conditions import Key, Attr
from aws_lambda_powertools import Logger
import time
from decimal import Decimal

logger = Logger(child=True)


class TelemetryFetcher:
    """
    Utility for fetching telemetry data from DynamoDB.

    Uses efficient query patterns:
    1) Query by sensor_id + timestamp range
    2) Query via GSIs if they exist (hazard_level / geohash)
    3) Scan only as last resort
    """

    # Optional GSI names
    HAZARD_LEVEL_INDEX = "HazardLevelIndex"
    FAILURE_STAGE_INDEX = "FailureStageIndex"
    SPATIAL_INDEX = "SpatialIndex"

    def __init__(self, dynamodb_resource, table_name: str):
        self.table = dynamodb_resource.Table(table_name)
        self.table_name = table_name
        logger.info(f"Initialized TelemetryFetcher for table: {table_name}")

    # Utilities
    @staticmethod
    def to_native(x):
        """
        Convert DynamoDB Decimals to Python native int/float recursively.
        """
        if isinstance(x, Decimal):
            if x == x.to_integral_value():
                return int(x)
            return float(x)
        if isinstance(x, dict):
            return {k: TelemetryFetcher.to_native(v) for k, v in x.items()}
        if isinstance(x, list):
            return [TelemetryFetcher.to_native(v) for v in x]
        return x

    # Primary fetch methods
    def fetch_by_time_range(
        self,
        start_time: int,
        end_time: int,
        sensor_ids: Optional[List[str]] = None
    ) -> Dict[str, List[Dict]]:
        """
        Fetch telemetry within a time range.

        If sensor_ids is provided, uses efficient Query per sensor.
        Otherwise, attempts to discover active sensors (via a minimal scan),
        then queries each sensor efficiently.

        Returns: { sensor_id: [records...] }
        """
        logger.info(f"Fetching telemetry from {start_time} to {end_time}")

        if sensor_ids:
            return self._fetch_by_sensors(sensor_ids, start_time, end_time)

        return self._fetch_all_sensors(start_time, end_time)

    def _fetch_by_sensors(
        self,
        sensor_ids: List[str],
        start_time: int,
        end_time: int
    ) -> Dict[str, List[Dict]]:
        """
        Query telemetry for specific sensors using (sensor_id, timestamp) keys.

        Returns: { sensor_id: [records...] }
        """
        telemetry_by_sensor: Dict[str, List[Dict]] = {}

        for sensor_id in sensor_ids:
            try:
                items: List[Dict] = []
                response = self.table.query(
                    KeyConditionExpression=(
                        Key("sensor_id").eq(sensor_id) &
                        Key("timestamp").between(start_time, end_time)
                    ),
                    ScanIndexForward=True,
                )
                items.extend(response.get("Items", []))

                while "LastEvaluatedKey" in response:
                    response = self.table.query(
                        KeyConditionExpression=(
                            Key("sensor_id").eq(sensor_id) &
                            Key("timestamp").between(start_time, end_time)
                        ),
                        ExclusiveStartKey=response["LastEvaluatedKey"],
                        ScanIndexForward=True,
                    )
                    items.extend(response.get("Items", []))

                if items:
                    items = [TelemetryFetcher.to_native(i) for i in items]
                    telemetry_by_sensor[sensor_id] = items

            except Exception as e:
                logger.warning(f"Failed to query sensor {sensor_id}: {e}")
                continue

        total_records = sum(len(v) for v in telemetry_by_sensor.values())
        logger.info(f"Fetched {total_records} records for {len(telemetry_by_sensor)} sensors")
        return telemetry_by_sensor

    def _fetch_all_sensors(self, start_time: int, end_time: int) -> Dict[str, List[Dict]]:
        """
        Fetch telemetry for all sensors within a time range.

        Strategy:
        1) discover active sensor IDs (scan with minimal projection)
        2) query each sensor efficiently
        """
        sensor_ids = self._get_active_sensor_ids(start_time, end_time)

        if not sensor_ids:
            logger.warning("No active sensors found in time range")
            return {}

        logger.info(f"Found {len(sensor_ids)} active sensors, querying each...")
        return self._fetch_by_sensors(sensor_ids, start_time, end_time)

    def _get_active_sensor_ids(self, start_time: int, end_time: int) -> List[str]:
        """
        Discover sensor IDs with data in the time range.
        """
        sensor_ids = set()

        try:
            response = self.table.scan(
                ProjectionExpression="sensor_id",
                FilterExpression=Attr("timestamp").between(start_time, end_time),
            )

            for item in response.get("Items", []):
                if "sensor_id" in item:
                    sensor_ids.add(item["sensor_id"])

            while "LastEvaluatedKey" in response:
                response = self.table.scan(
                    ProjectionExpression="sensor_id",
                    FilterExpression=Attr("timestamp").between(start_time, end_time),
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                for item in response.get("Items", []):
                    if "sensor_id" in item:
                        sensor_ids.add(item["sensor_id"])

        except Exception as e:
            logger.exception(f"Failed to scan for sensor IDs: {e}")

        return list(sensor_ids)

    # Optional GSI-based methods
    def fetch_by_hazard_level(
        self,
        hazard_level: str,
        start_time: int,
        end_time: int
    ) -> Dict[str, List[Dict]]:
        """
        Fetch telemetry for sensors in a specific hazard level using HazardLevelIndex GSI.

        Requires a GSI:
          - PK: hazard_level
          - SK: timestamp
        """
        logger.info(f"Fetching telemetry for hazard_level={hazard_level}")

        telemetry_by_sensor: Dict[str, List[Dict]] = {}

        try:
            items: List[Dict] = []
            response = self.table.query(
                IndexName=self.HAZARD_LEVEL_INDEX,
                KeyConditionExpression=(
                    Key("hazard_level").eq(hazard_level) &
                    Key("timestamp").between(start_time, end_time)
                ),
                ScanIndexForward=True,
            )
            items.extend(response.get("Items", []))

            while "LastEvaluatedKey" in response:
                response = self.table.query(
                    IndexName=self.HAZARD_LEVEL_INDEX,
                    KeyConditionExpression=(
                        Key("hazard_level").eq(hazard_level) &
                        Key("timestamp").between(start_time, end_time)
                    ),
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                    ScanIndexForward=True,
                )
                items.extend(response.get("Items", []))

            items = [TelemetryFetcher.to_native(i) for i in items]

            for item in items:
                sid = item.get("sensor_id")
                if not sid:
                    continue
                telemetry_by_sensor.setdefault(sid, []).append(item)

            total_records = sum(len(v) for v in telemetry_by_sensor.values())
            logger.info(
                f"Fetched {total_records} records for {len(telemetry_by_sensor)} sensors "
                f"at hazard_level={hazard_level}"
            )

        except Exception as e:
            logger.exception(f"Failed to query by hazard level: {e}")

        return telemetry_by_sensor

    def fetch_by_geohash(
        self,
        geohash: str,
        start_time: int,
        end_time: int
    ) -> Dict[str, List[Dict]]:
        """
        Fetch telemetry for a geohash area using SpatialIndex GSI.

        Requires a GSI:
          - PK: geohash (often a prefix / bucket)
          - SK: timestamp
        """
        logger.info(f"Fetching telemetry for geohash={geohash}")

        telemetry_by_sensor: Dict[str, List[Dict]] = {}

        try:
            items: List[Dict] = []
            response = self.table.query(
                IndexName=self.SPATIAL_INDEX,
                KeyConditionExpression=(
                    Key("geohash").eq(geohash) &
                    Key("timestamp").between(start_time, end_time)
                ),
                ScanIndexForward=True,
            )
            items.extend(response.get("Items", []))

            while "LastEvaluatedKey" in response:
                response = self.table.query(
                    IndexName=self.SPATIAL_INDEX,
                    KeyConditionExpression=(
                        Key("geohash").eq(geohash) &
                        Key("timestamp").between(start_time, end_time)
                    ),
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                    ScanIndexForward=True,
                )
                items.extend(response.get("Items", []))

            items = [TelemetryFetcher.to_native(i) for i in items]

            for item in items:
                sid = item.get("sensor_id")
                if not sid:
                    continue
                telemetry_by_sensor.setdefault(sid, []).append(item)

            total_records = sum(len(v) for v in telemetry_by_sensor.values())
            logger.info(
                f"Fetched {total_records} records for {len(telemetry_by_sensor)} sensors "
                f"at geohash={geohash}"
            )

        except Exception as e:
            logger.exception(f"Failed to query by geohash: {e}")

        return telemetry_by_sensor

    # Convenience methods
    def fetch_latest_per_sensor(
        self,
        sensor_ids: Optional[List[str]] = None,
        lookback_hours: int = 24
    ) -> Dict[str, Dict]:
        """
        Fetch the most recent telemetry record for each sensor.

        Optimisation:
        - If sensor_ids is known, does Query per sensor with:
            ScanIndexForward=False, Limit=1
        - If sensor_ids is None, discovers sensors (scan) then queries each.
        """
        end_time = int(time.time())
        start_time = end_time - (lookback_hours * 3600)

        if sensor_ids is None:
            sensor_ids = self._get_active_sensor_ids(start_time, end_time)

        latest_by_sensor: Dict[str, Dict] = {}

        for sensor_id in sensor_ids:
            try:
                resp = self.table.query(
                    KeyConditionExpression=(
                        Key("sensor_id").eq(sensor_id) &
                        Key("timestamp").between(start_time, end_time)
                    ),
                    ScanIndexForward=False,
                    Limit=1,
                )
                items = resp.get("Items", [])
                if items:
                    latest_by_sensor[sensor_id] = TelemetryFetcher.to_native(items[0])
            except Exception as e:
                logger.warning(f"Failed to fetch latest for {sensor_id}: {e}")

        logger.info(f"Got latest telemetry for {len(latest_by_sensor)} sensors")
        return latest_by_sensor

    def fetch_for_analysis_window(self, sensor_id: str, window_minutes: int = 60) -> List[Dict]:
        """
        Fetch telemetry for a single sensor over a recent window (default 60 min).
        """
        end_time = int(time.time())
        start_time = end_time - (window_minutes * 60)
        result = self._fetch_by_sensors([sensor_id], start_time, end_time)
        return result.get(sensor_id, [])


def get_recent_telemetry(
    dynamodb_resource,
    table_name: str,
    sensor_ids: List[str],
    hours: int = 1
) -> Dict[str, List[Dict]]:

    fetcher = TelemetryFetcher(dynamodb_resource, table_name)
    end_time = int(time.time())
    start_time = end_time - (hours * 3600)
    return fetcher.fetch_by_time_range(start_time, end_time, sensor_ids)
