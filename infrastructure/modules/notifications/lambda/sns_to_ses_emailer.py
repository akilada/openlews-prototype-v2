import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import boto3

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


ses = boto3.client("sesv2")


RISK_COLOURS = {
    "Yellow": "#F2C94C",
    "Orange": "#F2994A",
    "Red": "#EB5757",
    "Unknown": "#9B9B9B",
}


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return v if v is not None and v != "" else default


def _parse_json_maybe(s: str) -> Any:
    try:
        return json.loads(s)
    except Exception:
        return s


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _fmt_pct(conf: Any) -> str:
    c = _safe_float(conf, 0.0)
    return f"{round(c * 100):d}%"


def _get_tz() -> timezone:
    tz_name = _env("TIMEZONE", "Asia/Colombo")
    if ZoneInfo:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            return timezone.utc
    return timezone.utc


def _fmt_time(ts: Any) -> str:
    try:
        t = int(ts)
    except Exception:
        return "Unknown time"

    tz = _get_tz()
    dt = datetime.fromtimestamp(t, tz=tz)
    return dt.strftime("%Y-%m-%d %H:%M")


def _location_label(alert: Dict[str, Any]) -> str:
    loc = alert.get("location") or {}
    label = (loc.get("label") or "").strip()
    if label:
        return label
    lat = alert.get("latitude")
    lon = alert.get("longitude")
    if lat is not None and lon is not None:
        return f"{float(lat):.5f}, {float(lon):.5f}"
    return "Unknown location"


def _map_links(alert: Dict[str, Any]) -> Tuple[str, str]:
    loc = alert.get("location") or {}
    search_url = (loc.get("google_maps_url") or alert.get("google_maps_url") or "").strip()
    dir_url = (loc.get("google_maps_directions_url") or "").strip()

    if search_url and dir_url:
        return search_url, dir_url

    lat = alert.get("latitude")
    lon = alert.get("longitude")
    if lat is None or lon is None:
        return "", ""

    latf = float(lat)
    lonf = float(lon)
    zoom = _env("GOOGLE_MAPS_ZOOM", "16")
    search_url = f"https://www.google.com/maps/search/?api=1&query={latf:.6f},{lonf:.6f}"
    dir_url = f"https://www.google.com/maps/dir/?api=1&destination={latf:.6f},{lonf:.6f}"
    _ = zoom
    return search_url, dir_url


def _extract_narrative(alert: Dict[str, Any]) -> Dict[str, str]:
    """
    Detector stores narrative_english as JSON string like {"alert": {"title":..., "situation":...}}
    This normalise to fields for nicer rendering.
    """
    raw = alert.get("narrative_english") or ""
    if not raw:
        return {}

    parsed = _parse_json_maybe(raw)

    if isinstance(parsed, dict):
        a = parsed.get("alert") if "alert" in parsed else parsed
        if isinstance(a, dict):
            out = {}
            for k in ["title", "situation", "risk", "action", "issued", "contact"]:
                v = a.get(k)
                if isinstance(v, str) and v.strip():
                    out[k] = v.strip()
            return out

    # fallback: treat as plain text block
    if isinstance(raw, str) and raw.strip():
        return {"text": raw.strip()}

    return {}


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


