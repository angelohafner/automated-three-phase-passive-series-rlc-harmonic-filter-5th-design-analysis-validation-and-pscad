"""Run a half-step PSCAD case and compare complex phasors to a completed study."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path)
    parser.add_argument("--case", default="tuned_5th")
    args = parser.parse_args()
    study = args.study.resolve()
    config = json.loads((study / "config.json").read_text(encoding="utf-8"))
    config["time_step_us"] /= 2
    config["sample_step_us"] = config["time_step_us"]
    selected = next(case for case in config["cases"] if case["name"] == args.case)
    config["cases"] = [selected]
    target = study / ("convergence_"+args.case)
    configuration = study / ("convergence_"+args.case+".json")
    if target.exists():
        raise FileExistsError(f"Convergence output already exists: {target}")
    configuration.write_text(json.dumps(config, indent=2), encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, "-u", str(root / "run_study.py"), "--config", str(configuration),
                    "--template", str(study / "projects" / "HarmonicBase.pscx"),
                    "--output", str(target)], cwd=root, check=True)
    coarse = pd.read_csv(study / args.case / "harmonics.csv").set_index(["phase", "order"])
    fine = pd.read_csv(target / args.case / "harmonics.csv").set_index(["phase", "order"])
    rows = []
    for index in coarse.index:
        for channel in ["Iload", "Isystem", "Ifilter", "Ilinear", "Vpcc"]:
            first = complex(coarse.loc[index, channel+"_real"], coarse.loc[index, channel+"_imag"])
            second = complex(fine.loc[index, channel+"_real"], fine.loc[index, channel+"_imag"])
            if abs(second) > 1e-5:
                rows.append({"phase": index[0], "order": index[1], "channel": channel,
                             "complex_difference_pct": 100*abs(first-second)/abs(second),
                             "coarse_rms": abs(first), "fine_rms": abs(second),
                             "angle_difference_deg": np.angle(first/second, deg=True)})
    comparison = pd.DataFrame(rows)
    comparison.to_csv(study / "convergence.csv", index=False)
    maximum = float(comparison.complex_difference_pct.max())
    result = {"case": args.case, "coarse_step_us": config["time_step_us"]*2,
              "fine_step_us": config["time_step_us"], "fine_sample_step_us": config["sample_step_us"],
              "max_complex_difference_pct": maximum, "limit_pct": config["theory_tolerance_pct"],
              "passed": maximum <= config["theory_tolerance_pct"]}
    (study / "convergence.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
