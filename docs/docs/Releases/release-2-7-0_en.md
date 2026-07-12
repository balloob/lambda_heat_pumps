---
title: "Release 2.7.0"
---

# Release 2.7.0

*Last updated: 2026-07-12*

> **Current Release** · Branch `V2.7.0`

---

## Summary

Release 2.7.0 includes a bug fix for users with German umlauts in the device name, and a new mechanism to define the default register order for 32-bit Modbus sensors per firmware version. No breaking changes.

---

## Bug Fixes

### Umlauts in device name cause energy sensor lookup to fail ([#93](https://github.com/GuidoJeuken-6512/lambda_heat_pumps/issues/93))

**Affected:** Users who configured a device name containing umlauts (e.g. `Wärmepumpe`) in the integration's Options Flow **and** have not configured an external energy sensor (falling back to the integration's own sensor).

**Symptom:** The debug log repeatedly shows lines like:

```
[Energy] HP1 electrical: Sensor sensor.wärmepumpe_hp1_compressor_power_consumption_accumulated not available (state=None)
```

**Root cause:** Home Assistant's entity registry automatically transliterates umlauts to ASCII when first creating an entity (`ä` → `a`). The actual entity is therefore named `sensor.warmepumpe_hp1_…`, but the internal lookup was constructing `sensor.wärmepumpe_hp1_…` — the names never matched.

**Fix:** New helper function `slugify_name_prefix_for_lookup()` in `utils.py` that applies the same transliteration as Home Assistant's entity registry for read-only lookups. All `unique_id`-relevant paths are unchanged — no impact on existing entities, history, or counter state.

**Affected files:** `custom_components/lambda_heat_pumps/utils.py`, `custom_components/lambda_heat_pumps/coordinator.py`

---

## New Features

### Firmware-dependent default for register order (`int32_register_order`)

**Affected:** `custom_components/lambda_heat_pumps/const_base.py` · `custom_components/lambda_heat_pumps/modbus_utils.py` · `custom_components/lambda_heat_pumps/__init__.py`

Previously, the default for the 32-bit register order (`"high_first"`) was hardcoded — regardless of the configured firmware version. Since the correct value can differ per firmware version, each entry in the firmware configuration now carries its own register-order default.

**New `FIRMWARE_CONFIG` structure in `const_base.py`:**

```python
FIRMWARE_CONFIG: dict[str, dict] = {
    "V1.1.0-3K":  {"version": 8, "reg_order": "high_first"},
    "V0.0.10-3K": {"version": 8, "reg_order": "high_first"},
    # ...
}
# Backward compatibility — all existing callers unchanged:
FIRMWARE_VERSION: dict[str, int] = {k: v["version"] for k, v in FIRMWARE_CONFIG.items()}
```

**Priority chain (lowest to highest):**

1. `"high_first"` — absolute fallback
2. `FIRMWARE_CONFIG[fw_version]["reg_order"]` — firmware-dependent default *(new)*
3. `modbus.int32_byte_order` in `lambda_wp_config.yaml` — legacy override
4. `modbus.int32_register_order` in `lambda_wp_config.yaml` — explicit override

The YAML override in `lambda_wp_config.yaml` is fully preserved and still takes precedence over the firmware default.

**For developers / maintainers:** When a new firmware version uses a different register order, it is sufficient to add the corresponding entry in `FIRMWARE_CONFIG` with the correct `"reg_order"` value — `FIRMWARE_VERSION` is derived from it automatically.

---

## Affected Files

| File | Change |
|---|---|
| `custom_components/lambda_heat_pumps/utils.py` | New function `slugify_name_prefix_for_lookup()`; import `ha_slugify` |
| `custom_components/lambda_heat_pumps/coordinator.py` | 2 lookup sites use `slugify_name_prefix_for_lookup` instead of `normalize_name_prefix` |
| `custom_components/lambda_heat_pumps/const_base.py` | `FIRMWARE_CONFIG` as new primary structure; `FIRMWARE_VERSION` as derived compat dict |
| `custom_components/lambda_heat_pumps/modbus_utils.py` | `get_int32_register_order(hass, entry)` — firmware-dependent default before YAML fallback |
| `custom_components/lambda_heat_pumps/__init__.py` | Call site passes `entry` to `get_int32_register_order` |
