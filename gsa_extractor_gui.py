"""Tkinter GUI for gsa_force_extractor.

Three tabs:
  1. Setup     — GSA file, output paths, unit/sign settings.
  2. Jobs      — list of jobs with a per-job editor (location, combo, forces,
                 axis mapping, envelopes).
  3. Run       — Run button, status log, results table with Copy-to-clipboard.

Toolbar (always visible): New / Load / Save / Save As / Quit.

This file is the *view* layer only. All extraction logic lives in
gsa_force_extractor (already covered by 28 unit tests).

Run:
    python gsa_extractor_gui.py [optional-config.json]
"""

from __future__ import annotations

import io
import os
import sys
import time
import traceback
from dataclasses import replace
from typing import Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import gsa_force_extractor as gfe


# Defaults used when a brand-new job / config is created.
DEFAULT_AXES_4 = {"Pu": "Fx", "Mu": "Myy", "Vu": "Fz", "Tu": "Mxx"}
DEFAULT_FORCES = ["Pu", "Mu", "Vu", "Tu"]
DEFAULT_ENVELOPES = [
    gfe.EnvelopeRule("max", "Mu", 1),
    gfe.EnvelopeRule("min", "Mu", 1),
    gfe.EnvelopeRule("max_abs", "Vu", 1),
    gfe.EnvelopeRule("max", "Pu", 1),
    gfe.EnvelopeRule("min", "Pu", 1),
]
KNOWN_FORCE_UNITS = ["kN", "N", "kip", "lbf"]
KNOWN_MOMENT_UNITS = ["kN.m", "N.m", "kip-in", "kip-ft", "lbf-ft"]


def empty_config() -> gfe.Config:
    return gfe.Config(
        gsa_file="",
        output_csv="",
        output_tsv=None,
        units=gfe.UnitsCfg(),
        signs=gfe.SignsCfg(),
        jobs=[default_job("New job")],
    )


def default_job(name: str) -> gfe.JobCfg:
    return gfe.JobCfg(
        name=name,
        location={"element": 1, "position": 0.5},
        combo="C1",
        axes=dict(DEFAULT_AXES_4),
        forces_to_output=list(DEFAULT_FORCES),
        envelopes=[replace(e) for e in DEFAULT_ENVELOPES],
    )


# ---------------------------------------------------------------------------
# Per-job editor frame
# ---------------------------------------------------------------------------

