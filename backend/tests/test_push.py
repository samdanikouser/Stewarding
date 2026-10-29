import pytest
from pywebpush import WebPushException
from sqlalchemy import select

from app.config import settings
from app.models import PushSubscription
from app.services import push

from .helpers import MGR, STEWARD
from .test_manual_attendance import manual

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123"
SUBSCRIPTION = {"endpoint": ENDPOINT, "keys": {"p256dh": "key", "auth": "secret"}}


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setattr(settings, "vapid_public_key", "public")
    monkeypatch.setattr(settings, "vapid_private_key", "private")


@pytest.fixture
def sent(monkeypatch):
    """Captures what would be pushed and runs the background send on the spot."""
    out = []
    monkeypatch.setattr(push, "_send", lambda info, payload: out.append((info["endpoint"], payload)))

    class Inline:
        def __init__(self, target, args, daemon):
            self.run = lambda: target(*args)

        def start(self):
            self.run()

    monkeypatch.setattr(push.threading, "Thread", Inline)
    return out


def test_push_is_off_until_the_server_has_keys(client, login):
    h = login(STEWARD)
    assert client.get("/api/push/key", headers=h).json() == {"public_key": None}
    assert client.post("/api/push/subscribe", json=SUBSCRIPTION, headers=h).status_code == 503


def test_only_known_push_services_can_be_subscribed(client, login, keys):
    h = login(STEWARD)
    assert client.get("/api/push/key", headers=h).json() == {"public_key": "public"}
    for bad in ("http://fcm.googleapis.com/x", "https://localhost/x", "https://evilgoogleapis.com/x", "https://10.0.0.5/x"):
        assert client.post("/api/push/subscribe", json={**SUBSCRIPTION, "endpoint": bad}, headers=h).status_code == 400
    assert client.post("/api/push/subscribe", json=SUBSCRIPTION, headers=h).status_code == 201


def test_a_new_notification_is_pushed_to_the_recipients_devices_after_commit(client, login, db, keys, sent):
    steward = login(STEWARD)
    client.post("/api/push/subscribe", json=SUBSCRIPTION, headers=steward)
    assert manual(client, login(MGR), db).status_code == 201
    assert len(sent) == 1 and sent[0][0] == ENDPOINT
    assert sent[0][1]["title"].startswith("Attendance added for") and sent[0][1]["link"] == "/attendance"


def test_nothing_is_pushed_when_the_transaction_rolls_back(db, keys, sent):
    from app.services.notify import notify

    notify(db, [1], "t", "Title", key="k1")
    db.rollback()
    db.commit()
    assert sent == []


def test_a_device_the_push_service_has_forgotten_is_removed(client, login, db, keys, monkeypatch):
    steward = login(STEWARD)
    client.post("/api/push/subscribe", json=SUBSCRIPTION, headers=steward)

    class Gone:
        status_code = 410

    def boom(info, payload):
        raise WebPushException("gone", response=Gone())

    monkeypatch.setattr(push, "_send", boom)
    assert client.post("/api/push/test", headers=steward).json() == {"sent": 0}
    db.expire_all()
    assert db.scalars(select(PushSubscription)).all() == []
