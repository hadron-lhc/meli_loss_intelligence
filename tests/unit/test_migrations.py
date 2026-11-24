import pytest

from loss_intelligence.db.migrate import MigrationError, discover_migrations


def test_discover_migrations_requires_version_prefix(tmp_path) -> None:
    (tmp_path / "bad.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(MigrationError, match="invalid migration filename"):
        discover_migrations(tmp_path)


def test_discover_migrations_rejects_duplicate_versions(tmp_path) -> None:
    (tmp_path / "001_first.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "001_second.sql").write_text("SELECT 2;", encoding="utf-8")
    with pytest.raises(MigrationError, match="duplicate migration version"):
        discover_migrations(tmp_path)


def test_discover_migrations_rejects_empty_directory(tmp_path) -> None:
    with pytest.raises(MigrationError, match="no migrations found"):
        discover_migrations(tmp_path)


def test_migration_checksum_changes_with_content(tmp_path) -> None:
    path = tmp_path / "001_test.sql"
    path.write_text("SELECT 1;", encoding="utf-8")
    first = discover_migrations(tmp_path)[0].checksum

    path.write_text("SELECT 2;", encoding="utf-8")
    second = discover_migrations(tmp_path)[0].checksum

    assert first != second
