from io import BytesIO

from PIL import Image
from sqlalchemy import select

from app.api.uploads import upload_path
from app.models import InventoryItem

MGR = "manager@example.test"
SUP = "sup.mk@example.test"


def picture(size=(2000, 1500), mode="RGB", fmt="PNG"):
    out = BytesIO()
    Image.new(mode, size, (200, 30, 30, 255) if mode == "RGBA" else (200, 30, 30)).save(out, fmt)
    return out.getvalue()


def upload(client, h, item_id, data, name="photo.png", kind="image/png"):
    return client.post(f"/api/inventory/items/{item_id}/image", headers=h, files={"file": (name, data, kind)})


def first_item(db):
    return db.scalar(select(InventoryItem))


def test_a_big_picture_is_kept_as_a_small_jpeg_thumbnail(client, login, db):
    h = login(MGR)
    item = first_item(db)
    r = upload(client, h, item.id, picture())
    assert r.status_code == 200
    name = r.json()["image_path"]
    assert name.endswith(".jpg")
    stored = client.get(f"/api/uploads/{name}", headers=h)
    thumb = Image.open(BytesIO(stored.content))
    assert thumb.format == "JPEG" and max(thumb.size) == 320 and len(stored.content) < len(picture())
    listed = client.get("/api/inventory/items", headers=h, params={"search": item.code}).json()["items"]
    assert [i["image_path"] for i in listed if i["id"] == item.id] == [name]


def test_a_transparent_png_is_flattened_and_a_small_picture_is_not_enlarged(client, login, db):
    h = login(MGR)
    item = first_item(db)
    name = upload(client, h, item.id, picture((100, 80), "RGBA")).json()["image_path"]
    assert Image.open(BytesIO(client.get(f"/api/uploads/{name}", headers=h).content)).size == (100, 80)


def test_replacing_or_removing_a_picture_deletes_the_old_file(client, login, db):
    h = login(MGR)
    item = first_item(db)
    first = upload(client, h, item.id, picture()).json()["image_path"]
    second = upload(client, h, item.id, picture((400, 400))).json()["image_path"]
    assert first != second and not upload_path(first).exists() and upload_path(second).exists()
    assert client.delete(f"/api/inventory/items/{item.id}/image", headers=h).json() == {"image_path": None}
    assert not upload_path(second).exists()
    db.expire_all()
    assert db.get(InventoryItem, item.id).image_path is None


def test_only_pictures_are_accepted_and_only_by_those_who_manage_items(client, login, db):
    h = login(MGR)
    item = first_item(db)
    assert upload(client, h, item.id, b"%PDF-1.4 not a picture", "a.pdf", "application/pdf").status_code == 415
    assert upload(client, h, item.id, b"\x89PNG\r\n\x1a\n" + b"junk" * 10).status_code == 400
    assert upload(client, h, item.id, picture(), ).status_code == 200
    assert upload(client, login(SUP), item.id, picture()).status_code == 403
    assert client.delete(f"/api/inventory/items/{item.id}/image", headers=login(SUP)).status_code == 403
    assert upload(client, h, 99999, picture()).status_code == 404