class JobEditor(ttk.Frame):
    """Form bound to a single JobCfg. Call `bind_job(job)` to load it,
    `commit()` to write the form back into the job dataclass.
    """

    LOCATION_KINDS = ("element", "elements", "group", "property")

    def __init__(self, master, on_change=None):
        super().__init__(master)
        self.job: Optional[gfe.JobCfg] = None
        self._on_change = on_change or (lambda: None)
        self._build()

    def _build(self):
        # --- Name + combo + location ---
        top = ttk.LabelFrame(self, text="Identity & target")
        top.pack(fill="x", padx=6, pady=4)
        for c in range(4):
            top.columnconfigure(c, weight=1 if c in (1, 3) else 0)

        ttk.Label(top, text="Job name:").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.name_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.name_var).grid(row=0, column=1, columnspan=3, sticky="we", padx=4, pady=2)

        ttk.Label(top, text="Combo:").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        self.combo_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.combo_var, width=12).grid(row=1, column=1, sticky="w", padx=4, pady=2)

        ttk.Label(top, text="Position (0..1 or 'max'):").grid(row=1, column=2, sticky="e", padx=4, pady=2)
        self.position_var = tk.StringVar(value="max")
        ttk.Entry(top, textvariable=self.position_var, width=8).grid(row=1, column=3, sticky="w", padx=4, pady=2)

        # Location selector
        loc_frame = ttk.LabelFrame(self, text="Location selector (pick one)")
        loc_frame.pack(fill="x", padx=6, pady=4)
        self.loc_kind_var = tk.StringVar(value="element")
        for i, kind in enumerate(self.LOCATION_KINDS):
            ttk.Radiobutton(
                loc_frame, text=kind, variable=self.loc_kind_var,
                value=kind, command=self._update_loc_hint,
            ).grid(row=0, column=i, sticky="w", padx=6, pady=2)
        self.loc_value_var = tk.StringVar()
        ttk.Entry(loc_frame, textvariable=self.loc_value_var).grid(
            row=1, column=0, columnspan=4, sticky="we", padx=4, pady=2
        )
        self.loc_hint = ttk.Label(loc_frame, text="", foreground="#555")
        self.loc_hint.grid(row=2, column=0, columnspan=4, sticky="w", padx=4)
        self.sum_across_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            loc_frame,
            text=("Sum forces across elements (treat selection as a group; "
                  "outputs one summed row per envelope)"),
            variable=self.sum_across_var,
        ).grid(row=3, column=0, columnspan=4, sticky="w", padx=4, pady=(2, 4))
        loc_frame.columnconfigure(3, weight=1)

        # --- Forces & axis mapping ---
        forces_frame = ttk.LabelFrame(self, text="Forces to extract & axis mapping")
        forces_frame.pack(fill="x", padx=6, pady=4)
        self.force_check_vars: dict[str, tk.BooleanVar] = {}
        self.force_axis_vars: dict[str, tk.StringVar] = {}
        ttk.Label(forces_frame, text="App force").grid(row=0, column=0, padx=4)
        ttk.Label(forces_frame, text="Map to GSA axis").grid(row=0, column=1, padx=4)
        for i, f in enumerate(gfe.APP_FORCE_ORDER, start=1):
            v = tk.BooleanVar(value=False)
            self.force_check_vars[f] = v
            ttk.Checkbutton(forces_frame, text=f, variable=v,
                            command=self._on_change).grid(row=i, column=0, sticky="w", padx=4)
            axis_var = tk.StringVar(value=DEFAULT_AXES_4.get(f, "Fx"))
            self.force_axis_vars[f] = axis_var
            cb = ttk.Combobox(
                forces_frame, textvariable=axis_var,
                values=sorted(gfe.GSA_AXES), width=6, state="readonly",
            )
            cb.grid(row=i, column=1, sticky="w", padx=4)

        # --- Envelopes table ---
        env_frame = ttk.LabelFrame(self, text="Envelopes (one row per design action)")
        env_frame.pack(fill="both", expand=True, padx=6, pady=4)

        cols = ("action", "on", "top_n")
        self.env_tree = ttk.Treeview(env_frame, columns=cols, show="headings", height=6)
        for c, w in zip(cols, (90, 90, 70)):
            self.env_tree.heading(c, text=c)
            self.env_tree.column(c, width=w, anchor="center")
        self.env_tree.pack(side="left", fill="both", expand=True, padx=4, pady=4)

        env_btns = ttk.Frame(env_frame)
        env_btns.pack(side="right", fill="y", padx=4, pady=4)
        ttk.Button(env_btns, text="Add",    command=self._env_add).pack(fill="x", pady=2)
        ttk.Button(env_btns, text="Edit",   command=self._env_edit).pack(fill="x", pady=2)
        ttk.Button(env_btns, text="Delete", command=self._env_delete).pack(fill="x", pady=2)
        self.env_tree.bind("<Double-1>", lambda e: self._env_edit())

    def _update_loc_hint(self):
        kind = self.loc_kind_var.get()
        hints = {
            "element":  "Single integer element ID, e.g. 124",
            "elements": "Comma-separated element IDs, e.g. 12, 13, 14",
            "group":    "Group name as defined in GSA, e.g. PierCap",
            "property": "Section property number, e.g. 5",
        }
        self.loc_hint.config(text=hints[kind])

    # -- Envelope dialog ------------------------------------------------

    def _env_add(self):
        result = EnvelopeDialog(self, self._checked_forces()).result
        if result is not None:
            self.env_tree.insert("", "end", values=(result.action, result.on, result.top_n))

    def _env_edit(self):
        sel = self.env_tree.selection()
        if not sel:
            return
        cur = self.env_tree.item(sel[0])["values"]
        existing = gfe.EnvelopeRule(action=cur[0], on=cur[1], top_n=int(cur[2]))
        result = EnvelopeDialog(self, self._checked_forces(), existing).result
        if result is not None:
            self.env_tree.item(sel[0], values=(result.action, result.on, result.top_n))

    def _env_delete(self):
        for sel in self.env_tree.selection():
            self.env_tree.delete(sel)

    def _checked_forces(self) -> list[str]:
        return [f for f in gfe.APP_FORCE_ORDER if self.force_check_vars[f].get()]

    # -- Bind / commit --------------------------------------------------

    def bind_job(self, job: gfe.JobCfg) -> None:
        self.job = job
        self.name_var.set(job.name)
        self.combo_var.set(job.combo)
        self.position_var.set(str(job.location.get("position", 0.5)))

        # Location selector
        for kind in self.LOCATION_KINDS:
            if kind in job.location:
                self.loc_kind_var.set(kind)
                val = job.location[kind]
                if kind == "elements" and isinstance(val, list):
                    self.loc_value_var.set(", ".join(str(x) for x in val))
                else:
                    self.loc_value_var.set(str(val))
                break
        else:
            self.loc_kind_var.set("element")
            self.loc_value_var.set("")
        self._update_loc_hint()
        self.sum_across_var.set(bool(job.location.get("sum_across_elements", False)))

        # Forces & axes
        for f in gfe.APP_FORCE_ORDER:
            self.force_check_vars[f].set(f in job.forces_to_output)
            if f in job.axes:
                self.force_axis_vars[f].set(job.axes[f])

        # Envelopes
        for item in self.env_tree.get_children():
            self.env_tree.delete(item)
        for e in job.envelopes:
            self.env_tree.insert("", "end", values=(e.action, e.on, e.top_n))

    def commit(self) -> gfe.JobCfg:
        """Read every form field back into a fresh JobCfg.

        Raises ValueError on parse problems so the caller can surface them.
        """
        if self.job is None:
            raise RuntimeError("commit() called with no bound job")
        forces = self._checked_forces()
        if not forces:
            raise ValueError("Select at least one force to extract.")
        axes = {f: self.force_axis_vars[f].get() for f in forces}

        # Location
        kind = self.loc_kind_var.get()
        raw = self.loc_value_var.get().strip()
        if not raw:
            raise ValueError(f"Location {kind!r} value is empty.")
        if kind == "element":
            loc_value = int(raw)
        elif kind == "elements":
            loc_value = [int(x.strip()) for x in raw.split(",") if x.strip()]
            if not loc_value:
                raise ValueError("'elements' must be a non-empty comma-separated list.")
        elif kind == "property":
            loc_value = int(raw)
        else:  # group
            loc_value = raw

        pos_text = self.position_var.get().strip()
        if pos_text.lower() == "max":
            position = "max"
        else:
            try:
                position = float(pos_text)
            except ValueError:
                raise ValueError(
                    "Position must be a number (e.g. 0.5) or 'max'."
                )

        # Envelopes from the tree
        envelopes: list[gfe.EnvelopeRule] = []
        for iid in self.env_tree.get_children():
            v = self.env_tree.item(iid)["values"]
            envelopes.append(gfe.EnvelopeRule(action=v[0], on=v[1], top_n=int(v[2])))
        if not envelopes:
            raise ValueError("Add at least one envelope rule.")

        location = {kind: loc_value, "position": position}
        if self.sum_across_var.get():
            location["sum_across_elements"] = True
        new_job = gfe.JobCfg(
            name=self.name_var.get().strip() or "Unnamed job",
            location=location,
            combo=self.combo_var.get().strip() or "C1",
            axes=axes,
            forces_to_output=forces,
            envelopes=envelopes,
        )
        return new_job


