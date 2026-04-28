"""Folder merger: utility to consolidate file lists from multiple cloud providers."""


def merge_files(file_lists: list[list[dict]]) -> list[dict]:
    """Merge file lists and aggregate sizes for duplicated names/types."""

    merged = {}

    for files in file_lists:
        for f in files:
            name = f.get("name", "unknown")
            file_type = f.get("type", "file")
            key = (name, file_type)

            if key not in merged:
                merged[key] = {
                    "name": name,
                    "type": file_type,
                    "providers": [],
                    "accounts": [],
                    "ids": [],
                    "size": 0,
                }

            provider = f.get("provider", "unknown")
            account_id = f.get("account_id")
            account_email = f.get("account_email")

            if provider not in merged[key]["providers"]:
                merged[key]["providers"].append(provider)

            merged[key]["ids"].append(
                {"account_id": account_id, "provider": provider, "id": f.get("id")}
            )

            merged[key]["accounts"].append(
                {"id": account_id, "email": account_email, "provider": provider}
            )

            # Aggregate size if available
            merged[key]["size"] += f.get("size", 0)

    return list(merged.values())
