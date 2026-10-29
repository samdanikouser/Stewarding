import base64

from .helpers import MGR, STEWARD, loc_id, make_lot

ONE_PIXEL = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def make(client, h, db, template, loc="MK"):
    return client.post("/api/equipment/from-template", json={"template": template, "location_id": loc_id(db, loc)}, headers=h).json()


def checks(point, phase):
    return [c for c in point["schedules"] if c["phase"] == phase]


def start(client, h, point):
    lot = make_lot(point["location_id"])
    return client.post("/api/monitoring/readings/batch", headers=h, json={"equipment_id": point["id"], "readings": [
        {"schedule_id": c["id"], "value": 3, "lot_ids": [lot]} for c in checks(point, "start")]})


def finish(client, h, point, start_id, **over):
    readings = [{"schedule_id": c["id"], "value": 1 if c["value_type"] == "yes_no" else 3} for c in checks(point, "finish")]
    return client.post("/api/monitoring/readings/batch", headers=h, json={"equipment_id": point["id"], "start_reading_id": start_id, "readings": readings, **over})


def test_defrosting_and_cooling_are_two_step_and_cooking_is_not(client, login, db, clock):
    m = login(MGR)
    phases = {t: {c["phase"] for c in make(client, m, db, t)["schedules"]} for t in ("defrosting", "cooling", "cooking")}
    assert phases == {"defrosting": {"start", "finish"}, "cooling": {"start", "finish"}, "cooking": {None}}
    cooking = make(client, m, db, "cooking", "BQ")
    assert all(c["require_reference"] and c["reference_label"] == "Item or product name" and not c["trace_lots"] for c in cooking["schedules"])
    for template in ("defrosting", "cooling", "reheating"):
        point = make(client, m, db, template, "BQ")
        assert all(c["trace_lots"] and not c["require_reference"] for c in point["schedules"] if c["phase"] != "finish")
        assert not any(c["trace_lots"] for c in point["schedules"] if c["phase"] == "finish")


def test_a_time_in_stays_pending_until_the_time_out_is_recorded(client, login, db, clock):
    m = login(MGR)
    point = make(client, m, db, "defrosting")
    started = start(client, login(STEWARD), point).json()
    pending = client.get("/api/monitoring/pending", headers=m).json()
    assert [(p["equipment_id"], p["item"]) for p in pending] == [(point["id"], started[0]["reference"])] and started[0]["reference"].startswith("POU-TEST-")
    due = [d for d in client.get("/api/monitoring/due", headers=m).json() if d["equipment_id"] == point["id"]]
    assert {d["stage"] for d in due} == {"Time in"}

    assert finish(client, m, point, None).status_code == 400
    done = finish(client, m, point, started[0]["id"])
    assert done.status_code == 201 and {r["reference"] for r in done.json()} == {started[0]["reference"]}
    assert client.get("/api/monitoring/pending", headers=m).json() == []
    assert finish(client, m, point, started[0]["id"]).status_code == 409


def test_a_time_out_cannot_close_an_entry_of_another_point(client, login, db, clock):
    m = login(MGR)
    one, other = make(client, m, db, "defrosting"), make(client, m, db, "cooling")
    started = start(client, m, one).json()
    assert finish(client, m, other, started[0]["id"]).status_code == 400


def test_the_monitoring_record_lists_every_point_and_shows_pending_time_outs(client, login, db, clock):
    m = login(MGR)
    point = make(client, m, db, "defrosting")
    make(client, m, db, "chiller")
    start(client, m, point)
    doc = client.get("/api/reports/records/monitoring?date_from=2026-03-02&date_to=2026-03-02", headers=m).json()
    titles = [g["title"] for g in doc["groups"]]
    assert any("Chiller" in t for t in titles) and any("Defrosting" in t for t in titles)
    group = next(g for g in doc["groups"] if "Defrosting" in g["title"])
    assert [k for k, _ in group["columns"]][:3] == ["date", "time", "time_out"]
    assert group["rows"][0]["time_out"] == "Pending" and dict(group["totals"])["Waiting for time out"] == 1


