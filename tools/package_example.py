"""Bundle the complete source and selected PSCAD results without compiler caches."""

import argparse
from pathlib import Path
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path)
    parser.add_argument("--validation", type=Path)
    parser.add_argument("--output", type=Path, default=Path("PassiveHarmonicFilter.zip"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    files = []
    for pattern in ["*.py", "*.md", "*.json", "requirements.txt"]:
        files.extend(root.glob(pattern))
    for directory in ["harmonic_filter", "tools", "tests", "docs"]:
        files.extend(path for path in (root / directory).rglob("*")
                     if path.is_file() and path.suffix in {".py", ".md"})
    for directory in [args.study, args.validation]:
        if directory is None:
            continue
        directory = directory.resolve()
        if not directory.is_relative_to(root):
            raise ValueError("Selected result directories must be inside the example root")
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(directory)
            if "projects" in relative.parts and path.parent.name != "projects":
                continue
            if path.suffix in {".pscx", ".pswx", ".psmx", ".csv", ".png", ".json", ".md", ".xml", ".out", ".inf", ".log", ".map"}:
                files.append(path)
    with zipfile.ZipFile(args.output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(set(files)):
            archive.write(path, path.relative_to(root).as_posix())
    print(f"Bundle: {args.output.resolve()} ({args.output.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
