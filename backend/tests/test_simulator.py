from app.domain.models import DesignParameters
from app.services.simulator import simulate


def baseline() -> DesignParameters:
    return DesignParameters(fin_count=48, fin_thickness=0.65, fin_height=52, fin_spacing=2.4, air_velocity=3.2)


def test_simulator_is_deterministic_without_noise():
    assert simulate(baseline()) == simulate(baseline())


def test_velocity_reduces_thermal_resistance_and_increases_pressure_drop():
    slow = baseline().model_copy(update={"air_velocity": 1.0})
    fast = baseline().model_copy(update={"air_velocity": 5.0})
    assert simulate(fast).thermal_resistance < simulate(slow).thermal_resistance
    assert simulate(fast).pressure_drop > simulate(slow).pressure_drop


def test_noise_is_reproducible_with_seed():
    assert simulate(baseline(), noise_std=0.5, seed=7).t_max == simulate(baseline(), noise_std=0.5, seed=7).t_max
