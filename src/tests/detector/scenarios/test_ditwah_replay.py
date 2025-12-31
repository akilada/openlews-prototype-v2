"""
Ditwah 2025 Slow-Creep Scenario Replay

Tests escalation path for slow-moving landslide with gradual warning signals.

Scenario:
- Slow moisture accumulation over 10 days
- Gradual tilt acceleration (creep)
- Progressive vibration (acoustic emissions)
- Expected: Yellow → Orange → Red escalation
"""

import sys
import os

sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../../src/lambdas/detector")
    ),
)

from core.risk_scorer import RiskScorer


def load_ditwah_telemetry():
    """
    Simulate 10-day slow creep scenario.

    Returns:
        List of daily telemetry snapshots
    """
    telemetry_sequence = []

    for day in range(11):  # Days 0-10
        # Gradual moisture increase (drizzle + poor drainage)
        moisture = min(85, 25 + day * 6)  # 25% → 85% over 10 days

        # Slowly accelerating tilt (creep phase)
        if day < 3:
            tilt_rate = 0.3  # Imperceptible
        elif day < 6:
            tilt_rate = 1.0 + (day - 3) * 0.5  # Starting to move
        elif day < 9:
            tilt_rate = 2.5 + (day - 6) * 1.0  # Accelerating
        else:
            tilt_rate = 5.5 + (day - 9) * 1.5  # Pre-failure creep

        # Progressive vibration (micro-cracking)
        if day < 5:
            vibration = 6  # Near baseline
        elif day < 8:
            vibration = 12 + (day - 5) * 3  # Increasing
        else:
            vibration = 21 + (day - 8) * 8  # Acoustic emissions spike

        # Gradual rainfall (not extreme, just persistent)
        rainfall_24h = 40 + day * 5  # 40mm → 90mm/day

        # Pore pressure slowly increasing
        pore_pressure = -8 + day * 2  # -8 kPa → +12 kPa

        # Safety factor declining
        safety_factor = max(0.95, 1.7 - day * 0.075)  # 1.7 → 0.95

        telemetry = {
            "day": day,
            "sensor_id": "DITWAH_SENSOR_01",
            "moisture_percent": moisture,
            "tilt_rate_mm_hr": tilt_rate,
            "vibration_count": vibration,
            "vibration_baseline": 5,
            "pore_pressure_kpa": pore_pressure,
            "safety_factor": safety_factor,
            "rainfall_24h_mm": rainfall_24h,
            "critical_moisture_percent": 45.0,  # Residual soil
            "latitude": 6.7800,
            "longitude": 80.9000,
        }

        telemetry_sequence.append(telemetry)

    return telemetry_sequence


def test_ditwah_replay():
    """
    Replay Ditwah slow-creep scenario and verify escalation path.
    """
    print("\n" + "=" * 60)
    print("DITWAH 2025 SLOW-CREEP SCENARIO REPLAY")
    print("=" * 60)

    scorer = RiskScorer()
    telemetry_sequence = load_ditwah_telemetry()

    risk_history = []
    level_history = []

    for telemetry in telemetry_sequence:
        day = telemetry["day"]
        risk = scorer.calculate_sensor_risk(telemetry)

        # Classify risk level
        if risk < 0.3:
            level = "Green"
        elif risk < 0.6:
            level = "Yellow"
        elif risk < 0.8:
            level = "Orange"
        else:
            level = "Red"

        risk_history.append(risk)
        level_history.append(level)

        print(
            f"Day {day:2d}: Risk={risk:.3f} [{level:6s}] | "
            f"Moisture={telemetry['moisture_percent']:.1f}% | "
            f"Tilt={telemetry['tilt_rate_mm_hr']:.2f}mm/hr | "
            f"SF={telemetry['safety_factor']:.2f}"
        )

    print("\n" + "-" * 60)
    print("ESCALATION PATH:")

    # Track escalations
    yellow_day = level_history.index("Yellow") if "Yellow" in level_history else None
    orange_day = level_history.index("Orange") if "Orange" in level_history else None
    red_day = level_history.index("Red") if "Red" in level_history else None

    print(f"  Yellow Alert:  Day {yellow_day if yellow_day is not None else 'NEVER'}")
    print(f"  Orange Alert:  Day {orange_day if orange_day is not None else 'NEVER'}")
    print(f"  Red Alert:     Day {red_day if red_day is not None else 'NEVER'}")
    print("-" * 60)

    # Assertions
    assert yellow_day is not None, "❌ FAILED: No Yellow alert!"
    assert orange_day is not None, "❌ FAILED: No Orange escalation!"
    assert red_day is not None, "❌ FAILED: No Red escalation!"

    # Verify proper ordering
    assert (
        yellow_day < orange_day
    ), f"❌ FAILED: Invalid escalation order (Yellow day {yellow_day} >= Orange day {orange_day})"
    assert (
        orange_day < red_day
    ), f"❌ FAILED: Invalid escalation order (Orange day {orange_day} >= Red day {red_day})"

    # Verify gradual escalation (not all on same day)
    assert (
        red_day - yellow_day >= 2
    ), f"❌ FAILED: Escalation too rapid ({red_day - yellow_day} days)"

    print("\n✅ SUCCESS: Proper escalation path verified")
    print(
        f"   Yellow (Day {yellow_day}) → Orange (Day {orange_day}) → Red (Day {red_day})"
    )
    print(f"   Total warning period: {red_day - yellow_day} days\n")

    # Verify risk is monotonically increasing (creep characteristic)
    for i in range(1, len(risk_history)):
        if risk_history[i] < risk_history[i - 1] - 0.05:  # Allow small fluctuations
            print(
                f"⚠️  WARNING: Risk decreased on Day {i} "
                f"({risk_history[i]:.3f} < {risk_history[i-1]:.3f})"
            )

    return True


if __name__ == "__main__":
    test_ditwah_replay()
