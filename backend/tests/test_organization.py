import io

from openpyxl import load_workbook
from PIL import Image
from sqlalchemy import select

from app.models import AuditLog

from .helpers import MGR, STEWARD, SUP, loc_id

URL = "/api/organization"
BODY = {"name": "Example Kitchens", "legal_name": "Example Catering LLC", "address": "12 Corniche Road, Kuwait City",
        "phone": "+965 1234 5678", "email": "ops@example.com", "website": "https://example.com",
        "registration_number": "CR-998877", "report_footer": "Confidential - for internal audit use"}


def png(color=(20, 90, 140)):
    buf = io.BytesIO()
    Image.new("RGB", (120, 60), color).save(buf, "PNG")
    return buf.getvalue()


def test_organization_starts_blank_and_the_manager_can_set_it(client, login, db):
    assert client.get(f"{URL}/public").json() == {"name": "", "has_logo": False}
    assert client.get(URL, headers=login(SUP)).json()["name"] == ""
    saved = client.put(URL, json=BODY, headers=login(MGR))
    assert saved.status_code == 200 and saved.json()["name"] == "Example Kitchens" and saved.json()["logo"] is None
    assert client.get(f"{URL}/public").json()["name"] == "Example Kitchens"
    assert client.get(URL, headers=login(STEWARD)).json()["registration_number"] == "CR-998877"
    assert db.scalar(select(AuditLog.id).where(AuditLog.action == "organization.update"))


def test_only_a_manager_can_change_the_organization(client, login):
    for who in (SUP, STEWARD):
        assert client.put(URL, json=BODY, headers=login(who)).status_code == 403
        assert client.post(f"{URL}/logo", files={"file": ("l.png", png(), "image/png")}, headers=login(who)).status_code == 403
        assert client.delete(f"{URL}/logo", headers=login(who)).status_code == 403


def test_organization_fields_are_validated_and_trimmed(client, login):
    h = login(MGR)
    assert client.put(URL, json={**BODY, "name": "  "}, headers=h).status_code == 422
    assert client.put(URL, json={**BODY, "email": "not-an-email"}, headers=h).status_code == 422
    assert client.put(URL, json={**BODY, "phone": "call me"}, headers=h).status_code == 422
    assert client.put(URL, json={**BODY, "website": "example.com"}, headers=h).status_code == 422
    assert client.put(URL, json={**BODY, "address": "x" * 501}, headers=h).status_code == 422
    ok = client.put(URL, json={"name": "  Example  ", "email": "", "website": "", "legal_name": "  "}, headers=h).json()
    assert ok["name"] == "Example" and ok["email"] == "" and ok["legal_name"] == ""


def test_logo_upload_serves_publicly_and_can_be_removed(client, login):
    h = login(MGR)
    done = client.post(f"{URL}/logo", files={"file": ("logo.png", png(), "image/png")}, headers=h)
    assert done.status_code == 201 and done.json()["logo"].endswith(".png")
    shown = client.get(f"{URL}/logo")
    assert shown.status_code == 200 and shown.content.startswith(b"\x89PNG")
    assert client.get(f"{URL}/public").json()["has_logo"] is True
    assert client.post(f"{URL}/logo", files={"file": ("a.gif", b"GIF89a" + b"0" * 20, "image/gif")}, headers=h).status_code == 415
    assert client.post(f"{URL}/logo", files={"file": ("big.png", png() + b"0" * (2 * 1024 * 1024), "image/png")}, headers=h).status_code == 413
    assert client.delete(f"{URL}/logo", headers=h).json()["logo"] is None
    assert client.get(f"{URL}/logo").status_code == 404


