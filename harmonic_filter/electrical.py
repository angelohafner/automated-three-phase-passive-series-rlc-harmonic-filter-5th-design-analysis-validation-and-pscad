"""Filter sizing and a frequency-domain reference independent of PSCAD."""

from dataclasses import dataclass
import math
import numpy as np


PHASES = {"A": 0.0, "B": -120.0, "C": 120.0}


def phase_angle(order, angle_deg, phase):
    return (angle_deg + order * PHASES[phase] + 180) % 360 - 180


def sequence_name(order):
    return ("zero", "positive", "negative")[order % 3]


@dataclass(frozen=True)
class FilterBranch:
    resistance_ohm: float
    inductance_h: float
    capacitance_f: float

    def impedance(self, frequency_hz):
        frequency = np.asarray(frequency_hz)
        if np.any(frequency <= 0):
            raise ValueError("Impedance frequency must be positive")
        omega = 2 * np.pi * frequency
        return self.resistance_ohm + 1j * (omega * self.inductance_h - 1/(omega*self.capacitance_f))

    @property
    def tuning_hz(self):
        return 1/(2*np.pi*np.sqrt(self.inductance_h*self.capacitance_f))

    @property
    def quality_factor(self):
        return 2*np.pi*self.tuning_hz*self.inductance_h/self.resistance_ohm


def design_filter(voltage_ll_rms_v, reactive_var, fundamental_hz, tuning_hz,
                  quality_factor=50.0, resistance_ohm=None):
    values = [voltage_ll_rms_v, reactive_var, fundamental_hz, tuning_hz, quality_factor]
    if not all(math.isfinite(value) and value > 0 for value in values) or tuning_hz <= fundamental_hz:
        raise ValueError("Positive values and tuning above the fundamental are required")
    omega = 2*np.pi*fundamental_hz
    tuned_omega = 2*np.pi*tuning_hz
    factor = tuned_omega/omega - omega/tuned_omega
    if resistance_ohm is None:
        tuned_reactance = voltage_ll_rms_v**2 * factor / (reactive_var*(factor**2+quality_factor**-2))
        resistance = tuned_reactance/quality_factor
    else:
        resistance = resistance_ohm
        discriminant = voltage_ll_rms_v**4 - 4*reactive_var**2*resistance**2
        if not math.isfinite(resistance) or resistance <= 0 or discriminant < 0:
            raise ValueError("Specified resistance cannot supply the requested reactive power")
        net_reactance = (voltage_ll_rms_v**2+np.sqrt(discriminant))/(2*reactive_var)
        tuned_reactance = net_reactance/factor
    return FilterBranch(resistance, tuned_reactance/tuned_omega, 1/(tuned_omega*tuned_reactance))


def case_filter(config, case):
    nominal = design_filter(config.voltage_ll_rms_v, config.filter_reactive_var,
                            config.frequency_hz, config.nominal_tuning_hz,
                            config.nominal_quality_factor, config.filter_resistance_ohm)
    omega = 2*np.pi*case.tuning_hz
    inductance = 1/(omega**2*nominal.capacitance_f)
    resistance = config.filter_resistance_ohm
    if resistance is None:
        resistance = omega*inductance/case.quality_factor
    return FilterBranch(resistance, inductance, nominal.capacitance_f)


def impedances(config, case, frequency_hz):
    grid = case.grid_scale*(config.grid_resistance_ohm + 2j*np.pi*np.asarray(frequency_hz)*config.grid_inductance_h)
    branch = case_filter(config, case).impedance(frequency_hz)
    linear_admittance = config.linear_load_kw*1000/config.voltage_ll_rms_v**2
    equivalent = 1/(1/grid + (1/branch if case.filter_enabled else 0) + linear_admittance)
    return grid, branch, equivalent


def solve_phasors(config, case):
    """Return SI RMS sine-reference phasors indexed from zero to max_harmonic."""
    frequency = config.frequency_hz*np.arange(1, config.max_harmonic+1)
    grid, branch, equivalent = impedances(config, case, frequency)
    linear_admittance = config.linear_load_kw*1000/config.voltage_ll_rms_v**2
    results = {}
    for phase in PHASES:
        injection = np.zeros(config.max_harmonic+1, dtype=complex)
        for item in config.harmonics:
            if item.enabled:
                injection[item.order] = item.rms_a*np.exp(1j*np.deg2rad(phase_angle(item.order, item.angle_deg, phase)))
        source = np.zeros(config.max_harmonic+1, dtype=complex)
        source[1] = config.voltage_ll_rms_v/np.sqrt(3)*np.exp(1j*np.deg2rad(PHASES[phase]))
        voltage = np.zeros_like(injection)
        voltage[1:] = equivalent*(injection[1:] + source[1:]/grid)
        system = np.zeros_like(injection)
        system[1:] = (voltage[1:]-source[1:])/grid
        filtered = np.zeros_like(injection)
        if case.filter_enabled:
            filtered[1:] = voltage[1:]/branch
        for name, value in [("Iload", injection), ("Isystem", system),
                            ("Ifilter", filtered), ("Ilinear", linear_admittance*voltage),
                            ("Vpcc", voltage)]:
            results[f"{name}_{phase}"] = value
    return results


def synthesize_reference(config, case):
    """Generate analytic steady-state samples, explicitly separate from PSCAD data."""
    import pandas as pd
    time = np.arange(round(config.duration_s*1e6/config.sample_step_us)+1)*config.sample_step_us*1e-6
    output = {"time_s": time}
    for name, phasors in solve_phasors(config, case).items():
        signal = np.zeros_like(time)
        for order in np.flatnonzero(abs(phasors) > 1e-12):
            signal += np.sqrt(2)*abs(phasors[order])*np.sin(2*np.pi*order*config.frequency_hz*time+np.angle(phasors[order]))
        output[name] = signal
    return pd.DataFrame(output)
