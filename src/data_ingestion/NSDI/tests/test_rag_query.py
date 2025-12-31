#!/usr/bin/env python3
"""
Test RAG Query Script for NDIS Hazard Zones (Demo-Grade MVP)

Key improvements (minimal but high impact):
- Auto-applies metadata filters when query mentions hazard severity (high/moderate/low/critical).
- Uses bounds filtering for Badulla (because district fields are often "Unknown").
- Supports "largest area" style queries by retrieving more results then sorting locally.
- Pinecone import + error messages aligned with renamed official package "pinecone".

Usage:
    python test_rag_query.py
    python test_rag_query.py "Find very high hazard zones near Badulla"
"""

import os
import sys
import re
from typing import List, Dict, Any, Optional, Tuple

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    print("❌ Error: sentence-transformers not installed")
    print("Run: pip install sentence-transformers")
    sys.exit(1)

try:
    from pinecone import Pinecone
except ImportError:
    print("❌ Error: pinecone not installed")
    print('Run: pip install "pinecone<8"   (recommended for Python 3.9)')
    sys.exit(1)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    print("⚠️  python-dotenv not installed. Using environment variables only.")


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "lews-geological-knowledge")

# IMPORTANT: your ingestion used namespace "openlews"
# Default here is set to "openlews" to align with your prototype.
NAMESPACE = os.getenv("PINECONE_NAMESPACE", "openlews")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# If your metadata uses "hazard_level" (recommended), keep this.
# If you changed earlier versions, you can override with env var.
LEVEL_FIELD = os.getenv("PINECONE_LEVEL_FIELD", "hazard_level")

# Default Badulla bounds (matches what you used for ingestion)
# Format: min_lat,max_lat,min_lon,max_lon
DEFAULT_BADULLA_BOUNDS = os.getenv("BADULLA_BOUNDS", "6.8,7.2,80.8,81.2")

# When we need to sort by area, we must retrieve more than top_k
AREA_SORT_FETCH_K = int(os.getenv("AREA_SORT_FETCH_K", "200"))


# -----------------------------------------------------------------------------
# Query Planning (lightweight “MVP intelligence”)
# -----------------------------------------------------------------------------
HAZARD_ALIASES = {
    # phrase -> allowed hazard levels in the dataset
    "very high": ["Very High", "High"],  # fallback to High if Very High not present
    "high": ["High"],
    "moderate": ["Moderate"],
    "medium": ["Moderate"],
    "low": ["Low"],
    "critical": ["Very High", "High"],  # dataset may not have "Critical"
    "dangerous": ["Very High", "High"],
    "severe": ["Very High", "High"],
    "extreme": ["Very High"],
}

AREA_HINTS = [
    "largest area",
    "biggest area",
    "largest zones",
    "biggest zones",
    "largest polygons",
    "largest",
    "biggest",
]


def _parse_bounds(bounds_csv: str) -> Optional[Tuple[float, float, float, float]]:
    try:
        parts = [float(x.strip()) for x in bounds_csv.split(",")]
        if len(parts) != 4:
            return None
        return (parts[0], parts[1], parts[2], parts[3])
    except Exception:
        return None


def _contains_badulla(query_text: str) -> bool:
    return "badulla" in query_text.lower()


def _detect_hazard_levels(query_text: str) -> Optional[List[str]]:
    q = query_text.lower()
    found: List[str] = []

    # check multi-word first
    if "very high" in q:
        found.extend(HAZARD_ALIASES["very high"])

    # then check other keywords
    for key, levels in HAZARD_ALIASES.items():
        if key == "very high":
            continue
        if re.search(rf"\b{re.escape(key)}\b", q):
            found.extend(levels)

    # de-dup preserve order
    seen = set()
    ordered = []
    for lvl in found:
        if lvl not in seen:
            ordered.append(lvl)
            seen.add(lvl)

    return ordered or None


def _wants_area_sort(query_text: str) -> bool:
    q = query_text.lower()
    return any(h in q for h in AREA_HINTS)