def test_a_template_point_can_be_renamed(client, login, db, clock):
    m = login(MGR)
    point = make(client, m, db, "cooking")
    renamed = client.put(f"/api/equipment/{point['id']}", json={"name": "Hot kitchen cooking"}, headers=m)
    assert renamed.status_code == 200 and renamed.json()["name"] == "Hot kitchen cooking"


def test_date_and_time_fields_and_forms_without_a_schedule(client, login, db, clock):
    m = login(MGR)
    body = {"name": "Pest control visit", "kind": "Other", "location_ids": [loc_id(db, "MK")], "frequency": {"mode": "on_demand"},
            "fields": [{"title": "Visit date", "value_type": "date"}, {"title": "Arrival time", "value_type": "time"}]}
    made = client.post("/api/equipment/forms", json=body, headers=m)
    assert made.status_code == 201, made.text
    point = made.json()["points"][0]
    assert {c["timing"] for c in point["schedules"]} == {"manual"}
    assert [d for d in client.get("/api/monitoring/due", headers=m).json() if d["equipment_id"] == point["id"]] == []
    date_check, time_check = point["schedules"]
    ok = client.post("/api/monitoring/readings/batch", headers=m, json={"equipment_id": point["id"], "readings": [
        {"schedule_id": date_check["id"], "answer": "2026-03-02"}, {"schedule_id": time_check["id"], "answer": "14:30"}]})
    assert ok.status_code == 201 and [r["display"] for r in ok.json()] == ["2026-03-02", "14:30"]
    bad = client.post("/api/monitoring/readings", headers=m, json={"equipment_id": point["id"], "schedule_id": date_check["id"], "answer": "31/02/2026"})
    assert bad.status_code == 400


def test_an_existing_check_can_be_turned_into_a_time_in_and_keeps_its_step_when_edited_by_other_clients(client, login, db, clock):
    m = login(MGR)
    point = make(client, m, db, "chiller")
    sched = point["schedules"][0]
    body = {"stage": sched["stage"], "parameter": "Temperature", "unit": "C", "value_type": "number", "timing": "checkpoint",
            "min_value": 0, "max_value": 5, "phase": "start", "require_reference": True, "reference_label": "Item name"}
    edited = client.put(f"/api/equipment/schedules/{sched['id']}", json=body, headers=m).json()
    assert (edited["phase"], edited["reference_label"]) == ("start", "Item name")
    body.pop("phase"), body.pop("reference_label")
    assert client.put(f"/api/equipment/schedules/{sched['id']}", json=body, headers=m).json()["phase"] == "start"


def test_a_scheduled_check_cannot_be_recorded_twice_for_the_same_time(client, login, db, clock):
    m = login(MGR)
    point = make(client, m, db, "chiller")
    morning = point["schedules"][0]
    body = {"equipment_id": point["id"], "schedule_id": morning["id"], "value": 3}
    clock.set(2026, 3, 2, 4, 30)
    assert client.post("/api/monitoring/readings", json=body, headers=m).status_code == 201
    again = client.post("/api/monitoring/readings", json=body, headers=m)
    assert again.status_code == 409 and "already recorded" in again.json()["detail"]
    due = [d for d in client.get("/api/monitoring/due", headers=m).json() if d["schedule_id"] == morning["id"]]
    assert [d["status"] for d in due] == ["done"]
    clock.advance(days=1)
    assert client.post("/api/monitoring/readings", json=body, headers=m).status_code == 201


