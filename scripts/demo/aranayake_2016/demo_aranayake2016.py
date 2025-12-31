#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    ARANAYAKE 2016 LANDSLIDE DEMO SCRIPT                      ║
║                                                                              ║
║  Simulates the May 17, 2016 Aranayake disaster scenario using OpenLEWS       ║
║  IoT-LLM framework with hybrid Quincunx + Vertical sensor placement.         ║
║                                                                              ║
║  Historical Facts:                                                           ║
║  - Location: Kegalle District, Sabaragamuwa Province                         ║
║  - Crown: 7.1476°N, 80.4546°E (Samasariya/Elangapitiya Hill)                 ║
║  - Rainfall: 446.5mm over 72 hours (May 14-17, 2016)                         ║
║  - Casualties: 127 dead/missing                                              ║
║  - Runout: ~2km debris flow destroying Siripura, Elangapitiya, Pallebage     ║
║                                                                              ║
║  Sensor Topology: 36 sensors in Hybrid (Quincunx + Vertical) arrangement     ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# AWS SDK
import boto3
from botocore.exceptions import ClientError

# ═══════════════════════════════════════════════════════════════════════════════
# ENVIRONMENT LOADING
# ═══════════════════════════════════════════════════════════════════════════════

def load_env_file():
    """Load .env file if present (without requiring python-dotenv)."""
    env_paths = [
        Path.cwd() / ".env",
        Path(__file__).parent / ".env",
        Path.cwd() / ".env.local",
    ]
    
    for env_path in env_paths:
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if not line or line.startswith('#'):
                        continue
                    # Parse KEY=value
                    if '=' in line:
                        key, _, value = line.partition('=')
                        key = key.strip()
                        value = value.strip()
                        # Remove quotes if present
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]
                        # Only set if not already in environment
                        if key and key not in os.environ:
                            os.environ[key] = value
            return env_path
    return None

# Load .env on import
_env_file = load_env_file()

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class DemoConfig:
    """Demo configuration with defaults from environment."""
    region: str = field(default_factory=lambda: os.getenv("AWS_REGION", "ap-southeast-2"))
    telemetry_table: str = field(default_factory=lambda: os.getenv("TELEMETRY_TABLE", "openlews-dev-telemetry"))
    alerts_table: str = field(default_factory=lambda: os.getenv("ALERTS_TABLE", "openlews-dev-alerts"))
    hazard_zones_table: str = field(default_factory=lambda: os.getenv("HAZARD_ZONES_TABLE", "openlews-dev-hazard-zones"))
    detector_lambda: str = field(default_factory=lambda: os.getenv("DETECTOR_LAMBDA", "openlews-dev-detector"))
    rag_lambda: str = field(default_factory=lambda: os.getenv("RAG_LAMBDA", "openlews-dev-rag-query"))
    sns_topic_arn: str = field(default_factory=lambda: os.getenv("SNS_TOPIC_ARN", ""))
    ingestor_api_url: str = field(default_factory=lambda: os.getenv("INGESTOR_API_URL", ""))
    ingestor_api_token: str = field(default_factory=lambda: os.getenv("INGESTOR_API_TOKEN", ""))
    
    # Aranayake coordinates
    crown_lat: float = 7.1476
    crown_lon: float = 80.4546
    toe_lat: float = 6.9639  # Pallebage village
    toe_lon: float = 80.4209
    
    # Demo settings
    sensor_prefix: str = "ARANAYAKE_"
    demo_timestamp: int = field(default_factory=lambda: int(time.time()))
    cleanup_after: bool = False
    verbose: bool = True
    skip_detector: bool = False
    skip_logs: bool = False
    use_api_gateway: bool = False  # If True, ingest via API Gateway instead of direct DynamoDB


# ═══════════════════════════════════════════════════════════════════════════════
# CONSOLE STYLING (Rich-like output without dependencies)
# ═══════════════════════════════════════════════════════════════════════════════

