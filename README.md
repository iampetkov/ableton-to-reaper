# Ableton to Reaper Converter

A Python tool that converts Ableton Live project files (.als) to 
Reaper project files (.RPP), preserving track structure, FX chains, 
plugin states, automation, and audio stems, after being exported correctly.

Built to enable handoff to a mixing engineer working in Reaper - 
without losing the session.

## What it does

- Parses Ableton Live 11/12 project files on macOS (Apple Silicon)
- Transfers track structure, group/folder hierarchy, fader volumes and pan
- Maps Ableton a limited number of Ableton native plugins to Reaper or 3rd party equivalents:
  - EQ Eight → ReaEQ (8-band, with parameter conversion)
  - Compressor / Glue Compressor → Melda MCompressor
  - Gate → ReaGate
  - Utility → Melda MUtility
- Passes through third-party VST3 plugins (ValhallaSupermassive, 
  Kirchhoff-EQ, IVGI2, and several others) with state intact parameters
- Imports already exported audio stems with correct durations and filenames
- Transfers plugin bypass automation (per-track, per-plugin)
- Transfers several plugins' parameter automations
- Generates a conversion report

## Components

- `migrate.py` — CLI entry point
- `gui.py` — Tkinter GUI
- `als_parser.py` — Ableton project parser
- `rpp_generator.py` — Reaper project generator
- `vst_db.py` — VST database lookup
- `report_generator.py` — conversion report

## Requirements

- Python 3.x (stdlib only — no external dependencies)
- macOS (Apple Silicon)
- Reaper 7.x

## Screenshot

<img width="682" height="650" alt="image" src="https://github.com/user-attachments/assets/ed7d1501-fdf0-4a94-9862-51ff8f55912c" />


## Known limitations

- Utility plugin parameter transfer is partial (inserts at default state).
- ReaEQ filter Q not fully matching EQEight Q values after a certain steeper point.
- Only a limited set of plugins is currently being parsed.
