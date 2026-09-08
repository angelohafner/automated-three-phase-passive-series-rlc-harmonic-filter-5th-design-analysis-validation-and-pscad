"""Steady-state RMS phasors, THD, complex KCL and reference comparisons."""

import numpy as np
import pandas as pd

from .electrical import PHASES, solve_phasors, sequence_name


def fit_phasors(time, signals, fundamental_hz, max_harmonic):
    time, signals = np.asarray(time), np.asarray(signals)
    if time.ndim != 1 or len(time) != len(signals) or len(time) <= 2*max_harmonic+1:
        raise ValueError("Insufficient or incompatible time and signal samples")
    if not np.all(np.isfinite(signals)) or not np.all(np.isfinite(time)) or np.any(np.diff(time) <= 0):
        raise ValueError("Samples must be finite and time strictly increasing")
    angle = 2*np.pi*fundamental_hz*time[:, None]*np.arange(1, max_harmonic+1)
    basis = np.column_stack([np.ones(len(time)), np.sin(angle), np.cos(angle)])
    coefficients, _, rank, _ = np.linalg.lstsq(basis, signals, rcond=None)
    if rank != 2*max_harmonic+1:
        raise ValueError("Harmonic basis is rank deficient; check sampling")
    phasors = np.zeros((max_harmonic+1, *signals.shape[1:]), dtype=complex)
    phasors[1:] = (coefficients[1:max_harmonic+1] + 1j*coefficients[max_harmonic+1:])/np.sqrt(2)
    return phasors, coefficients[0]


def thd_percent(phasors, floor=1e-8):
    fundamental = abs(phasors[1])
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(fundamental > floor, 100*np.sqrt(np.sum(abs(phasors[2:])**2, axis=0))/fundamental, np.nan)


def current_balance(load, system, filtered, linear=0):
    return load-system-filtered-linear


def select_windows(frame, config):
    time = frame["time_s"].to_numpy()
    step = np.median(np.diff(time))
    if np.max(abs(np.diff(time)-step)) > max(1e-9, step*0.002):
        raise ValueError("Nonuniform samples: inspect raw output before RMS analysis")
    if time[-1] < config.duration_s - 1.5*step:
        raise ValueError("Simulation output ended before the requested duration")
    period = config.analysis_cycles/config.frequency_hz
    end = config.duration_s
    start = end-period
    if start-period < config.steady_start_s-1e-9:
        raise ValueError("Not enough post-transient data for two steady-state windows")
    windows = []
    for left, right in [(start, end), (start-period, start)]:
        window = frame[(time >= left-1e-9) & (time < right-1e-9)]
        if len(window) < period/step-2:
            raise ValueError("Incomplete analysis window")
        windows.append(window)
    return windows


