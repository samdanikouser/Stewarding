import re
from pathlib import Path

import pytest

from app.services.settings import DEFAULTS, LIMITS

from .helpers import MGR


def test_every_setting_has_a_range_that_holds_its_default():
    assert set(LIMITS) == set(DEFAULTS)
    assert all(low <= DEFAULTS[key] <= high for key, (low, high) in LIMITS.items())


def test_the_ranges_are_sent_to_the_settings_screen(client, login):
    body = client.get("/api/settings", headers=login(MGR)).json()
    assert body["limits"]["attendance.face_match_max"] == [10, 80]


@pytest.mark.parametrize("key", sorted(LIMITS))
def test_a_setting_accepts_its_limits_and_refuses_anything_beyond(client, login, key):
    m = login(MGR)
    low, high = LIMITS[key]
    for value in (low, high):
        assert client.put("/api/settings", json={"values": {key: value}}, headers=m).status_code == 200
    assert client.put("/api/settings", json={"values": {key: high + 1}}, headers=m).status_code == 400
    assert client.put("/api/settings", json={"values": {key: low - 1}}, headers=m).status_code == 400
    assert client.get("/api/settings", headers=m).json()["settings"][key] == high


def test_every_setting_has_an_entry_on_the_settings_screens():
    registry = Path(__file__).resolve().parents[2] / "frontend/src/pages/settings/settingsRegistry.ts"
    if not registry.exists():
        pytest.skip("the frontend is not part of this checkout")
    assert set(re.findall(r"key: '([^']+)'", registry.read_text())) == set(DEFAULTS)