class BatchProgressDialog(tk.Toplevel):
    """Modal dialog showing extraction progress with per-permutation detail."""

    def __init__(self, master, total_jobs: int):
        super().__init__(master)
        self.title("Extracting…")
        self.resizable(False, False)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.cancelled = False
        self._start_time = time.monotonic()
        self._total_jobs = total_jobs

        self._job_var = tk.StringVar(value="Initialising…")
        ttk.Label(self, textvariable=self._job_var,
                  wraplength=380).pack(padx=20, pady=(14, 2))

        self._detail_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self._detail_var,
                  foreground="#555", wraplength=380).pack(padx=20, pady=(0, 4))

        self._prog = ttk.Progressbar(self, length=360, maximum=total_jobs)
        self._prog.pack(padx=20, pady=2)

        self._time_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self._time_var,
                  foreground="#555").pack(padx=20, pady=(0, 4))

        ttk.Button(self, text="Cancel", command=self._cancel).pack(pady=(2, 14))

        self.grab_set()
        self.update_idletasks()
        self.geometry(f"+{master.winfo_rootx() + 200}+{master.winfo_rooty() + 180}")

    def set_job(self, index: int, name: str, total: int):
        self._job_var.set(f"Job {index + 1} of {total}: {name}")
        self._detail_var.set("")
        self._prog["value"] = index
        self._update_time(index, total)
        self.update()

    def set_perm_progress(self, target_idx: int, n_targets: int,
                          perm_idx: int, n_perms: int):
        """Called per-permutation from run_job's progress callback."""
        if n_targets > 1:
            self._detail_var.set(
                f"  Element {target_idx + 1}/{n_targets} — "
                f"permutation {perm_idx + 1}/{n_perms}")
        else:
            self._detail_var.set(
                f"  Permutation {perm_idx + 1}/{n_perms}")
        # Only update the UI every few perms to avoid overhead
        if perm_idx % 5 == 0 or perm_idx == n_perms - 1:
            self.update()

    def finish(self):
        elapsed = time.monotonic() - self._start_time
        self._prog["value"] = self._prog["maximum"]
        self._detail_var.set(f"Done in {elapsed:.1f}s")
        self.update()
        self.grab_release()
        self.destroy()

    def _update_time(self, done: int, total: int):
        elapsed = time.monotonic() - self._start_time
        if done > 0:
            rate = elapsed / done
            remaining = rate * (total - done)
            self._time_var.set(
                f"Elapsed {elapsed:.0f}s — est. {remaining:.0f}s remaining")
        else:
            self._time_var.set(f"Elapsed {elapsed:.0f}s")

    def _cancel(self):
        self.cancelled = True
        self._job_var.set("Cancelling…")
        self.update()


