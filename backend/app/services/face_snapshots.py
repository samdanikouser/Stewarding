from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AttendanceRecord
from .settings import get_setting


def purge_face_snapshots(db: Session, now: datetime) -> int:
    """Deletes snapshots older than the retention period and clears them from the record; 0 days keeps them."""
    days = get_setting(db, "attendance.snapshot_days")
    if not days:
        return 0
    cutoff = now - timedelta(days=days)
    removed = 0
    stale = select(AttendanceRecord).where(
        (AttendanceRecord.check_in_snapshot.is_not(None) & (AttendanceRecord.check_in_at < cutoff))
        | (AttendanceRecord.check_out_snapshot.is_not(None) & (AttendanceRecord.check_out_at < cutoff)))
    for record in db.scalars(stale):
        for column, taken in (("check_in_snapshot", record.check_in_at), ("check_out_snapshot", record.check_out_at)):
            name = getattr(record, column)
            if name and taken and taken < cutoff:
                (Path(settings.upload_dir) / "faces" / name).unlink(missing_ok=True)
                setattr(record, column, None)
                removed += 1
    return removed