class Console:
    """Simple console styling for demo output."""
    
    # ANSI color codes
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    
    @classmethod
    def header(cls, text: str, char: str = "═") -> None:
        """Print a styled header."""
        width = 80
        border = char * width
        print(f"\n{cls.CYAN}{cls.BOLD}{border}{cls.RESET}")
        print(f"{cls.CYAN}{cls.BOLD}  {text}{cls.RESET}")
        print(f"{cls.CYAN}{cls.BOLD}{border}{cls.RESET}\n")
    
    @classmethod
    def subheader(cls, text: str) -> None:
        """Print a subheader."""
        print(f"\n{cls.YELLOW}{cls.BOLD}▶ {text}{cls.RESET}")
        print(f"{cls.DIM}{'─' * 70}{cls.RESET}")
    
    @classmethod
    def step(cls, number: int, total: int, text: str) -> None:
        """Print a step indicator."""
        print(f"\n{cls.MAGENTA}{cls.BOLD}╔{'═' * 76}╗{cls.RESET}")
        print(f"{cls.MAGENTA}{cls.BOLD}║  STEP {number}/{total}: {text:<66}║{cls.RESET}")
        print(f"{cls.MAGENTA}{cls.BOLD}╚{'═' * 76}╝{cls.RESET}\n")
    
    @classmethod
    def success(cls, text: str) -> None:
        """Print success message."""
        print(f"  {cls.GREEN}✅ {text}{cls.RESET}")
    
    @classmethod
    def warning(cls, text: str) -> None:
        """Print warning message."""
        print(f"  {cls.YELLOW}⚠️  {text}{cls.RESET}")
    
    @classmethod
    def error(cls, text: str) -> None:
        """Print error message."""
        print(f"  {cls.RED}❌ {text}{cls.RESET}")
    
    @classmethod
    def info(cls, text: str) -> None:
        """Print info message."""
        print(f"  {cls.BLUE}ℹ️  {text}{cls.RESET}")
    
    @classmethod
    def data(cls, label: str, value: Any) -> None:
        """Print a data row."""
        print(f"  {cls.DIM}│{cls.RESET} {label:<25} {cls.BOLD}{value}{cls.RESET}")
    
    @classmethod
    def table_header(cls, columns: List[Tuple[str, int]]) -> None:
        """Print table header."""
        header = "  ┌"
        for i, (name, width) in enumerate(columns):
            header += "─" * (width + 2)
            header += "┬" if i < len(columns) - 1 else "┐"
        print(f"{cls.DIM}{header}{cls.RESET}")
        
        row = "  │"
        for name, width in columns:
            row += f" {cls.BOLD}{name:<{width}}{cls.RESET}{cls.DIM} │"
        print(row + cls.RESET)
        
        separator = "  ├"
        for i, (_, width) in enumerate(columns):
            separator += "─" * (width + 2)
            separator += "┼" if i < len(columns) - 1 else "┤"
        print(f"{cls.DIM}{separator}{cls.RESET}")
    
    @classmethod
    def table_row(cls, values: List[Tuple[str, int]], highlight: bool = False) -> None:
        """Print table row."""
        color = cls.YELLOW if highlight else ""
        row = f"  {cls.DIM}│{cls.RESET}"
        for value, width in values:
            row += f" {color}{value:<{width}}{cls.RESET}{cls.DIM} │"
        print(row + cls.RESET)
    
    @classmethod
    def table_footer(cls, columns: List[Tuple[str, int]]) -> None:
        """Print table footer."""
        footer = "  └"
        for i, (_, width) in enumerate(columns):
            footer += "─" * (width + 2)
            footer += "┴" if i < len(columns) - 1 else "┘"
        print(f"{cls.DIM}{footer}{cls.RESET}")
    
    @classmethod
    def progress(cls, current: int, total: int, prefix: str = "") -> None:
        """Print a progress bar."""
        width = 40
        filled = int(width * current / total)
        bar = "█" * filled + "░" * (width - filled)
        pct = current / total * 100
        print(f"\r  {prefix} [{cls.GREEN}{bar}{cls.RESET}] {pct:5.1f}% ({current}/{total})", end="", flush=True)
        if current == total:
            print()
    
    @classmethod
    def slope_diagram(cls) -> None:
        """Print ASCII art of the Aranayake slope with sensor positions."""
        diagram = f"""
{cls.CYAN}  ARANAYAKE LANDSLIDE SLOPE PROFILE - SENSOR DEPLOYMENT{cls.RESET}
{cls.DIM}  ═══════════════════════════════════════════════════════════════════════{cls.RESET}

                                    {cls.RED}▲ CROWN ZONE (~600m){cls.RESET}
                                   {cls.RED}/│\\{cls.RESET}  Samasariya Hill
                                  {cls.YELLOW}○ ○ ○{cls.RESET}     ← 3×3 Quincunx (9 sensors)
                                 {cls.YELLOW}○ ○ ○{cls.RESET}        C01-C09
                                  {cls.YELLOW}○ ○ ○{cls.RESET}
                                 /     \\
                                /       \\
                               /  {cls.RED}MAIN SCARP (~400m){cls.RESET}
                              /   "Unusual Width"   \\
                           {cls.YELLOW}○ ○ ○ ○ ○{cls.RESET}   {cls.MAGENTA}│{cls.RESET}      ← 5×3 Quincunx (12 sensors)
                          {cls.YELLOW}○ ○ ○ ○ ○{cls.RESET}    {cls.MAGENTA}│● 2m{cls.RESET}    M01-M12
                           {cls.YELLOW}○ ○{cls.RESET}         {cls.MAGENTA}│● 5m{cls.RESET}  ← Vertical Borehole (3 sensors)
                          /            {cls.MAGENTA}│● 10m{cls.RESET}   V01-V03
                         /              \\
                        /  {cls.YELLOW}DEBRIS CHANNEL (~200m){cls.RESET}
                       /                  \\
                      {cls.YELLOW}○ ○ ○{cls.RESET}                ← 3×3 Quincunx (9 sensors)
                     {cls.YELLOW}○ ○ ○{cls.RESET}                   D01-D09
                      {cls.YELLOW}○ ○ ○{cls.RESET}
                     /      \\
                    /        \\
                   /  {cls.GREEN}TOE/VILLAGE ZONE (~50m){cls.RESET}
                  /   Pallebage Village      \\
                 {cls.GREEN}○   ○   ○{cls.RESET}                    ← 1×3 Line (3 sensors)
              {cls.DIM}═══════════════════════════════════{cls.RESET}   T01-T03
                   {cls.DIM}~2km runout distance{cls.RESET}

{cls.DIM}  ═══════════════════════════════════════════════════════════════════════{cls.RESET}
  {cls.BOLD}LEGEND:{cls.RESET} {cls.YELLOW}○{cls.RESET} = Surface Sensor   {cls.MAGENTA}●{cls.RESET} = Borehole Sensor   {cls.RED}▲{cls.RESET} = Crown
  {cls.BOLD}TOTAL:{cls.RESET}  36 sensors (Hybrid Quincunx + Vertical topology)
"""
        print(diagram)
    
    @classmethod
    def risk_indicator(cls, level: str) -> str:
        """Get colored risk indicator."""
        colors = {
            "Green": f"{cls.GREEN}🟢 Green{cls.RESET}",
            "Yellow": f"{cls.YELLOW}🟡 Yellow{cls.RESET}",
            "Orange": f"{cls.YELLOW}{cls.BOLD}🟠 Orange{cls.RESET}",
            "Red": f"{cls.RED}{cls.BOLD}🔴 Red{cls.RESET}",
            "CRITICAL": f"{cls.BG_RED}{cls.WHITE}{cls.BOLD} CRITICAL {cls.RESET}",
        }
        return colors.get(level, level)


# ═══════════════════════════════════════════════════════════════════════════════
# SENSOR PLACEMENT GENERATOR
# ═══════════════════════════════════════════════════════════════════════════════