def _build_email(alert: Dict[str, Any]) -> Tuple[str, str, str]:
    app = _env("APP_NAME", "OpenLEWS")
    risk = (alert.get("risk_level") or "Unknown").strip()
    colour = RISK_COLOURS.get(risk, RISK_COLOURS["Unknown"])
    confidence = _fmt_pct(alert.get("confidence"))
    action = (alert.get("recommended_action") or "Monitor closely").strip()
    ttf = (alert.get("time_to_failure") or "unknown").strip()
    created = _fmt_time(alert.get("created_at"))
    location = _location_label(alert)

    search_url, dir_url = _map_links(alert)

    hazard = (alert.get("geological_context") or {}).get("hazard_level", "Unknown")
    soil = (alert.get("geological_context") or {}).get("soil_type", "Unknown")

    lat = alert.get("latitude")
    lon = alert.get("longitude")

    # Subject
    subject = f"[{app}] {risk} — {action} — {location}"
    if len(subject) > 120:
        subject = subject[:117] + "..."

    narrative = _extract_narrative(alert)

    # Plain text body
    lines = []
    lines.append(f"{app} ALERT ({risk}) — {action}")
    lines.append("")
    lines.append(f"Location: {location}")
    if lat is not None and lon is not None:
        lines.append(f"Coordinates: {float(lat):.6f}, {float(lon):.6f}")
    if search_url:
        lines.append(f"Map: {search_url}")
    if dir_url:
        lines.append(f"Directions: {dir_url}")
    lines.append("")
    lines.append(f"Confidence: {confidence}")
    lines.append(f"Time to failure: {ttf}")
    lines.append(f"Hazard context: {hazard} | Soil: {soil}")
    lines.append(f"Issued (Sri Lanka Time): {created}")
    lines.append("")
    if narrative:
        if "text" in narrative:
            lines.append(narrative["text"])
        else:
            for k in ["title", "situation", "risk", "action", "issued", "contact"]:
                if k in narrative:
                    lines.append(f"{k.upper()}: {narrative[k]}")
            lines.append("")
    lines.append(f"Alert ID: {alert.get('alert_id', '')}")

    text_body = "\n".join(lines)

    # HTML body
    loc_html = _html_escape(location)
    action_html = _html_escape(action)
    risk_html = _html_escape(risk)
    conf_html = _html_escape(confidence)

    coords_html = ""
    if lat is not None and lon is not None:
        coords_html = f"{float(lat):.6f}, {float(lon):.6f}"

    buttons = ""
    if search_url:
        buttons += f"""
          <a href="{search_url}" style="display:inline-block;padding:10px 14px;margin-right:10px;border-radius:10px;background:#1a73e8;color:#fff;text-decoration:none;font-weight:600;">Open in Google Maps</a>
        """
    if dir_url:
        buttons += f"""
          <a href="{dir_url}" style="display:inline-block;padding:10px 14px;border-radius:10px;background:#34a853;color:#fff;text-decoration:none;font-weight:600;">Directions</a>
        """

    narrative_html = ""
    if narrative:
        if "text" in narrative:
            narrative_html = f"<pre style='white-space:pre-wrap;font-family:inherit;line-height:1.4;margin:0;'>{_html_escape(narrative['text'])}</pre>"
        else:
            def block(title: str, key: str) -> str:
                v = narrative.get(key)
                if not v:
                    return ""
                return f"""
                  <div style="margin-bottom:10px;">
                    <div style="font-weight:700;margin-bottom:4px;">{title}</div>
                    <div style="line-height:1.45;">{_html_escape(v)}</div>
                  </div>
                """
            narrative_html = (
                block("Title", "title") +
                block("Situation", "situation") +
                block("Risk", "risk") +
                block("Action Required", "action") +
                block("Issued", "issued") +
                block("Contact", "contact")
            )

    technical_json = _html_escape(json.dumps(alert, ensure_ascii=False, indent=2))

    html_body = f"""
<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f6f7fb;font-family:Arial,Helvetica,sans-serif;">
    <div style="max-width:720px;margin:0 auto;padding:20px;">
      <div style="background:#fff;border-radius:16px;box-shadow:0 6px 20px rgba(0,0,0,0.06);overflow:hidden;">
        <div style="padding:16px 18px;background:{colour};color:#fff;">
          <div style="font-size:12px;opacity:0.95;letter-spacing:0.04em;">OPENLEWS ALERT</div>
          <div style="font-size:22px;font-weight:800;margin-top:4px;">{risk_html} — {action_html}</div>
          <div style="margin-top:6px;font-size:14px;opacity:0.95;">Confidence: {conf_html} • Time to failure: {_html_escape(ttf)}</div>
        </div>

        <div style="padding:18px;">
          <div style="font-size:16px;font-weight:800;margin-bottom:6px;">{loc_html}</div>
          <div style="color:#555;font-size:14px;margin-bottom:14px;">
            {("Coordinates: " + coords_html) if coords_html else ""}
          </div>

          <div style="margin-bottom:14px;">
            {buttons}
          </div>

          <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:14px;">
            <div style="flex:1;min-width:220px;background:#f3f4f6;border-radius:12px;padding:12px;">
              <div style="font-size:12px;color:#666;font-weight:700;">Issued (Sri Lanka Time)</div>
              <div style="font-size:14px;font-weight:700;margin-top:4px;">{_html_escape(created)}</div>
            </div>
            <div style="flex:1;min-width:220px;background:#f3f4f6;border-radius:12px;padding:12px;">
              <div style="font-size:12px;color:#666;font-weight:700;">Hazard context</div>
              <div style="font-size:14px;font-weight:700;margin-top:4px;">{_html_escape(str(hazard))} • Soil: {_html_escape(str(soil))}</div>
            </div>
          </div>

          <div style="background:#fff7ed;border:1px solid #fed7aa;border-radius:12px;padding:12px;margin-bottom:14px;">
            <div style="font-weight:800;margin-bottom:6px;">Recommended action</div>
            <div style="line-height:1.45;">{_html_escape(action)}</div>
          </div>

          <div style="border-top:1px solid #eee;padding-top:14px;">
            <div style="font-weight:800;margin-bottom:10px;">Message</div>
            {narrative_html if narrative_html else f"<div style='color:#666;line-height:1.5;'>{_html_escape(alert.get('llm_reasoning','') or '')}</div>"}
          </div>

          <details style="margin-top:16px;">
            <summary style="cursor:pointer;font-weight:700;color:#444;">Technical details (JSON)</summary>
            <pre style="white-space:pre-wrap;background:#0b1020;color:#d8dee9;padding:12px;border-radius:12px;overflow:auto;margin-top:10px;font-size:12px;line-height:1.4;">{technical_json}</pre>
          </details>

          <div style="margin-top:16px;color:#888;font-size:12px;">
            Alert ID: {_html_escape(alert.get("alert_id",""))}
          </div>
        </div>
      </div>

      <div style="text-align:center;color:#98a2b3;font-size:12px;margin-top:14px;">
        Sent by OpenLEWS via Amazon SES • Do not reply
      </div>
    </div>
  </body>
</html>
""".strip()

    return subject, html_body, text_body


def _send_email(subject: str, html_body: str, text_body: str) -> None:
    from_email = _env("SES_FROM_EMAIL")
    to_emails = [e.strip() for e in _env("SES_TO_EMAILS").split(",") if e.strip()]

    if not from_email:
        raise RuntimeError("SES_FROM_EMAIL is not set")
    if not to_emails:
        raise RuntimeError("SES_TO_EMAILS is not set")

    ses.send_email(
        FromEmailAddress=from_email,
        Destination={"ToAddresses": to_emails},
        Content={
            "Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                },
            }
        },
    )


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    records = event.get("Records", [])
    sent = 0
    errors: List[str] = []

    for r in records:
        try:
            sns = r.get("Sns", {})
            msg = sns.get("Message", "")

            alert = _parse_json_maybe(msg)
            if not isinstance(alert, dict):
                raise ValueError("SNS Message is not JSON alert dict")

            subject, html_body, text_body = _build_email(alert)
            _send_email(subject, html_body, text_body)
            sent += 1

        except Exception as e:
            errors.append(str(e))

    return {
        "statusCode": 200 if sent > 0 else 500,
        "sent": sent,
        "errors": errors[:5],
    }
