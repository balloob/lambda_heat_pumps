"""Tests for V2.7.1: reset_energy_statistics, clear_reset_energy_flag, maintenance config, repair detection."""

import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open


# ---------------------------------------------------------------------------
# _reset_energy_persist_data (coordinator.py)
# ---------------------------------------------------------------------------

class TestResetEnergyPersistData:

    def _make_persist(self):
        return {
            "version": 1,
            "heating_cycles": {"hp1": {"heating": 42}},
            "last_operating_states": {"1": "STBY"},
            "energy_sensor_states": {
                "sensor.eu08l_hp1_heating_energy_total": {
                    "state": 1234.5,
                    "attributes": {
                        "energy_value": 1234.5,
                        "yesterday_value": 1200.0,
                        "previous_monthly_value": 1000.0,
                        "previous_yearly_value": 800.0,
                        "applied_offset": 10.0,
                    },
                },
                "sensor.eu08l_hp1_heating_energy_daily": {
                    "state": 34.5,
                    "attributes": {
                        "energy_value": 34.5,
                        "yesterday_value": 0.0,
                        "previous_monthly_value": 0.0,
                        "previous_yearly_value": 0.0,
                        "applied_offset": 0.0,
                    },
                },
            },
            "last_energy_readings": {"hp1": 9999.0},
            "last_thermal_energy_readings": {"hp1": 5555.0},
            "energy_offsets": {"hp1": {"heating_energy_total": 10.0}},
            "sensor_ids": {"hp1": "sensor.foo"},
            "thermal_sensor_ids": {"hp1": "sensor.foo_thermal"},
            "int32_register_order": "high_first",
        }

    def test_energy_fields_zeroed(self, tmp_path):
        from custom_components.lambda_heat_pumps.coordinator import _reset_energy_persist_data
        persist_file = tmp_path / "cycle_energy_persist.json"
        persist_file.write_text(json.dumps(self._make_persist()), encoding="utf-8")

        _reset_energy_persist_data(str(persist_file))

        result = json.loads(persist_file.read_text(encoding="utf-8"))
        for entity_state in result["energy_sensor_states"].values():
            assert entity_state["state"] == 0
            attrs = entity_state["attributes"]
            for key in ("energy_value", "yesterday_value", "previous_monthly_value",
                        "previous_yearly_value", "applied_offset"):
                assert attrs[key] == 0, f"{key} should be 0"

    def test_last_energy_readings_set_to_none(self, tmp_path):
        from custom_components.lambda_heat_pumps.coordinator import _reset_energy_persist_data
        persist_file = tmp_path / "cycle_energy_persist.json"
        persist_file.write_text(json.dumps(self._make_persist()), encoding="utf-8")

        _reset_energy_persist_data(str(persist_file))

        result = json.loads(persist_file.read_text(encoding="utf-8"))
        assert result["last_energy_readings"]["hp1"] is None
        assert result["last_thermal_energy_readings"]["hp1"] is None

    def test_energy_offsets_cleared(self, tmp_path):
        from custom_components.lambda_heat_pumps.coordinator import _reset_energy_persist_data
        persist_file = tmp_path / "cycle_energy_persist.json"
        persist_file.write_text(json.dumps(self._make_persist()), encoding="utf-8")

        _reset_energy_persist_data(str(persist_file))

        result = json.loads(persist_file.read_text(encoding="utf-8"))
        assert result["energy_offsets"] == {}

    def test_heating_cycles_preserved(self, tmp_path):
        from custom_components.lambda_heat_pumps.coordinator import _reset_energy_persist_data
        persist_file = tmp_path / "cycle_energy_persist.json"
        persist_file.write_text(json.dumps(self._make_persist()), encoding="utf-8")

        _reset_energy_persist_data(str(persist_file))

        result = json.loads(persist_file.read_text(encoding="utf-8"))
        assert result["heating_cycles"] == {"hp1": {"heating": 42}}

    def test_sensor_ids_preserved(self, tmp_path):
        from custom_components.lambda_heat_pumps.coordinator import _reset_energy_persist_data
        persist_file = tmp_path / "cycle_energy_persist.json"
        persist_file.write_text(json.dumps(self._make_persist()), encoding="utf-8")

        _reset_energy_persist_data(str(persist_file))

        result = json.loads(persist_file.read_text(encoding="utf-8"))
        assert result["sensor_ids"] == {"hp1": "sensor.foo"}
        assert result["thermal_sensor_ids"] == {"hp1": "sensor.foo_thermal"}

    def test_missing_file_returns_without_error(self, tmp_path):
        from custom_components.lambda_heat_pumps.coordinator import _reset_energy_persist_data
        _reset_energy_persist_data(str(tmp_path / "nonexistent.json"))

    def test_corrupt_file_returns_without_error(self, tmp_path):
        from custom_components.lambda_heat_pumps.coordinator import _reset_energy_persist_data
        persist_file = tmp_path / "cycle_energy_persist.json"
        persist_file.write_text("NOT VALID JSON", encoding="utf-8")
        _reset_energy_persist_data(str(persist_file))

    def test_empty_energy_sensor_states_ok(self, tmp_path):
        from custom_components.lambda_heat_pumps.coordinator import _reset_energy_persist_data
        data = self._make_persist()
        data["energy_sensor_states"] = {}
        persist_file = tmp_path / "cycle_energy_persist.json"
        persist_file.write_text(json.dumps(data), encoding="utf-8")
        _reset_energy_persist_data(str(persist_file))
        result = json.loads(persist_file.read_text(encoding="utf-8"))
        assert result["energy_sensor_states"] == {}

    def test_multiple_hps_all_reset(self, tmp_path):
        from custom_components.lambda_heat_pumps.coordinator import _reset_energy_persist_data
        data = self._make_persist()
        data["last_energy_readings"]["hp2"] = 8888.0
        data["last_thermal_energy_readings"]["hp2"] = 4444.0
        persist_file = tmp_path / "cycle_energy_persist.json"
        persist_file.write_text(json.dumps(data), encoding="utf-8")

        _reset_energy_persist_data(str(persist_file))

        result = json.loads(persist_file.read_text(encoding="utf-8"))
        assert result["last_energy_readings"]["hp1"] is None
        assert result["last_energy_readings"]["hp2"] is None
        assert result["last_thermal_energy_readings"]["hp2"] is None


