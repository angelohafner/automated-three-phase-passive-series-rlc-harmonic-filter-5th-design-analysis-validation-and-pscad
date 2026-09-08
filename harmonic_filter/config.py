"""Editable study configuration; all electrical quantities use SI units."""

from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
import math


@dataclass
class Harmonic:
    order: int
    rms_a: float
    angle_deg: float = 0.0
    enabled: bool = True


@dataclass
class SimulationCase:
    name: str
    enabled: bool = True
    filter_enabled: bool = True
    tuning_hz: float = 300.0
    quality_factor: float = 50.0
    grid_scale: float = 1.0


@dataclass
class StudyConfig:
    pscad_executable: Path = Path("C:/Program Files (x86)/PSCAD/5.1.0/bin/win64/pscad.exe")
    output_root: Path = Path("results")
    compiler: str = "GFortran 8.1 (64-bit)"
    frequency_hz: float = 60.0
    voltage_ll_rms_v: float = 480.0
    grid_resistance_ohm: float = 0.02
    grid_inductance_h: float = 0.0002
    linear_load_kw: float = 0.0
    filter_reactive_var: float = 30000.0
    nominal_tuning_hz: float = 300.0
    nominal_quality_factor: float = 50.0
    filter_resistance_ohm: float | None = None
    duration_s: float = 1.0
    time_step_us: float = 10.0
    sample_step_us: float = 20.0
    steady_start_s: float = 0.6
    analysis_cycles: int = 12
    max_harmonic: int = 25
    kcl_tolerance_pct: float = 0.1
    steady_tolerance_pct: float = 0.5
    theory_tolerance_pct: float = 1.0
    harmonics: list[Harmonic] = field(default_factory=lambda: [
        Harmonic(1, 100.0, 180.0),
        Harmonic(5, 20.0, 0.0),
        Harmonic(7, 14.0, 20.0),
        Harmonic(11, 9.0, -10.0),
        Harmonic(13, 7.0, 30.0),
    ])
    cases: list[SimulationCase] = field(default_factory=lambda: [
        SimulationCase("without_filter", filter_enabled=False),
        SimulationCase("tuned_5th"),
        SimulationCase("detuned_285hz", tuning_hz=285.0),
        SimulationCase("stiff_grid", grid_scale=0.5),
        SimulationCase("weak_grid", grid_scale=2.0),
        SimulationCase("low_quality", quality_factor=20.0),
    ])

    def validate(self):
        positive = [self.frequency_hz, self.voltage_ll_rms_v, self.grid_resistance_ohm,
                    self.grid_inductance_h, self.duration_s, self.time_step_us,
                    self.sample_step_us, self.filter_reactive_var,
                    self.nominal_quality_factor, self.kcl_tolerance_pct,
                    self.steady_tolerance_pct, self.theory_tolerance_pct]
        if not all(math.isfinite(value) and value > 0 for value in positive):
            raise ValueError("Positive finite system values are required")
        if self.linear_load_kw < 0 or not math.isfinite(self.linear_load_kw):
            raise ValueError("linear_load_kw must be finite and nonnegative")
        if self.nominal_tuning_hz <= self.frequency_hz:
            raise ValueError("Filter tuning must be above the fundamental")
        if self.max_harmonic < 25 or self.analysis_cycles < 1:
            raise ValueError("Analyze at least order 25 and one full cycle")
        if self.steady_start_s < 0 or self.duration_s - 2*self.analysis_cycles/self.frequency_hz < self.steady_start_s - 1e-9:
            raise ValueError("Two analysis windows must fit after steady_start_s")
        ratio = self.sample_step_us / self.time_step_us
        if ratio < 1 or not math.isclose(ratio, round(ratio), abs_tol=1e-9):
            raise ValueError("Sample step must be an integer multiple of integration step")
        if 1e6/self.sample_step_us <= 2*self.max_harmonic*self.frequency_hz:
            raise ValueError("Sample rate violates Nyquist for the requested harmonics")
        orders = [item.order for item in self.harmonics]
        if not orders or len(orders) != len(set(orders)):
            raise ValueError("Harmonic orders must be nonempty and unique")
        for item in self.harmonics:
            if not isinstance(item.order, int) or not 1 <= item.order <= self.max_harmonic:
                raise ValueError("Harmonic order must be an integer within the analysis range")
            if not math.isfinite(item.rms_a) or item.rms_a < 0 or not math.isfinite(item.angle_deg):
                raise ValueError("Harmonic RMS must be nonnegative and angles finite")
        names = [case.name for case in self.cases]
        if len(names) != len(set(names)):
            raise ValueError("Case names must be unique")
        for case in self.cases:
            if not case.name.isascii() or not case.name.isidentifier() or len(case.name) > 25:
                raise ValueError("Use ASCII case identifiers with at most 25 characters")
            if not all(math.isfinite(v) and v > 0 for v in [case.grid_scale, case.quality_factor, case.tuning_hz]):
                raise ValueError("Case parameters must be positive and finite")
            if case.tuning_hz <= self.frequency_hz:
                raise ValueError("Case tuning must be above the fundamental")

    def to_dict(self):
        values = asdict(self)
        values["pscad_executable"] = str(self.pscad_executable)
        values["output_root"] = str(self.output_root)
        return values

    @classmethod
    def from_json(cls, path):
        values = json.loads(Path(path).read_text(encoding="utf-8"))
        for name in ["pscad_executable", "output_root"]:
            if name in values:
                values[name] = Path(values[name])
        if "harmonics" in values:
            values["harmonics"] = [Harmonic(**item) for item in values["harmonics"]]
        if "cases" in values:
            values["cases"] = [SimulationCase(**item) for item in values["cases"]]
        config = cls(**values)
        config.validate()
        return config
