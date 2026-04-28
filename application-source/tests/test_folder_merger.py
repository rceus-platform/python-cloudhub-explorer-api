"""Tests for the folder_merger utility."""

from app.utils.folder_merger import merge_files


def test_merge_files_empty():
    """Test merging an empty list of file lists."""

    assert not merge_files([])


def test_merge_files_single():
    """Test merging a single file list."""

    files = [
        {"id": "1", "name": "f1", "type": "file", "size": 100, "provider": "gdrive"},
        {"id": "2", "name": "f2", "type": "folder", "provider": "gdrive"}
    ]
    merged = merge_files([files])
    # Implementation adds 'providers', 'accounts', 'ids' keys
    assert len(merged) == 2
    assert merged[0]["name"] == "f1"
    assert "gdrive" in merged[0]["providers"]


def test_merge_files_aggregation():
    """Test merging and aggregating folder/file sizes."""

    list1 = [
        {"id": "1", "name": "doc", "type": "folder", "size": 100, "provider": "gdrive"},
        {"id": "2", "name": "image.jpg", "type": "file", "size": 500, "provider": "gdrive"}
    ]
    list2 = [
        {"id": "3", "name": "doc", "type": "folder", "size": 200, "provider": "mega"},
        {"id": "4", "name": "video.mp4", "type": "file", "size": 1000, "provider": "mega"}
    ]

    merged = merge_files([list1, list2])

    # "doc" should be merged and sizes aggregated (100 + 200 = 300)
    docs = [f for f in merged if f["name"] == "doc"]
    assert len(docs) == 1
    assert docs[0]["size"] == 300
    assert "gdrive" in docs[0]["providers"]
    assert "mega" in docs[0]["providers"]

    # Others should be present
    names = {f["name"] for f in merged}
    assert "image.jpg" in names
    assert "video.mp4" in names
    assert len(merged) == 3


def test_merge_files_mixed_types():
    """Test that files/folders with same name but different types are NOT merged."""

    list1 = [{"id": "1", "name": "test", "type": "file", "size": 100, "provider": "gdrive"}]
    list2 = [{"id": "2", "name": "test", "type": "folder", "size": 200, "provider": "gdrive"}]

    merged = merge_files([list1, list2])
    assert len(merged) == 2
