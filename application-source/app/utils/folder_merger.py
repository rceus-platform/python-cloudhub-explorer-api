"""
Folder Merger Utility

Responsibilities:
- Merge file lists from multiple cloud providers
- De-duplicate files based on name and type
- Preserve provider-specific IDs for merged folders
"""


def merge_files(file_lists: list[list[dict]]) -> list[dict]:
    """Merge files and preserve provider-specific IDs"""

    merged = {}

    for files in file_lists:
        for f in files:
            key = (f["name"], f["type"])

            if key not in merged:
                merged[key] = {
                    "name": f["name"],
                    "type": f["type"],
                    "providers": [],
                    "accounts": [],  # Store account context
                    "ids": [],       # Store all source IDs
                }

            provider = f["provider"]
            account_id = f.get("account_id")
            account_email = f.get("account_email")

            if provider not in merged[key]["providers"]:
                merged[key]["providers"].append(provider)

            merged[key]["ids"].append({
                "account_id": account_id,
                "provider": provider,
                "id": f["id"]
            })

            merged[key]["accounts"].append({
                "id": account_id,
                "email": account_email,
                "provider": provider
            })

            if f["type"] == "file":
                merged[key]["size"] = f.get("size", 0)

    return list(merged.values())
