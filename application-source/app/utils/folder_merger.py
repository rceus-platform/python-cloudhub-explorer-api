"""Folder Merger Utility.

Responsibilities:
- Consolidate file lists from multiple providers into a unified structure
- Resolve duplicate entries by merging provider-specific identifiers

Boundaries:
- Does not handle file fetching or sorting
"""

from typing import Any


def merge_files(file_lists: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Merge files and preserve provider-specific IDs."""

    merged = {}

    for files in file_lists:
        for f in files:
            key = (f["name"], f["type"])

            if key not in merged:
                merged[key] = {
                    "name": f["name"],
                    "type": f["type"],
                    "providers": [],
                    "ids": {},  # Required for frontend
                }

            provider = f["provider"]

            # Track providers
            if provider not in merged[key]["providers"]:
                merged[key]["providers"].append(provider)  # type: ignore[union-attr]

            # Store provider-specific ID (support multiple accounts per provider)
            if provider not in merged[key]["ids"]:
                merged[key]["ids"][provider] = f["id"]
            else:
                existing_id = merged[key]["ids"][provider]
                if isinstance(existing_id, list):
                    if f["id"] not in existing_id:
                        existing_id.append(f["id"])
                elif existing_id != f["id"]:
                    merged[key]["ids"][provider] = [existing_id, f["id"]]

            # Normalize key order for consistent frontend stringification
            merged[key]["ids"] = dict(sorted(merged[key]["ids"].items()))

            # Add size for files
            if f["type"] == "file":
                merged[key]["size"] = f.get("size", 0)
                if f.get("thumbnail_url"):
                    merged[key]["thumbnail_url"] = f["thumbnail_url"]

    return list(merged.values())  # type: ignore[return-value]
