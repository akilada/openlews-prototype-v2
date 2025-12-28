#!/usr/bin/env python3
"""
Pinecone Index Setup Script for NSDI RAG Pipeline

Run this BEFORE running the main NSDI ingestion pipeline.
"""

import os
import sys
import time
from typing import Any, Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    print("⚠️  python-dotenv not installed. Using environment variables only.")

# --- Pinecone imports (preferred: gRPC client) ---
try:
    # Recommended by Pinecone docs for serverless indexes :contentReference[oaicite:3]{index=3}
    from pinecone.grpc import PineconeGRPC as Pinecone
    from pinecone import ServerlessSpec
except ImportError as e:
    print("❌ Error importing Pinecone SDK.")
    print("Make sure you installed the correct package.")
    print()
    print("If you're on Python 3.9:")
    print('  pip uninstall -y pinecone-client pinecone')
    print('  pip install "pinecone[grpc]<8"')
    print()
    print("If you're on Python 3.10+:")
    print('  pip uninstall -y pinecone-client')
    print('  pip install "pinecone[grpc]" --upgrade')
    print()
    print(f"Details: {e}")
    sys.exit(1)

# Configuration
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "lews-geological-knowledge")
DIMENSION = int(os.getenv("PINECONE_DIMENSION", "384"))  # all-MiniLM-L6-v2 => 384
METRIC = os.getenv("PINECONE_METRIC", "cosine")
CLOUD = os.getenv("PINECONE_CLOUD", "aws")
REGION = os.getenv("PINECONE_REGION", "us-east-1")


def get_api_key() -> str:
    """Get Pinecone API key from env or user input."""
    if PINECONE_API_KEY:
        return PINECONE_API_KEY

    print("\n🔑 Pinecone API Key Not Found")
    print("=" * 60)
    print("You need a Pinecone API key to continue.")
    print("Get one from the Pinecone console (Starter plan).")
    print("=" * 60)

    api_key = input("Paste your Pinecone API key here: ").strip()
    if not api_key:
        print("❌ No API key provided. Exiting.")
        sys.exit(1)

    save_to_env = input("\nSave API key to .env file? (y/n): ").strip().lower()
    if save_to_env == "y":
        with open(".env", "a", encoding="utf-8") as f:
            f.write(f"\nPINECONE_API_KEY={api_key}\n")
        print("✓ Saved to .env file")

    return api_key


def _extract_index_names(list_indexes_result: Any) -> list[str]:
    """
    Pinecone SDK versions return different shapes for list_indexes().
    This function tries to normalize to a list of index names.
    """
    if hasattr(list_indexes_result, "names") and callable(list_indexes_result.names):
        try:
            return list(list_indexes_result.names())
        except Exception:
            pass

    if isinstance(list_indexes_result, list):
        names: list[str] = []
        for item in list_indexes_result:
            if isinstance(item, dict) and "name" in item:
                names.append(item["name"])
            elif hasattr(item, "name"):
                names.append(getattr(item, "name"))
        return names

    if isinstance(list_indexes_result, dict):
        for key in ("indexes", "data"):
            if key in list_indexes_result and isinstance(list_indexes_result[key], list):
                return [x.get("name") for x in list_indexes_result[key] if isinstance(x, dict) and x.get("name")]

    try:
        txt = str(list_indexes_result)
        names = []
        for part in txt.split():
            if part.startswith("name="):
                names.append(part.split("=", 1)[1].strip(",)\"'"))
        return names
    except Exception:
        return []


def check_index_exists(pc: Pinecone, index_name: str) -> bool:
    """Check if index exists."""
    try:
        existing = pc.list_indexes()
        names = _extract_index_names(existing)
        return index_name in names
    except Exception as e:
        print(f"⚠️  Could not list indexes: {e}")
        return False


def wait_for_index_ready(pc: Pinecone, index_name: str, max_wait_seconds: int = 180) -> bool:
    """Wait until the index is ready."""
    start = time.time()
    while time.time() - start < max_wait_seconds:
        try:
            desc = pc.describe_index(index_name)
            status = None
            if isinstance(desc, dict):
                status = desc.get("status", {})
                if isinstance(status, dict) and status.get("ready") is True:
                    return True
            else:
                # object form
                if hasattr(desc, "status") and getattr(desc.status, "ready", None) is True:
                    return True
        except Exception:
            pass

        print(".", end="", flush=True)
        time.sleep(2)

    print("\n⚠️  Index creation is taking longer than expected.")
    print("Check the Pinecone console for status.")
    return False


