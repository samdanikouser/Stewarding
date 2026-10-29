import socket
import threading

import pytest
from sqlalchemy import select

from app.models import AuditLog

from .helpers import MGR, STEWARD, SUP, SUP_RB
from .test_traceability import food, receive

PRINTERS = "/api/label-printers"


class FakePrinter:
    """A printer's raw port: collects whatever a client sends."""

    def __init__(self):
        self.server = socket.create_server(("127.0.0.1", 0))
        self.port = self.server.getsockname()[1]
        self.received: list[bytes] = []
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while True:
            try:
                connection, _ = self.server.accept()
            except OSError:
                return
            with connection:
                data = b""
                while chunk := connection.recv(65536):
                    data += chunk
                self.received.append(data)

    def close(self):
        self.server.close()

    @property
    def text(self) -> str:
        for _ in range(50):
            if self.received:
                break
            threading.Event().wait(0.05)
        return b"".join(self.received).decode()


@pytest.fixture
def printer(monkeypatch):
    fake = FakePrinter()
    allow = lambda host, port: ["127.0.0.1"]  # noqa: E731 - the stand-in printer listens on this computer
    monkeypatch.setattr("app.api.label_printers.private_addresses", allow)
    monkeypatch.setattr("app.services.printers.private_addresses", allow)
    yield fake
    fake.close()


def add(client, h, host="192.168.1.50", name="Butchery Zebra", **over):
    return client.post(PRINTERS, headers=h, json={"name": name, "host": host, "port": 9100, "dpi": 203, **over})


def test_a_printer_must_be_on_the_private_network(client, login, db, clock):
    m = login(MGR)
    for host in ("127.0.0.1", "169.254.169.254", "8.8.8.8", "0.0.0.0"):
        refused = add(client, m, host=host)
        assert refused.status_code == 400, host
    assert add(client, m, host="not a host!!").status_code == 422
    assert add(client, m, host="printer.invalid").status_code == 400
    for n, host in enumerate(("192.168.1.50", "10.0.0.9", "172.16.4.2")):
        assert add(client, m, host=host, name=f"Printer {n}").status_code == 201
    assert add(client, m, host="192.168.1.51", name="printer 0").status_code == 409                # names are unique


def test_only_managers_set_printers_up_and_others_never_see_the_address(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    assert add(client, sup).status_code == 403
    made = add(client, m).json()
    assert made["host"] == "192.168.1.50" and made["port"] == 9100
    seen = client.get(PRINTERS, headers=sup).json()
    assert [p["name"] for p in seen] == ["Butchery Zebra"] and "host" not in seen[0]
    assert client.get(PRINTERS, headers=login(STEWARD)).status_code == 403
    client.put(f"{PRINTERS}/{made['id']}", headers=m, json={"name": "Butchery Zebra", "host": "192.168.1.50", "port": 9100, "dpi": 300, "active": False})
    assert client.get(PRINTERS, headers=sup).json() == []                                           # a switched-off printer is hidden from them
    assert client.get(PRINTERS, headers=m).json()[0]["dpi"] == 300
    assert client.put(f"{PRINTERS}/{made['id']}", headers=sup, json={"name": "x1", "host": "192.168.1.9"}).status_code == 403
    assert client.delete(f"{PRINTERS}/{made['id']}", headers=sup).status_code == 403
    assert client.delete(f"{PRINTERS}/{made['id']}", headers=m).status_code == 200


def test_labels_go_straight_to_the_printer_as_zpl(client, login, db, clock, printer):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    lot = receive(client, sup, db, item).json()
    zebra = add(client, m, host="192.168.1.50", name="Receiving Zebra", dpi=300).json()
    client.put(f"{PRINTERS}/{zebra['id']}", headers=m, json={"name": "Receiving Zebra", "host": "192.168.1.50", "port": printer.port, "dpi": 300})
    sent = client.post(f"{PRINTERS}/print", headers=sup, json={"printer_id": zebra["id"], "lot_ids": [lot["id"]], "copies": 2})
    assert sent.status_code == 200 and sent.json() == {"printed": 2, "printer": "Receiving Zebra"}
    text = printer.text
    assert text.count("^XA") == 2 and text.count("^XZ") == 2 and "^PW886" in text and lot["code"] in text and "Chicken breast" in text and "Received" in text
    assert db.scalar(select(AuditLog).where(AuditLog.action == "label.print")) is not None
    assert client.post(f"{PRINTERS}/{zebra['id']}/test", headers=m).json() == {"printed": 1}
    assert "TEST-0001" in printer.text
    assert client.post(f"{PRINTERS}/{zebra['id']}/test", headers=sup).status_code == 403


def test_printing_respects_who_may_see_the_lot_how_many_and_whether_the_printer_answers(client, login, db, clock, printer):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    lot = receive(client, sup, db, item).json()
    zebra = add(client, m, name="Zebra A").json()
    client.put(f"{PRINTERS}/{zebra['id']}", headers=m, json={"name": "Zebra A", "host": "192.168.1.50", "port": printer.port})
    send = lambda who, **over: client.post(f"{PRINTERS}/print", headers=who, json={"printer_id": zebra["id"], "lot_ids": [lot["id"]], **over})  # noqa: E731
    assert send(login(SUP_RB)).status_code == 403                       # a lot at another site
    assert send(login(STEWARD)).status_code == 403
    assert send(sup, copies=50, lot_ids=[lot["id"]] * 5).status_code == 400   # 250 labels at once
    assert client.post(f"{PRINTERS}/print", headers=sup, json={"printer_id": 999, "lot_ids": [lot["id"]]}).status_code == 404
    client.put(f"{PRINTERS}/{zebra['id']}", headers=m, json={"name": "Zebra A", "host": "192.168.1.50", "port": 1})   # nothing listens on port 1
    down = send(sup)
    assert down.status_code == 502 and "Could not reach the label printer" in down.json()["detail"] and "192.168" not in down.json()["detail"]
    client.put(f"{PRINTERS}/{zebra['id']}", headers=m, json={"name": "Zebra A", "host": "192.168.1.50", "port": printer.port, "active": False})
    assert send(sup).status_code == 404                                  # switched off