def test_reports_carry_the_organization_in_every_format(client, login, db, clock):
    h = login(MGR)
    client.put(URL, json=BODY, headers=h)
    client.post(f"{URL}/logo", files={"file": ("logo.png", png(), "image/png")}, headers=h)
    q = "date_from=2026-03-02&date_to=2026-03-02"
    doc = client.get(f"/api/reports/records/attendance?{q}", headers=h).json()
    assert doc["organization"]["name"] == "Example Kitchens" and doc["organization"]["logo_path"]
    for kind in ("attendance", "monitoring", "checklist_chart"):
        pdf = client.get(f"/api/reports/records/{kind}/export?fmt=pdf&{q}", headers=h)
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    csv = client.get(f"/api/reports/records/attendance/export?fmt=csv&{q}", headers=h).content.decode("utf-8-sig")
    assert csv.splitlines()[0] == "Example Kitchens" and "CR-998877" in csv
    sheet = load_workbook(io.BytesIO(client.get(f"/api/reports/records/attendance/export?fmt=xlsx&{q}", headers=h).content)).worksheets[0]
    assert sheet["A1"].value == "Example Kitchens"
    period = client.get(f"/api/reports/daily/export?fmt=pdf&location_id={loc_id(db, 'MK')}", headers=h)
    assert period.content.startswith(b"%PDF")
    summary = client.get("/api/reports/daily", headers=h).json()
    assert summary["organization"]["report_footer"] == "Confidential - for internal audit use"


def test_reports_without_an_organization_still_work(client, login, db, clock):
    h = login(MGR)
    pdf = client.get("/api/reports/records/attendance/export?fmt=pdf&date_from=2026-03-02&date_to=2026-03-02", headers=h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_time_zone_defaults_to_kuwait_and_is_validated(client, login):
    h = login(MGR)
    assert client.get(URL, headers=h).json()["timezone"] == "Asia/Kuwait"
    zones = client.get(f"{URL}/timezones", headers=h).json()
    assert "Asia/Kuwait" in zones and "Asia/Dubai" in zones and len(zones) > 100
    assert client.put(URL, json={**BODY, "timezone": "Mars/Olympus"}, headers=h).status_code == 422
    assert client.put(URL, json={**BODY, "timezone": "Asia/Dubai"}, headers=h).json()["timezone"] == "Asia/Dubai"
    assert client.get(f"{URL}/timezones").status_code == 401


def test_reports_state_generated_time_in_the_organization_zone(client, login, db, clock):
    h = login(MGR)
    client.put(URL, json=BODY, headers=h)  # Asia/Kuwait, UTC+3; the test clock is 02:05 UTC
    doc = client.get("/api/reports/records/attendance?date_from=2026-03-02&date_to=2026-03-02", headers=h).json()
    assert doc["generated_at"] == "02 Mar 2026 05:05 (Asia/Kuwait)"
    csv = client.get("/api/reports/records/attendance/export?fmt=csv&date_from=2026-03-02&date_to=2026-03-02", headers=h).content.decode("utf-8-sig")
    assert "02 Mar 2026 05:05 (Asia/Kuwait)" in csv
    summary = client.get("/api/reports/daily/export?fmt=csv", headers=h).content.decode("utf-8-sig")
    assert "Generated,02 Mar 2026 05:05 (Asia/Kuwait)" in summary
    client.put(URL, json={**BODY, "timezone": "Asia/Dubai"}, headers=h)
    again = client.get("/api/reports/records/attendance?date_from=2026-03-02&date_to=2026-03-02", headers=h).json()
    assert again["generated_at"] == "02 Mar 2026 06:05 (Asia/Dubai)"


def test_the_currency_is_saved_in_capitals_and_shown_on_report_headers(client, login):
    m = login(MGR)
    assert client.get(URL, headers=m).json()["currency"] == ""
    assert client.put(URL, json={**BODY, "currency": " kwd "}, headers=m).json()["currency"] == "KWD"
    assert client.put(URL, json={**BODY, "currency": "K W D 1"}, headers=m).status_code == 422
    assert client.put(URL, json={**BODY, "currency": ""}, headers=m).json()["currency"] == ""
    from app.services.exporters import _org_lines
    assert "Amounts in KWD" in _org_lines({"name": "Example", "currency": "KWD"})
    assert not any(line.startswith("Amounts in") for line in _org_lines({"name": "Example", "currency": ""}))
