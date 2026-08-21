import math
import random

from app.domain.models import DesignParameters, SimulationResult


SIMULATOR_VERSION = "1.0.0"


def simulate(design: DesignParameters, noise_std: float = 0.0, seed: int = 42) -> SimulationResult:
    """Deterministic reduced-order heat-sink model. This is not CFD."""
    occupied_width = (
        design.fin_count * design.fin_thickness
        + (design.fin_count - 1) * design.fin_spacing
        + 4.0
    ) / 1000
    width = max(0.12, occupied_width)
    length = 0.09
    base_thickness = 0.004
    height = design.fin_height / 1000
    thickness = design.fin_thickness / 1000
    spacing = design.fin_spacing / 1000
    velocity = design.air_velocity

    aluminum_k = 201.0
    aluminum_density = 2700.0
    air_density = 1.184
    air_viscosity = 1.849e-5

    hydraulic_diameter = max(2 * spacing * height / (spacing + height), 1e-5)
    reynolds = air_density * velocity * hydraulic_diameter / air_viscosity
    h = 8.0 + 11.5 * math.sqrt(velocity) + 0.002 * math.sqrt(max(reynolds, 1.0))

    perimeter = 2 * (length + thickness)
    cross_section = max(length * thickness, 1e-9)
    m = math.sqrt(h * perimeter / (aluminum_k * cross_section))
    fin_efficiency = math.tanh(m * height) / max(m * height, 1e-9)

    fin_area = 2 * length * height + length * thickness
    exposed_base = max(width * length - design.fin_count * thickness * length, 0.0)
    effective_area = exposed_base + design.fin_count * fin_efficiency * fin_area
    convection_resistance = 1 / max(h * effective_area, 1e-9)
    spreading_and_contact = 0.22 + 0.10 * (20 / design.fin_count) ** 0.35
    base_resistance = base_thickness / (aluminum_k * width * length)
    thermal_resistance = spreading_and_contact + base_resistance + convection_resistance

    channel_ratio = length / hydraulic_diameter
    friction_factor = 64 / reynolds if reynolds < 2300 else 0.3164 / reynolds**0.25
    dynamic_pressure = 0.5 * air_density * velocity**2
    pressure_drop = dynamic_pressure * (friction_factor * channel_ratio + 1.7)

    volume = width * length * base_thickness + design.fin_count * thickness * height * length
    mass = volume * aluminum_density * 1000
    t_max = design.ambient_temperature + design.heat_load * thermal_resistance

    if noise_std:
        t_max += random.Random(seed).gauss(0.0, noise_std)

    return SimulationResult(
        t_max=round(t_max, 3),
        thermal_resistance=round(thermal_resistance, 5),
        pressure_drop=round(pressure_drop, 3),
        mass=round(mass, 2),
        fin_efficiency=round(fin_efficiency, 5),
        heat_transfer_coefficient=round(h, 3),
        simulator_version=SIMULATOR_VERSION,
    )
