"""Command line entry point."""
import argparse
import sys
from pathlib import Path

from .parser import parse
from .render import to_json, to_mermaid

EXT = {"mermaid": ".md", "json": ".json"}


def build_parser():
    ap = argparse.ArgumentParser(
        prog="drawio-digest",
        description="Extract structure from .drawio files as Mermaid or JSON.",
    )
    ap.add_argument("files", nargs="+", type=Path, help=".drawio files to convert")
    ap.add_argument("-f", "--format", choices=("mermaid", "json"), default="mermaid")
    ap.add_argument("-o", "--outdir", type=Path,
                    help="write next to each source file if omitted")
    ap.add_argument("--stdout", action="store_true", help="print instead of writing files")
    ap.add_argument("--direction", default="TD", choices=("TD", "LR", "BT", "RL"),
                    help="mermaid flow direction (default: TD)")
    ap.add_argument("--no-notes", action="store_true",
                    help="omit the review notes about recovered/dropped edges")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero if any edge was dropped")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    dropped_total = 0
    failed = False

    for path in args.files:
        try:
            diagram = parse(path)
        except (OSError, ValueError) as exc:
            print("%s: %s" % (path, exc), file=sys.stderr)
            failed = True
            continue

        if args.format == "json":
            text = to_json(diagram)
        else:
            text = to_mermaid(diagram, args.direction, notes=not args.no_notes)

        recovered = sum(len(p.recovered) for p in diagram.pages)
        dropped = sum(len(p.dropped) for p in diagram.pages)
        dropped_total += dropped

        if args.stdout:
            print(text)
            continue

        outdir = args.outdir or path.parent
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / (path.stem + EXT[args.format])
        out.write_text(text, encoding="utf-8")

        note = ""
        if recovered:
            note += "  (recovered %d)" % recovered
        if dropped:
            note += "  (dropped %d)" % dropped
        print("%s -> %s%s" % (path, out, note))

    if failed:
        return 2
    return 1 if args.strict and dropped_total else 0


if __name__ == "__main__":
    sys.exit(main())
