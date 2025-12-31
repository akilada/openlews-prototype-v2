"""
Unit Tests for Fusion Algorithm

Tests spatial correlation, cluster detection, and composite risk scoring.
"""

import pytest
import sys
import os

# Add parent directory to path
sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../src/lambdas/detector")
    ),
)

from core.fusion_algorithm import FusionAlgorithm


class TestFusionAlgorithm:

    def setup_method(self):
        """Initialize fusion algorithm for each test."""
        self.fusion = FusionAlgorithm()

    def test_haversine_distance(self):
        """Test distance calculation."""
        # Badulla to Haldummulla (~10km)
        lat1, lon1 = 6.9934, 81.0550
        lat2, lon2 = 6.9000, 81.1000

        distance = self.fusion._haversine_distance(lat1, lon1, lat2, lon2)

        assert 9000 < distance < 12000, f"Distance {distance}m outside expected range"

    def test_spatial_correlation_high_agreement(self):
        """Test high spatial correlation (neighbours agree)."""
        # Mock 5 sensors in quincunx, all with high risk
        sensor_risks = {
            "SENSOR_01": {"risk_score": 0.8},
            "SENSOR_02": {"risk_score": 0.75},
            "SENSOR_03": {"risk_score": 0.82},
            "SENSOR_04": {"risk_score": 0.78},
            "SENSOR_05": {"risk_score": 0.2},  # One low-risk sensor
        }

        telemetry_data = {
            "SENSOR_01": [{"latitude": 6.9934, "longitude": 81.0550}],
            "SENSOR_02": [{"latitude": 6.9936, "longitude": 81.0552}],  # ~25m away
            "SENSOR_03": [{"latitude": 6.9932, "longitude": 81.0548}],  # ~25m away
            "SENSOR_04": [{"latitude": 6.9934, "longitude": 81.0555}],  # ~40m away
            "SENSOR_05": [{"latitude": 6.9950, "longitude": 81.0600}],  # Far away
        }

        correlation = self.fusion.calculate_spatial_correlation(
            "SENSOR_01", sensor_risks, telemetry_data
        )

        # Should have high correlation (3/3 nearby sensors agree on high risk)
        assert correlation >= 0.6, f"Expected high correlation, got {correlation}"

    def test_spatial_correlation_isolated_anomaly(self):
        """Test low correlation for isolated high-risk sensor (likely fault)."""
        sensor_risks = {
            "SENSOR_01": {"risk_score": 0.9},  # High risk
            "SENSOR_02": {"risk_score": 0.1},  # Low risk
            "SENSOR_03": {"risk_score": 0.15},  # Low risk
            "SENSOR_04": {"risk_score": 0.12},  # Low risk
        }

        telemetry_data = {
            "SENSOR_01": [{"latitude": 6.9934, "longitude": 81.0550}],
            "SENSOR_02": [{"latitude": 6.9936, "longitude": 81.0552}],
            "SENSOR_03": [{"latitude": 6.9932, "longitude": 81.0548}],
            "SENSOR_04": [{"latitude": 6.9934, "longitude": 81.0555}],
        }

        correlation = self.fusion.calculate_spatial_correlation(
            "SENSOR_01", sensor_risks, telemetry_data
        )

        # Should have low correlation (isolated anomaly)
        assert (
            correlation < 0.3
        ), f"Expected low correlation for isolated anomaly, got {correlation}"

    def test_composite_risk_boost(self):
        """Test risk boost when correlation is high."""
        individual_risk = 0.7
        high_correlation = 0.8

        composite = self.fusion.calculate_composite_risk(
            individual_risk, high_correlation
        )

        # Should be boosted (1.3x)
        expected = min(1.0, 0.7 * 1.3)
        assert abs(composite - expected) < 0.01, f"Expected {expected}, got {composite}"

    def test_composite_risk_reduction(self):
        """Test risk reduction when correlation is low (sensor fault)."""
        individual_risk = 0.8
        low_correlation = 0.2

        composite = self.fusion.calculate_composite_risk(
            individual_risk, low_correlation
        )

        # Should be reduced (0.5x)
        expected = 0.8 * 0.5
        assert abs(composite - expected) < 0.01, f"Expected {expected}, got {composite}"

    def test_cluster_detection_aranayake_pattern(self):
        """Test cluster detection for Aranayake-type failure (3+ sensors)."""
        # Mock Aranayake: 4 sensors in center with high risk
        sensor_risks = {
            "SENSOR_01": {"composite_risk": 0.85},
            "SENSOR_02": {"composite_risk": 0.80},
            "SENSOR_03": {"composite_risk": 0.82},
            "SENSOR_04": {"composite_risk": 0.78},
            "SENSOR_05": {"composite_risk": 0.2},  # Outside cluster
        }

        telemetry_data = {
            "SENSOR_01": [{"latitude": 6.9934, "longitude": 81.0550}],
            "SENSOR_02": [{"latitude": 6.9936, "longitude": 81.0552}],
            "SENSOR_03": [{"latitude": 6.9932, "longitude": 81.0548}],
            "SENSOR_04": [{"latitude": 6.9934, "longitude": 81.0555}],
            "SENSOR_05": [{"latitude": 7.0000, "longitude": 81.1000}],  # Far away
        }

        clusters = self.fusion.detect_clusters(sensor_risks, telemetry_data)

        assert len(clusters) >= 1, "Should detect at least 1 cluster"
        assert clusters[0]["size"] >= 3, f"Cluster size {clusters[0]['size']} < 3"
        assert clusters[0]["avg_risk"] > 0.7, "Cluster average risk should be high"

    def test_no_cluster_for_isolated_sensors(self):
        """Test that isolated high-risk sensors don't form clusters."""
        sensor_risks = {
            "SENSOR_01": {"composite_risk": 0.85},
            "SENSOR_02": {"composite_risk": 0.15},
            "SENSOR_03": {"composite_risk": 0.20},
        }

        telemetry_data = {
            "SENSOR_01": [{"latitude": 6.9934, "longitude": 81.0550}],
            "SENSOR_02": [{"latitude": 6.9936, "longitude": 81.0552}],
            "SENSOR_03": [{"latitude": 6.9932, "longitude": 81.0548}],
        }

        clusters = self.fusion.detect_clusters(sensor_risks, telemetry_data)

        assert len(clusters) == 0, "Should not detect cluster for isolated sensor"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