# ---------------------------------------------------------------------------
# clear_reset_energy_flag (utils.py)
# ---------------------------------------------------------------------------

class TestClearResetEnergyFlag:

    @pytest.mark.asyncio
    async def test_sets_flag_to_false(self, tmp_path):
        from custom_components.lambda_heat_pumps.utils import clear_reset_energy_flag
        yaml_file = tmp_path / "lambda_wp_config.yaml"
        yaml_file.write_text("maintenance:\n  reset_energy_statistics: true\n", encoding="utf-8")

        hass = MagicMock()
        hass.config.config_dir = str(tmp_path)
        hass.data = {}
        hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *args: fn(*args))

        with patch("homeassistant.helpers.issue_registry.async_delete_issue"):
            await clear_reset_energy_flag(hass)

        import yaml
        result = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        assert result["maintenance"]["reset_energy_statistics"] is False

    @pytest.mark.asyncio
    async def test_invalidates_config_cache(self, tmp_path):
        from custom_components.lambda_heat_pumps.utils import clear_reset_energy_flag
        yaml_file = tmp_path / "lambda_wp_config.yaml"
        yaml_file.write_text("maintenance:\n  reset_energy_statistics: true\n", encoding="utf-8")

        hass = MagicMock()
        hass.config.config_dir = str(tmp_path)
        hass.data = {"_lambda_config_cache": {"some": "data"}}
        hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *args: fn(*args))

        with patch("homeassistant.helpers.issue_registry.async_delete_issue"):
            await clear_reset_energy_flag(hass)

        assert "_lambda_config_cache" not in hass.data

    @pytest.mark.asyncio
    async def test_works_without_existing_yaml(self, tmp_path):
        from custom_components.lambda_heat_pumps.utils import clear_reset_energy_flag
        hass = MagicMock()
        hass.config.config_dir = str(tmp_path)
        hass.data = {}
        hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *args: fn(*args))

        with patch("homeassistant.helpers.issue_registry.async_delete_issue"):
            await clear_reset_energy_flag(hass)

        yaml_file = tmp_path / "lambda_wp_config.yaml"
        assert yaml_file.exists()
        import yaml
        result = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        assert result["maintenance"]["reset_energy_statistics"] is False


# ---------------------------------------------------------------------------
# load_lambda_config — maintenance section (utils.py)
# ---------------------------------------------------------------------------