class SensorPlacement:
    """Generate sensor positions using hybrid Quincunx + Vertical topology."""
    
    # Earth radius in meters
    EARTH_RADIUS_M = 6_371_000
    
    @staticmethod
    def _offset_coords(lat: float, lon: float, north_m: float, east_m: float) -> Tuple[float, float]:
        """Offset coordinates by meters (north/east)."""
        # 1 degree latitude ≈ 111,320 meters
        # 1 degree longitude ≈ 111,320 * cos(lat) meters
        m_per_deg_lat = 111_320.0
        m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat))
        
        new_lat = lat + (north_m / m_per_deg_lat)
        new_lon = lon + (east_m / m_per_deg_lon)
        return (new_lat, new_lon)
    
    @staticmethod
    def _interpolate_coords(lat1: float, lon1: float, lat2: float, lon2: float, t: float) -> Tuple[float, float]:
        """Interpolate between two coordinates (t=0 to 1)."""
        return (lat1 + t * (lat2 - lat1), lon1 + t * (lon2 - lon1))
    
    @classmethod
    def generate_quincunx_grid(
        cls,
        center_lat: float,
        center_lon: float,
        rows: int,
        cols: int,
        spacing_m: float,
        prefix: str
    ) -> List[Dict[str, Any]]:
        """
        Generate a Quincunx (staggered) grid of sensors.
        
        Quincunx pattern offsets alternate rows by half the column spacing,
        ensuring any linear feature (crack, water flow) must cross a sensor.
        """
        sensors = []
        sensor_num = 1
        
        # Calculate grid extents
        total_width = (cols - 1) * spacing_m
        total_height = (rows - 1) * spacing_m * 0.866  # √3/2 for hex packing
        
        for row in range(rows):
            # Alternate row offset (Quincunx pattern)
            row_offset = (spacing_m / 2) if (row % 2 == 1) else 0
            
            for col in range(cols):
                north = (row - (rows - 1) / 2) * spacing_m * 0.866
                east = (col - (cols - 1) / 2) * spacing_m + row_offset
                
                lat, lon = cls._offset_coords(center_lat, center_lon, north, east)
                
                sensors.append({
                    "sensor_id": f"{prefix}{sensor_num:02d}",
                    "latitude": round(lat, 8),
                    "longitude": round(lon, 8),
                    "zone": prefix.rstrip("_"),
                    "type": "surface",
                    "depth_m": 0.5,  # Standard surface installation
                })
                sensor_num += 1
        
        return sensors
    
    @classmethod
    def generate_vertical_borehole(
        cls,
        lat: float,
        lon: float,
        depths_m: List[float],
        prefix: str
    ) -> List[Dict[str, Any]]:
        """Generate vertical borehole sensors at specified depths."""
        sensors = []
        for i, depth in enumerate(depths_m, 1):
            sensors.append({
                "sensor_id": f"{prefix}{i:02d}",
                "latitude": round(lat, 8),
                "longitude": round(lon, 8),
                "zone": "VERTICAL_BOREHOLE",
                "type": "borehole",
                "depth_m": depth,
            })
        return sensors
    
    @classmethod
    def generate_aranayake_deployment(cls, config: DemoConfig) -> List[Dict[str, Any]]:
        """
        Generate complete Aranayake sensor deployment.
        
        Topology based on JICA report observations:
        - Crown zone: 3×3 Quincunx (capture initiation)
        - Main scarp: 5×3 Quincunx + 3 vertical (capture "unusual width" + depth)
        - Debris channel: 3×3 Quincunx (track propagation)
        - Toe/village: 1×3 line (final warning)
        """
        all_sensors = []
        
        # Interpolation points along the 2km runout
        # t=0.0 (crown) to t=1.0 (toe)
        crown = (config.crown_lat, config.crown_lon)
        toe = (config.toe_lat, config.toe_lon)
        
        # 1. CROWN ZONE (t ≈ 0.0-0.1, ~600m elevation)
        # Spacing: 15m ensures all 9 sensors are within 50m CORRELATION_RADIUS_M
        # Max diagonal distance in 3x3 grid: sqrt(2) * 2 * 15m * 0.866 ≈ 37m < 50m ✓
        crown_center = cls._interpolate_coords(*crown, *toe, 0.05)
        crown_sensors = cls.generate_quincunx_grid(
            center_lat=crown_center[0],
            center_lon=crown_center[1],
            rows=3, cols=3,
            spacing_m=15,  # Reduced from 20m to ensure all within 50m radius
            prefix=f"{config.sensor_prefix}C"
        )
        for s in crown_sensors:
            s["zone"] = "CROWN"
            s["elevation_m"] = 600
        all_sensors.extend(crown_sensors)
        
        # 2. MAIN SCARP ZONE (t ≈ 0.2-0.4, ~400m elevation)
        # Key zone for detecting "unusual width" (JICA report)
        # Using 4x3 grid at 15m spacing: max diagonal ≈ 45m < 50m ✓
        scarp_center = cls._interpolate_coords(*crown, *toe, 0.30)
        scarp_sensors = cls.generate_quincunx_grid(
            center_lat=scarp_center[0],
            center_lon=scarp_center[1],
            rows=3, cols=4,  # Wider to capture "unusual width"
            spacing_m=15,    # Reduced from 25m to ensure cluster detection
            prefix=f"{config.sensor_prefix}M"
        )
        for s in scarp_sensors:
            s["zone"] = "MAIN_SCARP"
            s["elevation_m"] = 400
        all_sensors.extend(scarp_sensors)
        
        # 3. VERTICAL BOREHOLE in main scarp (soil-bedrock interface detection)
        # Position within the main scarp cluster so borehole sensors contribute
        # to cluster detection (same lat/lon, different depths)
        borehole_loc = cls._offset_coords(scarp_center[0], scarp_center[1], 5, 10)
        borehole_sensors = cls.generate_vertical_borehole(
            lat=borehole_loc[0],
            lon=borehole_loc[1],
            depths_m=[2.0, 5.0, 10.0],
            prefix=f"{config.sensor_prefix}V"
        )
        for s in borehole_sensors:
            s["elevation_m"] = 400
            s["zone"] = "MAIN_SCARP"  # Same zone as surface sensors for clustering
        all_sensors.extend(borehole_sensors)
        
        # 4. DEBRIS CHANNEL (t ≈ 0.5-0.7, ~200m elevation)
        # 3x3 grid at 15m: max diagonal ≈ 37m < 50m ✓
        channel_center = cls._interpolate_coords(*crown, *toe, 0.60)
        channel_sensors = cls.generate_quincunx_grid(
            center_lat=channel_center[0],
            center_lon=channel_center[1],
            rows=3, cols=3,
            spacing_m=15,  # Reduced from 20m
            prefix=f"{config.sensor_prefix}D"
        )
        for s in channel_sensors:
            s["zone"] = "DEBRIS_CHANNEL"
            s["elevation_m"] = 200
        all_sensors.extend(channel_sensors)
        
        # 5. TOE/VILLAGE ZONE (t ≈ 0.95, ~50m elevation)
        # 1x3 line at 20m spacing: max distance = 40m < 50m ✓
        toe_center = cls._interpolate_coords(*crown, *toe, 0.95)
        toe_sensors = cls.generate_quincunx_grid(
            center_lat=toe_center[0],
            center_lon=toe_center[1],
            rows=1, cols=3,
            spacing_m=20,  # Reduced from 30m
            prefix=f"{config.sensor_prefix}T"
        )
        for s in toe_sensors:
            s["zone"] = "TOE_VILLAGE"
            s["elevation_m"] = 50
        all_sensors.extend(toe_sensors)
        
        return all_sensors


# ═══════════════════════════════════════════════════════════════════════════════
# TELEMETRY GENERATOR
# ═══════════════════════════════════════════════════════════════════════════════

