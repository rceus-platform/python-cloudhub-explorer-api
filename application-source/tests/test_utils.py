"""Tests for utility functions, including folder merging."""

from app.utils.folder_merger import merge_files


def test_merge_files_basic():
    """Test basic merging of files from different providers."""

    file_lists = [
        [
            {"id": "g1", "name": "file1", "type": "file", "provider": "gdrive", "size": 100},
            {"id": "g2", "name": "folder1", "type": "folder", "provider": "gdrive"}
        ],
        [
            {"id": "m1", "name": "file1", "type": "file", "provider": "mega", "size": 100},
            {"id": "m2", "name": "folder2", "type": "folder", "provider": "mega"}
        ]
    ]

    merged = merge_files(file_lists)

    # file1 should be merged
    file1 = next(f for f in merged if f["name"] == "file1")
    assert "gdrive" in file1["providers"]
    assert "mega" in file1["providers"]
    assert len(file1["ids"]) == 2
    # Verify aggregated size
    assert file1["size"] == 200

    # folders should be separate (different names)
    assert any(f["name"] == "folder1" for f in merged)
    assert any(f["name"] == "folder2" for f in merged)


def test_merge_files_same_folder_name():
    """Test merging of folders with the same name from different providers."""

    file_lists = [
        [{"id": "g1", "name": "Shared", "type": "folder", "provider": "gdrive"}],
        [{"id": "m1", "name": "Shared", "type": "folder", "provider": "mega"}]
    ]

    merged = merge_files(file_lists)
    assert len(merged) == 1
    assert merged[0]["name"] == "Shared"
    assert "gdrive" in merged[0]["providers"]
    assert "mega" in merged[0]["providers"]
    assert len(merged[0]["ids"]) == 2


def test_merge_files_empty():
    """Test merging behavior with empty lists."""

    assert not merge_files([])
    assert not merge_files([[]])
