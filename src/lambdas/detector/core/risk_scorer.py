"""
Risk Scoring Engine for Individual Sensors

Implements the individual sensor risk calculation based on:
- Mohr-Coulomb failure criteria
- NBRO rainfall thresholds
- Aranayake 2016 forensic analysis
- Meeriyabedda 2014 precursor signatures

Each sensor reading is scored 0.0 (safe) to 1.0 (critical failure).
"""

from typing import Dict
from aws_lambda_powertools import Logger

logger = Logger(child=True)


class RiskScorer:
    """
    Calculate individual sensor risk scores.
    """
    
    # NBRO rainfall thresholds (mm/24h)
    RAINFALL_YELLOW = 75.0
    RAINFALL_ORANGE = 100.0
    RAINFALL_RED = 150.0
    RAINFALL_CRITICAL = 200.0  # Aranayake-level intensity
    
    # Tilt rate thresholds (mm/hour)
    TILT_RATE_MINOR = 1.0
    TILT_RATE_MODERATE = 5.0  # Aranayake pre-failure signature
    TILT_RATE_CRITICAL = 10.0
    
    # Vibration multipliers (vs baseline)
    VIBRATION_ELEVATED = 2.0
    VIBRATION_HIGH = 5.0  # Meeriyabedda acoustic signature
    VIBRATION_CRITICAL = 10.0
    
    # Safety Factor thresholds
    SAFETY_FACTOR_CAUTION = 1.5
    SAFETY_FACTOR_WARNING = 1.2
    SAFETY_FACTOR_FAILURE = 1.0
    
    # Component weights for composite score
    WEIGHTS = {
        'moisture': 0.35,
        'tilt_velocity': 0.25,
        'vibration': 0.15,
        'pore_pressure': 0.15,
        'safety_factor': 0.10
    }
    
    def __init__(self):
        logger.info("Initializing RiskScorer", extra={
            'weights': self.WEIGHTS
        })
    
    def calculate_sensor_risk(self, telemetry: Dict) -> float:
        """
        Calculate composite risk score for a sensor.
        
        Args:
            telemetry: Latest sensor reading
            
        Returns:
            Risk score (0.0 to 1.0)
        """
        # Extract readings
        moisture = telemetry.get('moisture_percent', 0)
        tilt_rate = telemetry.get('tilt_rate_mm_hr', 0)
        vibration_count = telemetry.get('vibration_count', 0)
        vibration_baseline = telemetry.get('vibration_baseline', 5)
        pore_pressure = telemetry.get('pore_pressure_kpa', -10)  # Default negative (suction)
        safety_factor = telemetry.get('safety_factor', 2.0)
        rainfall_24h = telemetry.get('rainfall_24h_mm', 0)
        
        # Get critical moisture threshold from enrichment (if available)
        critical_moisture = telemetry.get('critical_moisture_percent', 40.0)
        
        # Calculate component scores
        moisture_score = self._score_moisture(moisture, critical_moisture)
        tilt_score = self._score_tilt_velocity(tilt_rate)
        vibration_score = self._score_vibration(vibration_count, vibration_baseline)
        pore_pressure_score = self._score_pore_pressure(pore_pressure)
        safety_factor_score = self._score_safety_factor(safety_factor)
        
        # Calculate weighted composite
        composite_risk = (
            moisture_score * self.WEIGHTS['moisture'] +
            tilt_score * self.WEIGHTS['tilt_velocity'] +
            vibration_score * self.WEIGHTS['vibration'] +
            pore_pressure_score * self.WEIGHTS['pore_pressure'] +
            safety_factor_score * self.WEIGHTS['safety_factor']
        )
        
        # Rainfall can amplify risk (multiplier, not additive)
        rainfall_multiplier = self._rainfall_amplification(rainfall_24h)
        composite_risk = min(1.0, composite_risk * rainfall_multiplier)
        
        logger.debug(f"Risk calculated for {telemetry.get('sensor_id')}", extra={
            'moisture_score': moisture_score,
            'tilt_score': tilt_score,
            'vibration_score': vibration_score,
            'pore_pressure_score': pore_pressure_score,
            'safety_factor_score': safety_factor_score,
            'rainfall_multiplier': rainfall_multiplier,
            'composite_risk': composite_risk
        })
        
        return composite_risk
    
    def _score_moisture(self, moisture: float, critical_threshold: float) -> float:
        """
        Score soil moisture relative to critical threshold.
        
        This implements the matric suction loss mechanism from research:
        - Below 80% of critical: Safe (matric suction present)
        - At critical: Suction lost, strength reduced
        - Above critical: Positive pore pressure building
        
        Args:
            moisture: Current moisture percent (0-100)
            critical_threshold: Site-specific critical value from RAG
            
        Returns:
            Score (0.0 to 1.0)
        """
        if moisture < critical_threshold * 0.8:
            return 0.0
        elif moisture < critical_threshold:
            # Approaching critical (suction declining)
            return 0.3
        elif moisture < critical_threshold * 1.2:
            # At or slightly above critical
            return 0.6
        else:
            # Well above critical (positive pore pressure likely)
            return 1.0
    
    def _score_tilt_velocity(self, rate: float) -> float:
        """
        Score tilt rate (rate of change).
        
        Based on Aranayake forensics: 5mm/hr was observed 6 hours before failure.
        
        Args:
            rate: Tilt rate in mm/hour
            
        Returns:
            Score (0.0 to 1.0)
        """
        if rate < self.TILT_RATE_MINOR:
            return 0.0
        elif rate < self.TILT_RATE_MODERATE:
            return 0.2
        elif rate < self.TILT_RATE_CRITICAL:
            # Aranayake-level creep
            return 0.7
        else:
            # Extreme creep, failure imminent
            return 1.0
    
    def _score_vibration(self, count: int, baseline: int) -> float:
        """
        Score vibration/acoustic emissions.
        
        Based on Meeriyabedda precursors: 5x baseline was reported
        before failure (animals agitated, ground noise).
        
        Args:
            count: Current vibration event count
            baseline: Normal background level
            
        Returns:
            Score (0.0 to 1.0)
        """
        if baseline == 0:
            baseline = 5  # Default to avoid division by zero
        
        multiplier = count / baseline
        
        if multiplier < self.VIBRATION_ELEVATED:
            return 0.0
        elif multiplier < self.VIBRATION_HIGH:
            return 0.3
        elif multiplier < self.VIBRATION_CRITICAL:
            # Meeriyabedda-level acoustic activity
            return 0.7
        else:
            return 1.0
    
    def _score_pore_pressure(self, pressure: float) -> float:
        """
        Score pore water pressure.
        
        Negative = Matric suction (stabilizing)
        Positive = Buoyancy effect (destabilizing)
        
        Based on Mohr-Coulomb: σ_eff = σ_total - u_w
        
        Args:
            pressure: Pore pressure in kPa (negative = suction)
            
        Returns:
            Score (0.0 to 1.0)
        """
        if pressure < 0:
            # Negative pressure = suction = stable
            return 0.0
        elif pressure < 5:
            # Slight positive pressure
            return 0.4
        elif pressure < 10:
            # Moderate positive pressure
            return 0.7
        else:
            # High positive pressure (buoyancy effect strong)
            return 1.0
    
    def _score_safety_factor(self, safety_factor: float) -> float:
        """
        Score Factor of Safety.
        
        FoS = Resisting Forces / Driving Forces
        FoS < 1.0 = Failure
        
        Args:
            safety_factor: Calculated or estimated FoS
            
        Returns:
            Score (0.0 to 1.0)
        """
        if safety_factor > self.SAFETY_FACTOR_CAUTION:
            return 0.0
        elif safety_factor > self.SAFETY_FACTOR_WARNING:
            return 0.3
        elif safety_factor >= self.SAFETY_FACTOR_FAILURE:
            return 0.7
        else:
            # FoS < 1.0 = Active failure
            return 1.0
    
    def _rainfall_amplification(self, rainfall_24h: float) -> float:
        """
        Calculate rainfall amplification factor.
        
        Heavy rainfall accelerates all failure mechanisms:
        - Increases pore pressure
        - Reduces matric suction
        - Increases slope weight (water loading)
        
        Args:
            rainfall_24h: 24-hour cumulative rainfall (mm)
            
        Returns:
            Amplification factor (1.0 to 1.5)
        """
        if rainfall_24h < self.RAINFALL_YELLOW:
            return 1.0
        elif rainfall_24h < self.RAINFALL_ORANGE:
            return 1.1  # 10% amplification
        elif rainfall_24h < self.RAINFALL_RED:
            return 1.2  # 20% amplification
        elif rainfall_24h < self.RAINFALL_CRITICAL:
            return 1.3  # 30% amplification
        else:
            # Aranayake-level (>200mm/24h)
            return 1.5  # 50% amplification
