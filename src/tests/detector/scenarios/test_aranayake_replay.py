"""
Aranayake 2016 Scenario Replay Test

Tests that detector would have issued Red alert 6+ hours before failure.

Historical Facts:
- May 14-17, 2016
- 446.5mm rain over 72 hours
- Failure at hour 68
- Expected: Red alert by hour 62 (6h warning)
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../src/lambdas/detector')))

from core.risk_scorer import RiskScorer


def load_aranayake_telemetry():
    """
    Load simulated Aranayake telemetry sequence.
    
    Returns:
        List of hourly telemetry snapshots (hour 0-72)
    """
    # This would load from simulator output
    # For now, return mock data showing progression to failure
    
    telemetry_sequence = []
    
    for hour in range(73):
        # Progressive saturation
        moisture = min(95, 20 + (hour / 72) * 75)  # 20% → 95%
        
        # Accelerating tilt (creep)
        if hour < 40:
            tilt_rate = 0.5
        elif hour < 60:
            tilt_rate = 2.0 + (hour - 40) * 0.2  # Accelerating
        else:
            tilt_rate = 6.0 + (hour - 60) * 0.5  # Rapid creep
        
        # Vibration spikes near failure
        if hour < 50:
            vibration = 8
        elif hour < 65:
            vibration = 15 + (hour - 50) * 2
        else:
            vibration = 50 + (hour - 65) * 10  # Acoustic emissions spike
        
        # Cumulative rainfall
        if hour < 24:
            rainfall_24h = hour * 5  # Light rain
        elif hour < 48:
            rainfall_24h = 120 + (hour - 24) * 8  # Heavy rain
        else:
            rainfall_24h = 300 + (hour - 48) * 6  # Extreme rain
        
        telemetry = {
            'hour': hour,
            'sensor_id': 'ARANAYAKE_CENTER',
            'moisture_percent': moisture,
            'tilt_rate_mm_hr': tilt_rate,
            'vibration_count': vibration,
            'vibration_baseline': 10,
            'pore_pressure_kpa': max(-5, -10 + (hour / 72) * 25),  # -10 → +15 kPa
            'safety_factor': max(0.8, 1.8 - (hour / 72) * 1.0),    # 1.8 → 0.8
            'rainfall_24h_mm': min(400, rainfall_24h),
            'critical_moisture_percent': 40.0,  # Colluvium threshold
            'latitude': 7.1667,
            'longitude': 80.2833
        }
        
        telemetry_sequence.append(telemetry)
    
    return telemetry_sequence


def test_aranayake_replay():
    """
    Replay Aranayake scenario and verify early warning.
    """
    print("\n" + "="*60)
    print("ARANAYAKE 2016 SCENARIO REPLAY")
    print("="*60)
    
    scorer = RiskScorer()
    telemetry_sequence = load_aranayake_telemetry()
    
    first_yellow = None
    first_orange = None
    first_red = None
    
    for telemetry in telemetry_sequence:
        hour = telemetry['hour']
        risk = scorer.calculate_sensor_risk(telemetry)
        
        # Classify risk level
        if risk < 0.3:
            level = 'Green'
        elif risk < 0.6:
            level = 'Yellow'
        elif risk < 0.8:
            level = 'Orange'
        else:
            level = 'Red'
        
        # Track first occurrence of each level
        if level == 'Yellow' and first_yellow is None:
            first_yellow = hour
        if level == 'Orange' and first_orange is None:
            first_orange = hour
        if level == 'Red' and first_red is None:
            first_red = hour
        
        # Print key hours
        if hour % 12 == 0 or level in ['Orange', 'Red']:
            print(f"Hour {hour:2d}: Risk={risk:.3f} [{level:6s}] | "
                  f"Moisture={telemetry['moisture_percent']:.1f}% | "
                  f"Tilt={telemetry['tilt_rate_mm_hr']:.1f}mm/hr | "
                  f"Rain={telemetry['rainfall_24h_mm']:.0f}mm")
    
    print("\n" + "-"*60)
    print("ALERT TIMELINE:")
    print(f"  First Yellow Alert: Hour {first_yellow or 'NEVER'}")
    print(f"  First Orange Alert: Hour {first_orange or 'NEVER'}")
    print(f"  First Red Alert:    Hour {first_red or 'NEVER'}")
    print("  Actual Failure:     Hour 68")
    print("-"*60)
    
    # Assertions
    failure_hour = 68
    required_warning_hours = 6
    
    assert first_red is not None, "❌ FAILED: No Red alert issued!"
    assert first_red <= failure_hour - required_warning_hours, \
        f"❌ FAILED: Red alert too late! Issued at hour {first_red}, " \
        f"need by hour {failure_hour - required_warning_hours}"
    
    warning_time = failure_hour - first_red
    print(f"\n✅ SUCCESS: Red alert issued {warning_time} hours before failure")
    print(f"   (Requirement: {required_warning_hours}+ hours)\n")
    
    return True


if __name__ == '__main__':
    test_aranayake_replay()
