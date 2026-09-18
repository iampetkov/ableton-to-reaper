#!/usr/bin/env python3
"""
gui.py — Ableton → Reaper Migration Tool GUI
Run with: python gui.py
"""

import sys
import json
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from als_parser import parse_als
from rpp_generator import generate_rpp
from report_generator import generate_report

# ── Palette ────────────────────────────────────────────────────────────────
BG        = "#1a1a1f"
SURFACE   = "#24242b"
SURFACE2  = "#2e2e38"
BORDER    = "#3a3a48"
ACCENT    = "#c8a96e"       # warm gold — DAW/hardware feel
ACCENT_DIM= "#7a6540"
TEXT      = "#e8e6e0"
TEXT_DIM  = "#7a7870"
TEXT_DARK = "#1a1a1f"
GREEN     = "#5bbf7a"
RED       = "#e06060"
YELLOW    = "#d4a844"

FONT_MONO = ("JetBrains Mono", 10) if sys.platform == "darwin" else ("Courier New", 10)
FONT_UI   = ("SF Pro Display", 11) if sys.platform == "darwin" else ("Segoe UI", 11)
FONT_SM   = ("SF Pro Display", 10) if sys.platform == "darwin" else ("Segoe UI", 10)
FONT_TITLE= ("SF Pro Display", 18, "bold") if sys.platform == "darwin" else ("Segoe UI", 18, "bold")
FONT_SUB  = ("SF Pro Display", 11) if sys.platform == "darwin" else ("Segoe UI", 11)


class MigrationApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Ableton → Reaper")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(620, 560)

        # State
        self.als_path   = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.stems_dir  = tk.StringVar()
        self._running   = False

        self._build_ui()
        self._center()

    # ── Layout ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=BG, pady=24)
        hdr.pack(fill="x", padx=32)
        tk.Label(hdr, text="Ableton → Reaper", font=FONT_TITLE,
                 bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(hdr, text="Migrate projects with FX chains intact",
                 font=FONT_SUB, bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(2, 0))

        # Divider
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=32)

        # Form
        form = tk.Frame(self, bg=BG)
        form.pack(fill="x", padx=32, pady=24)

        self._browse_row(form, 0, "Ableton project (.als)",
                         self.als_path, self._browse_als)
        self._browse_row(form, 1, "Output folder",
                         self.output_dir, self._browse_output)
        self._browse_row(form, 2, "Stems folder  (optional)",
                         self.stems_dir, self._browse_stems,
                         placeholder="Leave blank — fill in after exporting from Ableton")

        # Run button
        btn_frame = tk.Frame(self, bg=BG)
        btn_frame.pack(fill="x", padx=32, pady=(0, 20))

        self.run_btn = tk.Button(
            btn_frame, text="Convert Project",
            font=(FONT_UI[0], 12, "bold"),
            bg=ACCENT, fg=TEXT_DARK, activebackground=ACCENT_DIM,
            activeforeground=TEXT, relief="flat", cursor="hand2",
            padx=28, pady=10,
            command=self._run
        )
        self.run_btn.pack(side="left")

        self.status_lbl = tk.Label(btn_frame, text="", font=FONT_SM,
                                   bg=BG, fg=TEXT_DIM)
        self.status_lbl.pack(side="left", padx=16)

        # Progress bar
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("Gold.Horizontal.TProgressbar",
                        troughcolor=SURFACE2, background=ACCENT,
                        bordercolor=SURFACE2, lightcolor=ACCENT, darkcolor=ACCENT)
        self.progress = ttk.Progressbar(self, style="Gold.Horizontal.TProgressbar",
                                        mode="indeterminate", length=400)
        self.progress.pack(padx=32, fill="x")

        # Log area
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=32, pady=(20, 0))
        log_hdr = tk.Frame(self, bg=BG)
        log_hdr.pack(fill="x", padx=32, pady=(10, 4))
        tk.Label(log_hdr, text="Log", font=FONT_SM,
                 bg=BG, fg=TEXT_DIM).pack(side="left")

        log_frame = tk.Frame(self, bg=SURFACE, bd=0, highlightbackground=BORDER,
                             highlightthickness=1)
        log_frame.pack(fill="both", expand=True, padx=32, pady=(0, 24))

        self.log = tk.Text(
            log_frame, bg=SURFACE, fg=TEXT, font=FONT_MONO,
            relief="flat", bd=0, padx=12, pady=10,
            state="disabled", wrap="word",
            insertbackground=ACCENT, selectbackground=ACCENT_DIM
        )
        scroll = tk.Scrollbar(log_frame, bg=SURFACE2, troughcolor=SURFACE,
                               relief="flat", bd=0)
        scroll.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.config(yscrollcommand=scroll.set)
        scroll.config(command=self.log.yview)

        # Log tags
        self.log.tag_config("ok",      foreground=GREEN)
        self.log.tag_config("warn",    foreground=YELLOW)
        self.log.tag_config("err",     foreground=RED)
        self.log.tag_config("dim",     foreground=TEXT_DIM)
        self.log.tag_config("accent",  foreground=ACCENT)
        self.log.tag_config("heading", foreground=ACCENT, font=(FONT_MONO[0], 10, "bold"))

    def _browse_row(self, parent, row, label, var, command, placeholder=""):
        tk.Label(parent, text=label, font=FONT_SM, bg=BG, fg=TEXT_DIM,
                 anchor="w").grid(row=row*2, column=0, columnspan=2,
                                  sticky="w", pady=(12 if row > 0 else 0, 3))

        entry_frame = tk.Frame(parent, bg=SURFACE, highlightbackground=BORDER,
                                highlightthickness=1)
        entry_frame.grid(row=row*2+1, column=0, sticky="ew", pady=(0, 0))
        parent.columnconfigure(0, weight=1)

        entry = tk.Entry(entry_frame, textvariable=var,
                         bg=SURFACE, fg=TEXT if not placeholder else TEXT_DIM,
                         font=FONT_UI, relief="flat", bd=0,
                         insertbackground=ACCENT)
        entry.pack(side="left", fill="x", expand=True, padx=10, pady=8)

        if placeholder:
            self._add_placeholder(entry, var, placeholder)

        btn = tk.Button(entry_frame, text="Browse", font=FONT_SM,
                        bg=SURFACE2, fg=TEXT_DIM, activebackground=BORDER,
                        activeforeground=TEXT, relief="flat", cursor="hand2",
                        padx=10, pady=4, command=command)
        btn.pack(side="right", padx=(0, 4), pady=4)

        return entry

    def _add_placeholder(self, entry, var, text):
        def on_focus_in(e):
            if var.get() == text:
                var.set("")
                entry.config(fg=TEXT)
        def on_focus_out(e):
            if not var.get():
                var.set(text)
                entry.config(fg=TEXT_DIM)
        entry.bind("<FocusIn>", on_focus_in)
        entry.bind("<FocusOut>", on_focus_out)
        if not var.get():
            var.set(text)
            entry.config(fg=TEXT_DIM)

    # ── Browse callbacks ────────────────────────────────────────────────────

    def _initial_dir(self, var: tk.StringVar, fallback_var: tk.StringVar = None) -> str:
        """Return the best initial directory for a file dialog.
        Uses the current value of var (or its parent dir for files), falling back
        to fallback_var, then the user's home directory."""
        val = var.get().strip()
        if val and Path(val).exists():
            p = Path(val)
            return str(p if p.is_dir() else p.parent)
        if fallback_var:
            fb = fallback_var.get().strip()
            if fb and Path(fb).exists():
                p = Path(fb)
                return str(p if p.is_dir() else p.parent)
        return str(Path.home())

    def _browse_als(self):
        path = filedialog.askopenfilename(
            title="Select Ableton project",
            initialdir=self._initial_dir(self.als_path),
            filetypes=[("Ableton Live Set", "*.als"), ("All files", "*.*")]
        )
        if path:
            self.als_path.set(path)
            if not self.output_dir.get():
                self.output_dir.set(str(Path(path).parent / "reaper_export"))

    def _browse_output(self):
        path = filedialog.askdirectory(
            title="Select output folder",
            initialdir=self._initial_dir(self.output_dir, self.als_path)
        )
        if path:
            self.output_dir.set(path)

    def _browse_stems(self):
        path = filedialog.askdirectory(
            title="Select stems folder",
            initialdir=self._initial_dir(self.stems_dir, self.als_path)
        )
        if path:
            self.stems_dir.set(path)

    # ── Logging ────────────────────────────────────────────────────────────

    def _log(self, msg, tag=""):
        self.log.config(state="normal")
        self.log.insert("end", msg + "\n", tag)
        self.log.see("end")
        self.log.config(state="disabled")

    def _log_clear(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    # ── Run ────────────────────────────────────────────────────────────────

    def _run(self):
        if self._running:
            return

        als = self.als_path.get().strip()
        out = self.output_dir.get().strip()

        if not als or not Path(als).exists():
            self._set_status("Select a valid .als file first", RED)
            return
        if not out:
            self._set_status("Select an output folder first", RED)
            return

        placeholder = "Leave blank — fill in after exporting from Ableton"
        stems = self.stems_dir.get().strip()
        if stems == placeholder:
            stems = ""

        self._running = True
        self.run_btn.config(state="disabled", bg=ACCENT_DIM)
        self._log_clear()
        self.progress.start(12)
        self._set_status("Converting…", TEXT_DIM)

        thread = threading.Thread(
            target=self._run_migration,
            args=(als, out, stems),
            daemon=True
        )
        thread.start()

    def _run_migration(self, als: str, out_dir: str, stems: str):
        try:
            als_path = Path(als)
            out_path = Path(out_dir)
            out_path.mkdir(parents=True, exist_ok=True)

            stem_name = als_path.stem

            # Step 1 — Parse
            self._log(f"  Parsing  {als_path.name}", "dim")
            project = parse_als(als_path)

            track_count = len(project["tracks"])
            tempo = project["tempo"]
            self._log(f"  ✓  {track_count} tracks · {tempo} BPM · {project['time_signature']}", "ok")

            # Log track summary
            self._log("", "")
            self._log("  Tracks found:", "heading")
            for t in project["tracks"]:
                devs = [d.get("type", "?") for d in t["devices"]]
                tp_flag = "  ⚠ 3rd party" if any(d == "THIRD_PARTY" for d in devs) else ""
                dev_str = ", ".join(d for d in devs if d != "THIRD_PARTY")
                self._log(f"    {t['name']}  [{t['type']}]", "accent")
                if dev_str:
                    self._log(f"      → {dev_str}{tp_flag}", "dim")
                elif tp_flag:
                    self._log(f"      {tp_flag}", "warn")

            # Step 2 — Generate RPP
            self._log("", "")
            self._log("  Generating Reaper project…", "dim")
            rpp_path = out_path / f"{stem_name}.RPP"
            report = generate_rpp(project, rpp_path, stems)
            self._log(f"  ✓  {rpp_path.name}", "ok")

            # Step 3 — Report
            report_path = out_path / f"{stem_name}_migration_report.txt"
            generate_report(report, report_path)

            # Summary
            self._log("", "")
            self._log("  ─────────────────────────────────", "dim")

            passthrough    = report.get("passthrough", [])
            tp_found       = report.get("third_party_found", [])
            tp_missing     = report.get("third_party_plugins", [])
            approx         = report.get("approximations", [])
            missing_stems  = report.get("missing_stems", [])

            if passthrough:
                self._log(f"  ✓  {len(passthrough)} plugin(s) — full state transferred:", "ok")
                for w in passthrough:
                    self._log(f"     · {w['track']}  →  {w.get('plugin_name', '?')}", "ok")

            if tp_found:
                self._log(f"  ⚠  {len(tp_found)} plugin(s) — loaded with DEFAULT settings (state not transferred):", "warn")
                for w in tp_found:
                    self._log(f"     · {w['track']}  →  {w.get('plugin_name', '?')} ({w.get('plugin_type','?')})", "warn")

            if tp_missing:
                self._log(f"  ✗  {len(tp_missing)} plugin(s) — not found, placeholder inserted:", "warn")
                for w in tp_missing:
                    self._log(f"     · {w['track']}  →  {w.get('plugin_name', '?')} ({w.get('plugin_type','?')})", "warn")

            if approx:
                self._log(f"  ~  {len(approx)} approximation(s) to check by ear:", "dim")
                for w in approx:
                    self._log(f"     · {w['track']}  →  {w.get('message','')}", "dim")

            if missing_stems:
                self._log(f"  ✗  {len(missing_stems)} stem(s) not matched — track(s) left empty:", "warn")
                for w in missing_stems:
                    self._log(f"     · {w['track']}", "warn")

            if not passthrough and not tp_found and not tp_missing and not approx and not missing_stems:
                self._log("  ✓  Clean migration — no manual steps needed", "ok")

            self._log("", "")
            self._log(f"  Output  →  {out_path}/", "accent")
            self._log(f"  Report  →  {report_path.name}", "dim")

            self.after(0, lambda: self._set_status("Done", GREEN))

        except Exception as e:
            import traceback
            self._log(f"\n  ✗  Error: {e}", "err")
            self._log(traceback.format_exc(), "err")
            self.after(0, lambda: self._set_status("Failed — see log", RED))

        finally:
            self.after(0, self._finish)

    def _finish(self):
        self.progress.stop()
        self.run_btn.config(state="normal", bg=ACCENT)
        self._running = False

    def _set_status(self, msg, color=TEXT_DIM):
        self.status_lbl.config(text=msg, fg=color)

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _center(self):
        self.update_idletasks()
        w, h = 680, 620
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")


if __name__ == "__main__":
    app = MigrationApp()
    app.mainloop()
