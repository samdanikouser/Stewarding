from datetime import datetime

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import FoodItem, InventoryBalance, InventoryItem, Location, Lot, StockTransaction, User

MGR = "manager@example.test"
SUP = "sup.mk@example.test"
SUP_RB = "sup.rb@example.test"
STEWARD = "steward.mk@example.test"
STEWARD_RB = "steward.rb@example.test"


def make_lot(location_id):
    """A received poultry lot written straight to the database, for checks that only need a lot to name; returns its id."""
    with SessionLocal() as db:
        item = db.scalar(select(FoodItem)) or FoodItem(name="Chicken breast", food_group="poultry")
        db.add(item)
        db.flush()
        lot = Lot(code=f"POU-TEST-{db.scalar(select(func.count(Lot.id))) + 1:02d}", kind="received", food_item_id=item.id, food_group=item.food_group,
                  condition="chilled_raw", supplier_lot="B1", location_id=location_id, created_by=db.scalar(select(User.id)), created_at=datetime(2026, 3, 2, 2, 5))
        db.add(lot)
        db.commit()
        return lot.id


def loc_id(db, code):
    return db.scalar(select(Location.id).where(Location.code == code))


def item_id(db, code):
    return db.scalar(select(InventoryItem.id).where(InventoryItem.code == code))


def balance(db, code, location_code):
    db.expire_all()
    value = db.scalar(select(InventoryBalance.qty).where(
        InventoryBalance.item_id == item_id(db, code), InventoryBalance.location_id == loc_id(db, location_code)))
    return value or 0


def ledger_sum(db, code, location_code):
    db.expire_all()
    rows = db.scalars(select(StockTransaction.qty_delta).where(
        StockTransaction.item_id == item_id(db, code), StockTransaction.location_id == loc_id(db, location_code)))
    return sum(rows)


def retire_item(client, manager, db, code):
    """Writes the item's stock off at every location, then makes it inactive."""
    item = db.scalar(select(InventoryItem).where(InventoryItem.code == code))
    for held in db.scalars(select(InventoryBalance).where(InventoryBalance.item_id == item.id)).all():
        if held.qty:
            client.post("/api/inventory/transactions", headers=manager, json={
                "item_id": item.id, "location_id": held.location_id, "txn_type": "adjustment", "qty": -held.qty, "reason": "Written off before retiring"})
    return client.put(f"/api/inventory/items/{item.id}", headers=manager, json={"active": False})
