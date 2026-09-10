"""Central runtime configuration and reproducibility record.

Every LLM call in the system resolves its model name and seed through this
module so that a single pinned snapshot is used across the whole pipeline.
Temperature zero alone does not make a hosted model reproducible, so runs are
additionally identified by the model snapshot, the request seed, the returned
system fingerprint, the corpus hash, and the code commit.
"""

import os
import glob
import json
import hashlib
import platform
import subprocess
from datetime import datetime, timezone
from importlib import metadata
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

# Pinned snapshot. The bare "gpt-4o" alias moves over time, which makes any
# result recorded against it impossible to reproduce later.
DEFAULT_MODEL_SNAPSHOT = "gpt-4o-2024-08-06"
DEFAULT_EMBEDDING_SNAPSHOT = "text-embedding-3-small"

# Packages whose versions materially affect generation or retrieval output.
TRACKED_PACKAGES = ["litellm", "openai", "chromadb", "pydantic", "tiktoken"]


def model_name() -> str:
    """Return the bare model identifier, e.g. gpt-4o-2024-08-06."""
    return os.getenv("DEFAULT_MODEL", DEFAULT_MODEL_SNAPSHOT)


def litellm_model() -> str:
    """Return the model identifier in the provider-prefixed form LiteLLM expects."""
    return f"openai/{model_name()}"


def embedding_model() -> str:
    """Return the embedding model identifier."""
    return os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_SNAPSHOT)


def seed() -> int:
    """Return the request seed used for every completion call."""
    return int(os.getenv("SEED", "42"))


def temperature() -> float:
    """Return the sampling temperature used across the pipeline."""
    return float(os.getenv("TEMPERATURE", "0.0"))


def model_configuration() -> Dict[str, Any]:
    """Return the generation settings that identify how an answer was produced.

    Recorded in evidence traces so a reviewer can tell whether two analyses
    were produced under the same configuration.
    """
    return {
        "model": model_name(),
        "embedding_model": embedding_model(),
        "temperature": temperature(),
        "seed": seed(),
    }


def system_fingerprint(response: Any) -> Optional[str]:
    """Extract the backend fingerprint from a completion response, if present.

    The provider returns this to identify the backend configuration that served
    the request. It changes when the backend changes, which is the signal that
    otherwise identical requests may stop producing identical output.
    """
    return getattr(response, "system_fingerprint", None)


def hash_corpus(knowledge_path: str) -> str:
    """SHA-256 over every knowledge base file, in sorted filename order."""
    h = hashlib.sha256()
    files = sorted(
        glob.glob(os.path.join(knowledge_path, "*.md"))
        + glob.glob(os.path.join(knowledge_path, "*.txt"))
    )
    for filepath in files:
        try:
            with open(filepath, "rb") as f:
                h.update(f.read())
        except Exception:
            pass
    return h.hexdigest()


def corpus_manifest(knowledge_path: str) -> List[Dict[str, Any]]:
    """Per-file name, byte size and SHA-256 for the knowledge base."""
    entries = []
    files = sorted(
        glob.glob(os.path.join(knowledge_path, "*.md"))
        + glob.glob(os.path.join(knowledge_path, "*.txt"))
    )
    for filepath in files:
        try:
            with open(filepath, "rb") as f:
                data = f.read()
            entries.append({
                "file": os.path.basename(filepath),
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            })
        except Exception:
            continue
    return entries


def _git_commit() -> Optional[str]:
    """Current commit hash, or None if git is unavailable or this is not a repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _package_versions() -> Dict[str, str]:
    """Installed versions of the packages that affect output."""
    versions = {}
    for name in TRACKED_PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except Exception:
            versions[name] = "not installed"
    return versions


def run_manifest(knowledge_path: Optional[str] = None) -> Dict[str, Any]:
    """Assemble the full reproducibility record for a run.

    Written alongside experimental results so that a later reader can identify
    the exact model snapshot, seed, corpus and code that produced them.
    """
    knowledge_path = knowledge_path or os.getenv("KNOWLEDGE_BASE_PATH", "./knowledge_data")
    return {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": model_name(),
        "embedding_model": embedding_model(),
        "seed": seed(),
        "temperature": temperature(),
        "max_tokens": int(os.getenv("MAX_TOKENS", "6000")),
        "rag_top_k": int(os.getenv("RAG_TOP_K", "5")),
        "corpus_sha256": hash_corpus(knowledge_path),
        "corpus_files": corpus_manifest(knowledge_path),
        "git_commit": _git_commit(),
        "packages": _package_versions(),
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def write_run_manifest(output_path: str, knowledge_path: Optional[str] = None) -> Dict[str, Any]:
    """Write the run manifest to disk as JSON and return it."""
    manifest = run_manifest(knowledge_path)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest
