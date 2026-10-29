"""Browser push: each new notification is also sent to every device its recipient turned alerts on for.

Sending waits for the commit that created the notification (so nobody is alerted about something that was rolled back)
and runs on a background thread, so a slow push service never delays a request. It does nothing until the keys are set.
"""
import json
import logging
import threading
from urllib.parse import urlparse

from pywebpush import WebPushException, webpush
from sqlalchemy import delete, event, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..models import PushSubscription

log = logging.getLogger(__name__)

# the push services of Chrome and Edge, Firefox and Safari; anything else is refused so the server never calls arbitrary addresses
PUSH_HOSTS = ("googleapis.com", "services.mozilla.com", "push.apple.com", "notify.windows.com")


def enabled() -> bool:
    return bool(settings.vapid_public_key and settings.vapid_private_key)


def allowed_endpoint(endpoint: str) -> bool:
    url = urlparse(endpoint)
    host = url.hostname or ""
    return url.scheme == "https" and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)


def _send(info: dict, payload: dict) -> None:
    # always high urgency: phones hold back "normal" pushes while idle (Android Doze, iOS), which is how a reminder arrives minutes late
    webpush(subscription_info=info, data=json.dumps(payload), vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject}, ttl=86400, headers={"Urgency": "high"}, timeout=10)


def deliver(items: list[dict]) -> int:
    """Sends each item to its user's devices and returns how many went out; a device the push service no longer knows is forgotten."""
    sent = 0
    with SessionLocal() as db:
        for item in items:
            subs = db.scalars(select(PushSubscription).where(PushSubscription.user_id == item["user_id"])).all()
            for sub in subs:
                try:
                    _send({"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                          {k: item[k] for k in ("title", "body", "link", "tag")})
                    sent += 1
                except WebPushException as exc:
                    if exc.response is not None and exc.response.status_code in (404, 410):
                        db.execute(delete(PushSubscription).where(PushSubscription.id == sub.id))
                        db.commit()
                    else:
                        log.warning("push to subscription %s failed: %s", sub.id, exc)
                except Exception:  # noqa: BLE001 - one bad device must not stop the rest
                    log.exception("push to subscription %s failed", sub.id)
    return sent


def queue(db: Session, user_id: int, title: str, body: str | None, link: str | None, priority: str, key: str) -> None:
    """Remembers a new notification to push once the transaction that holds it commits."""
    if enabled():
        db.info.setdefault("push", []).append({"user_id": user_id, "title": title, "body": body or "", "link": link or "/tasks",
                                               "priority": priority, "tag": key})


def _after_commit(db: Session) -> None:
    items = db.info.pop("push", None)
    if items:
        threading.Thread(target=deliver, args=(items,), daemon=True).start()


def _after_rollback(db: Session) -> None:
    db.info.pop("push", None)


event.listen(Session, "after_commit", _after_commit)
event.listen(Session, "after_rollback", _after_rollback)
