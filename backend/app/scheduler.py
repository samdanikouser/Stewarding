import logging
import threading
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import timeutil
from .db import SessionLocal
from .models import Location
from .services import checklists, snapshots
from .services.alerts import run_alerts
from .services.face_snapshots import purge_face_snapshots

log = logging.getLogger("stewarding.scheduler")
INTERVAL_SECONDS = 60


def run_cycle(db: Session, now=None) -> dict:
    """One scheduler pass: generate today's tasks, flag overdue ones; idempotent."""
    now = now or timeutil.utc_now()
    created = 0
    for location in db.scalars(select(Location).where(Location.active.is_(True))):
        created += checklists.generate_for_location(db, location, now)
    overdue = checklists.mark_overdue(db, now)
    alerts = run_alerts(db, now)
    db.commit()  # alerts go out now, not after the slower housekeeping below
    stock = snapshots.refresh(db, now)
    faces = purge_face_snapshots(db, now)
    db.commit()
    return {"created": created, "overdue": overdue, "alerts": alerts, "snapshots": stock, "face_snapshots_removed": faces}


def _loop() -> None:
    while True:
        try:
            started = time.monotonic()
            with SessionLocal() as db:
                result = run_cycle(db)
            log.info("scheduler cycle took %.1fs: %s", time.monotonic() - started, result)
        except Exception:
            log.exception("scheduler cycle failed")
        time.sleep(INTERVAL_SECONDS)


def start_background() -> None:
    threading.Thread(target=_loop, name="stewarding-scheduler", daemon=True).start()
