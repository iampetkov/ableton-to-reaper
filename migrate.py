#!/usr/bin/env python3
"""
migrate.py — Ableton → Reaper Migration Tool
Usage:
    python migrate.py <file.als>              # single project
    python migrate.py <directory/>            # batch: all .als files in dir
    python migrate.py <file.als> --stems <stems_dir>  # with stems path
    python migrate.py <file.als> --json-only  # parse only, no RPP output
"""

import argparse
import json
import sys
from pathlib import Path

# Add src to path if running from project root
sys.path.insert(0, str(Path(__file__).parent / "src"))

from als_parser import parse_als
from rpp_generator import generate_rpp
from report_generator import generate_report


def migrate_single(als_path: Path, output_dir: Path, stems_dir: str = "", json_only: bool = False) -> bool:
    print(f"\n{'─'*55}")
    print(f"  Migrating: {als_path.name}")
    print(f"{'─'*55}")

    # 1. Parse
    try:
        print("  [1/3] Parsing .als file...")
        project = parse_als(als_path)
        print(f"        ✓ {len(project['tracks'])} tracks, {project['tempo']} BPM")
    except Exception as e:
        print(f"        ✗ Parse failed: {e}")
        return False

    stem = als_path.stem  # filename without extension
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save JSON
    json_path = output_dir / f"{stem}_parsed.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(project, f, indent=2, ensure_ascii=False)
    print(f"        → {json_path.name}")

    if json_only:
        print("  JSON-only mode — skipping RPP generation.")
        return True

    # 2. Generate RPP
    try:
        print("  [2/3] Generating Reaper project...")
        rpp_path = output_dir / f"{stem}.RPP"
        report = generate_rpp(project, rpp_path, stems_dir)
        print(f"        ✓ {rpp_path.name}")
    except Exception as e:
        print(f"        ✗ RPP generation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # 3. Generate report
    try:
        print("  [3/3] Writing migration report...")
        report_path = output_dir / f"{stem}_migration_report.txt"
        generate_report(report, report_path)
        print(f"        ✓ {report_path.name}")

        # Print quick summary
        tp = len(report.get("third_party_plugins", []))
        approx = len(report.get("approximations", []))
        if tp > 0:
            print(f"\n  ⚠  {tp} third-party plugin(s) need manual setup → see report")
        if approx > 0:
            print(f"  ~  {approx} approximation(s) to review by ear → see report")
        if tp == 0 and approx == 0:
            print(f"\n  ✓  Clean migration — no manual steps required")
    except Exception as e:
        print(f"        ✗ Report generation failed: {e}")
        return False

    print(f"\n  Output folder: {output_dir}/")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Migrate Ableton Live projects to Reaper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python migrate.py MyProject.als
  python migrate.py MyProject.als --stems ./Stems
  python migrate.py ./projects/              # batch convert directory
  python migrate.py MyProject.als --out ./output --json-only
        """
    )
    parser.add_argument("input", help=".als file or directory containing .als files")
    parser.add_argument("--out", "-o", default=None,
                        help="Output directory (default: ./migrated/<project_name>/)")
    parser.add_argument("--stems", "-s", default="",
                        help="Path to stems directory (will be written into RPP item paths)")
    parser.add_argument("--json-only", action="store_true",
                        help="Only parse and export JSON, skip RPP generation")
    args = parser.parse_args()

    input_path = Path(args.input)

    # Collect .als files
    if input_path.is_dir():
        als_files = sorted(input_path.glob("*.als"))
        if not als_files:
            print(f"No .als files found in {input_path}")
            sys.exit(1)
        print(f"Found {len(als_files)} .als file(s) in {input_path}")
    elif input_path.is_file() and input_path.suffix.lower() == ".als":
        als_files = [input_path]
    else:
        print(f"Error: '{input_path}' is not a .als file or directory")
        sys.exit(1)

    success = 0
    fail = 0

    for als_path in als_files:
        if args.out:
            out_dir = Path(args.out) / als_path.stem
        else:
            out_dir = Path("migrated") / als_path.stem

        ok = migrate_single(
            als_path,
            out_dir,
            stems_dir=args.stems,
            json_only=args.json_only,
        )
        if ok:
            success += 1
        else:
            fail += 1

    print(f"\n{'═'*55}")
    print(f"  Done: {success} succeeded, {fail} failed")
    if success > 0 and not args.json_only:
        print(f"  Open the .RPP files in Reaper to review your projects.")
        print(f"  Check *_migration_report.txt for any manual steps.")
    print(f"{'═'*55}\n")

    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
