#!/usr/bin/env bash
set -euo pipefail

echo "=== OpenLEWS High-Risk CLUSTER Demo (forces alerts + RAG + Bedrock) ==="

REGION="${REGION:-ap-southeast-2}"
TELEMETRY_TABLE="${TELEMETRY_TABLE:-openlews-dev-telemetry}"
ALERTS_TABLE="${ALERTS_TABLE:-openlews-dev-alerts}"
DETECTOR_FN="${DETECTOR_FN:-openlews-dev-detector}"

# Use an existing sensor only as an "anchor" for lat/lon/geohash/enrichment
ANCHOR_SENSOR="${ANCHOR_SENSOR:-BADULLA_Q23}"

# Demo cluster sensors (new IDs)
CLUSTER_PREFIX="${CLUSTER_PREFIX:-DEMO_CLUSTER_}"
CLUSTER_SIZE="${CLUSTER_SIZE:-5}"

NOW_TS="$(date +%s)"
SINCE_TS="$((NOW_TS - 900))"   # last 15 mins

WORKDIR="/tmp/openlews_demo"
mkdir -p "${WORKDIR}"

echo "Region:          ${REGION}"
echo "Telemetry table: ${TELEMETRY_TABLE}"
echo "Alerts table:    ${ALERTS_TABLE}"
echo "Detector fn:     ${DETECTOR_FN}"
echo "Anchor sensor:   ${ANCHOR_SENSOR}"
echo "Cluster size:    ${CLUSTER_SIZE}"
echo "Timestamp:       ${NOW_TS}"
echo

echo "Fetching anchor sensor latest telemetry..."
aws dynamodb query \
  --table-name "${TELEMETRY_TABLE}" \
  --region "${REGION}" \
  --no-cli-pager \
  --key-condition-expression "sensor_id = :s" \
  --expression-attribute-values "{\":s\":{\"S\":\"${ANCHOR_SENSOR}\"}}" \
  --scan-index-forward \
  --limit 1 \
  --output json > "${WORKDIR}/anchor_latest.json"

python3 - <<PY > "${WORKDIR}/anchor_parsed.json"
import json, sys
data=json.load(open("${WORKDIR}/anchor_latest.json","r",encoding="utf-8"))
items=data.get("Items",[])
if not items:
    raise SystemExit(f"No telemetry found for anchor sensor ${ANCHOR_SENSOR}")

it=items[0]
def getN(key):
    v=it.get(key, {})
    return float(v.get("N")) if "N" in v else None
def getS(key):
    v=it.get(key, {})
    return v.get("S") if "S" in v else None

out={
  "lat": getN("latitude"),
  "lon": getN("longitude"),
  "geohash": getS("geohash"),
  "ndis_enrichment": it.get("ndis_enrichment"),
}
if out["lat"] is None or out["lon"] is None or out["geohash"] is None:
    raise SystemExit("Anchor record missing latitude/longitude/geohash")

print(json.dumps(out))
PY

ANCHOR_LAT="$(python3 -c 'import json;print(json.load(open("'"${WORKDIR}/anchor_parsed.json"'"))["lat"])')"
ANCHOR_LON="$(python3 -c 'import json;print(json.load(open("'"${WORKDIR}/anchor_parsed.json"'"))["lon"])')"
ANCHOR_GH="$(python3 -c 'import json;print(json.load(open("'"${WORKDIR}/anchor_parsed.json"'"))["geohash"])')"

echo "Anchor location: ${ANCHOR_LAT}, ${ANCHOR_LON}"
echo "Anchor geohash:  ${ANCHOR_GH}"
echo

echo "Creating ${CLUSTER_SIZE} sensors within ~50m radius..."
python3 - <<PY > "${WORKDIR}/cluster_items.jsonl"
import json, math

anchor=json.load(open("${WORKDIR}/anchor_parsed.json","r",encoding="utf-8"))
lat0=float(anchor["lat"])
lon0=float(anchor["lon"])
gh=anchor["geohash"]
ndis=anchor.get("ndis_enrichment")

# Offsets in metres (keep within 50m)
# (north/south/east/west + centre)
offsets_m=[
  (0, 0),
  (20, 0),
  (-20, 0),
  (0, 20),
  (0, -20),
  (30, 30),
  (-30, -30),
]

# Convert metres to degrees
# 1 deg lat ~ 111_320 m
# 1 deg lon ~ 111_320 * cos(lat) m
m_per_deg_lat = 111320.0
m_per_deg_lon = 111320.0 * math.cos(math.radians(lat0))

def add_offset(lat, lon, north_m, east_m):
    return (
        lat + (north_m / m_per_deg_lat),
        lon + (east_m / m_per_deg_lon),
    )

cluster_size=int(${CLUSTER_SIZE})
for i in range(cluster_size):
    north_m, east_m = offsets_m[i % len(offsets_m)]
    lat, lon = add_offset(lat0, lon0, north_m, east_m)

    sensor_id=f"${CLUSTER_PREFIX}{i+1:02d}"
    item={
      "sensor_id": {"S": sensor_id},
      "timestamp": {"N": str(${NOW_TS})},
      "latitude": {"N": f"{lat:.8f}"},
      "longitude": {"N": f"{lon:.8f}"},
      "geohash": {"S": gh},

      # High-risk metrics (designed to push risk_score ~ 1.0)
      "moisture_percent": {"N": "95"},
      "tilt_rate_mm_hr": {"N": "6.0"},
      "pore_pressure_kpa": {"N": "15"},
      "safety_factor": {"N": "0.95"},
      "rainfall_24h_mm": {"N": "220"},
      "vibration_count": {"N": "35"},
      "vibration_baseline": {"N": "5"},
    }

    if ndis:
      item["ndis_enrichment"]=ndis
      item["enriched"]={"BOOL": True}

    print(json.dumps(item))
PY

# Put items
while IFS= read -r line; do
  SID="$(python3 -c 'import json;print(json.loads("""'"$line"'""")["sensor_id"]["S"])')"
  echo "Putting ${SID}..."
  aws dynamodb put-item \
    --table-name "${TELEMETRY_TABLE}" \
    --region "${REGION}" \
    --no-cli-pager \
    --item "${line}" >/dev/null
done < "${WORKDIR}/cluster_items.jsonl"

echo
echo "Invoking detector..."
aws lambda invoke \
  --function-name "${DETECTOR_FN}" \
  --region "${REGION}" \
  --no-cli-pager \
  --payload '{}' \
  "${WORKDIR}/detector_out.json" >/dev/null

echo "Detector response:"
cat "${WORKDIR}/detector_out.json"
echo

echo "Checking alerts table (last 15 mins)..."
aws dynamodb scan \
  --table-name "${ALERTS_TABLE}" \
  --region "${REGION}" \
  --no-cli-pager \
  --filter-expression "#ca >= :t" \
  --expression-attribute-names '{"#ca":"created_at"}' \
  --expression-attribute-values "{\":t\":{\"N\":\"${SINCE_TS}\"}}" \
  --limit 20 \
  --output json | python3 -c '
import json,sys
d=json.load(sys.stdin)
items=d.get("Items",[])
print(f"Alerts found: {len(items)}")
for it in items[:10]:
    aid=it.get("alert_id",{}).get("S")
    rl=it.get("risk_level",{}).get("S")
    st=it.get("status",{}).get("S")
    print(f"- {aid} | {rl} | {st}")
'

echo
echo "=== Done ==="
echo "Check CloudWatch logs for 'Querying RAG' and 'Requesting LLM risk assessment'."
