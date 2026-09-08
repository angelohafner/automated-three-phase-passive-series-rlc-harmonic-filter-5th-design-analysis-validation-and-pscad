"""Comparative plots and a self-contained study report."""

from dataclasses import asdict
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .electrical import case_filter, impedances


COLORS = ["#222222", "#d04938", "#167b71", "#8463a6", "#376caa", "#a16e13"]


def save_figure(figure, path):
    figure.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(figure)


def plot_case(result, config, output_dir):
    case = result["case"]
    steady = result["steady"]
    last = steady[steady.time_s >= config.duration_s-3/config.frequency_hz]
    figure, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    for name, color in zip(["Iload", "Isystem", "Ifilter"], COLORS):
        axes[0].plot(last.time_s, last[name+"_A"], label=name, color=color, linewidth=1.2)
    axes[0].set(ylabel="Current (A)", title=f"{case.name} | phase A | {result['origin']}")
    axes[0].legend(ncol=3)
    for phase, color in zip("ABC", COLORS):
        axes[1].plot(last.time_s, last["Vpcc_"+phase], label=phase, color=color, linewidth=1)
    axes[1].set(ylabel="PCC voltage (V)", xlabel="Time (s)")
    axes[1].legend(ncol=3)
    for axis in axes:
        axis.grid(alpha=0.2)
    save_figure(figure, output_dir / "waveforms.png")
    table = result["table"].query("phase == 'A'")
    figure, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    for axis, name, color in zip(axes, ["Iload", "Isystem", "Ifilter"], COLORS):
        axis.bar(table.order, table[name+"_rms"], color=color, width=0.65)
        axis.set(ylabel="RMS (A)", title=name)
        axis.grid(axis="y", alpha=0.2)
    axes[-1].set(xlabel="Harmonic order", xticks=np.arange(1, config.max_harmonic+1))
    figure.suptitle(f"{case.name} | phase A | {result['origin']}")
    figure.tight_layout()
    save_figure(figure, output_dir / "current_spectra.png")
    figure, axis = plt.subplots(figsize=(11, 4))
    selected = table[table.order.isin([item.order for item in config.harmonics])]
    x = np.arange(len(selected))
    for index, (name, color) in enumerate(zip(["Iload", "Isystem", "Ifilter"], COLORS)):
        axis.bar(x+(index-1)*0.24, selected[name+"_rms"], 0.24, label=name, color=color)
    axis.set(xticks=x, xticklabels=selected.order, ylabel="RMS (A)", xlabel="Harmonic order",
             title=f"{case.name}: measured current magnitudes")
    axis.legend(ncol=3)
    axis.grid(axis="y", alpha=0.2)
    save_figure(figure, output_dir / "current_comparison.png")
    figure, axis = plt.subplots(figsize=(9, 4))
    for phase, color in zip("ABC", COLORS):
        residual = steady["Iload_"+phase]-steady["Isystem_"+phase]-steady["Ifilter_"+phase]-steady["Ilinear_"+phase]
        axis.plot(steady.time_s, residual, color=color, label=phase, linewidth=0.8)
    axis.set(xlabel="Time (s)", ylabel="KCL residual (A)", title=case.name)
    axis.legend()
    save_figure(figure, output_dir / "time_kcl.png")


def plot_comparison(results, config, output_dir):
    metrics = pd.concat([result["metrics"] for result in results], ignore_index=True)
    table = pd.concat([result["table"] for result in results], ignore_index=True)
    metrics.to_csv(output_dir / "comparison_metrics.csv", index=False)
    table.to_csv(output_dir / "comparison_harmonics.csv", index=False)
    figure, axes = plt.subplots(2, 2, figsize=(12, 7), sharex=True)
    names = [result["case"].name for result in results]
    for axis, channel in zip(axes.flat, ["Iload_A", "Isystem_A", "Ifilter_A", "Vpcc_A"]):
        values = [float(metrics[(metrics.case == name) & (metrics.channel == channel)].thd_pct.iloc[0]) for name in names]
        axis.bar(names, values, color=COLORS[:len(names)] if len(names) <= len(COLORS) else COLORS[1])
        axis.set(title=channel, ylabel="THD 2-25 (%)")
        axis.tick_params(axis="x", rotation=35)
        axis.grid(axis="y", alpha=0.2)
    figure.suptitle("Steady-state harmonic distortion | "+results[0]["origin"])
    figure.tight_layout()
    save_figure(figure, output_dir / "thd_comparison.png")
    frequency = np.linspace(1, max(1800, config.max_harmonic*config.frequency_hz), 12000)
    figure, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    frequency_table = {"frequency_hz": frequency}
    for index, result in enumerate(results):
        case = result["case"]
        grid, branch, equivalent = impedances(config, case, frequency)
        color = COLORS[index % len(COLORS)]
        if case.filter_enabled:
            axes[0].semilogy(frequency, abs(branch), label=case.name, color=color)
        axes[1].semilogy(frequency, abs(equivalent), label=case.name, color=color)
        for name, impedance in [("grid", grid), ("filter", branch), ("pcc", equivalent)]:
            frequency_table[f"{case.name}_{name}_ohm"] = abs(impedance)
            frequency_table[f"{case.name}_{name}_angle_deg"] = np.angle(impedance, deg=True)
    for axis in axes:
        axis.axvline(300, color="0.5", linewidth=0.8, linestyle="--")
        axis.set(ylabel="Magnitude (ohm)")
        axis.grid(alpha=0.2)
        if axis.get_legend_handles_labels()[0]:
            axis.legend(fontsize=8, ncol=3)
    axes[0].set_title("Series RLC filter impedance (calculated)")
    axes[1].set(title="Equivalent impedance seen from PCC (calculated)", xlabel="Frequency (Hz)")
    figure.tight_layout()
    save_figure(figure, output_dir / "impedance_scan.png")
    pd.DataFrame(frequency_table).to_csv(output_dir / "impedance_scan.csv", index=False)


