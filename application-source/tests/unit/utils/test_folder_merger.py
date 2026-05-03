"""Tests for the folder merger utility."""

from app.utils.folder_merger import merge_files


def test_merge_files_same_provider_multiple_accounts():
    """Test merging files with the same name from different accounts of the same provider."""

    list1 = [{"name": "file1", "type": "file", "provider": "gdrive", "id": "id1"}]
    list2 = [{"name": "file1", "type": "file", "provider": "gdrive", "id": "id2"}]

    merged = merge_files([list1, list2])
    assert len(merged) == 1
    assert merged[0]["ids"]["gdrive"] == ["id1", "id2"]


def test_merge_files_same_id_same_provider():
    """Test merging files that have the exact same ID and provider."""

    list1 = [{"name": "file1", "type": "file", "provider": "gdrive", "id": "id1"}]
    list2 = [{"name": "file1", "type": "file", "provider": "gdrive", "id": "id1"}]

    merged = merge_files([list1, list2])
    assert len(merged) == 1
    assert merged[0]["ids"]["gdrive"] == "id1"


def test_merge_files_existing_list_id():
    """Test merging files when multiple IDs already exist for a provider."""

    list1 = [{"name": "file1", "type": "file", "provider": "gdrive", "id": "id1"}]
    list2 = [{"name": "file1", "type": "file", "provider": "gdrive", "id": "id2"}]
    list3 = [{"name": "file1", "type": "file", "provider": "gdrive", "id": "id3"}]

    merged = merge_files([list1, list2, list3])
    assert len(merged) == 1
    assert merged[0]["ids"]["gdrive"] == ["id1", "id2", "id3"]