def analyze_case(frame, config, case, output_dir, origin):
    output_dir.mkdir(parents=True, exist_ok=True)
    channels = [f"{name}_{phase}" for phase in PHASES
                for name in ["Iload", "Isystem", "Ifilter", "Ilinear", "Vpcc"]]
    missing = set(channels)-set(frame.columns)
    if missing:
        raise ValueError(f"Missing independent measurement channels: {sorted(missing)}")
    steady, previous = select_windows(frame, config)
    phasors, dc = fit_phasors(steady.time_s, steady[channels].to_numpy(), config.frequency_hz, config.max_harmonic)
    earlier, earlier_dc = fit_phasors(previous.time_s, previous[channels].to_numpy(), config.frequency_hz, config.max_harmonic)
    reference = solve_phasors(config, case)
    phasor_map = dict(zip(channels, phasors.T))
    rms = np.sqrt(np.mean(steady[channels].to_numpy()**2, axis=0))
    thd = thd_percent(phasors)
    angle = 2*np.pi*config.frequency_hz*steady.time_s.to_numpy()[:, None]*np.arange(1, config.max_harmonic+1)
    reconstructed = dc + np.sqrt(2)*(np.sin(angle) @ phasors[1:].real + np.cos(angle) @ phasors[1:].imag)
    residual_rms = np.sqrt(np.mean((steady[channels].to_numpy()-reconstructed)**2, axis=0))
    statistics, table, validation = [], [], []
    for index, name in enumerate(channels):
        scale = max(rms[index], 1.0)
        stability = 100*max(np.max(abs(phasors[:, index]-earlier[:, index])), abs(dc[index]-earlier_dc[index]))/scale
        theory_error = 100*np.max(abs(phasors[:, index]-reference[name]))/max(np.max(abs(reference[name])), 1.0)
        dc_percent = 100*abs(dc[index])/max(np.max(abs(reference[name])), 1.0)
        residual_percent = 100*residual_rms[index]/max(np.max(abs(reference[name])), 1.0)
        statistics.append({"case": case.name, "origin": origin, "channel": name,
                           "rms_total": rms[index], "dc": dc[index],
                           "fundamental_rms": abs(phasors[1, index]),
                           "harmonic_rms": float(np.sqrt(np.sum(abs(phasors[2:, index])**2))),
                           "fundamental_angle_deg": np.angle(phasors[1, index], deg=True),
                           "thd_pct": thd[index], "steady_change_pct": stability,
                           "theory_error_pct": theory_error, "dc_pct": dc_percent,
                           "unmodeled_rms": residual_rms[index], "unmodeled_pct": residual_percent})
        validation.extend([
            {"check": "steady_state", "channel": name, "value_pct": stability,
             "limit_pct": config.steady_tolerance_pct, "passed": stability <= config.steady_tolerance_pct},
            {"check": "analytic_phasors", "channel": name, "value_pct": theory_error,
             "limit_pct": config.theory_tolerance_pct, "passed": theory_error <= config.theory_tolerance_pct},
            {"check": "unexpected_dc", "channel": name, "value_pct": dc_percent,
             "limit_pct": config.theory_tolerance_pct, "passed": dc_percent <= config.theory_tolerance_pct},
            {"check": "unmodeled_waveform", "channel": name, "value_pct": residual_percent,
             "limit_pct": config.theory_tolerance_pct, "passed": residual_percent <= config.theory_tolerance_pct},
        ])
        for order in range(1, config.max_harmonic+1):
            if abs(reference[name][order]) > 1e-5:
                relative_error = 100*abs(phasors[order, index]-reference[name][order])/abs(reference[name][order])
                validation.append({"check": "analytic_harmonic", "channel": f"{name}_h{order}",
                                   "value_pct": relative_error, "limit_pct": config.theory_tolerance_pct,
                                   "passed": relative_error <= config.theory_tolerance_pct})
    for phase in PHASES:
        load, system, filtered, linear = [phasor_map[f"{name}_{phase}"] for name in ["Iload", "Isystem", "Ifilter", "Ilinear"]]
        residual = current_balance(load, system, filtered, linear)
        time_residual = current_balance(*[steady[f"{name}_{phase}"].to_numpy() for name in ["Iload", "Isystem", "Ifilter", "Ilinear"]])
        base = max(float(np.sqrt(np.mean(steady[f"Iload_{phase}"].to_numpy()**2))), 1.0)
        for label, value in [("time_kcl_rms", np.sqrt(np.mean(time_residual**2))),
                             ("time_kcl_peak", np.max(abs(time_residual))),
                             ("harmonic_kcl", np.max(abs(residual)))]:
            percent = 100*float(value)/base
            validation.append({"check": label, "channel": phase, "value_pct": percent,
                               "limit_pct": config.kcl_tolerance_pct, "passed": percent <= config.kcl_tolerance_pct})
        for order in range(1, config.max_harmonic+1):
            injected = abs(load[order])
            present = injected > max(1e-5, abs(load[1])*1e-6)
            row = {"case": case.name, "origin": origin, "phase": phase, "order": order,
                   "frequency_hz": order*config.frequency_hz, "sequence": sequence_name(order)}
            for name in ["Iload", "Isystem", "Ifilter", "Ilinear", "Vpcc"]:
                value = phasor_map[f"{name}_{phase}"][order]
                row.update({name+"_rms": abs(value), name+"_angle_deg": np.angle(value, deg=True) if abs(value) > 1e-5 else np.nan,
                            name+"_real": value.real, name+"_imag": value.imag,
                            name+"_theory_error_pct": 100*abs(value-reference[f"{name}_{phase}"][order])/abs(reference[f"{name}_{phase}"][order])
                            if abs(reference[f"{name}_{phase}"][order]) > 1e-5 else np.nan})
            row.update({"filter_magnitude_pct": 100*abs(filtered[order])/injected if present else np.nan,
                        "system_magnitude_pct": 100*abs(system[order])/injected if present else np.nan,
                        "filter_projection_pct": 100*(filtered[order]/load[order]).real if present else np.nan,
                        "system_projection_pct": 100*(system[order]/load[order]).real if present else np.nan,
                        "linear_projection_pct": 100*(linear[order]/load[order]).real if present else np.nan,
                        "kcl_error_a": abs(residual[order]),
                        "kcl_error_pct": 100*abs(residual[order])/injected if present else np.nan,
                        "kcl_real_a": residual[order].real, "kcl_imag_a": residual[order].imag})
            table.append(row)
            if present:
                validation.append({"check": "harmonic_kcl_relative", "channel": f"{phase}_h{order}",
                                   "value_pct": row["kcl_error_pct"], "limit_pct": config.kcl_tolerance_pct,
                                   "passed": row["kcl_error_pct"] <= config.kcl_tolerance_pct})
    rotation = np.exp(2j*np.pi/3)
    sequences = []
    for name in ["Iload", "Isystem", "Ifilter", "Ilinear", "Vpcc"]:
        phase_a, phase_b, phase_c = [phasor_map[f"{name}_{phase}"] for phase in PHASES]
        components = {"zero": (phase_a+phase_b+phase_c)/3,
                      "positive": (phase_a+rotation*phase_b+rotation**2*phase_c)/3,
                      "negative": (phase_a+rotation**2*phase_b+rotation*phase_c)/3}
        for order in range(1, config.max_harmonic+1):
            expected = sequence_name(order)
            desired = abs(components[expected][order])
            unwanted = np.sqrt(sum(abs(value[order])**2 for key, value in components.items() if key != expected))
            percent = 100*unwanted/desired if desired > 1e-5 else np.nan
            sequences.append({"channel": name, "order": order, "expected_sequence": expected,
                              **{key+"_rms": abs(value[order]) for key, value in components.items()},
                              "unwanted_sequence_pct": percent})
            if np.isfinite(percent):
                validation.append({"check": "harmonic_sequence", "channel": f"{name}_h{order}",
                                   "value_pct": percent, "limit_pct": config.theory_tolerance_pct,
                                   "passed": percent <= config.theory_tolerance_pct})
    table, statistics, validation = pd.DataFrame(table), pd.DataFrame(statistics), pd.DataFrame(validation)
    table.to_csv(output_dir / "harmonics.csv", index=False)
    statistics.to_csv(output_dir / "metrics.csv", index=False)
    validation.to_csv(output_dir / "validation.csv", index=False)
    pd.DataFrame(sequences).to_csv(output_dir / "sequences.csv", index=False)
    return {"case": case, "table": table, "metrics": statistics, "validation": validation,
            "steady": steady, "phasors": phasor_map, "origin": origin}