def format_phasor(row, name):
    magnitude, angle = row[name+"_rms"], row[name+"_angle_deg"]
    return f"{magnitude:.4f} / {angle:.2f} deg" if np.isfinite(angle) else f"{magnitude:.4g} / n.a."


def write_report(results, config, output_dir):
    passed = all(bool(result["validation"].passed.all()) for result in results)
    lines = ["# Estudo de filtro harmonico passivo", "",
             f"Origem dos dados: **{results[0]['origin']}**.", "",
             f"Validacao automatica: **{'PASS' if passed else 'FAIL'}**.", "",
             "Fasores RMS com referencia em seno e angulos referidos a t=0.",
             "Correntes em A, tensoes em V. Iload entra no PCC; Isystem sai para a rede;",
             "Ifilter sai para o filtro. Ilinear sai para a carga linear opcional.", "",
             "KCL: Iload = Isystem + Ifilter + Ilinear. Com carga linear desativada, Ilinear=0.", "",
             "Percentuais abaixo sao razoes de modulos. Nao sao parcelas escalares aditivas;",
             "podem exceder 100%. As projecoes complexas constam dos CSV.", "",
             "Na fundamental, a fonte de tensao tambem alimenta o filtro: os percentuais",
             "nao representam exclusivamente a divisao da corrente injetada.", "",
             "A THD depende tambem do modulo da fundamental. Neste exemplo, a carga",
             "fundamental tem fator de potencia proximo da unidade e o filtro pode",
             "aumentar o RMS total da corrente da rede por sobrecompensacao capacitiva.",
             "Compare tambem os amperes harmonicos, nao apenas o percentual de THD.", "",
             "![THD](thd_comparison.png)", "", "![Impedancias](impedance_scan.png)", ""]
    for result in results:
        case = result["case"]
        branch = case_filter(config, case)
        lines.extend([f"## {case.name}", "",
                      f"Filtro {'conectado' if case.filter_enabled else 'isolado pelo disjuntor'}; "
                      f"R={branch.resistance_ohm:.8f} ohm, L={branch.inductance_h*1000:.6f} mH, "
                      f"C={branch.capacitance_f*1e6:.6f} uF; ft={branch.tuning_hz:.3f} Hz, Q={branch.quality_factor:.2f}.", "",
                      "| Ordem | Hz | Iload (A / deg) | Isystem (A / deg) | Ifilter (A / deg) | Filtro % | Sistema % | Erro KCL % |",
                      "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"])
        subset = result["table"].query("phase == 'A'")
        subset = subset[subset.order.isin([item.order for item in config.harmonics])]
        for _, row in subset.iterrows():
            lines.append(f"| {row.order} | {row.frequency_hz:.0f} | {format_phasor(row, 'Iload')} | "
                         f"{format_phasor(row, 'Isystem')} | {format_phasor(row, 'Ifilter')} | "
                         f"{row.filter_magnitude_pct:.2f} | {row.system_magnitude_pct:.2f} | {row.kcl_error_pct:.5g} |")
        lines.extend(["", "| Canal fase A | RMS total | Fundamental RMS | RMS h2-25 | THD % |", "| --- | ---: | ---: | ---: | ---: |"])
        for _, row in result["metrics"][result["metrics"].channel.str.endswith("_A")].iterrows():
            lines.append(f"| {row.channel} | {row.rms_total:.4f} | {row.fundamental_rms:.4f} | {row.harmonic_rms:.4f} | {row.thd_pct:.3f} |")
        failures = result["validation"][~result["validation"].passed]
        if len(failures):
            lines.extend(["", "Validacoes reprovadas: " + "; ".join(f"{row.check}/{row.channel}={row.value_pct:.4g}%"
                                                                  for _, row in failures.iterrows())])
        lines.extend(["", f"![Formas de onda]({case.name}/waveforms.png)", "",
                      f"![Espectros]({case.name}/current_spectra.png)", "",
                      f"![Comparacao]({case.name}/current_comparison.png)", "",
                      f"Dados completos: [{case.name}/harmonics.csv]({case.name}/harmonics.csv), "
                      f"[validacao]({case.name}/validation.csv).", ""])
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    (output_dir / "filter_designs.json").write_text(json.dumps({
        result["case"].name: asdict(case_filter(config, result["case"])) for result in results
    }, indent=2), encoding="utf-8")
    return passed