def _build_pinecone_filter(
    hazard_levels: Optional[List[str]] = None,
    bounds: Optional[Tuple[float, float, float, float]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Build Pinecone metadata filter using supported operators.
    Only $and / $or allowed at top level. :contentReference[oaicite:1]{index=1}
    """
    clauses: List[Dict[str, Any]] = []

    if hazard_levels:
        # Support both "hazard_level" and "level" just in case,
        # without requiring you to re-ingest immediately.
        clauses.append(
            {
                "$or": [
                    {LEVEL_FIELD: {"$in": hazard_levels}},
                    {"level": {"$in": hazard_levels}},
                ]
            }
        )

    if bounds:
        min_lat, max_lat, min_lon, max_lon = bounds
        # Numeric comparisons are supported. :contentReference[oaicite:2]{index=2}
        clauses.extend(
            [
                {"centroid_lat": {"$gte": min_lat}},
                {"centroid_lat": {"$lte": max_lat}},
                {"centroid_lon": {"$gte": min_lon}},
                {"centroid_lon": {"$lte": max_lon}},
            ]
        )

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _get_total_vector_count(stats: Any) -> int:
    # pinecone SDK may return dict-like or object-like
    try:
        if isinstance(stats, dict):
            return int(stats.get("total_vector_count", 0))
        return int(getattr(stats, "total_vector_count", 0))
    except Exception:
        return 0


def _get_matches(results: Any) -> List[Dict[str, Any]]:
    # results may be dict-like or object-like
    try:
        if isinstance(results, dict):
            return results.get("matches", []) or []
        matches = getattr(results, "matches", None)
        return list(matches) if matches else []
    except Exception:
        return []


# -----------------------------------------------------------------------------
# Core Functions
# -----------------------------------------------------------------------------
def initialize_rag_system():
    """Initialize embedding model and Pinecone connection."""
    if not PINECONE_API_KEY:
        print("❌ Error: PINECONE_API_KEY not set")
        print("Set it in .env file or environment variable")
        sys.exit(1)

    print("🔧 Initializing RAG system...")
    print(f"   Model: {EMBEDDING_MODEL}")
    print(f"   Index: {INDEX_NAME}")
    print(f"   Namespace: {NAMESPACE}")
    print(f"   Level field: {LEVEL_FIELD}")

    print("\n📥 Loading embedding model...")
    model = SentenceTransformer(EMBEDDING_MODEL)
    print("✓ Model loaded")

    print("\n🌲 Connecting to Pinecone...")
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(INDEX_NAME)

    stats = index.describe_index_stats()
    total_vectors = _get_total_vector_count(stats)

    print(f"✓ Connected to index '{INDEX_NAME}'")
    print(f"   Total vectors: {total_vectors}")

    if total_vectors == 0:
        print("\n⚠️  Warning: Index is empty!")
        print("Populate it using your NDIS pipeline first.")

    return model, index


def query_hazard_zones(
    model: SentenceTransformer,
    index: Any,
    query_text: str,
    top_k: int = 5,
    filters: Optional[Dict[str, Any]] = None,
    auto_filters: bool = True,
    bounds: Optional[Tuple[float, float, float, float]] = None,
) -> List[Dict[str, Any]]:
    """
    Query Pinecone for relevant hazard zones.

    auto_filters=True adds:
    - hazard severity filters (if present in query)
    - Badulla bounds filter (if query mentions "Badulla" and no explicit bounds passed)
    """
    planned_bounds = bounds
    if auto_filters and planned_bounds is None and _contains_badulla(query_text):
        planned_bounds = _parse_bounds(DEFAULT_BADULLA_BOUNDS)

    hazard_levels = _detect_hazard_levels(query_text) if auto_filters else None
    auto_filter = _build_pinecone_filter(
        hazard_levels=hazard_levels, bounds=planned_bounds
    )

    # Merge user-provided filter with auto filter (AND)
    final_filter = None
    if filters and auto_filter:
        final_filter = {"$and": [filters, auto_filter]}
    else:
        final_filter = filters or auto_filter

    query_vector = model.encode(query_text).tolist()

    query_params: Dict[str, Any] = {
        "vector": query_vector,
        "top_k": top_k,
        "include_metadata": True,
        "namespace": NAMESPACE,
    }
    if final_filter:
        query_params["filter"] = final_filter

    results = index.query(**query_params)
    return _get_matches(results)


def print_results(query: str, results: List[Dict[str, Any]]):
    """Pretty print query results."""
    print("\n" + "=" * 70)
    print(f"🔍 Query: {query}")
    print("=" * 70)

    if not results:
        print("❌ No results found")
        return

    for i, match in enumerate(results, 1):
        metadata = match.get("metadata", {}) or {}

        zone_id = match.get("id") or match.get("id", "Unknown")
        score = match.get("score", 0.0)

        level = metadata.get("hazard_level") or metadata.get("level") or "Unknown"

        print(f"\n{i}. Zone ID: {zone_id}")
        print(f"   Similarity Score: {score:.4f} (1.0 = perfect match)")
        print(f"   Hazard Level: {level}")

        lat = metadata.get("centroid_lat")
        lon = metadata.get("centroid_lon")
        if lat is not None and lon is not None:
            try:
                print(f"   Location: {float(lat):.4f}°N, {float(lon):.4f}°E")
            except Exception:
                print(f"   Location: {lat}, {lon}")
            print(f"   Google Maps: https://www.google.com/maps?q={lat},{lon}")

        geohash = metadata.get("geohash")
        if geohash:
            print(f"   Geohash: {geohash}")

        area = metadata.get("area_sqm")
        if area is not None:
            print(f"   Area (shape_area): {area}")

    print("\n" + "=" * 70)


def demo_queries(model: SentenceTransformer, index: Any):
    """Run demo queries with auto filters."""
    demo_questions = [
        # Badulla + severity (bounds + metadata filtering makes this trustworthy)
        "Find high hazard zones near Badulla",
        "Show me very high risk landslide areas near Badulla",
        "Critical landslide risk locations near Badulla",
        # Demonstrate filter-only query (no location required)
        "Show me moderate hazard zones",
        # Demonstrate area sorting
        "Which zones have the largest area near Badulla?",
    ]

    print("\n" + "=" * 70)
    print("🎓 DEMO: Running Sample Queries (with smart filters)")
    print("=" * 70)

    for i, question in enumerate(demo_questions, 1):
        print(f"\n[{i}/{len(demo_questions)}] {question}")

        if _wants_area_sort(question):
            # Fetch more, then sort locally by metadata area_sqm descending
            candidates = query_hazard_zones(
                model, index, question, top_k=AREA_SORT_FETCH_K, auto_filters=True
            )
            candidates_sorted = sorted(
                candidates,
                key=lambda m: float((m.get("metadata", {}) or {}).get("area_sqm", 0.0)),
                reverse=True,
            )
            results = candidates_sorted[:3]
        else:
            results = query_hazard_zones(
                model, index, question, top_k=3, auto_filters=True
            )

        if results:
            print(f"   ✓ Found {len(results)} results (top shown)")
            for j, match in enumerate(results, 1):
                md = match.get("metadata", {}) or {}
                level = md.get("hazard_level") or md.get("level") or "Unknown"
                score = match.get("score", 0.0)
                print(f"      {j}. {match.get('id')} - {level} (score: {score:.3f})")
        else:
            print("   ❌ No results")

        import time

        time.sleep(0.4)

    print("\n" + "=" * 70)


def filtered_query_example(model: SentenceTransformer, index: Any):
    """Example of explicit filtered queries (manual filters)."""
    print("\n" + "=" * 70)
    print("🎯 DEMO: Filtered Queries (Explicit)")
    print("=" * 70)

    # Very High hazard zones
    print("\n1) Explicit filter: hazard_level IN ['Very High']")
    results = query_hazard_zones(
        model,
        index,
        "landslide zones",
        top_k=5,
        filters={LEVEL_FIELD: {"$in": ["Very High"]}},
        auto_filters=False,
    )
    print(f"   Found {len(results)} results")

    print("\n2) Explicit filter: hazard_level IN ['High','Very High']")
    results = query_hazard_zones(
        model,
        index,
        "dangerous areas",
        top_k=5,
        filters={LEVEL_FIELD: {"$in": ["High", "Very High"]}},
        auto_filters=False,
    )
    print(f"   Found {len(results)} results")

    # Badulla bounds filter demo
    badulla = _parse_bounds(DEFAULT_BADULLA_BOUNDS)
    if badulla:
        print("\n3) Explicit bounds filter: Badulla bounds + High/Very High")
        bounds_filter = _build_pinecone_filter(
            hazard_levels=["High", "Very High"], bounds=badulla
        )
        results = query_hazard_zones(
            model,
            index,
            "hazard zones",
            top_k=5,
            filters=bounds_filter,
            auto_filters=False,
        )
        print(f"   Found {len(results)} results")

    print("\n" + "=" * 70)


def interactive_mode(model: SentenceTransformer, index: Any):
    """Interactive query mode with smart filters."""
    print("\n" + "=" * 70)
    print("💬 Interactive Query Mode (smart filters enabled)")
    print("=" * 70)
    print("Tips:")
    print("- Include 'Badulla' to apply demo bounds automatically.")
    print("- Use hazard words: high / very high / moderate / low / critical.")
    print("- Type 'area' or 'largest' to see area sorting behaviour.")
    print("Type 'exit' to stop.")
    print("=" * 70)

    while True:
        try:
            query = input("\n🔍 Query: ").strip()
            if not query:
                continue

            if query.lower() in ["exit", "quit", "q"]:
                print("\n👋 Goodbye!")
                break

            if query.lower() == "help":
                print("\nExample queries:")
                print("- Find high hazard zones near Badulla")
                print("- Show me very high risk landslide areas near Badulla")
                print("- Which zones have the largest area near Badulla?")
                print("- Show me moderate hazard zones")
                continue

            if _wants_area_sort(query):
                candidates = query_hazard_zones(
                    model, index, query, top_k=AREA_SORT_FETCH_K, auto_filters=True
                )
                candidates_sorted = sorted(
                    candidates,
                    key=lambda m: float(
                        (m.get("metadata", {}) or {}).get("area_sqm", 0.0)
                    ),
                    reverse=True,
                )
                results = candidates_sorted[:5]
            else:
                results = query_hazard_zones(
                    model, index, query, top_k=5, auto_filters=True
                )

            print_results(query, results)

        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")


def main():
    model, index = initialize_rag_system()

    # CLI single query
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        if _wants_area_sort(query):
            candidates = query_hazard_zones(
                model, index, query, top_k=AREA_SORT_FETCH_K, auto_filters=True
            )
            candidates_sorted = sorted(
                candidates,
                key=lambda m: float((m.get("metadata", {}) or {}).get("area_sqm", 0.0)),
                reverse=True,
            )
            results = candidates_sorted[:5]
        else:
            results = query_hazard_zones(
                model, index, query, top_k=5, auto_filters=True
            )

        print_results(query, results)
        return

    # Menu
    print("\n" + "=" * 70)
    print("🎯 NDIS RAG Query Test")
    print("=" * 70)
    print("\nWhat would you like to do?")
    print("1. Run demo queries (smart filters)")
    print("2. Run filtered query examples (explicit)")
    print("3. Interactive mode")
    print("4. Custom single query")

    choice = input("\nChoice (1-4): ").strip()

    if choice == "1":
        demo_queries(model, index)
    elif choice == "2":
        filtered_query_example(model, index)
    elif choice == "3":
        interactive_mode(model, index)
    elif choice == "4":
        query = input("\nEnter your query: ").strip()
        if query:
            if _wants_area_sort(query):
                candidates = query_hazard_zones(
                    model, index, query, top_k=AREA_SORT_FETCH_K, auto_filters=True
                )
                candidates_sorted = sorted(
                    candidates,
                    key=lambda m: float(
                        (m.get("metadata", {}) or {}).get("area_sqm", 0.0)
                    ),
                    reverse=True,
                )
                results = candidates_sorted[:5]
            else:
                results = query_hazard_zones(
                    model, index, query, top_k=5, auto_filters=True
                )
            print_results(query, results)
    else:
        print("❌ Invalid choice")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
