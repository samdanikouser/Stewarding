from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import require
from ..models import PushSubscription, User
from ..services import push

router = APIRouter(prefix="/api/push", tags=["push"])


class Keys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class SubscribeIn(BaseModel):
    endpoint: str = Field(max_length=600)
    keys: Keys


class UnsubscribeIn(BaseModel):
    endpoint: str = Field(max_length=600)


@router.get("/key")
def public_key(user: User = Depends(require("notification.view"))):
    """What the browser needs to subscribe; empty when push is not set up on the server."""
    return {"public_key": settings.vapid_public_key if push.enabled() else None}


@router.post("/subscribe", status_code=201)
def subscribe(body: SubscribeIn, user: User = Depends(require("notification.view")), db: Session = Depends(get_db)):
    if not push.enabled():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Push alerts are not set up on the server")
    if not push.allowed_endpoint(body.endpoint):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This browser's push service is not supported")
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if sub:  # the same device signed in as someone else takes the subscription over
        sub.user_id, sub.p256dh, sub.auth = user.id, body.keys.p256dh, body.keys.auth
    else:
        db.add(PushSubscription(user_id=user.id, endpoint=body.endpoint, p256dh=body.keys.p256dh, auth=body.keys.auth))
    db.commit()
    return {"ok": True}


@router.post("/unsubscribe")
def unsubscribe(body: UnsubscribeIn, user: User = Depends(require("notification.view")), db: Session = Depends(get_db)):
    db.execute(delete(PushSubscription).where(PushSubscription.endpoint == body.endpoint, PushSubscription.user_id == user.id))
    db.commit()
    return {"ok": True}


@router.post("/test")
def send_test(user: User = Depends(require("notification.view"))):
    """Sends a test alert to the signed-in person's own devices."""
    if not push.enabled():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Push alerts are not set up on the server")
    sent = push.deliver([{"user_id": user.id, "title": "Alerts are on", "body": "You will get alerts like this on this device.",
                          "link": "/tasks", "priority": "normal", "tag": "push-test"}])
    return {"sent": sent}