def create_index(pc: Pinecone, index_name: str, dimension: int, metric: str) -> bool:
    """Create a new Pinecone serverless index."""
    print(f"\n📦 Creating index: {index_name}")
    print(f"   Dimensions: {dimension}")
    print(f"   Metric: {metric}")
    print(f"   Cloud: {CLOUD}")
    print(f"   Region: {REGION}")

    try:
        pc.create_index(
            name=index_name,
            dimension=dimension,
            metric=metric,
            spec=ServerlessSpec(cloud=CLOUD, region=REGION),
            deletion_protection="disabled",
        )

        print("✓ Index created. Waiting for readiness", end="", flush=True)
        ready = wait_for_index_ready(pc, index_name)
        if ready:
            print(" ✓")
        return True
    except Exception as e:
        print(f"❌ Failed to create index: {e}")
        return False


def describe_index(pc: Pinecone, index_name: str) -> None:
    """Print basic index info."""
    try:
        desc = pc.describe_index(index_name)
        print("\nIndex Info:")
        if isinstance(desc, dict):
            print(f"  - Name: {desc.get('name', index_name)}")
            status = desc.get("status", {})
            if isinstance(status, dict):
                print(f"  - Ready: {status.get('ready', 'Unknown')}")
                print(f"  - State: {status.get('state', 'Unknown')}")
            print(f"  - Dimension: {desc.get('dimension', 'Unknown')}")
            print(f"  - Metric: {desc.get('metric', 'Unknown')}")
        else:
            print(f"  - Name: {getattr(desc, 'name', index_name)}")
            st = getattr(desc, "status", None)
            if st is not None:
                print(f"  - Ready: {getattr(st, 'ready', 'Unknown')}")
                print(f"  - State: {getattr(st, 'state', 'Unknown')}")
            print(f"  - Dimension: {getattr(desc, 'dimension', 'Unknown')}")
            print(f"  - Metric: {getattr(desc, 'metric', 'Unknown')}")
    except Exception as e:
        print(f"⚠️  Could not describe index: {e}")


def main() -> None:
    print("=" * 60)
    print("🌲 Pinecone Index Setup for NDIS RAG Pipeline")
    print("=" * 60)

    api_key = get_api_key()

    print("\n🔌 Connecting to Pinecone...")
    try:
        pc = Pinecone(api_key=api_key)
        print("✓ Connected successfully!")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        sys.exit(1)

    print(f"\n🔍 Checking if index '{INDEX_NAME}' exists...")
    if check_index_exists(pc, INDEX_NAME):
        print(f"✓ Index '{INDEX_NAME}' already exists!")
        describe_index(pc, INDEX_NAME)
        print("\n✅ You're all set! No need to create a new index.")
        print("\nNext: python ndis_rag_pipeline.py")
        return

    print(f"❌ Index '{INDEX_NAME}' does not exist.")
    print("\n🚀 Let's create it!")

    print("\nIndex Configuration:")
    print(f"  Name: {INDEX_NAME}")
    print(f"  Dimensions: {DIMENSION} (e.g., all-MiniLM-L6-v2 => 384)")
    print(f"  Metric: {METRIC}")
    print(f"  Cloud Provider: {CLOUD}")
    print(f"  Region: {REGION}")

    confirm = input("\nProceed with creation? (y/n): ").strip().lower()
    if confirm != "y":
        print("❌ Cancelled by user.")
        sys.exit(0)

    success = create_index(pc, INDEX_NAME, DIMENSION, METRIC)
    if not success:
        print("\n❌ Setup failed. Please check errors above.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("✅ Setup Complete!")
    print("=" * 60)
    describe_index(pc, INDEX_NAME)

    print("\nNext steps:")
    print("1. Install embeddings dependency (if used by ingestion):")
    print("   pip install sentence-transformers")
    print("2. Run the NDIS ingestion pipeline:")
    print("   python ndis_rag_pipeline.py")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
