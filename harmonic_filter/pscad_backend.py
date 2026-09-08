"""Guarded public-API PSCAD construction, parameterization and execution."""

from dataclasses import asdict
import importlib.metadata
import inspect
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

from .electrical import PHASES, case_filter, phase_angle


REQUIRED_DEFINITIONS = ["source_1", "src_ccin_1", "resistor", "inductor", "capacitor",
                        "ammeter", "voltmetergnd", "ground", "time-sig", "gain", "const",
                        "trig", "sumjct", "datalabel", "pgb", "breaker1"]


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def set_checked(component, **parameters):
    available = component.parameters()
    missing = set(parameters)-set(available)
    if missing:
        raise RuntimeError(f"Unsupported parameters {sorted(missing)} in {component}; available: {sorted(available)}")
    try:
        component.parameters(**parameters)
    except (ValueError, TypeError, RuntimeError) as error:
        raise RuntimeError(f"Cannot configure {component}: {parameters}: {error}") from error


class PscadSession:
    def __init__(self, config, output_dir, port=None):
        self.config, self.output_dir, self.port = config, Path(output_dir), port
        self.app = None
        self.owned = False

    def __enter__(self):
        import mhi.pscad
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if self.port is not None:
            self.app = mhi.pscad.connect(port=self.port, timeout=15)
            if any(item["name"] != "master" for item in self.app.projects()):
                raise RuntimeError("An attached instance must have an empty workspace; use a dedicated instance")
        else:
            if not self.config.pscad_executable.is_file():
                raise FileNotFoundError(self.config.pscad_executable)
            launch_parameters = inspect.signature(mhi.pscad.launch).parameters
            for parameter in ["version", "x64", "minimize", "silence", "timeout"]:
                if parameter not in launch_parameters:
                    raise RuntimeError(f"mhi.pscad lacks launch parameter {parameter}; installed {importlib.metadata.version('mhi.pscad')}")
            self.app = mhi.pscad.launch(version="5.1.0", x64=True, minimize=True,
                                        silence=True, timeout=60, exe=str(self.config.pscad_executable))
            self.owned = True
        try:
            if not str(self.app.version).startswith("5.1"):
                raise RuntimeError(f"Expected PSCAD 5.1, found {self.app.version}")
            compilers = list(self.app.setting_range("fortran_version"))
            if self.config.compiler not in compilers:
                raise RuntimeError(f"Compiler {self.config.compiler!r} unavailable; choose from {compilers}")
            self.app.settings(fortran_version=self.config.compiler)
            self.app.new_workspace(str((self.output_dir / "HarmonicFilter.pswx").resolve()))
            loaded = self.app.projects()
            if not any(item["name"] == "master" for item in loaded):
                raise RuntimeError("Master Library is not loaded")
            library = self.app.project("master")
            definitions = library.definitions()
            names = {str(name).split(":")[-1] for name in definitions}
            missing = set(REQUIRED_DEFINITIONS)-names
            if missing:
                raise RuntimeError(f"Master Library definitions missing: {sorted(missing)}")
            diagnostics = self.output_dir / "diagnostics"
            diagnostics.mkdir()
            write_json(diagnostics / "environment.json", {
                "pscad_version": str(self.app.version),
                "automation_version": importlib.metadata.version("mhi.pscad"),
                "executable": str(self.config.pscad_executable),
                "compiler": self.config.compiler, "available_compilers": compilers,
                "loaded_projects": loaded, "available_definitions": sorted(names),
            })
            for name in REQUIRED_DEFINITIONS:
                xml = library.definition(name).xml
                ET.ElementTree(xml).write(diagnostics / (name + ".xml"), encoding="utf-8", xml_declaration=True)
            print("PSCAD connected; real definitions exported", flush=True)
            return self
        except Exception:
            if self.owned:
                self.app.quit()
            raise

    def __exit__(self, exception_type, exception, traceback):
        try:
            if self.app:
                self.app.save_workspace()
        finally:
            if self.app and self.owned:
                self.app.quit()