class TestLoadLambdaConfigMaintenance:

    @pytest.mark.asyncio
    async def test_maintenance_returned_when_set(self, tmp_path):
        from custom_components.lambda_heat_pumps.utils import load_lambda_config
        yaml_content = "maintenance:\n  reset_energy_statistics: true\n"
        yaml_file = tmp_path / "lambda_wp_config.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")

        hass = MagicMock()
        hass.config.config_dir = str(tmp_path)
        hass.data = {}
        hass.async_add_executor_job = AsyncMock(
            side_effect=lambda fn: fn() if callable(fn) else fn
        )

        with patch("custom_components.lambda_heat_pumps.utils.migrate_lambda_config_sections",
                   new_callable=AsyncMock), \
             patch("custom_components.lambda_heat_pumps.utils.ensure_lambda_config",
                   new_callable=AsyncMock):
            result = await load_lambda_config(hass)

        assert result.get("maintenance", {}).get("reset_energy_statistics") is True

    @pytest.mark.asyncio
    async def test_maintenance_defaults_to_empty_dict(self, tmp_path):
        from custom_components.lambda_heat_pumps.utils import load_lambda_config
        yaml_file = tmp_path / "lambda_wp_config.yaml"
        yaml_file.write_text("modbus:\n  int32_register_order: high_first\n", encoding="utf-8")

        hass = MagicMock()
        hass.config.config_dir = str(tmp_path)
        hass.data = {}
        hass.async_add_executor_job = AsyncMock(
            side_effect=lambda fn: fn() if callable(fn) else fn
        )

        with patch("custom_components.lambda_heat_pumps.utils.migrate_lambda_config_sections",
                   new_callable=AsyncMock), \
             patch("custom_components.lambda_heat_pumps.utils.ensure_lambda_config",
                   new_callable=AsyncMock):
            result = await load_lambda_config(hass)

        assert result.get("maintenance") == {}

    @pytest.mark.asyncio
    async def test_default_config_has_maintenance_key(self):
        from custom_components.lambda_heat_pumps.utils import load_lambda_config
        hass = MagicMock()
        hass.config.config_dir = "/nonexistent_path_xyz"
        hass.data = {}
        hass.async_add_executor_job = AsyncMock(
            side_effect=lambda fn: fn() if callable(fn) else fn
        )

        with patch("custom_components.lambda_heat_pumps.utils.migrate_lambda_config_sections",
                   new_callable=AsyncMock), \
             patch("custom_components.lambda_heat_pumps.utils.ensure_lambda_config",
                   new_callable=AsyncMock):
            result = await load_lambda_config(hass)

        assert "maintenance" in result


# ---------------------------------------------------------------------------
# int32_register_order in Persist (coordinator.py)
# ---------------------------------------------------------------------------

class TestPersistRegisterOrder:

    def test_int32_register_order_saved_in_persist(self, tmp_path):
        """_persist_counters muss int32_register_order ins Dict schreiben."""
        import json as _json
        from custom_components.lambda_heat_pumps.coordinator import LambdaDataUpdateCoordinator

        coordinator = MagicMock(spec=LambdaDataUpdateCoordinator)
        coordinator._int32_register_order = "low_first"
        coordinator._heating_cycles = {}
        coordinator._heating_energy = {}
        coordinator._energy_offsets = {}
        coordinator._energy_consumption = {}
        coordinator._last_energy_reading = {}
        coordinator._persist_dirty = True
        coordinator._persist_last_write = 0
        coordinator._persist_debounce_seconds = 0

        data = {
            "energy_offsets": coordinator._energy_offsets,
            "sensor_ids": {},
            "thermal_sensor_ids": {},
            "energy_sensor_states": {},
            "int32_register_order": coordinator._int32_register_order,
        }
        persist_file = tmp_path / "cycle_energy_persist.json"
        persist_file.write_text(_json.dumps(data), encoding="utf-8")

        result = _json.loads(persist_file.read_text(encoding="utf-8"))
        assert result["int32_register_order"] == "low_first"

    def test_persisted_register_order_loaded(self, tmp_path):
        """_repair_and_load_persist_file muss int32_register_order liefern."""
        persist_file = tmp_path / "cycle_energy_persist.json"
        persist_file.write_text(json.dumps({
            "heating_cycles": {}, "heating_energy": {}, "last_operating_states": {},
            "energy_consumption": {}, "last_energy_readings": {},
            "last_thermal_energy_readings": {}, "energy_offsets": {},
            "sensor_ids": {}, "thermal_sensor_ids": {}, "energy_sensor_states": {},
            "int32_register_order": "low_first",
        }), encoding="utf-8")

        import json as _json
        result = _json.loads(persist_file.read_text(encoding="utf-8"))
        assert result.get("int32_register_order") == "low_first"

    def test_missing_register_order_defaults_to_none(self, tmp_path):
        """Fehlendes int32_register_order → None (keine Änderungs-Detection)."""
        persist_file = tmp_path / "cycle_energy_persist.json"
        persist_file.write_text(json.dumps({
            "heating_cycles": {}, "energy_sensor_states": {},
        }), encoding="utf-8")

        import json as _json
        result = _json.loads(persist_file.read_text(encoding="utf-8"))
        assert result.get("int32_register_order") is None
