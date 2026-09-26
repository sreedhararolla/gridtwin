from gridtwin.fleet.disaggregate import disaggregate
from gridtwin.fleet.models import DeviceState


def make_device(device_id: str, soc_pct: float) -> DeviceState:
    return DeviceState(
        device_id=device_id,
        soc_pct=soc_pct,
        energy_kwh=39.2,
        max_power_kw=1000.0,  # high enough that energy, not the power limit, binds headroom
        round_trip_efficiency=0.9,
        reserve_floor_pct=0.20,
    )


def test_discharge_splits_proportional_to_headroom():
    devices = [make_device("a", 0.9), make_device("b", 0.3)]
    setpoints = disaggregate(1000.0, devices)  # ask for far more than the fleet can give
    assert setpoints["a"] > setpoints["b"] > 0
    assert all(v >= 0 for v in setpoints.values())


def test_charge_splits_negative_proportional_to_headroom():
    devices = [make_device("a", 0.1), make_device("b", 0.9)]
    setpoints = disaggregate(-1000.0, devices)
    assert setpoints["a"] < setpoints["b"] < 0


def test_target_is_capped_to_achievable():
    devices = [make_device("a", 0.5)]
    setpoints = disaggregate(1000.0, devices)
    from gridtwin.fleet.device import headroom_mw

    discharge_mw, _ = headroom_mw(devices[0])
    assert setpoints["a"] == discharge_mw


def test_zero_capacity_returns_zero_setpoints():
    devices = [make_device("a", 0.20)]  # already at the reserve floor
    setpoints = disaggregate(50.0, devices)
    assert setpoints["a"] == 0.0