class CircuitBuilder:
    def __init__(self, project, config):
        self.project, self.config = project, config
        self.canvas = project.canvas("Main")
        self.components = []
        self.connections = []
        self.port_cache = {}

    def add(self, definition, x, y, **parameters):
        component = self.canvas.create_component("master:" + definition, x, y)
        set_checked(component, **parameters)
        self.components.append(component)
        return component

    def port(self, component, name):
        if component.iid not in self.port_cache:
            self.port_cache[component.iid] = component.ports()
        ports = self.port_cache[component.iid]
        if name not in ports:
            raise RuntimeError(f"Missing active port {name!r} on {component}; active: {ports}")
        return ports[name]

    def point(self, component, name):
        port = self.port(component, name)
        return (port[0], port[1])

    def wire(self, first, second, *via):
        start, end = self.port(*first), self.port(*second)
        if (int(start[4]) == 3) != (int(end[4]) == 3):
            raise RuntimeError(f"Electrical/control port mismatch: {first}, {second}")
        if start[3] and end[3] and start[3] != end[3]:
            raise RuntimeError(f"Port dimension mismatch: {start}, {end}")
        points = [(start[0], start[1]), *via, (end[0], end[1])]
        self.draw_wire(*points)
        self.connections.append({"from_id": first[0].iid, "from_port": first[1],
                                 "to_id": second[0].iid, "to_port": second[1], "vertices": points})

    def draw_wire(self, *vertices):
        unique = [vertices[0]]
        for point in vertices[1:]:
            if point != unique[-1]:
                unique.append(point)
        if len(unique) > 1:
            for start, end in zip(unique, unique[1:]):
                if start[0] != end[0] and start[1] != end[1]:
                    raise RuntimeError(f"Explicit orthogonal routing required: {start}, {end}")
            self.canvas.create_wire(*unique)

    def label(self, component, port_name, signal_name):
        port = self.port(component, port_name)
        if int(port[4]) == 3:
            raise RuntimeError("A data label cannot be placed on an electrical node")
        return self.add("datalabel", port[0], port[1], Name=signal_name)

    def ground(self, component, port_name):
        x, y = self.point(component, port_name)
        ground = self.add("ground", x, y+2)
        self.wire((component, port_name), (ground, "A"))

    def reverse_horizontal(self, component, left, right):
        start, end = self.point(component, left), self.point(component, right)
        if start[1] != end[1]:
            raise RuntimeError(f"Expected horizontal component: {component}")
        component.rotate_180()
        self.port_cache.pop(component.iid, None)

    def sine(self, phase, harmonic, x, y):
        suffix = f"{phase}_{harmonic.order}"
        omega = self.add("gain", x, y, Name="Omega_"+suffix, G=2*np.pi*self.config.frequency_hz*harmonic.order)
        self.label(omega, "IN", "SimulationTime")
        shift = self.add("const", x+10, y+5, Name="Phase_"+suffix,
                         Value=np.deg2rad(phase_angle(harmonic.order, harmonic.angle_deg, phase)))
        summer = self.add("sumjct", x+18, y, Name="Angle_"+suffix, D=1, F=1)
        self.wire((omega, "OUT"), (summer, "IND"))
        port = self.point(summer, "INF")
        source = self.point(shift, "OUT")
        self.wire((shift, "OUT"), (summer, "INF"), (port[0], source[1]))
        sine = self.add("trig", x+26, y, Name="Sine_"+suffix, Type=1, Mode=0)
        amplitude = self.add("gain", x+34, y, Name="Amplitude_"+suffix,
                             G=np.sqrt(2)*harmonic.rms_a/1000 if harmonic.enabled else 0.0)
        self.wire((summer, "OUT"), (sine, "IN"))
        self.wire((sine, "OUT"), (amplitude, "IN"))
        self.label(amplitude, "OUT", "Harmonic_"+suffix)
        return "Harmonic_"+suffix

    def controls(self):
        time = self.add("time-sig", 10, 155)
        self.label(time, "OUT", "SimulationTime")
        switch = self.add("const", 25, 155, Name="FilterEnabled", Value=0)
        self.label(switch, "OUT", "FilterState")
        zero = self.add("const", 40, 155, Name="Zero", Value=0)
        self.label(zero, "OUT", "ZeroSignal")
        bank_width = max(55, 10*(len(self.config.harmonics)-1)+12)
        sum_y = max(115, 22+14*len(self.config.harmonics))
        for phase_index, phase in enumerate(PHASES):
            x = 110 + bank_width*phase_index
            self.canvas.create_annotation(x, 10, f"Phase {phase}: harmonic controls")
            signals = [self.sine(phase, harmonic, x, 22+14*index)
                       for index, harmonic in enumerate(self.config.harmonics)]
            previous = signals[0]
            for index, signal in enumerate(signals[1:]):
                summer = self.add("sumjct", x+10*index, sum_y, Name=f"Total_{phase}_{index}", D=1, F=1)
                self.label(summer, "IND", previous)
                self.label(summer, "INF", signal)
                previous = f"Partial_{phase}_{index}"
                self.label(summer, "OUT", previous)
            command = self.add("gain", x+15, sum_y+15, Name=f"Command_{phase}", G=1.0)
            self.label(command, "IN", previous)
            self.label(command, "OUT", f"CurrentCommand_{phase}")

    def network(self):
        for phase_index, phase in enumerate(PHASES):
            print(f"Building phase {phase}", flush=True)
            y = 22+40*phase_index
            self.canvas.create_annotation(10, y-8, f"Phase {phase}: PCC current splitting")
            source = self.add("source_1", 12, y, Name="GridSource_"+phase,
                              Type=6, Grnd=1, Spec=0, Cntrl=0, AC=1,
                              Vm=f"{self.config.voltage_ll_rms_v/np.sqrt(3)/1000:.12g} [kV]",
                              f=f"{self.config.frequency_hz} [Hz]", Ph=f"{PHASES[phase]} [deg]", Tc="0.02 [s]")
            self.reverse_horizontal(source, "NA", "NB")
            resistance = self.add("resistor", 22, y, Name="GridR_"+phase, R="0.02 [ohm]")
            inductance = self.add("inductor", 30, y, Name="GridL_"+phase, L="0.0002 [H]")
            meter = self.add("ammeter", 40, y, Name="Isystem_"+phase)
            self.reverse_horizontal(meter, "N1", "N2")
            voltage = self.add("voltmetergnd", 46, y, Name="Vpcc_"+phase)
            self.wire((source, "NA"), (resistance, "A"))
            self.wire((resistance, "B"), (inductance, "A"))
            self.wire((inductance, "B"), (meter, "N2"))
            self.wire((meter, "N1"), (voltage, "N1"))
            filter_meter = self.add("ammeter", 49, y+6, Name="Ifilter_"+phase)
            breaker = self.add("breaker1", 55, y+6, NAME="FilterState", RON="1e-6 [ohm]", ROFF="1e12 [ohm]")
            branch_r = self.add("resistor", 61, y+6, Name="FilterR_"+phase, R="0.03 [ohm]")
            branch_l = self.add("inductor", 68, y+6, Name="FilterL_"+phase, L="0.001 [H]")
            branch_c = self.add("capacitor", 75, y+6, Name="FilterC_"+phase, C="300 [uF]")
            self.wire((voltage, "N1"), (filter_meter, "N1"), (46, y+6))
            self.wire((filter_meter, "N2"), (breaker, "B"))
            self.wire((breaker, "A"), (branch_r, "A"))
            self.wire((branch_r, "B"), (branch_l, "A"))
            self.wire((branch_l, "B"), (branch_c, "A"))
            self.ground(branch_c, "B")
            if self.config.linear_load_kw > 0:
                linear_meter = self.add("ammeter", 49, y+14, Name="Ilinear_"+phase)
                linear_r = self.add("resistor", 61, y+14, Name="LinearR_"+phase,
                                    R=f"{self.config.voltage_ll_rms_v**2/(self.config.linear_load_kw*1000):.12g} [ohm]")
                self.wire((voltage, "N1"), (linear_meter, "N1"), (46, y+14))
                self.wire((linear_meter, "N2"), (linear_r, "A"))
                self.ground(linear_r, "B")
            injection = self.add("src_ccin_1", 73, y+22, Name="HarmonicSource_"+phase, Cntrl=1)
            injection_meter = self.add("ammeter", 63, y+22, Name="Iload_"+phase)
            self.reverse_horizontal(injection_meter, "N1", "N2")
            self.wire((injection, "A"), (injection_meter, "N1"))
            self.wire((injection_meter, "N2"), (voltage, "N1"), (46, y+22))
            self.ground(injection, "B")
            self.label(injection, "Mag", "CurrentCommand_"+phase)

    def measurements(self):
        for phase_index, phase in enumerate(PHASES):
            for index, quantity in enumerate(["Iload", "Isystem", "Ifilter", "Ilinear", "Vpcc"]):
                name = quantity+"_"+phase
                channel = self.add("pgb", 10+18*index, 175+10*phase_index, Name=name,
                                   UseSignalName=0, Scale=1000.0, Units="V" if quantity == "Vpcc" else "A")
                self.label(channel, "Signl", "ZeroSignal" if quantity == "Ilinear" and self.config.linear_load_kw == 0 else name)

    def build(self):
        set_checked(self.canvas, size="100X100", orient="LANDSCAPE")
        self.network()
        self.controls()
        self.measurements()
        self.project.save()

    def export_diagnostics(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        write_json(directory / "components.json", [{
            "iid": item.iid, "definition": item.defn_name, "location": list(item.location),
            "parameters": item.parameters(),
            "ports": {name: list(port) for name, port in (self.port_cache[item.iid] if item.iid in self.port_cache else item.ports()).items()},
        } for item in self.components])
        write_json(directory / "connections.json", self.connections)


def find_named(project, definition, name):
    matches = project.find_all("master:"+definition, name)
    if len(matches) != 1:
        raise RuntimeError(f"Template requires exactly one master:{definition} named {name!r}; found {len(matches)}")
    return matches[0]


def configure_case(project, config, case):
    branch = case_filter(config, case)
    set_checked(project, time_duration=config.duration_s, time_step=config.time_step_us,
                sample_step=config.sample_step_us, PlotType="OUT", StartType="STANDARD",
                SnapType="NONE", output_filename=case.name+".out")
    set_checked(find_named(project, "const", "FilterEnabled"), Value=0.0 if case.filter_enabled else 1.0)
    gain_names = {item.parameters().get("Name", "") for item in project.find_all("master:gain")}
    for phase in PHASES:
        set_checked(find_named(project, "source_1", "GridSource_"+phase),
                    Vm=f"{config.voltage_ll_rms_v/np.sqrt(3)/1000:.12g} [kV]",
                    f=f"{config.frequency_hz:.12g} [Hz]", Ph=f"{PHASES[phase]} [deg]")
        set_checked(find_named(project, "resistor", "GridR_"+phase), R=f"{case.grid_scale*config.grid_resistance_ohm:.12g} [ohm]")
        set_checked(find_named(project, "inductor", "GridL_"+phase), L=f"{case.grid_scale*config.grid_inductance_h:.12g} [H]")
        set_checked(find_named(project, "resistor", "FilterR_"+phase), R=f"{branch.resistance_ohm:.12g} [ohm]")
        set_checked(find_named(project, "inductor", "FilterL_"+phase), L=f"{branch.inductance_h:.12g} [H]")
        set_checked(find_named(project, "capacitor", "FilterC_"+phase), C=f"{branch.capacitance_f*1e6:.12g} [uF]")
        if config.linear_load_kw > 0:
            set_checked(find_named(project, "resistor", "LinearR_"+phase),
                        R=f"{config.voltage_ll_rms_v**2/(config.linear_load_kw*1000):.12g} [ohm]")
        elif project.find_all("master:resistor", "LinearR_"+phase):
            raise RuntimeError("Template has a linear load but configuration disables it; use a matching template")
        for harmonic in config.harmonics:
            suffix = f"{phase}_{harmonic.order}"
            set_checked(find_named(project, "gain", "Omega_"+suffix), G=2*np.pi*config.frequency_hz*harmonic.order)
            set_checked(find_named(project, "const", "Phase_"+suffix), Value=np.deg2rad(phase_angle(harmonic.order, harmonic.angle_deg, phase)))
            set_checked(find_named(project, "gain", "Amplitude_"+suffix), G=np.sqrt(2)*harmonic.rms_a/1000 if harmonic.enabled else 0.0)
        expected = {f"Amplitude_{phase}_{harmonic.order}" for harmonic in config.harmonics}
        actual = {name for name in gain_names if str(name).startswith("Amplitude_"+phase+"_")}
        if actual != expected:
            raise RuntimeError(f"Template harmonic rows differ from configuration: {actual ^ expected}")
    project.save()
    return branch


def read_pscad_output(raw_directory, basename):
    """Read scalar OUT channel indices from INF; never infer signal column order."""
    raw_directory = Path(raw_directory)
    info = raw_directory / (basename+".inf")
    if not info.is_file():
        raise FileNotFoundError(f"Missing PSCAD channel metadata: {info}")
    channels = {}
    for line in info.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        match = re.search(r'PGB\((\d+)\).*?Desc="([^"]+)"', line, re.IGNORECASE)
        if match:
            index, name = int(match.group(1)), match.group(2)
            if index in channels or name in channels.values():
                raise ValueError("Duplicate output channel index or name")
            channels[index] = name
    if not channels:
        raise ValueError(f"No scalar PGB metadata found in {info}")
    blocks, output = {}, {}
    for index, name in sorted(channels.items()):
        block_index, column = (index-1)//10+1, (index-1)%10+1
        if block_index not in blocks:
            path = raw_directory / f"{basename}_{block_index:02d}.out"
            data = np.loadtxt(path, skiprows=1, ndmin=2)
            if not np.all(np.isfinite(data)):
                raise ValueError(f"Nonfinite simulation values in {path}")
            if "time_s" not in output:
                output["time_s"] = data[:, 0]
            elif len(data) != len(output["time_s"]) or not np.allclose(data[:, 0], output["time_s"], atol=1e-10, rtol=0):
                raise ValueError("Time columns differ between output blocks")
            blocks[block_index] = data
        if column >= blocks[block_index].shape[1]:
            raise ValueError(f"Output column missing for {name}")
        output[name] = blocks[block_index][:, column]
    return pd.DataFrame(output)


def run_project(project, config, case, case_directory):
    case_directory.mkdir(parents=True, exist_ok=True)
    print(f"Building/running {case.name}", flush=True)
    project.run()
    messages = project.messages()
    write_json(case_directory / "build_messages.json", [message._asdict() if hasattr(message, "_asdict") else str(message) for message in messages])
    errors = [message for message in messages if "error" in str(getattr(message, "status", "")).lower()]
    if errors:
        raise RuntimeError(f"PSCAD errors in {case.name}: {errors}")
    temporary = Path(project.temp_folder)
    raw = case_directory / "raw"
    raw.mkdir()
    for pattern in [case.name+"*.out", case.name+".inf", "*.log", "*.map"]:
        for source in temporary.glob(pattern):
            shutil.copy2(source, raw / source.name)
    frame = read_pscad_output(raw, case.name)
    if frame.time_s.iloc[-1] < config.duration_s-2*config.sample_step_us*1e-6:
        raise RuntimeError(f"PSCAD did not complete {case.name}; inspect build_messages.json")
    frame.to_csv(case_directory / "waveforms.csv", index=False)
    return frame
