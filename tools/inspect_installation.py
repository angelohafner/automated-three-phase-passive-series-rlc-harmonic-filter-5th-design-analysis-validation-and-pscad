"""Inspect local PSCAD definitions and optionally probe the public live API."""

import argparse
import importlib.metadata
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def inspect_library(library_path):
    root = ET.parse(library_path).getroot()
    definitions = {}
    for definition in root.iter("Definition"):
        parameters = []
        for parameter in definition.findall("./form/category/parameter"):
            parameters.append({
                **parameter.attrib,
                "default": parameter.findtext("value"),
                "choices": [item.text for item in parameter.findall("choice")],
            })
        definitions[definition.get("name")] = {
            "metadata": {item.get("name"): item.get("value")
                         for item in definition.findall("./paramlist/param")},
            "parameters": parameters,
            "ports": ([{**port.attrib, "condition": port.text}
                       for port in definition.findall(".//svg//port")]
                      or [{**port.attrib,
                           **{item.get("name"): item.get("value") for item in port.findall("./paramlist/param")}}
                          for port in definition.findall("./graphics/Port")]),
            "scripts": {segment.get("name"): segment.text
                        for segment in definition.findall("./script/segment")},
        }
    return definitions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("results/inspection"))
    parser.add_argument("--installation", type=Path,
                        default=Path("C:/Program Files (x86)/PSCAD/5.1.0"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    definitions = inspect_library(args.installation / "master.pslx")
    (args.output / "master_catalog.json").write_text(
        json.dumps(definitions, indent=2), encoding="utf-8")
    selected = ["src_ccin_1", "source_1", "time-sig", "gain", "const",
                "trig", "sumjct", "ammeter", "voltmetergnd", "ground", "pgb"]
    for name in selected:
        definition = definitions[name]
        print(name, [(p["name"], p["default"], p.get("unit"), p["choices"])
                     for p in definition["parameters"]], flush=True)
    if args.live:
        import mhi.pscad
        app = mhi.pscad.launch(version="5.1.0", x64=True, minimize=True,
                               silence=True, timeout=60)
        try:
            print("CONNECTED", app.version, flush=True)
            print("PROJECTS", app.projects(), flush=True)
            print("COMPILERS", app.setting_range("fortran_version"), flush=True)
            print("COMPILER", app.settings().get("fortran_version"), flush=True)
            try:
                print("CERTIFICATE PRESENT", app.get_current_certificate() is not None, flush=True)
            except RuntimeError as error:
                print("CERTIFICATE QUERY", str(error), flush=True)
            app.new_workspace(str((args.output / "Inspection.pswx").resolve()))
            project = app.create_case(str((args.output / "Inspection.pscx").resolve()))
            print("PROJECT PARAMETERS", project.parameters(), flush=True)
            canvas = project.canvas("Main")
            live = {}
            for index, name in enumerate(selected):
                component = canvas.create_component("master:" + name, 10 + index * 12, 10)
                live[name] = {"parameters": component.parameters(),
                              "properties": {"iid": component.iid,
                                             "definition": component.defn_name,
                                             "location": component.location},
                              "ports": {key: list(value) for key, value in component.ports().items()}}
                print("LIVE", name, live[name], flush=True)
            (args.output / "live_api.json").write_text(
                json.dumps(live, indent=2, default=str), encoding="utf-8")
            app.save_workspace()
        finally:
            app.quit()
    print("mhi.pscad", importlib.metadata.version("mhi.pscad"), flush=True)


if __name__ == "__main__":
    main()
