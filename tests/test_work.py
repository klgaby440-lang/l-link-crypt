"""Tests du socle Work et des protections de chemins."""

import pytest
from fastapi import HTTPException

from llink_api.api.routes.work import (
    file_path,
    normalize_file_name,
    normalize_folder,
    validate_content_size,
)


def test_work_file_path_normalizes_safe_folders():
    assert file_path("reports/2026", "summary.md") == "reports/2026/summary.md"
    assert file_path("", "notes.txt") == "notes.txt"
    assert normalize_folder(r"reports\2026") == "reports/2026"


@pytest.mark.parametrize("name", ["", ".", "..", "../secret.txt", "folder/file.txt", r"folder\file.txt"])
def test_work_rejects_unsafe_file_names(name):
    with pytest.raises(HTTPException) as exc:
        normalize_file_name(name)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("folder", ["../outside", "/absolute/path", "a/../b", "a//b", "a/./b"])
def test_work_rejects_unsafe_folder_paths(folder):
    with pytest.raises(HTTPException) as exc:
        normalize_folder(folder)
    assert exc.value.status_code == 422


def test_work_rejects_content_over_firestore_safe_limit():
    validate_content_size("petit fichier")
    with pytest.raises(HTTPException) as exc:
        validate_content_size("x" * 700_001)
    assert exc.value.status_code == 413


def test_work_cloud_routes_require_authenticated_account(client):
    assert client.get("/api/work/projects").status_code == 401
    assert client.get("/api/work/files").status_code == 401
    assert client.post(
        "/api/work/files",
        json={"name": "note.md", "content": "bonjour"},
    ).status_code == 401
