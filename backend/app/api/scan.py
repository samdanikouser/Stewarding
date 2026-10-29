from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from reportlab.graphics import renderSVG
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import timeutil
from ..db import get_db
from ..deps import check_location, current_user, require
from ..models import Equipment, Location, ScanEvent, User
from ..services.scan import make_token, read_token

router = APIRouter(prefix="/api/scan", tags=["QR codes"])

SIZE = 200


class ScanIn(BaseModel):
    token: str


def _svg(url: str) -> str:
    widget = QrCodeWidget(url, barLevel="M")
    x1, y1, x2, y2 = widget.getBounds()
    drawing = Drawing(SIZE, SIZE, transform=[SIZE / (x2 - x1), 0, 0, SIZE / (y2 - y1), 0, 0])
    drawing.add(widget)
    return renderSVG.drawToString(drawing)


@router.post("")
def scan(body: ScanIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Records that the signed-in person scanned a code, and says which place it belongs to."""
    named = read_token(body.token)
    if named is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This is not a QR code from this system")
    kind, target_id = named
    target = db.get(Equipment if kind == "equipment" else Location, target_id)
    if target is None or not target.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This QR code is no longer in use")
    location_id = target.location_id if kind == "equipment" else target.id
    check_location(user, db, location_id)
    db.add(ScanEvent(user_id=user.id, kind=kind, target_id=target_id, created_at=timeutil.utc_now()))
    db.commit()
    return {"kind": kind, "id": target_id, "name": target.name, "location_id": location_id,
            "location_name": db.get(Location, location_id).name}


@router.get("/codes")
def codes(base: str = Query(pattern=r"^https?://[^\s/]+$"), user: User = Depends(require("settings.manage")),
          db: Session = Depends(get_db)):
    """Every active location and monitoring point with the QR code to print for it."""
    locations = db.scalars(select(Location).where(Location.active).order_by(Location.name)).all()
    points = db.scalars(select(Equipment).where(Equipment.active).order_by(Equipment.name)).all()
    names = {location.id: location.name for location in locations}

    def entry(kind: str, target, location_id: int) -> dict:
        url = f"{base}/scan/{make_token(kind, target.id)}"
        return {"kind": kind, "id": target.id, "name": target.name, "location_id": location_id,
                "location_name": names.get(location_id, ""), "url": url, "svg": _svg(url)}

    return {"locations": [entry("location", loc, loc.id) for loc in locations],
            "points": [entry("equipment", eq, eq.location_id) for eq in points]}
