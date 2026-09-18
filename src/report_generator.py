"""
report_generator.py
Generates a human-readable migration report from the conversion report dict.
"""

from pathlib import Path
from typing import Any
import json


SECTION = "=" * 60


def generate_report(report: dict, output_path: str | Path) -> str:
    output_path = Path(output_path)
    lines = []

    def h(title: str):
        lines.append("")
        lines.append(SECTION)
        lines.append(f"  {title}")
        lines.append(SECTION)

    def sub(title: str):
        lines.append(f"\n  --- {title} ---")

    lines.append("ABLETON → REAPER MIGRATION REPORT")
    lines.append(SECTION)
    lines.append(f"  Source:  {report.get('source_file', 'Unknown')}")
    lines.append(f"  Output:  {report.get('output_file', 'Unknown')}")
    lines.append(f"  Tracks:  {report.get('track_count', 0)}")
    lines.append(f"  Warnings: {len(report.get('warnings', []))}")

    # Third-party plugins
    found = report.get("third_party_found", [])
    third_party = report.get("third_party_plugins", [])

    if found:
        h("✓  THIRD-PARTY PLUGINS — LOADED FROM REAPER DATABASE")
        lines.append("")
        lines.append("  These plugins were found in Reaper's VST database and added")
        lines.append("  with default state. They will open in Reaper — settings need")
        lines.append("  to be re-configured manually.")
        lines.append("")
        for i, w in enumerate(found, 1):
            track = w.get("track", "Unknown Track")
            name = w.get("plugin_name", "Unknown Plugin")
            lines.append(f"  [{i}] Track: \"{track}\"  →  {name}")
        lines.append("")

    if third_party:
        h("⚠  THIRD-PARTY PLUGINS — NOT FOUND (PLACEHOLDER INSERTED)")
        lines.append("")
        lines.append("  These plugins were NOT found in Reaper's VST database.")
        lines.append("  A disabled placeholder marks each position in the FX chain.")
        lines.append("  Fix: Reaper → Preferences → Plug-ins → VST → Re-scan,")
        lines.append("  then re-run the migration tool.")
        lines.append("")
        for i, w in enumerate(third_party, 1):
            track = w.get("track", "Unknown Track")
            name = w.get("plugin_name", "Unknown Plugin")
            ptype = w.get("plugin_type", "VST")
            lines.append(f"  [{i}] Track: \"{track}\"")
            lines.append(f"      Plugin: {name} ({ptype})")
            lines.append("")

    if not found and not third_party:
        h("✓  THIRD-PARTY PLUGINS")
        lines.append("  No third-party plugins found. All effects migrated automatically.")

    # Approximations
    approx = report.get("approximations", [])
    if approx:
        h("~  APPROXIMATIONS — CHECK BY EAR")
        lines.append("")
        lines.append("  These Ableton native devices were mapped to the closest Reaper")
        lines.append("  equivalent, but the sound may differ. Review each one.")
        lines.append("")
        for i, w in enumerate(approx, 1):
            track = w.get("track", "Unknown Track")
            msg = w.get("message", "")
            lines.append(f"  [{i}] Track: \"{track}\"")
            lines.append(f"      Note: {msg}")
            lines.append("")

    # Unsupported natives
    unsupported = report.get("unsupported", [])
    if unsupported:
        h("?  UNSUPPORTED ABLETON DEVICES — PLACEHOLDER ONLY")
        lines.append("")
        for i, w in enumerate(unsupported, 1):
            track = w.get("track", "Unknown Track")
            msg = w.get("message", "")
            lines.append(f"  [{i}] Track: \"{track}\"")
            lines.append(f"      {msg}")
            lines.append("")

    # Plugin mapping reference
    h("PLUGIN MAPPING REFERENCE")
    mappings = [
        ("EQ Eight",         "ReaEQ",                      "Full band-by-band mapping"),
        ("Compressor",       "ReaComp",                    "Full parameter mapping"),
        ("Glue Compressor",  "ReaComp",                    "Approximate — character differs"),
        ("Gate",             "ReaGate",                    "Full parameter mapping"),
        ("Limiter",          "JS: BrickwallLimiter",        "Approximate"),
        ("Saturator",        "JS: Saturation",             "Approximate — shape type not 1:1"),
        ("Utility",          "JS: volume_pan",             "Gain + pan mapped"),
        ("Reverb",           "JS: RCVerb",                 "Approximate — adjust by ear"),
        ("Delay",            "ReaDelay",                   "Time + feedback mapped"),
        ("Chorus",           "JS: Chorus",                 "Approximate"),
        ("Auto Filter",      "Placeholder",                "Not fully mapped"),
        ("Other natives",    "Placeholder (disabled)",     "Parameters logged"),
        ("3rd party VSTs",   "Placeholder (disabled)",     "Manual setup required"),
    ]
    lines.append("")
    lines.append(f"  {'Ableton Device':<22} {'Reaper Plugin':<28} Notes")
    lines.append(f"  {'-'*22} {'-'*28} {'-'*30}")
    for abl, rpr, note in mappings:
        lines.append(f"  {abl:<22} {rpr:<28} {note}")

    # Stems note
    h("STEMS / AUDIO FILES")
    lines.append("")
    lines.append("  Audio stems must be exported from Ableton separately.")
    lines.append("  Recommended export settings:")
    lines.append("    • File → Export Audio/Video")
    lines.append("    • Select 'All Individual Tracks'")
    lines.append("    • Format: WAV, 24-bit, matching project sample rate")
    lines.append("    • Render: check 'Save as project' to keep relative paths")
    lines.append("    • Include Return Tracks: yes (if processing info needed)")
    lines.append("    • Normalize: NO (preserve relative volumes)")
    lines.append("")
    lines.append("  After export, place stems in a 'Stems' folder alongside the .RPP file.")
    lines.append("  The Reaper project expects: Stems/<TrackName>.wav")

    # Final summary
    h("SUMMARY")
    total_warnings = len(report.get("warnings", []))
    lines.append("")
    if total_warnings == 0:
        lines.append("  ✓ Clean migration — no manual intervention required.")
    else:
        lines.append(f"  {len(third_party)} third-party plugin(s) need manual setup")
        lines.append(f"  {len(approx)} approximation(s) should be reviewed by ear")
        lines.append(f"  {len(unsupported)} unsupported device(s) have placeholders")
    lines.append("")
    lines.append("  Generated by ableton-to-reaper migration tool")
    lines.append(SECTION)

    content = "\n".join(lines)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    return content


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python report_generator.py <report.json> <output.txt>")
        sys.exit(1)
    with open(sys.argv[1]) as f:
        report = json.load(f)
    generate_report(report, sys.argv[2])
    print(f"Report written to {sys.argv[2]}")
