"""Ready-made monitoring points; each preset becomes a monitoring point with its checks."""
from datetime import time

TEMP = {"parameter": "Temperature", "unit": "°C", "value_type": "number"}
YES_NO = {"parameter": "Check", "unit": None, "value_type": "yes_no"}
ITEM = {"require_reference": True, "reference_label": "Item or product name"}
LOTS = {"trace_lots": True}
START = {"phase": "start"}
FINISH = {"phase": "finish"}


def at(hour: int, minute: int = 0) -> dict:
    return {"timing": "checkpoint", "time_of_day": time(hour, minute)}


TEMPLATES = [
    {"key": "chiller", "name": "Chiller or fridge", "prefix": "CH", "type": "Cold storage", "checks": [
        {"stage": "Morning temperature", **TEMP, **at(8), "min_value": 0, "max_value": 5, "source": "independent_probe"},
        {"stage": "Afternoon temperature", **TEMP, **at(16), "min_value": 0, "max_value": 5, "source": "independent_probe"}]},
    {"key": "freezer", "name": "Freezer", "prefix": "FZ", "type": "Cold storage", "checks": [
        {"stage": "Morning temperature", **TEMP, **at(8), "min_value": -40, "max_value": -18, "source": "independent_probe"},
        {"stage": "Afternoon temperature", **TEMP, **at(16), "min_value": -40, "max_value": -18, "source": "independent_probe"}]},
    {"key": "defrosting", "name": "Defrosting log", "prefix": "DF", "type": "Defrosting", "checks": [
        {"stage": "Time in", **TEMP, **at(9), **LOTS, **START, "min_value": 0, "max_value": 5, "source": "independent_probe"},
        {"stage": "Time out", **YES_NO, "parameter": "Fully defrosted", "timing": "checkpoint", **FINISH},
        {"stage": "Time out", **TEMP, "timing": "checkpoint", **FINISH, "min_value": 0, "max_value": 5, "source": "independent_probe"}]},
    {"key": "cooking", "name": "Cooking core temperature", "prefix": "CK", "type": "Cooking", "checks": [
        {"stage": "Lunch core temperature", **TEMP, **at(12), **ITEM, "min_value": 75, "max_value": 120, "source": "independent_probe"},
        {"stage": "Dinner core temperature", **TEMP, **at(18), **ITEM, "min_value": 75, "max_value": 120, "source": "independent_probe"}]},
    {"key": "reheating", "name": "Reheating", "prefix": "RH", "type": "Reheating", "checks": [
        {"stage": "Core temperature after reheating", **TEMP, **at(12), **LOTS, "min_value": 75, "max_value": 120,
         "source": "independent_probe"}]},
    {"key": "cooling", "name": "Cooling", "prefix": "CL", "type": "Cooling", "checks": [
        {"stage": "Time in", **TEMP, **at(14), **LOTS, **START, "min_value": 60, "max_value": 100, "source": "independent_probe"},
        {"stage": "Time out", **TEMP, "timing": "checkpoint", **FINISH, "min_value": -5, "max_value": 10, "source": "independent_probe"}]},
    {"key": "hot_holding", "name": "Hot holding", "prefix": "HH", "type": "Hot holding", "checks": [
        {"stage": "Holding temperature", **TEMP, "timing": "interval", "interval_minutes": 120, "time_of_day": time(11, 0),
         "min_value": 63, "max_value": 100, "source": "independent_probe"}]},
    {"key": "sanitiser", "name": "Sanitiser concentration", "prefix": "SN", "type": "Sanitising", "checks": [
        {"stage": "Start of day strength", "parameter": "Concentration", "unit": "ppm", "value_type": "number", **at(7),
         "min_value": 200, "max_value": 400, "source": "independent_probe"}]},
    {"key": "dishwasher", "name": "Dishwasher", "prefix": "DW", "type": "Dishwasher", "checks": [
        {"stage": "Wash", **TEMP, "timing": "startup", "min_value": 55, "max_value": 65},
        {"stage": "Final rinse", **TEMP, "timing": "startup", "min_value": 80, "max_value": 90}]},
    {"key": "goods_receiving", "name": "Goods receiving traceability", "prefix": "GR", "type": "Traceability", "checks": [
        {"stage": "Delivery temperature", **TEMP, **at(10), "min_value": -25, "max_value": 5, "require_reference": True,
         "source": "independent_probe"},
        {"stage": "Labels, batch and expiry checked", **YES_NO, **at(10, 30), "require_reference": True}]},
    {"key": "probe_calibration", "name": "Probe calibration", "prefix": "PC", "type": "Calibration", "checks": [
        {"stage": "Ice water test", **YES_NO, **at(8), "weekdays": "0"}]},
]
BY_KEY = {t["key"]: t for t in TEMPLATES}
