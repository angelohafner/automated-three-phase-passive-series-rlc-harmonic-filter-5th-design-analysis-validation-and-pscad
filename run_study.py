"""Build and run the PSCAD harmonic filter study or generate an analytic reference."""

import argparse
from datetime import datetime
import importlib.metadata
import json
from pathlib import Path
import shutil
import traceback
import pandas as pd

from harmonic_filter.config import StudyConfig
from harmonic_filter.analysis import analyze_case
from harmonic_filter.electrical import synthesize_reference
from harmonic_filter.reporting import plot_case, plot_comparison, write_report
from harmonic_filter.pscad_backend import PscadSession, CircuitBuilder, configure_case, run_project, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--write-config", type=Path)
    parser.add_argument("--analytical", action="store_true", help="Use analytic samples, not PSCAD simulation")
    parser.add_argument("--case", action="append", help="Run selected enabled case; repeat for multiple cases")
    parser.add_argument("--template", type=Path, help="Use a matching existing base PSCX with named components")
    parser.add_argument("--port", type=int, help="Attach to a dedicated empty PSCAD automation instance")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--analyze-output", type=Path, help="Reanalyze a completed run using its saved configuration and waveforms")
    args = parser.parse_args()
    if args.analyze_output:
        directory = args.analyze_output.resolve()
        config = StudyConfig.from_json(directory / "config.json")
        provenance = json.loads((directory / "provenance.json").read_text(encoding="utf-8"))
        results = []
        for case in config.cases:
            if case.name in provenance["selected_cases"]:
                target = directory / case.name
                result = analyze_case(pd.read_csv(target / "waveforms.csv"), config, case, target, provenance["origin"])
                plot_case(result, config, target)
                results.append(result)
        plot_comparison(results, config, directory)
        passed = write_report(results, config, directory)
        write_json(directory / "status.json", {"origin": provenance["origin"], "completed": True,
                   "validation_passed": passed, "cases": provenance["selected_cases"],
                   "reanalyzed": datetime.now().isoformat()})
        print(f"Reanalysis {'PASS' if passed else 'FAIL'}: {directory / 'report.md'}")
        return 0 if passed else 2
    config = StudyConfig.from_json(args.config) if args.config else StudyConfig()
    if args.write_config:
        config.validate()
        write_json(args.write_config, config.to_dict())
        print(f"Configuration: {args.write_config.resolve()}")
        return 0
    config.validate()
    if args.analytical and args.template:
        parser.error("--template requires PSCAD mode")
    selected = [case for case in config.cases if case.enabled and (not args.case or case.name in args.case)]
    if not selected or (args.case and set(args.case)-{case.name for case in selected}):
        parser.error("Requested cases must exist and be enabled")
    origin = "ANALYTICAL_REFERENCE" if args.analytical else "PSCAD_EMTDC"
    directory = args.output or config.output_root / (datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ("_analytic" if args.analytical else "_pscad"))
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "config.json", config.to_dict())
    write_json(directory / "provenance.json", {"origin": origin, "created": datetime.now().isoformat(),
               "packages": {name: importlib.metadata.version(name) for name in ["numpy", "pandas", "matplotlib"]},
               "selected_cases": [case.name for case in selected],
               "template": str(args.template.resolve()) if args.template else None})
    print(f"Output: {directory}", flush=True)
    results = []

    def process(case, frame):
        target = directory / case.name
        target.mkdir(exist_ok=True)
        if args.analytical:
            frame.to_csv(target / "waveforms.csv", index=False)
        result = analyze_case(frame, config, case, target, origin)
        plot_case(result, config, target)
        results.append(result)
        print(f"{case.name}: validation {'PASS' if result['validation'].passed.all() else 'FAIL'}", flush=True)

    try:
        if args.analytical:
            for case in selected:
                process(case, synthesize_reference(config, case))
        else:
            with PscadSession(config, directory, args.port) as session:
                project_directory = directory / "projects"
                project_directory.mkdir()
                base_path = project_directory / "HarmonicBase.pscx"
                if args.template:
                    if not args.template.is_file():
                        raise FileNotFoundError(args.template)
                    copied = project_directory / args.template.name
                    shutil.copy2(args.template, copied)
                    session.app.load(str(copied))
                    base = session.app.project(copied.stem)
                    if copied != base_path:
                        base = base.save_as(str(base_path))
                else:
                    base = session.app.create_case(str(base_path))
                    builder = CircuitBuilder(base, config)
                    builder.build()
                    builder.export_diagnostics(directory / "diagnostics" / "base")
                configure_case(base, config, selected[0])
                for index, case in enumerate(selected):
                    if index:
                        session.app.load(str(base_path))
                        base = session.app.project("HarmonicBase")
                    project = base.save_as(str(project_directory / (case.name+".pscx")))
                    branch = configure_case(project, config, case)
                    session.app.save_workspace()
                    frame = run_project(project, config, case, directory / case.name)
                    process(case, frame)
        plot_comparison(results, config, directory)
        passed = write_report(results, config, directory)
        write_json(directory / "status.json", {"origin": origin, "completed": True,
                   "validation_passed": passed, "cases": [result["case"].name for result in results]})
        print(f"Report: {directory / 'report.md'}", flush=True)
        return 0 if passed else 2
    except Exception:
        (directory / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
        write_json(directory / "status.json", {"origin": origin, "completed": False, "validation_passed": False})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