class BatchDialog(tk.Toplevel):
    """Non-modal window with an Excel-like selectable table of extraction results.

    Uses a single Canvas with drawn rectangles + text items instead of
    hundreds of tk.Label widgets — opens instantly even for large tables.
    """

    _SEL_BG = "#3399ff"
    _SEL_FG = "white"
    _HEADER_BG = "#dcdcdc"
    _EVEN_BG = "white"
    _ODD_BG = "#f5f5f5"
    _ROW_H = 20
    _PAD_X = 6

    def __init__(self, master, rows: list[dict], columns: list[str],
                 on_rerun: callable = None):
        super().__init__(master)
        self.title("Batch Extraction Table")
        self.geometry("1100x520")
        self.minsize(700, 350)
        self.transient(master)

        self._rows = rows
        self._columns = columns
        self._sel_start: tuple[int, int] | None = None
        self._sel_end: tuple[int, int] | None = None

        # Pre-format cell text into a flat grid for fast access
        self._cell_text: list[list[str]] = []
        for r in rows:
            row_texts: list[str] = []
            for c in columns:
                v = r.get(c, "")
                if isinstance(v, float):
                    row_texts.append(f"{v:.2f}")
                else:
                    row_texts.append("" if v is None else str(v))
            self._cell_text.append(row_texts)

        # Compute column widths in pixels based on content
        import tkinter.font as tkfont
        self._cell_font = tkfont.Font(family="Consolas", size=9)
        self._header_font = tkfont.Font(family="Consolas", size=9, weight="bold")
        min_w = 70
        self._col_widths: list[int] = []
        for ci, col_name in enumerate(columns):
            w = self._header_font.measure(col_name) + 2 * self._PAD_X
            for row_texts in self._cell_text:
                cw = self._cell_font.measure(row_texts[ci]) + 2 * self._PAD_X
                if cw > w:
                    w = cw
            self._col_widths.append(max(w, min_w))

        # Column x-offsets (cumulative)
        self._col_x: list[int] = []
        x = 0
        for w in self._col_widths:
            self._col_x.append(x)
            x += w
        self._total_w = x
        self._n_rows = len(rows)
        self._n_cols = len(columns)

        # Top bar
        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=4)
        ttk.Button(top, text="Copy all to clipboard (TSV)",
                   command=self._copy_all).pack(side="left", padx=2)
        ttk.Button(top, text="Copy selection (Ctrl+C)",
                   command=self._copy_selection).pack(side="left", padx=2)
        if on_rerun:
            ttk.Button(top, text="Re-run extraction",
                       command=lambda: self._rerun(on_rerun)).pack(side="left", padx=2)
        self._status_var = tk.StringVar(value=f"{len(rows)} row(s)")
        ttk.Label(top, textvariable=self._status_var).pack(side="left", padx=8)

        # Canvas + scrollbars
        grid_border = ttk.Frame(self, relief="sunken", borderwidth=1)
        grid_border.pack(fill="both", expand=True, padx=6, pady=2)

        self._canvas = tk.Canvas(grid_border, highlightthickness=0, bg="white")
        self._vsb = ttk.Scrollbar(grid_border, orient="vertical",
                                  command=self._canvas.yview)
        self._hsb = ttk.Scrollbar(grid_border, orient="horizontal",
                                  command=self._canvas.xview)
        self._canvas.configure(yscrollcommand=self._vsb.set,
                               xscrollcommand=self._hsb.set)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._vsb.grid(row=0, column=1, sticky="ns")
        self._hsb.grid(row=1, column=0, sticky="we")
        grid_border.rowconfigure(0, weight=1)
        grid_border.columnconfigure(0, weight=1)

        total_h = (1 + self._n_rows) * self._ROW_H
        self._canvas.configure(scrollregion=(0, 0, self._total_w, total_h))

        # Draw the table
        self._sel_rects: list[int] = []  # canvas item ids for selection overlay
        self._draw_table()

        # Bindings
        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Control-c>", lambda e: self._copy_selection())
        self.bind("<Control-C>", lambda e: self._copy_selection())
        self.bind("<Escape>", lambda e: self._clear_selection())
        self._canvas.bind("<MouseWheel>",
                          lambda e: self._canvas.yview_scroll(
                              -1 * (e.delta // 120), "units"))

    def _draw_table(self):
        c = self._canvas
        rh = self._ROW_H
        # Header row
        for ci, col_name in enumerate(self._columns):
            x0 = self._col_x[ci]
            x1 = x0 + self._col_widths[ci]
            c.create_rectangle(x0, 0, x1, rh, fill=self._HEADER_BG,
                               outline="#bbb", width=1)
            c.create_text((x0 + x1) // 2, rh // 2, text=col_name,
                          font=self._header_font, anchor="center")
        # Data rows
        for ri, row_texts in enumerate(self._cell_text):
            y0 = (ri + 1) * rh
            y1 = y0 + rh
            bg = self._EVEN_BG if ri % 2 == 0 else self._ODD_BG
            for ci in range(self._n_cols):
                x0 = self._col_x[ci]
                x1 = x0 + self._col_widths[ci]
                c.create_rectangle(x0, y0, x1, y1, fill=bg,
                                   outline="#e0e0e0", width=1)
                c.create_text((x0 + x1) // 2, (y0 + y1) // 2,
                              text=row_texts[ci], font=self._cell_font,
                              anchor="center")

    # -- Hit testing ---------------------------------------------------

    def _cell_at_canvas(self, cx: float, cy: float) -> tuple[int, int] | None:
        """Return (data_row, col) from canvas coordinates, or None."""
        ri = int(cy // self._ROW_H) - 1  # subtract header row
        if ri < 0 or ri >= self._n_rows:
            return None
        ci = 0
        for i, xoff in enumerate(self._col_x):
            if cx >= xoff:
                ci = i
        if ci >= self._n_cols:
            return None
        return (ri, ci)

    # -- Selection management ------------------------------------------

    def _on_press(self, event):
        cx = self._canvas.canvasx(event.x)
        cy = self._canvas.canvasy(event.y)
        rc = self._cell_at_canvas(cx, cy)
        if rc is None:
            return
        self._sel_start = rc
        self._sel_end = rc
        self._draw_selection()

    def _on_drag(self, event):
        if self._sel_start is None:
            return
        cx = self._canvas.canvasx(event.x)
        cy = self._canvas.canvasy(event.y)
        rc = self._cell_at_canvas(cx, cy)
        if rc is not None:
            self._sel_end = rc
            self._draw_selection()

    def _on_release(self, event):
        if self._sel_start is None:
            return
        cx = self._canvas.canvasx(event.x)
        cy = self._canvas.canvasy(event.y)
        rc = self._cell_at_canvas(cx, cy)
        if rc is not None:
            self._sel_end = rc
            self._draw_selection()
        count = self._selected_cell_count()
        if count > 0:
            self._status_var.set(f"{count} cell(s) selected — Ctrl+C to copy")

    def _draw_selection(self):
        """Draw translucent selection overlay rectangles."""
        for sid in self._sel_rects:
            self._canvas.delete(sid)
        self._sel_rects.clear()
        r1, c1, r2, c2 = self._sel_rect()
        if r2 < r1:
            return
        rh = self._ROW_H
        for ri in range(r1, r2 + 1):
            for ci in range(c1, c2 + 1):
                x0 = self._col_x[ci]
                x1 = x0 + self._col_widths[ci]
                y0 = (ri + 1) * rh
                y1 = y0 + rh
                sid = self._canvas.create_rectangle(
                    x0, y0, x1, y1, fill=self._SEL_BG,
                    outline=self._SEL_BG, stipple="gray50")
                self._sel_rects.append(sid)

    def _clear_selection(self):
        for sid in self._sel_rects:
            self._canvas.delete(sid)
        self._sel_rects.clear()
        self._sel_start = None
        self._sel_end = None
        self._status_var.set(f"{len(self._rows)} row(s)")

    def _sel_rect(self) -> tuple[int, int, int, int]:
        if self._sel_start is None or self._sel_end is None:
            return (0, 0, -1, -1)
        r1 = min(self._sel_start[0], self._sel_end[0])
        r2 = max(self._sel_start[0], self._sel_end[0])
        c1 = min(self._sel_start[1], self._sel_end[1])
        c2 = max(self._sel_start[1], self._sel_end[1])
        return (r1, c1, r2, c2)

    def _selected_cell_count(self) -> int:
        r1, c1, r2, c2 = self._sel_rect()
        if r2 < r1:
            return 0
        return (r2 - r1 + 1) * (c2 - c1 + 1)

    # -- Copy ---------------------------------------------------------

    def _copy_selection(self):
        r1, c1, r2, c2 = self._sel_rect()
        if r2 < r1:
            self._status_var.set("No cells selected.")
            return
        buf = io.StringIO()
        for ri in range(r1, r2 + 1):
            cells = [self._cell_text[ri][ci] for ci in range(c1, c2 + 1)]
            buf.write("\t".join(cells) + "\n")
        self.clipboard_clear()
        self.clipboard_append(buf.getvalue())
        count = (r2 - r1 + 1) * (c2 - c1 + 1)
        self._status_var.set(f"Copied {count} cell(s) to clipboard.")

    def _copy_all(self):
        buf = io.StringIO()
        buf.write("\t".join(self._columns) + "\n")
        for r in self._rows:
            cells = []
            for c in self._columns:
                v = r.get(c, "")
                if isinstance(v, float):
                    cells.append(f"{v:.6g}")
                else:
                    cells.append("" if v is None else str(v))
            buf.write("\t".join(cells) + "\n")
        self.clipboard_clear()
        self.clipboard_append(buf.getvalue())
        self._status_var.set(f"Copied {len(self._rows)} row(s) to clipboard.")

    def _rerun(self, callback):
        self.destroy()
        callback()


class EnvelopeDialog(tk.Toplevel):
    """Modal dialog to add or edit one EnvelopeRule."""

    def __init__(self, master, available_forces: list[str],
                 existing: Optional[gfe.EnvelopeRule] = None):
        super().__init__(master)
        self.title("Envelope rule")
        self.transient(master)
        self.resizable(False, False)
        self.result: Optional[gfe.EnvelopeRule] = None

        if not available_forces:
            messagebox.showerror(
                "No forces selected",
                "Tick at least one force in the job editor before adding an envelope.",
                parent=master,
            )
            self.destroy()
            return

        ttk.Label(self, text="Action:").grid(row=0, column=0, sticky="e", padx=6, pady=4)
        self.action_var = tk.StringVar(value=existing.action if existing else "max")
        ttk.Combobox(self, textvariable=self.action_var,
                     values=("max", "min", "max_abs"),
                     state="readonly", width=10).grid(row=0, column=1, padx=6, pady=4)

        ttk.Label(self, text="On force:").grid(row=1, column=0, sticky="e", padx=6, pady=4)
        default_on = existing.on if existing and existing.on in available_forces else available_forces[0]
        self.on_var = tk.StringVar(value=default_on)
        ttk.Combobox(self, textvariable=self.on_var,
                     values=available_forces, state="readonly",
                     width=10).grid(row=1, column=1, padx=6, pady=4)

        ttk.Label(self, text="Top N:").grid(row=2, column=0, sticky="e", padx=6, pady=4)
        self.top_n_var = tk.IntVar(value=existing.top_n if existing else 1)
        ttk.Spinbox(self, from_=1, to=99, textvariable=self.top_n_var,
                    width=6).grid(row=2, column=1, sticky="w", padx=6, pady=4)

        btns = ttk.Frame(self)
        btns.grid(row=3, column=0, columnspan=2, pady=6)
        ttk.Button(btns, text="OK", command=self._ok).pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.wait_window(self)

    def _ok(self):
        try:
            top_n = int(self.top_n_var.get())
            if top_n < 1:
                raise ValueError
        except (tk.TclError, ValueError):
            messagebox.showerror("Invalid", "Top N must be a positive integer.", parent=self)
            return
        self.result = gfe.EnvelopeRule(
            action=self.action_var.get(),
            on=self.on_var.get(),
            top_n=top_n,
        )
        self.destroy()


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self, initial_config_path: Optional[str] = None):
        super().__init__()
        self.title("GSA Force Extractor")
        self.geometry("960x680")
        self.minsize(800, 580)

        self.cfg: gfe.Config = empty_config()
        self.current_config_path: Optional[str] = None
        self.last_results: list[dict] = []
        self.last_columns: list[str] = []
        self._batch_rows: list[dict] = []
        self._batch_cols: list[str] = []
        self._batch_flags: list[bool] = []  # one per job, True = include in batch
        self._current_job_index: Optional[int] = None

        self._build_ui()
        self._refresh_jobs_list(select_index=0)

        if initial_config_path:
            self._load_config_path(initial_config_path)

    # -- UI scaffolding -----------------------------------------------

    def _build_ui(self):
        # Toolbar
        bar = ttk.Frame(self)
        bar.pack(side="top", fill="x")
        for label, cmd in (
            ("New",      self._on_new),
            ("Load…",    self._on_load),
            ("Save",     self._on_save),
            ("Save As…", self._on_save_as),
            ("Quit",     self.destroy),
        ):
            ttk.Button(bar, text=label, command=cmd).pack(side="left", padx=2, pady=4)
        self.path_label = ttk.Label(bar, text="(unsaved)", foreground="#555")
        self.path_label.pack(side="left", padx=8)

        # Tabs
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=6)
        self._build_setup_tab(nb)
        self._build_jobs_tab(nb)
        self._build_run_tab(nb)
        self.notebook = nb

    def _build_setup_tab(self, nb: ttk.Notebook):
        f = ttk.Frame(nb)
        nb.add(f, text="Setup")
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text="GSA file:").grid(row=0, column=0, sticky="e", padx=6, pady=4)
        self.gsa_file_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.gsa_file_var).grid(row=0, column=1, sticky="we", padx=4, pady=4)
        ttk.Button(f, text="Browse…", command=self._pick_gsa_file).grid(row=0, column=2, padx=4)

        ttk.Label(f, text="Output CSV:").grid(row=1, column=0, sticky="e", padx=6, pady=4)
        self.csv_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.csv_var).grid(row=1, column=1, sticky="we", padx=4, pady=4)
        ttk.Button(f, text="Browse…", command=lambda: self._pick_save("csv", self.csv_var)).grid(row=1, column=2, padx=4)

        ttk.Label(f, text="Output TSV (optional):").grid(row=2, column=0, sticky="e", padx=6, pady=4)
        self.tsv_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.tsv_var).grid(row=2, column=1, sticky="we", padx=4, pady=4)
        ttk.Button(f, text="Browse…", command=lambda: self._pick_save("tsv", self.tsv_var)).grid(row=2, column=2, padx=4)

        units_frame = ttk.LabelFrame(f, text="Output units")
        units_frame.grid(row=3, column=0, columnspan=3, sticky="we", padx=6, pady=8)
        ttk.Label(units_frame, text="Force unit:").grid(row=0, column=0, sticky="e", padx=4, pady=2)
        self.output_force_var = tk.StringVar(value="kip")
        ttk.Combobox(units_frame, textvariable=self.output_force_var,
                     values=KNOWN_FORCE_UNITS, width=10).grid(row=0, column=1, padx=4, pady=2)
        ttk.Label(units_frame, text="Moment unit:").grid(row=0, column=2, sticky="e", padx=4, pady=2)
        self.output_moment_var = tk.StringVar(value="kip-in")
        ttk.Combobox(units_frame, textvariable=self.output_moment_var,
                     values=KNOWN_MOMENT_UNITS, width=10).grid(row=0, column=3, padx=4, pady=2)
        ttk.Label(units_frame, text="(GSA model units are detected automatically at run time.)",
                  foreground="#555").grid(row=1, column=0, columnspan=4, sticky="w", padx=4, pady=2)

        signs_frame = ttk.LabelFrame(f, text="GSA sign conventions (toggle if your model differs)")
        signs_frame.grid(row=4, column=0, columnspan=3, sticky="we", padx=6, pady=4)
        ttk.Label(
            signs_frame,
            text=("App convention: Pu < 0 = compression, Mu < 0 = hogging. "
                  "Tick a box if GSA's convention disagrees — the script flips on read."),
            foreground="#555", wraplength=860, justify="left",
        ).grid(row=0, column=0, sticky="w", padx=4, pady=(2, 4))
        self.axial_comp_pos_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            signs_frame,
            text="GSA reports compression as +Fx (uncommon) — flip so app sees compression as negative Pu / Ps",
            variable=self.axial_comp_pos_var,
        ).grid(row=1, column=0, sticky="w", padx=4, pady=2)
        self.moment_hog_pos_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            signs_frame,
            text="GSA reports hogging as +Myy / +Mzz — flip so app sees hogging as negative Mu / Ms",
            variable=self.moment_hog_pos_var,
        ).grid(row=2, column=0, sticky="w", padx=4, pady=2)

    def _build_jobs_tab(self, nb: ttk.Notebook):
        f = ttk.Frame(nb)
        nb.add(f, text="Jobs")

        # Left: list + buttons
        left = ttk.Frame(f)
        left.pack(side="left", fill="y", padx=4, pady=4)
        ttk.Label(left, text="Jobs:", font=("TkDefaultFont", 9)).pack(anchor="w")

        # Scrollable frame of job rows (Checkbutton + Label per job)
        list_border = ttk.Frame(left, relief="sunken", borderwidth=1)
        list_border.pack(fill="both", expand=True)
        self._jobs_canvas = tk.Canvas(list_border, width=240, height=340,
                                      highlightthickness=0, bg="white")
        self._jobs_vscroll = ttk.Scrollbar(list_border, orient="vertical",
                                           command=self._jobs_canvas.yview)
        self._jobs_canvas.configure(yscrollcommand=self._jobs_vscroll.set)
        self._jobs_canvas.pack(side="left", fill="both", expand=True)
        self._jobs_vscroll.pack(side="right", fill="y")

        self._jobs_inner = ttk.Frame(self._jobs_canvas)
        self._jobs_canvas.create_window((0, 0), window=self._jobs_inner, anchor="nw")
        self._jobs_inner.bind("<Configure>",
                              lambda e: self._jobs_canvas.configure(
                                  scrollregion=self._jobs_canvas.bbox("all")))
        # Mouse-wheel scrolling
        self._jobs_canvas.bind_all("<MouseWheel>",
                                   lambda e: self._jobs_canvas.yview_scroll(
                                       -1 * (e.delta // 120), "units"))

        self._job_rows: list[dict] = []  # [{frame, var, label}, ...]

        btn_row = ttk.Frame(left)
        btn_row.pack(fill="x", pady=4)
        ttk.Button(btn_row, text="Add",       command=self._job_add).pack(side="left", padx=2)
        ttk.Button(btn_row, text="Duplicate", command=self._job_dup).pack(side="left", padx=2)
        ttk.Button(btn_row, text="Delete",    command=self._job_del).pack(side="left", padx=2)

        ttk.Button(left, text="Batch Extraction Table",
                   command=self._on_batch_extract).pack(fill="x", pady=(8, 0))

        # Right: editor
        self.editor = JobEditor(f)
        self.editor.pack(side="left", fill="both", expand=True, padx=4, pady=4)

    def _build_run_tab(self, nb: ttk.Notebook):
        f = ttk.Frame(nb)
        nb.add(f, text="Run & Results")

        top = ttk.Frame(f)
        top.pack(fill="x", padx=4, pady=4)
        ttk.Button(top, text="Run extraction", command=self._on_run).pack(side="left", padx=2)
        ttk.Button(top, text="Copy results to clipboard (TSV)",
                   command=self._copy_results).pack(side="left", padx=2)
        ttk.Button(top, text="Open output CSV folder",
                   command=self._open_csv_folder).pack(side="left", padx=2)

        ttk.Label(f, text="Status:").pack(anchor="w", padx=6)
        self.status = tk.Text(f, height=6, wrap="word")
        self.status.pack(fill="x", padx=6, pady=2)

        ttk.Label(f, text="Results:").pack(anchor="w", padx=6, pady=(8, 0))
        tree_frame = ttk.Frame(f)
        tree_frame.pack(fill="both", expand=True, padx=6, pady=2)
        self.results_tree = ttk.Treeview(tree_frame, show="headings")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.results_tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.results_tree.xview)
        self.results_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.results_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="we")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

    # -- Job list ops --------------------------------------------------

    def _refresh_jobs_list(self, select_index: Optional[int] = None):
        # Sync batch flags length to jobs list
        while len(self._batch_flags) < len(self.cfg.jobs):
            self._batch_flags.append(True)
        self._batch_flags = self._batch_flags[:len(self.cfg.jobs)]

        # Destroy old row widgets
        for row in self._job_rows:
            row["frame"].destroy()
        self._job_rows.clear()

        # Build new rows
        for i, j in enumerate(self.cfg.jobs):
            row_frame = ttk.Frame(self._jobs_inner)
            row_frame.pack(fill="x", padx=2, pady=1)

            var = tk.BooleanVar(value=self._batch_flags[i])
            cb = ttk.Checkbutton(row_frame, variable=var,
                                 command=lambda idx=i: self._on_batch_toggle(idx))
            cb.pack(side="left", padx=(4, 2))

            lbl = tk.Label(row_frame, text=j.name, anchor="w",
                           font=("TkDefaultFont", 10), bg="white",
                           cursor="hand2", padx=4, pady=3)
            lbl.pack(side="left", fill="x", expand=True)
            lbl.bind("<Button-1>", lambda e, idx=i: self._select_job(idx))

            self._job_rows.append({"frame": row_frame, "var": var, "label": lbl})

        if select_index is not None and 0 <= select_index < len(self.cfg.jobs):
            self._select_job(select_index)
        else:
            self._current_job_index = None

    def _on_batch_toggle(self, idx: int):
        """Checkbox clicked — update batch flag."""
        self._batch_flags[idx] = self._job_rows[idx]["var"].get()
        # Clear batch cache since selection changed
        self._batch_rows = []
        self._batch_cols = []

    def _select_job(self, idx: int):
        """Select a job for editing (click on its name label)."""
        # Commit edits to the previously-selected job before switching.
        if self._current_job_index is not None and self._current_job_index != idx:
            try:
                self.cfg.jobs[self._current_job_index] = self.editor.commit()
                # Update label text in case name changed
                self._job_rows[self._current_job_index]["label"].config(
                    text=self.cfg.jobs[self._current_job_index].name)
            except ValueError as e:
                messagebox.showerror("Cannot switch jobs", str(e), parent=self)
                return

        # Highlight selected row
        for i, row in enumerate(self._job_rows):
            row["label"].config(bg="#cde4f7" if i == idx else "white")

        self.editor.bind_job(self.cfg.jobs[idx])
        self._current_job_index = idx

    def _job_add(self):
        self._commit_current_silent()
        new = default_job(f"Job {len(self.cfg.jobs) + 1}")
        self.cfg.jobs.append(new)
        self._batch_flags.append(True)
        self._refresh_jobs_list(select_index=len(self.cfg.jobs) - 1)

    def _job_dup(self):
        if self._current_job_index is None:
            return
        self._commit_current_silent()
        src = self.cfg.jobs[self._current_job_index]
        from copy import deepcopy
        new = deepcopy(src)
        new.name = src.name + " (copy)"
        self.cfg.jobs.insert(self._current_job_index + 1, new)
        self._batch_flags.insert(self._current_job_index + 1, True)
        self._refresh_jobs_list(select_index=self._current_job_index + 1)

    def _job_del(self):
        if self._current_job_index is None or len(self.cfg.jobs) <= 1:
            messagebox.showinfo("Cannot delete", "At least one job must remain.", parent=self)
            return
        idx = self._current_job_index
        del self.cfg.jobs[idx]
        del self._batch_flags[idx]
        new_idx = min(idx, len(self.cfg.jobs) - 1)
        self._refresh_jobs_list(select_index=new_idx)

    def _commit_current_silent(self):
        """Commit the current editor's edits, swallowing validation errors
        (used right before list mutations where we don't want to block)."""
        if self._current_job_index is None:
            return
        try:
            self.cfg.jobs[self._current_job_index] = self.editor.commit()
        except ValueError:
            pass

    def _on_batch_extract(self):
        """Show cached batch results or run a fresh extraction."""
        if self._batch_rows:
            BatchDialog(self, self._batch_rows, self._batch_cols,
                        on_rerun=self._run_batch_extract)
            return
        self._run_batch_extract()

    def _run_batch_extract(self):
        """Run all jobs with a progress dialog and show results."""
        self._read_setup_into_cfg()
        self._commit_current_silent()

        try:
            gfe._validate_config(self.cfg)
        except Exception as e:
            messagebox.showerror("Config invalid", str(e), parent=self)
            return
        if not self.cfg.gsa_file:
            messagebox.showinfo("GSA file missing",
                                "Set the GSA file path on the Setup tab.", parent=self)
            return

        try:
            adapter = gfe.open_gsa_model(self.cfg.gsa_file)
        except Exception as e:
            messagebox.showerror("GSA file error", str(e), parent=self)
            return

        # Only run jobs that are batch-enabled
        batch_jobs = [
            job for i, job in enumerate(self.cfg.jobs)
            if i < len(self._batch_flags) and self._batch_flags[i]
        ]
        if not batch_jobs:
            messagebox.showinfo("No jobs selected",
                                "Enable at least one job for batch "
                                "(double-click in the Jobs list).", parent=self)
            return

        cols = gfe.unified_columns(batch_jobs)
        all_rows: list[dict] = []
        errors: list[str] = []

        detected = adapter.discover_units()
        if detected is None:
            gsa_f, gsa_m = gfe.DEFAULT_GSA_FORCE, gfe.DEFAULT_GSA_MOMENT
        else:
            gsa_f, gsa_m = detected

        prog = BatchProgressDialog(self, len(batch_jobs))
        for i, job in enumerate(batch_jobs):
            if prog.cancelled:
                break
            prog.set_job(i, job.name, len(batch_jobs))
            try:
                rows = gfe.run_job(
                    adapter, job, gsa_f, gsa_m,
                    self.cfg.units, self.cfg.signs,
                    progress_cb=lambda ti, nt, pi, np:
                        prog.set_perm_progress(ti, nt, pi, np),
                )
                all_rows.extend(rows)
            except Exception as e:
                errors.append(f"{job.name}: {e}")
        prog.finish()

        if prog.cancelled and not all_rows:
            return

        if errors:
            messagebox.showwarning(
                "Some jobs failed",
                "\n".join(errors),
                parent=self,
            )
        if not all_rows:
            messagebox.showinfo("No results",
                                "Extraction produced no rows.", parent=self)
            return

        self._batch_rows = all_rows
        self._batch_cols = cols
        BatchDialog(self, all_rows, cols, on_rerun=self._run_batch_extract)

    # -- File pickers --------------------------------------------------

    def _pick_gsa_file(self):
        path = filedialog.askopenfilename(
            parent=self,
            title="Select GSA model",
            filetypes=[("GSA files", "*.gwb *.gwa"), ("All files", "*.*")],
        )
        if path:
            self.gsa_file_var.set(path)

    def _pick_save(self, ext: str, var: tk.StringVar):
        path = filedialog.asksaveasfilename(
            parent=self,
            title=f"Output {ext.upper()} file",
            defaultextension=f".{ext}",
            filetypes=[(f"{ext.upper()} files", f"*.{ext}"), ("All files", "*.*")],
        )
        if path:
            var.set(path)

    # -- Setup -> Config sync -----------------------------------------

    def _read_setup_into_cfg(self):
        self.cfg.gsa_file = self.gsa_file_var.get().strip()
        self.cfg.output_csv = self.csv_var.get().strip() or None
        self.cfg.output_tsv = self.tsv_var.get().strip() or None
        self.cfg.units.output_force = self.output_force_var.get().strip() or "kip"
        self.cfg.units.output_moment = self.output_moment_var.get().strip() or "kip-in"
        self.cfg.signs.axial_compression_positive_in_gsa = bool(self.axial_comp_pos_var.get())
        self.cfg.signs.moment_hogging_positive_in_gsa = bool(self.moment_hog_pos_var.get())

    def _write_cfg_into_setup(self):
        self.gsa_file_var.set(self.cfg.gsa_file or "")
        self.csv_var.set(self.cfg.output_csv or "")
        self.tsv_var.set(self.cfg.output_tsv or "")
        self.output_force_var.set(self.cfg.units.output_force)
        self.output_moment_var.set(self.cfg.units.output_moment)
        self.axial_comp_pos_var.set(self.cfg.signs.axial_compression_positive_in_gsa)
        self.moment_hog_pos_var.set(self.cfg.signs.moment_hogging_positive_in_gsa)

    # -- New / Load / Save --------------------------------------------

    def _on_new(self):
        if not messagebox.askokcancel("New config",
                                      "Discard current config and start fresh?", parent=self):
            return
        self.cfg = empty_config()
        self.current_config_path = None
        self.path_label.config(text="(unsaved)")
        self._batch_rows = []
        self._batch_cols = []
        self._batch_flags = []
        self._write_cfg_into_setup()
        self._refresh_jobs_list(select_index=0)

    def _on_load(self):
        path = filedialog.askopenfilename(
            parent=self,
            title="Load config",
            filetypes=[("JSON files", "*.json"), ("YAML files", "*.yaml *.yml"), ("All files", "*.*")],
        )
        if path:
            self._load_config_path(path)

    def _load_config_path(self, path: str):
        try:
            self.cfg = gfe.load_config(path)
        except Exception as e:
            messagebox.showerror("Load failed", str(e), parent=self)
            return
        self.current_config_path = path
        self.path_label.config(text=os.path.basename(path))
        self._batch_rows = []
        self._batch_cols = []
        self._batch_flags = []
        self._write_cfg_into_setup()
        self._refresh_jobs_list(select_index=0)
        self._set_status(f"Loaded {path}")

    def _on_save(self):
        if not self.current_config_path:
            return self._on_save_as()
        self._do_save(self.current_config_path)

    def _on_save_as(self):
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Save config",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("YAML files", "*.yaml *.yml")],
        )
        if path:
            self._do_save(path)

    def _do_save(self, path: str):
        self._read_setup_into_cfg()
        self._commit_current_silent()
        try:
            gfe.save_config(self.cfg, path)
        except Exception as e:
            messagebox.showerror("Save failed", str(e), parent=self)
            return
        self.current_config_path = path
        self.path_label.config(text=os.path.basename(path))
        self._set_status(f"Saved {path}")

    # -- Run -----------------------------------------------------------

    def _on_run(self):
        self._read_setup_into_cfg()
        self._commit_current_silent()
        self._set_status("Running…")
        self.update_idletasks()

        # Validate a fresh in-memory config before touching gsapy.
        try:
            gfe._validate_config(self.cfg)
        except Exception as e:
            self._set_status(f"Config invalid: {e}")
            messagebox.showerror("Config invalid", str(e), parent=self)
            return
        if not self.cfg.gsa_file:
            self._set_status("Set the GSA file path on the Setup tab.")
            return

        try:
            adapter = gfe.open_gsa_model(self.cfg.gsa_file)
        except Exception as e:
            self._set_status(f"Could not open GSA file:\n{e}")
            messagebox.showerror("GSA file error", str(e), parent=self)
            return

        cols = gfe.unified_columns(self.cfg.jobs)
        all_rows: list[dict] = []
        log = io.StringIO()

        # Auto-detect the model's display units (GSA returns numbers in
        # whatever units the model is configured to display).
        detected = adapter.discover_units()
        if detected is None:
            gsa_f, gsa_m = gfe.DEFAULT_GSA_FORCE, gfe.DEFAULT_GSA_MOMENT
            log.write(
                f"WARNING: could not auto-detect GSA units; assuming "
                f"{gsa_f} / {gsa_m}. "
                f"Verify a known value by hand before trusting the output.\n"
            )
        else:
            gsa_f, gsa_m = detected
            log.write(
                f"GSA model units detected: force={gsa_f}, moment={gsa_m}. "
                f"Output units: {self.cfg.units.output_force} / "
                f"{self.cfg.units.output_moment}.\n"
            )
        for job in self.cfg.jobs:
            try:
                rows = gfe.run_job(adapter, job, gsa_f, gsa_m,
                                   self.cfg.units, self.cfg.signs)
                all_rows.extend(rows)
                log.write(f"[OK] {job.name}: {len(rows)} rows\n")
            except Exception as e:
                log.write(f"[FAIL] {job.name}: {e}\n")
                log.write(traceback.format_exc(limit=2))

        # Write outputs
        if self.cfg.output_csv:
            try:
                gfe.write_csv(all_rows, cols, self.cfg.output_csv)
                log.write(f"Wrote {self.cfg.output_csv}\n")
            except Exception as e:
                log.write(f"CSV write failed: {e}\n")
        if self.cfg.output_tsv:
            try:
                gfe.write_tsv(all_rows, cols, self.cfg.output_tsv)
                log.write(f"Wrote {self.cfg.output_tsv}\n")
            except Exception as e:
                log.write(f"TSV write failed: {e}\n")

        self._set_status(log.getvalue() or "Done.")
        self._show_results(all_rows, cols)

    def _show_results(self, rows: list[dict], cols: list[str]):
        self.last_results = rows
        self.last_columns = cols
        # Reset the tree's columns
        for c in self.results_tree["columns"]:
            self.results_tree.heading(c, text="")
        self.results_tree["columns"] = cols
        for c in cols:
            self.results_tree.heading(c, text=c)
            self.results_tree.column(c, width=90, anchor="center", stretch=False)
        for iid in self.results_tree.get_children():
            self.results_tree.delete(iid)
        for r in rows:
            vals = []
            for c in cols:
                v = r.get(c, "")
                if isinstance(v, float):
                    vals.append(f"{v:.2f}")
                else:
                    vals.append("" if v is None else str(v))
            self.results_tree.insert("", "end", values=vals)

    def _copy_results(self):
        if not self.last_results:
            self._set_status("Nothing to copy — run an extraction first.")
            return
        buf = io.StringIO()
        buf.write("\t".join(self.last_columns) + "\n")
        for r in self.last_results:
            cells = []
            for c in self.last_columns:
                v = r.get(c, "")
                if isinstance(v, float):
                    cells.append(f"{v:.6g}")
                else:
                    cells.append("" if v is None else str(v))
            buf.write("\t".join(cells) + "\n")
        self.clipboard_clear()
        self.clipboard_append(buf.getvalue())
        self._set_status(f"Copied {len(self.last_results)} row(s) as TSV to clipboard.")

    def _open_csv_folder(self):
        path = self.csv_var.get().strip()
        if not path:
            return
        folder = os.path.dirname(path) or "."
        if os.path.isdir(folder):
            try:
                os.startfile(folder)  # Windows-only; fine for this app.
            except Exception as e:
                self._set_status(f"Open folder failed: {e}")

    def _set_status(self, text: str):
        self.status.delete("1.0", "end")
        self.status.insert("1.0", text)


def main(argv: Optional[list[str]] = None):
    argv = argv or sys.argv[1:]
    initial = argv[0] if argv else None
    app = App(initial_config_path=initial)
    app.mainloop()


if __name__ == "__main__":
    main()
