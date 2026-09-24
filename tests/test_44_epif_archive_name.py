import os

import pytest

from src.log_writer import epif_archive_name, save_epif


def test_epif_archive_name_exact_outputs():
    assert epif_archive_name("Winford", 17.1, "PG000025831", []) == "Winford_EPIF_$17.10_PG000025831.pdf"
    assert epif_archive_name("Winford", 1234.5, "PG000025831", []) == "Winford_EPIF_$1234.50_PG000025831.pdf"
    assert epif_archive_name("Acme <Lab> Supply", 17.1, "PG000025831", []) == "Acme Lab Supply_EPIF_$17.10_PG000025831.pdf"

    existing = ["Winford_EPIF_$17.10_PG000025831.pdf"]
    assert epif_archive_name("Winford", 17.1, "PG000025831", existing) == "Winford_EPIF_$17.10_PG000025831_2.pdf"

    existing = ["Winford_EPIF_$17.10_PG000025831.pdf", "Winford_EPIF_$17.10_PG000025831_2.pdf"]
    assert epif_archive_name("Winford", 17.1, "PG000025831", existing) == "Winford_EPIF_$17.10_PG000025831_3.pdf"

def test_save_epif_refuses_overwrite(tmp_path):
    dest_dir = str(tmp_path)
    file_bytes_1 = b"original"
    file_bytes_2 = b"new_content"
    filename = "Test_EPIF.pdf"

    path = save_epif(file_bytes_1, filename, target_dir=dest_dir)
    assert os.path.exists(path)
    with open(path, "rb") as f:
        assert f.read() == b"original"

    with pytest.raises(FileExistsError):
        save_epif(file_bytes_2, filename, target_dir=dest_dir)

    with open(path, "rb") as f:
        assert f.read() == b"original"