class TelemetryGenerator:
    """
    Generate realistic telemetry data for Aranayake scenario.
    
    Based on forensic analysis:
    - 446.5mm rainfall over 72 hours
    - Tilt rate 5mm/hr observed 6 hours before failure
    - Acoustic emissions (vibration) increased before failure
    - Soil reached critical saturation at ~68 hours
    """
    
    @staticmethod
    def calculate_geohash(lat: float, lon: float, precision: int = 6) -> str:
        """Calculate geohash for coordinates."""
        try:
            import pygeohash as pgh
            return pgh.encode(lat, lon, precision=precision)
        except ImportError:
            # Fallback: simple coordinate hash
            lat_bin = int((lat + 90) * 1000)
            lon_bin = int((lon + 180) * 1000)
            return f"{lat_bin:06d}{lon_bin:06d}"[:precision]
    
    @classmethod
    def generate_crisis_telemetry(
        cls,
        sensor: Dict[str, Any],
        timestamp: int,
        hour_of_scenario: int = 68  # Hours into the 72-hour event
    ) -> Dict[str, Any]:
        """
        Generate crisis-level telemetry for a sensor.
        
        Args:
            sensor: Sensor definition dict
            timestamp: Unix timestamp
            hour_of_scenario: Hour within the 72-hour event (0-72)
        """
        zone = sensor.get("zone", "UNKNOWN")
        depth_m = sensor.get("depth_m", 0.5)
        elevation_m = sensor.get("elevation_m", 300)
        
        # Base values scaled by zone and time
        progress = hour_of_scenario / 72.0  # 0.0 to 1.0
        
        # Crown zone saturates first (uphill)
        zone_factors = {
            "CROWN": {"moisture_base": 85, "tilt_mult": 1.2, "vib_mult": 1.0},
            "MAIN_SCARP": {"moisture_base": 92, "tilt_mult": 1.5, "vib_mult": 1.3},
            "VERTICAL_BOREHOLE": {"moisture_base": 95, "tilt_mult": 0.8, "vib_mult": 0.6},
            "DEBRIS_CHANNEL": {"moisture_base": 78, "tilt_mult": 0.9, "vib_mult": 1.1},
            "TOE_VILLAGE": {"moisture_base": 65, "tilt_mult": 0.5, "vib_mult": 0.8},
        }
        
        factors = zone_factors.get(zone, zone_factors["MAIN_SCARP"])
        
        # Add some sensor-specific variation (deterministic based on sensor_id hash)
        sensor_hash = hash(sensor["sensor_id"]) % 1000 / 1000.0
        variation = 0.9 + sensor_hash * 0.2  # 0.9 to 1.1
        
        # Calculate metrics
        moisture = min(98, factors["moisture_base"] + progress * 10) * variation
        
        # Tilt accelerates exponentially near failure
        if hour_of_scenario < 40:
            tilt_rate = 0.5 * factors["tilt_mult"]
        elif hour_of_scenario < 60:
            tilt_rate = (2.0 + (hour_of_scenario - 40) * 0.15) * factors["tilt_mult"]
        else:
            # Rapid creep phase (Aranayake signature: 5mm/hr 6 hours before)
            tilt_rate = (5.0 + (hour_of_scenario - 60) * 0.8) * factors["tilt_mult"]
        
        # Vibration (acoustic emissions) - baseline is 5
        vibration_baseline = 5
        if hour_of_scenario < 50:
            vibration = int(8 * factors["vib_mult"])
        elif hour_of_scenario < 65:
            vibration = int((15 + (hour_of_scenario - 50) * 2) * factors["vib_mult"])
        else:
            # Micro-cracking spike (Meeriyabedda pattern)
            vibration = int((35 + (hour_of_scenario - 65) * 8) * factors["vib_mult"])
        
        # Pore pressure: negative (suction) → positive
        pore_pressure = -8 + progress * 25  # -8 kPa → +17 kPa
        if zone == "VERTICAL_BOREHOLE":
            # Deeper sensors show higher pore pressure (perched water table)
            pore_pressure += depth_m * 0.8
        
        # Safety factor declining
        safety_factor = max(0.85, 1.8 - progress * 0.95)
        
        # Rainfall: 446.5mm over 72 hours, peaks in middle period
        if hour_of_scenario < 24:
            rainfall_24h = 80 + hour_of_scenario * 3
        elif hour_of_scenario < 48:
            rainfall_24h = 160 + (hour_of_scenario - 24) * 5  # Peak rain
        else:
            rainfall_24h = 280 + (hour_of_scenario - 48) * 3
        rainfall_24h = min(350, rainfall_24h)
        
        geohash = cls.calculate_geohash(sensor["latitude"], sensor["longitude"])
        
        return {
            "sensor_id": sensor["sensor_id"],
            "timestamp": timestamp,
            "latitude": sensor["latitude"],
            "longitude": sensor["longitude"],
            "geohash": geohash,
            
            # Core metrics
            "moisture_percent": round(moisture, 1),
            "tilt_rate_mm_hr": round(tilt_rate, 2),
            "pore_pressure_kpa": round(pore_pressure, 1),
            "vibration_count": vibration,
            "vibration_baseline": vibration_baseline,
            "safety_factor": round(safety_factor, 2),
            "rainfall_24h_mm": round(rainfall_24h, 1),
            
            # Trend indicators (for LLM context)
            "moisture_trend_pct_hr": round(progress * 3, 2),
            "tilt_acceleration_mm_hr2": round(0.1 + progress * 0.4, 3),
            
            # Sensor metadata
            "battery_percent": 85 - int(sensor_hash * 20),
            "temperature_c": 22 + sensor_hash * 5,
            
            # Geological context (will be enriched by ingestor)
            "critical_moisture_percent": 40.0,  # Colluvium threshold
        }


# ═══════════════════════════════════════════════════════════════════════════════
# AWS SERVICE CLIENTS
# ═══════════════════════════════════════════════════════════════════════════════

class AWSClients:
    """Manage AWS service clients."""
    
    def __init__(self, config: DemoConfig):
        self.config = config
        self.region = config.region
        
        self.dynamodb = boto3.resource("dynamodb", region_name=self.region)
        self.lambda_client = boto3.client("lambda", region_name=self.region)
        self.logs_client = boto3.client("logs", region_name=self.region)
        self.sns_client = boto3.client("sns", region_name=self.region)
        
        self.telemetry_table = self.dynamodb.Table(config.telemetry_table)
        self.alerts_table = self.dynamodb.Table(config.alerts_table)
        self.hazard_zones_table = self.dynamodb.Table(config.hazard_zones_table)


