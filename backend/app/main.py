from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import scheduler
from .api import (closures, rounds, absences, attendance, audit, auth, breakage, checklists, dashboard, employees, equipment, inventory,
                  label_printers, lookups, lots, notifications, organization, push, receipts, reports, roles, roster, settings as settings_api, stock, suppliers,
                  monitoring, profile, scan, training, training_admin, uploads)
from .config import settings
from .db import SessionLocal
from .seed import sync_roles
from .services import slidevideo


@asynccontextmanager
async def lifespan(_: FastAPI):
    if len(settings.secret_key) < 32:
        raise RuntimeError("STW_SECRET_KEY must be set to a random value of at least 32 characters")
    with SessionLocal() as db:
        sync_roles(db)
        slidevideo.fail_interrupted(db)
        db.commit()
    if settings.scheduler_enabled:
        scheduler.start_background()
    yield


app = FastAPI(title="Plato", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)
for module in (auth, employees, attendance, roster, checklists, uploads, equipment, monitoring, inventory, stock,
               breakage, notifications, push, dashboard, reports, settings_api, audit, suppliers, receipts, lookups, absences, organization, roles, label_printers, lots, profile, scan, training, training_admin, rounds, closures):
    app.include_router(module.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