def test_a_reviewer_rejects_readings_and_the_check_can_be_recorded_again(client, login, db, clock):
    m, steward, sup = login(MGR), login(STEWARD), login("sup.mk@example.test")
    point = make(client, m, db, "chiller")
    morning = point["schedules"][0]
    body = {"equipment_id": point["id"], "schedule_id": morning["id"], "value": 3}
    clock.set(2026, 3, 2, 4, 30)
    first = client.post("/api/monitoring/readings", json=body, headers=steward).json()
    assert client.post("/api/monitoring/readings", json=body, headers=steward).status_code == 409
    url = "/api/monitoring/readings/reject"
    assert client.post(url, json={"reading_ids": [first["id"]], "reason": "Probe was not in the product"}, headers=steward).status_code == 403
    assert client.post(url, json={"reading_ids": [first["id"]], "reason": "x"}, headers=sup).status_code == 422
    assert client.post(url, json={"reading_ids": [first["id"]], "reason": "Probe was not in the product"}, headers=sup).json() == {"rejected": 1, "skipped": 0}
    assert client.post(url, json={"reading_ids": [first["id"]], "reason": "Probe was not in the product"}, headers=sup).json() == {"rejected": 0, "skipped": 1}
    assert client.post(f"/api/monitoring/readings/{first['id']}/review", headers=m).status_code == 409
    shown = client.get("/api/monitoring/readings", headers=m).json()["items"][0]
    assert shown["reject_reason"] == "Probe was not in the product" and shown["rejected_by_name"] == "Sam Supervisor"
    assert client.post("/api/monitoring/readings", json=body, headers=steward).status_code == 201
    note = client.get("/api/notifications", headers=steward).json()["items"]
    assert any(n["title"] == "Record again: Morning temperature" for n in note)


def form_body(**over):
    return {"name": "Handover", "kind": "Other", "location_ids": [1], "frequency": {"mode": "on_demand"}, "fields": [
        {"title": "Handover notes", "value_type": "text", "required": True},
        {"title": "Extra comment", "value_type": "text", "required": False},
        {"title": "Supervisor signature", "value_type": "signature", "required": True},
        {"title": "Photo of the area", "value_type": "image", "required": False}], **over}


def upload_png(client, h):
    png = ONE_PIXEL
    return client.post("/api/uploads", files={"file": ("sig.png", png, "image/png")}, headers=h).json()["name"]


def test_signature_and_image_answers_and_optional_questions(client, login, db, clock):
    m = login(MGR)
    point = client.post("/api/equipment/forms", json=form_body(), headers=m).json()["points"][0]
    notes, extra, sign, photo = point["schedules"]
    assert [c["required"] for c in point["schedules"]] == [True, False, True, False]
    assert [c["value_type"] for c in point["schedules"]][2:] == ["signature", "image"]
    # optional questions never become due or overdue
    assert [d for d in client.get("/api/monitoring/due", headers=m).json() if d["equipment_id"] == point["id"]] == []
    send = lambda items: client.post("/api/monitoring/readings/batch", headers=m, json={"equipment_id": point["id"], "readings": items})
    name = upload_png(client, m)
    assert send([{"schedule_id": notes["id"], "answer": "All clear"}]).status_code == 400            # signature missing
    assert send([{"schedule_id": notes["id"], "answer": "All clear"}, {"schedule_id": sign["id"], "answer": "nope.png"}]).status_code == 400
    ok = send([{"schedule_id": notes["id"], "answer": "All clear"}, {"schedule_id": sign["id"], "answer": name}])
    assert ok.status_code == 201 and [r["value_type"] for r in ok.json()] == ["text", "signature"]
    assert ok.json()[1]["display"] == name
    pdf = client.get("/api/reports/records/monitoring/export?fmt=pdf&date_from=2026-03-02&date_to=2026-03-02", headers=m)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    both = send([{"schedule_id": notes["id"], "answer": "Again"}, {"schedule_id": sign["id"], "answer": name}, {"schedule_id": photo["id"], "answer": upload_png(client, m)}])
    assert both.status_code == 201 and len(both.json()) == 3
    assert client.post("/api/equipment/forms", json=form_body(fields=[{"title": "Only optional", "value_type": "text", "required": False}]), headers=m).status_code == 201
