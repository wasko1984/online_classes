"""Migrate the original WASKO SQLite data into the upgraded database.

Usage (from project root):
    python scripts/migrate_legacy_sqlite.py path/to/old/instance/wasko.db
Set DATABASE_URL to the target database (PostgreSQL recommended for production).
"""
import shutil
import sqlite3
import sys
from pathlib import Path

from app import app, db, Student, CourseMaterial, PASSPORT_DIR, MATERIALS_DIR

if len(sys.argv) != 2:
    raise SystemExit("Usage: python scripts/migrate_legacy_sqlite.py path/to/wasko.db")

source_db = Path(sys.argv[1]).resolve()
if not source_db.is_file():
    raise SystemExit(f"SQLite database not found: {source_db}")

project_root = Path(__file__).resolve().parents[1]
old_uploads = source_db.parent.parent / "uploads"

conn = sqlite3.connect(source_db)
conn.row_factory = sqlite3.Row

with app.app_context():
    for row in conn.execute("SELECT * FROM student ORDER BY id"):
        if db.session.scalar(db.select(Student).where(Student.reg_code == row["reg_code"])):
            continue
        student = Student(
            reg_code=row["reg_code"],
            full_name=row["full_name"],
            email=row["email"].strip().lower(),
            phone=row["phone"],
            passport_filename=Path(row["passport_filename"]).name,
            course=row["course"],
            status=row["status"],
        )
        # Let SQLAlchemy use the current time if the legacy timestamp is invalid.
        try:
            from datetime import datetime
            student.created_at = datetime.fromisoformat(row["created_at"])
        except Exception:
            pass
        db.session.add(student)

    for row in conn.execute("SELECT * FROM course_material ORDER BY id"):
        if db.session.scalar(db.select(CourseMaterial).where(CourseMaterial.filename == row["filename"])):
            continue
        db.session.add(CourseMaterial(
            course=row["course"],
            title=row["title"],
            filename=Path(row["filename"]).name,
            original_filename=Path(row["original_filename"]).name or Path(row["filename"]).name,
        ))

    db.session.commit()

# Copy old uploads if they exist.
if old_uploads.exists():
    for src in (old_uploads / "passports").glob("*"):
        if src.is_file():
            shutil.copy2(src, PASSPORT_DIR / src.name)
    for src in (old_uploads / "materials").glob("*"):
        if src.is_file():
            shutil.copy2(src, MATERIALS_DIR / src.name)

conn.close()
print("Legacy migration completed.")
