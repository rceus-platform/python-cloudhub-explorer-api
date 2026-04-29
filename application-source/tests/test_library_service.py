"""Library Service Tests.

Responsibilities:
- Validate file merging logic across providers
- Ensure metadata injection correctly handles empty/null states
- Verify watch history prioritization
"""

from app.utils.folder_merger import merge_files


def test_merge_files_duplicates():
    """Ensure files with the same name and type are merged with multiple IDs."""

    file_lists = [
        [{"name": "video.mp4", "type": "file", "provider": "gdrive", "id": "g1"}],
        [{"name": "video.mp4", "type": "file", "provider": "mega", "id": "m1"}],
    ]

    result = merge_files(file_lists)
    assert len(result) == 1
    assert result[0]["name"] == "video.mp4"
    assert "gdrive" in result[0]["ids"]
    assert "mega" in result[0]["ids"]
    assert result[0]["ids"]["gdrive"] == "g1"
    assert result[0]["ids"]["mega"] == "m1"


def test_merge_files_unique():
    """Ensure unique files are preserved independently."""

    file_lists = [
        [{"name": "a.mp4", "type": "file", "provider": "gdrive", "id": "g1"}],
        [{"name": "b.mp4", "type": "file", "provider": "gdrive", "id": "g2"}],
    ]

    result = merge_files(file_lists)
    assert len(result) == 2
    names = [f["name"] for f in result]
    assert "a.mp4" in names
    assert "b.mp4" in names


def test_merge_files_different_types():
    """Ensure folder and file with same name are not merged."""

    file_lists = [
        [{"name": "shared", "type": "folder", "provider": "gdrive", "id": "g1"}],
        [{"name": "shared", "type": "file", "provider": "gdrive", "id": "g2"}],
    ]

    result = merge_files(file_lists)
    assert len(result) == 2
