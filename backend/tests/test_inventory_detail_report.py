import io

from openpyxl import load_workbook

from .helpers import MGR, SUP, item_id, loc_id
from .test_receiving import receive

DAY = "date_from=2026-03-01&date_to=2026-03-31"


def build(client, h, kind="inventory_detail", fmt=None, extra=""):
    path = f"/api/reports/records/{kind}?{DAY}{extra}"
    return client.get(path if not fmt else f"/api/reports/records/{kind}/export?fmt={fmt}&{DAY}{extra}", headers=h)


def test_the_detailed_report_gives_every_location_every_item_and_the_category_breakdown(client, login, db, clock):
    m = login(MGR)
    pl, pn = item_id(db, "PL-001"), item_id(db, "PN-001")
    receive(client, m, db, [{"item_id": pl, "qty": 30, "unit_cost": 2.0}], invoice="DR-1", invoice_date="2026-03-02")
    receive(client, m, db, [{"item_id": pl, "qty": 4, "unit_cost": 2.0}], invoice="DR-R", doc_type="supplier_return")
    client.post("/api/inventory/transactions", json={"item_id": pl, "location_id": loc_id(db, "MK"), "txn_type": "issue", "qty": 3, "reason": "used"}, headers=m)
    client.post("/api/stock/transfers", json={"from_location_id": loc_id(db, "MK"), "to_location_id": loc_id(db, "BQ"), "lines": [{"item_id": pl, "qty": 10}]}, headers=m)
    body = build(client, m).json()
    titles = [g["title"] for g in body["groups"]]
    assert "All locations - Cost by category" in titles and titles[-1] == "All locations - Total per item"
    assert any(t == "Main Kitchen - Stock by item" for t in titles) and any(t == "Banquet Hall - Stock by item" for t in titles)
    mk = next(g for g in body["groups"] if g["title"] == "Main Kitchen - Stock by item")
    row = next(r for r in mk["rows"] if r["item"].startswith("PL-001"))
    # every line adds up: opening + purchases + returns + transfers in - out - issued - breakage - missing + count = closing
    assert row["purchases_qty"] == 30 and row["issued_qty"] == 3 and row["transfers_out_qty"] == 10 and row["returns_qty"] == -4
    assert row["opening_qty"] + row["purchases_qty"] + row["returns_qty"] + row["transfers_in_qty"] - row["transfers_out_qty"] - row["issued_qty"] \
        - row["breakage_damage_qty"] - row["missing_written_off_qty"] + row["baseline_adjustments_qty"] + row["count_adjustments_qty"] == row["closing_qty"]
    total = next(g for g in body["groups"] if g["title"] == "All locations - Total per item")
    whole = next(r for r in total["rows"] if r["item"].startswith("PL-001"))
    assert whole["transfers_in_qty"] == whole["transfers_out_qty"] == 10 and "Banquet Hall" in whole["split"]      # a transfer is not stock arriving or leaving
    assert whole["closing_qty"] == sum(r["closing_qty"] for g in body["groups"] if g["title"].endswith("Stock by item") for r in g["rows"] if r["item"].startswith("PL-001"))
    cats = next(g for g in body["groups"] if g["title"] == "All locations - Cost by category")
    assert {"Category", "Opening value", "Purchases", "Transfers in", "Transfers out", "Breakage and damage", "Closing value"} <= {c[1] for c in cats["columns"]}


def test_it_exports_to_excel_and_pdf_and_one_location_can_be_chosen(client, login, db, clock):
    m = login(MGR)
    only = build(client, m, extra=f"&location_id={loc_id(db, 'BQ')}").json()
    assert [g["title"] for g in only["groups"]] == ["Banquet Hall - This period and year to date", "Banquet Hall - Cost by category", "Banquet Hall - Stock by item"]
    xlsx = build(client, m, fmt="xlsx")
    assert xlsx.status_code == 200
    book = load_workbook(io.BytesIO(xlsx.content))
    assert len(book.sheetnames) >= 3 and any("Stock by item" in name or "item" in name.lower() for name in book.sheetnames)
    pdf = build(client, m, fmt="pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert build(client, login(SUP)).status_code in (200, 403)


def test_excel_figures_are_real_numbers_that_can_be_added_up(client, login, db, clock):
    m = login(MGR)
    book = load_workbook(io.BytesIO(build(client, m, fmt="xlsx").content))
    sheet = book[[n for n in book.sheetnames if "Stock by item" in n][0]]
    header = next(r for r in sheet.iter_rows(values_only=False) if r[0].value == "Category")
    col = {c.value: c.column for c in header}
    first = sheet.cell(row=header[0].row + 1, column=col["Closing value"])
    assert isinstance(first.value, (int, float)) and first.number_format == "#,##0.000"
    assert isinstance(sheet.cell(row=header[0].row + 1, column=col["Closing qty"]).value, int)


def test_the_report_sets_the_year_to_date_beside_the_period(client, login, db, clock):
    m = login(MGR)
    pl = item_id(db, "PL-001")
    receive(client, m, db, [{"item_id": pl, "qty": 10, "unit_cost": 2.0}], invoice="YTD-1", invoice_date="2026-01-20")      # earlier in the year
    receive(client, m, db, [{"item_id": pl, "qty": 5, "unit_cost": 2.0}], invoice="YTD-2", invoice_date="2026-03-02")       # inside the period
    body = build(client, m, extra=f"&location_id={loc_id(db, 'MK')}").json()
    group = next(g for g in body["groups"] if g["title"] == "Main Kitchen - This period and year to date")
    lines = {r["measure"]: r for r in group["rows"]}
    assert lines["Purchases"]["period"] == "10.000" and lines["Purchases"]["ytd"] == "30.000"          # March alone, then January and March
    assert float(lines["Opening value"]["ytd"]) <= float(lines["Opening value"]["period"])             # the year opens earlier than the month
    assert lines["Closing qty"]["period"] == lines["Closing qty"]["ytd"]                                # both end at the same place
    whole = build(client, m, kind="inventory_detail", extra="").json()
    assert whole["groups"][0]["title"] == "All locations - This period and year to date"
    full_year = client.get("/api/reports/records/inventory_detail?date_from=2026-01-01&date_to=2026-03-31", headers=m).json()
    assert not any("year to date" in g["title"] for g in full_year["groups"])                           # a period that already starts the year needs no extra column