# ═══════════════════════════════════════════════════════════════════════════════
# DEMO STEPS
# ═══════════════════════════════════════════════════════════════════════════════

class AranayakeDemo:
    """Main demo orchestrator."""
    
    def __init__(self, config: DemoConfig):
        self.config = config
        self.clients = AWSClients(config)
        self.sensors: List[Dict[str, Any]] = []
        self.telemetry: List[Dict[str, Any]] = []
        self.alerts: List[Dict[str, Any]] = []
        self.start_time = time.time()
    
    def run(self) -> None:
        """Execute the full demo."""
        self._print_banner()
        
        # Step 1: Generate sensor deployment
        self._step_1_generate_sensors()
        
        # Step 2: Generate crisis telemetry
        self._step_2_generate_telemetry()
        
        # Step 3: Ingest telemetry to DynamoDB
        self._step_3_ingest_telemetry()
        
        # Step 4: Invoke detector Lambda
        if not self.config.skip_detector:
            self._step_4_invoke_detector()
        
        # Step 5: Check alerts
        self._step_5_check_alerts()
        
        # Step 6: Display CloudWatch logs
        if not self.config.skip_logs:
            self._step_6_display_logs()
        
        # Summary
        self._print_summary()
        
        # Cleanup
        if self.config.cleanup_after:
            self._cleanup()
    
    def _print_banner(self) -> None:
        """Print demo banner."""
        Console.header("🌧️  ARANAYAKE 2016 LANDSLIDE SCENARIO - OPENLEWS DEMO")
        print(f"""
  {Console.BOLD}Historical Event:{Console.RESET}
  • Date: May 17, 2016
  • Location: Kegalle District, Sabaragamuwa Province
  • Rainfall: 446.5mm over 72 hours
  • Casualties: 127 dead/missing
  • Runout: ~2km debris flow

  {Console.BOLD}Environment:{Console.RESET}""")
        if _env_file:
            Console.data("Loaded .env", str(_env_file))
        else:
            Console.data("Loaded .env", "(none found, using environment)")
        
        print(f"""
  {Console.BOLD}Demo Configuration:{Console.RESET}""")
        Console.data("AWS Region", self.config.region)
        Console.data("Telemetry Table", self.config.telemetry_table)
        Console.data("Alerts Table", self.config.alerts_table)
        Console.data("Detector Lambda", self.config.detector_lambda)
        Console.data("Sensor Prefix", self.config.sensor_prefix)
        Console.data("Demo Timestamp", datetime.utcfromtimestamp(self.config.demo_timestamp).isoformat())
        
        # Show ingestion mode
        if self.config.use_api_gateway:
            print(f"""
  {Console.BOLD}Ingestion Mode:{Console.RESET} {Console.CYAN}API Gateway{Console.RESET}""")
            Console.data("API URL", self.config.ingestor_api_url or "(not configured)")
            Console.data("Auth Token", "✓ configured" if self.config.ingestor_api_token else "✗ not configured")
        else:
            print(f"""
  {Console.BOLD}Ingestion Mode:{Console.RESET} {Console.GREEN}Direct DynamoDB{Console.RESET}""")
        print()
    
    def _step_1_generate_sensors(self) -> None:
        """Generate hybrid sensor deployment."""
        Console.step(1, 6, "SENSOR DEPLOYMENT GENERATION")
        
        self.sensors = SensorPlacement.generate_aranayake_deployment(self.config)
        
        Console.success(f"Generated {len(self.sensors)} sensors in hybrid topology")
        
        # Display slope diagram
        Console.slope_diagram()
        
        # Show sensor summary by zone
        Console.subheader("Sensor Distribution by Zone")
        zone_counts: Dict[str, int] = {}
        for s in self.sensors:
            zone = s.get("zone", "UNKNOWN")
            zone_counts[zone] = zone_counts.get(zone, 0) + 1
        
        columns = [("Zone", 20), ("Sensors", 10), ("Type", 12), ("Spacing", 10)]
        Console.table_header(columns)
        
        zone_details = {
            "CROWN": ("Quincunx 3×3", "15m"),
            "MAIN_SCARP": ("Quincunx 4×3", "15m"),
            "VERTICAL_BOREHOLE": ("Vertical", "N/A"),
            "DEBRIS_CHANNEL": ("Quincunx 3×3", "15m"),
            "TOE_VILLAGE": ("Line 1×3", "20m"),
        }
        
        for zone, count in zone_counts.items():
            details = zone_details.get(zone, ("Unknown", "Unknown"))
            Console.table_row([
                (zone, 20),
                (str(count), 10),
                (details[0], 12),
                (details[1], 10),
            ])
        
        Console.table_row([
            (Console.BOLD + "TOTAL" + Console.RESET, 20),
            (Console.BOLD + str(len(self.sensors)) + Console.RESET, 10),
            ("", 12),
            ("", 10),
        ])
        Console.table_footer(columns)
    
    def _step_2_generate_telemetry(self) -> None:
        """Generate crisis-level telemetry for all sensors."""
        Console.step(2, 6, "TELEMETRY GENERATION (Hour 68 of 72)")
        
        hour_of_scenario = 68  # 4 hours before actual failure
        
        for sensor in self.sensors:
            telemetry = TelemetryGenerator.generate_crisis_telemetry(
                sensor=sensor,
                timestamp=self.config.demo_timestamp,
                hour_of_scenario=hour_of_scenario,
            )
            self.telemetry.append(telemetry)
        
        Console.success(f"Generated {len(self.telemetry)} telemetry records")
        
        # Show sample telemetry
        Console.subheader("Sample Telemetry (Critical Indicators)")
        
        columns = [
            ("Sensor ID", 18),
            ("Moisture%", 10),
            ("Tilt mm/h", 10),
            ("Pore kPa", 10),
            ("Vibration", 10),
            ("SF", 6),
        ]
        Console.table_header(columns)
        
        # Show one sensor from each zone
        shown_zones = set()
        for t in self.telemetry:
            sensor = next((s for s in self.sensors if s["sensor_id"] == t["sensor_id"]), {})
            zone = sensor.get("zone", "UNKNOWN")
            
            if zone in shown_zones:
                continue
            shown_zones.add(zone)
            
            # Highlight critical values
            moisture = t["moisture_percent"]
            tilt = t["tilt_rate_mm_hr"]
            pore = t["pore_pressure_kpa"]
            vib = t["vibration_count"]
            sf = t["safety_factor"]
            
            highlight = moisture > 90 or tilt > 5 or sf < 1.0
            
            Console.table_row([
                (t["sensor_id"], 18),
                (f"{moisture:.1f}%", 10),
                (f"{tilt:.2f}", 10),
                (f"{pore:.1f}", 10),
                (str(vib), 10),
                (f"{sf:.2f}", 6),
            ], highlight=highlight)
        
        Console.table_footer(columns)
        
        # Risk indicators
        print()
        Console.info(f"Rainfall (24h): {self.telemetry[0]['rainfall_24h_mm']:.0f}mm (NBRO Red threshold: 150mm)")
        Console.warning("Multiple sensors showing CRITICAL thresholds!")
    
    def _step_3_ingest_telemetry(self) -> None:
        """Ingest telemetry to DynamoDB (direct) or via API Gateway."""
        
        if self.config.use_api_gateway and self.config.ingestor_api_url:
            self._ingest_via_api_gateway()
        else:
            self._ingest_via_dynamodb()
    
    def _ingest_via_api_gateway(self) -> None:
        """Ingest telemetry via API Gateway (authenticated)."""
        Console.step(3, 6, "TELEMETRY INGESTION → API Gateway")
        
        api_url = self.config.ingestor_api_url.rstrip('/')
        endpoint = f"{api_url}/telemetry"
        
        Console.info(f"API Endpoint: {endpoint}")
        
        if self.config.ingestor_api_token:
            Console.success("Auth token configured")
        else:
            Console.warning("No auth token configured - requests may fail")
        
        success_count = 0
        error_count = 0
        
        # Prepare headers
        headers = {
            "Content-Type": "application/json",
        }
        if self.config.ingestor_api_token:
            headers["Authorization"] = f"Bearer {self.config.ingestor_api_token}"
        
        # Send telemetry in batches (API Gateway may have payload limits)
        batch_size = 10
        batches = [self.telemetry[i:i+batch_size] for i in range(0, len(self.telemetry), batch_size)]
        
        for batch_idx, batch in enumerate(batches):
            try:
                # Prepare batch payload
                payload = {
                    "records": batch,
                    "source": "demo_aranayake_2016",
                    "demo_mode": True,
                }
                
                data = json.dumps(payload).encode('utf-8')
                
                req = Request(endpoint, data=data, headers=headers, method='POST')
                
                with urlopen(req, timeout=30) as response:
                    status_code = response.status
                    response_body = response.read().decode('utf-8')
                    
                    if status_code in (200, 201, 202):
                        success_count += len(batch)
                    else:
                        error_count += len(batch)
                        if self.config.verbose:
                            Console.error(f"Batch {batch_idx+1} failed: {response_body[:100]}")
                
                Console.progress(
                    min((batch_idx + 1) * batch_size, len(self.telemetry)),
                    len(self.telemetry),
                    "Ingesting via API"
                )
                
                # Small delay between batches to avoid rate limiting
                time.sleep(0.1)
                
            except HTTPError as e:
                error_count += len(batch)
                error_body = e.read().decode('utf-8') if e.fp else str(e)
                if self.config.verbose:
                    Console.error(f"HTTP {e.code} for batch {batch_idx+1}: {error_body[:100]}")
            except URLError as e:
                error_count += len(batch)
                if self.config.verbose:
                    Console.error(f"Connection error for batch {batch_idx+1}: {e.reason}")
            except Exception as e:
                error_count += len(batch)
                if self.config.verbose:
                    Console.error(f"Error for batch {batch_idx+1}: {e}")
        
        print()  # New line after progress bar
        Console.success(f"Ingested {success_count}/{len(self.telemetry)} records via API Gateway")
        
        if error_count > 0:
            Console.error(f"{error_count} records failed")
        
        # API Gateway verification (optional - query alerts table for side effects)
        Console.subheader("API Gateway Response Summary")
        Console.data("Endpoint", endpoint)
        Console.data("Records Sent", len(self.telemetry))
        Console.data("Successful", success_count)
        Console.data("Failed", error_count)
    
    def _ingest_via_dynamodb(self) -> None:
        """Ingest telemetry directly to DynamoDB."""
        Console.step(3, 6, "TELEMETRY INGESTION → DynamoDB (Direct)")
        
        # Convert floats to Decimal for DynamoDB
        def to_decimal(obj):
            if isinstance(obj, float):
                return Decimal(str(round(obj, 8)))
            if isinstance(obj, dict):
                return {k: to_decimal(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [to_decimal(v) for v in obj]
            return obj
        
        success_count = 0
        error_count = 0
        
        with self.clients.telemetry_table.batch_writer() as writer:
            for i, t in enumerate(self.telemetry):
                try:
                    item = to_decimal(t)
                    item["ingested_at"] = datetime.utcnow().isoformat()
                    item["ttl"] = int(time.time()) + (30 * 24 * 3600)  # 30 days
                    
                    writer.put_item(Item=item)
                    success_count += 1
                    
                    Console.progress(i + 1, len(self.telemetry), "Ingesting")
                except Exception as e:
                    error_count += 1
                    if self.config.verbose:
                        Console.error(f"Failed to write {t['sensor_id']}: {e}")
        
        print()  # New line after progress bar
        Console.success(f"Ingested {success_count}/{len(self.telemetry)} records to DynamoDB")
        
        if error_count > 0:
            Console.error(f"{error_count} records failed")
        
        # Verify ingestion
        Console.subheader("Ingestion Verification")
        try:
            # Query one record to verify
            sample_id = self.telemetry[0]["sensor_id"]
            response = self.clients.telemetry_table.get_item(
                Key={
                    "sensor_id": sample_id,
                    "timestamp": self.config.demo_timestamp,
                }
            )
            if "Item" in response:
                Console.success(f"Verified: {sample_id} exists in DynamoDB")
                Console.data("Ingested At", response["Item"].get("ingested_at", "N/A"))
            else:
                Console.warning(f"Could not verify {sample_id}")
        except Exception as e:
            Console.error(f"Verification failed: {e}")
    
    def _step_4_invoke_detector(self) -> None:
        """Invoke the detector Lambda."""
        Console.step(4, 6, "DETECTOR LAMBDA INVOCATION")
        
        Console.info(f"Invoking: {self.config.detector_lambda}")
        
        try:
            start = time.time()
            response = self.clients.lambda_client.invoke(
                FunctionName=self.config.detector_lambda,
                InvocationType="RequestResponse",
                Payload=json.dumps({}),
            )
            elapsed = time.time() - start
            
            payload = json.loads(response["Payload"].read())
            status_code = response.get("StatusCode", 500)
            
            if status_code == 200:
                Console.success(f"Detector completed in {elapsed:.2f}s")
                
                # Parse response body
                if isinstance(payload.get("body"), str):
                    body = json.loads(payload["body"])
                else:
                    body = payload.get("body", payload)
                
                Console.subheader("Detector Results")
                Console.data("Status", body.get("status", "unknown"))
                Console.data("Sensors Analyzed", body.get("sensors_analyzed", 0))
                Console.data("Clusters Detected", body.get("clusters_detected", 0))
                Console.data("Alerts Created", body.get("alerts_created", 0))
                Console.data("Alerts Escalated", body.get("alerts_escalated", 0))
                Console.data("Execution Time", f"{body.get('execution_time', 0):.2f}s")
                
                if body.get("clusters_detected", 0) > 0:
                    Console.warning("⚠️  CLUSTER DETECTION TRIGGERED!")
                    Console.info("Multiple sensors showing correlated high-risk patterns")
                
                if body.get("alerts_created", 0) > 0:
                    Console.success(f"🚨 {body.get('alerts_created')} new alert(s) created!")
            else:
                Console.error(f"Detector failed with status {status_code}")
                if self.config.verbose:
                    Console.data("Response", json.dumps(payload, indent=2))
                    
        except Exception as e:
            Console.error(f"Failed to invoke detector: {e}")
    
    def _step_5_check_alerts(self) -> None:
        """Check alerts table for generated alerts."""
        Console.step(5, 6, "ALERT VERIFICATION → DynamoDB")
        
        # Scan for recent alerts
        since_ts = self.config.demo_timestamp - 900  # Last 15 minutes
        
        try:
            response = self.clients.alerts_table.scan(
                FilterExpression="#ca >= :t",
                ExpressionAttributeNames={"#ca": "created_at"},
                ExpressionAttributeValues={":t": since_ts},
                Limit=20,
            )
            
            items = response.get("Items", [])
            self.alerts = items
            
            if items:
                Console.success(f"Found {len(items)} alert(s) in alerts table")
                
                Console.subheader("Alert Details")
                
                columns = [
                    ("Alert ID", 35),
                    ("Risk Level", 12),
                    ("Status", 10),
                    ("Confidence", 10),
                ]
                Console.table_header(columns)
                
                for alert in items[:10]:
                    risk_level = alert.get("risk_level", "Unknown")
                    highlight = risk_level in ["Orange", "Red"]
                    
                    Console.table_row([
                        (str(alert.get("alert_id", "?"))[:35], 35),
                        (Console.risk_indicator(risk_level), 12),
                        (str(alert.get("status", "?")), 10),
                        (f"{float(alert.get('confidence', 0)):.2f}", 10),
                    ], highlight=highlight)
                
                Console.table_footer(columns)
                
                # Show first alert details
                if items:
                    first_alert = items[0]
                    Console.subheader("Sample Alert Details")
                    Console.data("Alert ID", first_alert.get("alert_id", "N/A"))
                    Console.data("Risk Level", Console.risk_indicator(first_alert.get("risk_level", "Unknown")))
                    Console.data("Confidence", f"{float(first_alert.get('confidence', 0)):.2f}")
                    Console.data("Recommended Action", first_alert.get("recommended_action", "N/A"))
                    Console.data("Time to Failure", first_alert.get("time_to_failure", "N/A"))
                    
                    if first_alert.get("narrative_english"):
                        print()
                        print(f"  {Console.CYAN}{Console.BOLD}Generated Narrative:{Console.RESET}")
                        narrative = first_alert.get("narrative_english", "")
                        # Wrap narrative
                        for line in narrative.split("\n"):
                            print(f"  {Console.DIM}│{Console.RESET} {line}")
                    
                    if first_alert.get("llm_reasoning"):
                        print()
                        print(f"  {Console.CYAN}{Console.BOLD}LLM Reasoning:{Console.RESET}")
                        reasoning = first_alert.get("llm_reasoning", "")
                        print(f"  {Console.DIM}│{Console.RESET} {reasoning[:200]}...")
                    
                    if first_alert.get("google_maps_url"):
                        print()
                        Console.info(f"Location: {first_alert.get('google_maps_url')}")
            else:
                Console.warning("No alerts found in the last 15 minutes")
                Console.info("This may indicate:")
                Console.info("  • Detector didn't find high-risk patterns")
                Console.info("  • Bedrock rate limiting (check CloudWatch logs)")
                Console.info("  • Alert deduplication prevented new alert")
                
        except Exception as e:
            Console.error(f"Failed to query alerts: {e}")
    
    def _step_6_display_logs(self) -> None:
        """Display relevant CloudWatch logs."""
        Console.step(6, 6, "CLOUDWATCH LOGS")
        
        log_groups = [
            f"/aws/lambda/{self.config.detector_lambda}",
        ]
        
        for log_group in log_groups:
            Console.subheader(f"Logs: {log_group}")
            
            try:
                # Get most recent log stream
                streams = self.clients.logs_client.describe_log_streams(
                    logGroupName=log_group,
                    orderBy="LastEventTime",
                    descending=True,
                    limit=1,
                )
                
                if not streams.get("logStreams"):
                    Console.warning("No log streams found")
                    continue
                
                stream_name = streams["logStreams"][0]["logStreamName"]
                
                # Get recent log events
                events = self.clients.logs_client.get_log_events(
                    logGroupName=log_group,
                    logStreamName=stream_name,
                    limit=20,
                    startFromHead=False,
                )
                
                if events.get("events"):
                    Console.success(f"Recent logs from {stream_name[:50]}...")
                    print()
                    
                    for event in events["events"][-15:]:
                        ts = datetime.utcfromtimestamp(event["timestamp"] / 1000).strftime("%H:%M:%S")
                        msg = event["message"].strip()[:100]
                        
                        # Color-code based on content
                        if "ERROR" in msg or "error" in msg:
                            color = Console.RED
                        elif "WARNING" in msg or "warn" in msg:
                            color = Console.YELLOW
                        elif "LLM" in msg or "Bedrock" in msg or "RAG" in msg:
                            color = Console.CYAN
                        elif "alert" in msg.lower():
                            color = Console.GREEN
                        else:
                            color = Console.DIM
                        
                        print(f"  {Console.DIM}[{ts}]{Console.RESET} {color}{msg}{Console.RESET}")
                else:
                    Console.warning("No recent log events")
                    
            except ClientError as e:
                if "ResourceNotFoundException" in str(e):
                    Console.warning(f"Log group not found: {log_group}")
                else:
                    Console.error(f"Failed to fetch logs: {e}")
            except Exception as e:
                Console.error(f"Failed to fetch logs: {e}")
    
    def _print_summary(self) -> None:
        """Print demo summary."""
        elapsed = time.time() - self.start_time
        
        Console.header("📊 DEMO SUMMARY")
        
        print(f"""
  {Console.BOLD}ARANAYAKE 2016 SCENARIO SIMULATION COMPLETE{Console.RESET}
  {'─' * 50}
""")
        Console.data("Sensors Deployed", len(self.sensors))
        Console.data("Telemetry Records", len(self.telemetry))
        Console.data("Alerts Generated", len(self.alerts))
        Console.data("Total Demo Time", f"{elapsed:.2f} seconds")
        
        print(f"""
  {Console.BOLD}Key Observations:{Console.RESET}""")
        
        # Calculate summary stats
        avg_moisture = sum(t["moisture_percent"] for t in self.telemetry) / len(self.telemetry)
        max_tilt = max(t["tilt_rate_mm_hr"] for t in self.telemetry)
        min_sf = min(t["safety_factor"] for t in self.telemetry)
        
        Console.data("Avg Moisture", f"{avg_moisture:.1f}% (Critical: 40%)")
        Console.data("Max Tilt Rate", f"{max_tilt:.2f} mm/hr (Aranayake signature: 5mm/hr)")
        Console.data("Min Safety Factor", f"{min_sf:.2f} (Failure: <1.0)")
        Console.data("Rainfall (24h)", f"{self.telemetry[0]['rainfall_24h_mm']:.0f}mm (NBRO Red: 150mm)")
        
        if self.alerts:
            print(f"""
  {Console.BOLD}Alert Summary:{Console.RESET}""")
            risk_counts = {}
            for a in self.alerts:
                level = a.get("risk_level", "Unknown")
                risk_counts[level] = risk_counts.get(level, 0) + 1
            
            for level, count in risk_counts.items():
                Console.data(f"{level} Alerts", count)
        
        print(f"""
  {Console.BOLD}CloudWatch Log Groups:{Console.RESET}
  {Console.DIM}•{Console.RESET} /aws/lambda/{self.config.detector_lambda}
  {Console.DIM}•{Console.RESET} /aws/lambda/{self.config.rag_lambda}

  {Console.BOLD}Next Steps:{Console.RESET}
  {Console.DIM}1.{Console.RESET} Check SNS topic for published notifications
  {Console.DIM}2.{Console.RESET} Review alert details in DynamoDB
  {Console.DIM}3.{Console.RESET} Analyze Bedrock token usage in CloudWatch
""")
    
    def _cleanup(self) -> None:
        """Clean up demo data."""
        Console.subheader("Cleanup")
        
        Console.info("Removing demo telemetry records...")
        
        deleted = 0
        for t in self.telemetry:
            try:
                self.clients.telemetry_table.delete_item(
                    Key={
                        "sensor_id": t["sensor_id"],
                        "timestamp": self.config.demo_timestamp,
                    }
                )
                deleted += 1
            except Exception:
                pass
        
        Console.success(f"Deleted {deleted} telemetry records")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Aranayake 2016 Landslide Demo for OpenLEWS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run full demo (direct DynamoDB ingestion)
  python demo_aranayake_2016.py

  # Run with API Gateway ingestion (uses .env for INGESTOR_API_URL and token)
  python demo_aranayake_2016.py --use-api

  # Run with API Gateway and explicit token
  python demo_aranayake_2016.py --use-api --api-token "your-bearer-token"

  # Skip detector invocation (just ingest data)
  python demo_aranayake_2016.py --skip-detector

  # Skip CloudWatch logs display
  python demo_aranayake_2016.py --skip-logs

  # Clean up after demo
  python demo_aranayake_2016.py --cleanup

  # Custom region and tables
  python demo_aranayake_2016.py --region ap-southeast-2 --telemetry-table my-table

Environment Variables (or .env file):
  AWS_REGION            AWS region (default: ap-southeast-2)
  TELEMETRY_TABLE       Telemetry DynamoDB table name
  ALERTS_TABLE          Alerts DynamoDB table name
  DETECTOR_LAMBDA       Detector Lambda function name
  INGESTOR_API_URL      API Gateway URL for telemetry ingestion
  INGESTOR_API_TOKEN    Bearer token for API Gateway authentication
        """,
    )
    
    parser.add_argument("--region", default=None, help="AWS region")
    parser.add_argument("--telemetry-table", default=None, help="Telemetry DynamoDB table")
    parser.add_argument("--alerts-table", default=None, help="Alerts DynamoDB table")
    parser.add_argument("--detector-lambda", default=None, help="Detector Lambda function name")
    parser.add_argument("--skip-detector", action="store_true", help="Skip detector Lambda invocation")
    parser.add_argument("--skip-logs", action="store_true", help="Skip CloudWatch logs display")
    parser.add_argument("--cleanup", action="store_true", help="Clean up demo data after run")
    parser.add_argument("--quiet", action="store_true", help="Reduce output verbosity")
    
    # API Gateway options
    parser.add_argument("--use-api", action="store_true", 
                        help="Use API Gateway for ingestion instead of direct DynamoDB")
    parser.add_argument("--api-url", default=None, 
                        help="API Gateway URL (overrides INGESTOR_API_URL env var)")
    parser.add_argument("--api-token", default=None, 
                        help="API Bearer token (overrides INGESTOR_API_TOKEN env var)")
    
    args = parser.parse_args()
    
    # Build config
    config = DemoConfig()
    
    if args.region:
        config.region = args.region
    if args.telemetry_table:
        config.telemetry_table = args.telemetry_table
    if args.alerts_table:
        config.alerts_table = args.alerts_table
    if args.detector_lambda:
        config.detector_lambda = args.detector_lambda
    
    config.skip_detector = args.skip_detector
    config.skip_logs = args.skip_logs
    config.cleanup_after = args.cleanup
    config.verbose = not args.quiet
    
    # API Gateway config
    config.use_api_gateway = args.use_api
    if args.api_url:
        config.ingestor_api_url = args.api_url
    if args.api_token:
        config.ingestor_api_token = args.api_token
    
    # Validate API Gateway config if using it
    if config.use_api_gateway and not config.ingestor_api_url:
        print(f"{Console.RED}❌ --use-api requires INGESTOR_API_URL in .env or --api-url{Console.RESET}")
        sys.exit(1)
    
    # Run demo
    try:
        demo = AranayakeDemo(config)
        demo.run()
    except KeyboardInterrupt:
        print(f"\n\n{Console.YELLOW}❌ Demo cancelled by user{Console.RESET}")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n{Console.RED}❌ Demo failed: {e}{Console.RESET}")
        if config.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()