"""
pywebview JS↔Python bridge.
Exposes `calculate` and `calculate_pt` methods that the JS frontend calls.
"""
import json
import os
import webview
import calc_engine
import pt_engine
import csi_import
import colshaft_demands
import colshaft_engine


class Api:
    def __init__(self):
        self._window = None  # set by app.py after create_window (private to avoid pywebview introspection issues)

    @property
    def window(self):
        return self._window

    @window.setter
    def window(self, value):
        self._window = value

    def calculate(self, inputs_json):
        """
        Called from JS: pywebview.api.calculate(JSON.stringify({inputs, demandRows, activeRow}))
        Returns JSON string with all results.
        """
        try:
            data = json.loads(inputs_json)
            raw_inputs = data["inputs"]
            demand_rows = data["demandRows"]
            active_row = data.get("activeRow", 0)
            results = calc_engine.calculate_all(raw_inputs, demand_rows, active_row)
            return json.dumps(results)
        except Exception as e:
            return json.dumps({"error": str(e)})

    def calculate_pt(self, pt_inputs_json):
        """
        Called from JS: pywebview.api.calculate_pt(JSON.stringify({spans, ...loss params...}))
        Returns JSON string with tendon profile and loss summary.
        """
        try:
            inputs = json.loads(pt_inputs_json)
            result = pt_engine.compute_full_profile(inputs)
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    def save_project(self, project_json):
        """Save project data to a user-chosen .aashto.json file (Save As dialog)."""
        try:
            result = self._window.create_file_dialog(
                dialog_type=webview.SAVE_DIALOG,
                save_filename='project.aashto.json',
                file_types=('AASHTO Project (*.aashto.json)',)
            )
            if not result:
                return json.dumps({"cancelled": True})
            filepath = result if isinstance(result, str) else result[0]
            if not filepath.endswith('.aashto.json'):
                filepath += '.aashto.json'
            json.loads(project_json)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(project_json)
            return json.dumps({"path": filepath})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def save_project_to_path(self, project_json, filepath):
        """Overwrite an existing project file without showing a dialog."""
        try:
            if not filepath or not os.path.isfile(filepath):
                return json.dumps({"error": "File not found: " + str(filepath)})
            json.loads(project_json)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(project_json)
            return json.dumps({"path": filepath})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def load_project(self):
        """Open a file dialog and return the project JSON contents plus the filepath."""
        try:
            result = self._window.create_file_dialog(
                dialog_type=webview.OPEN_DIALOG,
                file_types=('AASHTO Project (*.aashto.json)',)
            )
            if not result:
                return json.dumps({"cancelled": True})
            filepath = result if isinstance(result, str) else result[0]
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            data = json.loads(content)
            if 'version' not in data or 'sections' not in data:
                return json.dumps({"error": "Invalid project file: missing 'version' or 'sections'"})
            data['_filepath'] = filepath
            return json.dumps(data)
        except json.JSONDecodeError:
            return json.dumps({"error": "File is not valid JSON"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    # ---- Column on Shaft ------------------------------------------------
    def parse_csi(self, payload_json):
        """
        Called from JS: pywebview.api.parse_csi(JSON.stringify({paste, units}))
        Returns a JSON summary of the parsed CSi frame-forces table:
        {cases, frames, units, warnings, n_envelope, n_rows}.
        """
        try:
            data = json.loads(payload_json)
            pr = csi_import.parse_csi_frame_forces(data.get("paste") or "", data.get("units"))
            cats = {}
            counts = {}
            case_frames = {}    # 2026-10-20: frames per case (UI: P_dead required?)
            for r in pr.rows:
                counts[r.case] = counts.get(r.case, 0) + 1
                case_frames.setdefault(r.case, set()).add(r.frame)
            for c in pr.cases:
                cats[c] = colshaft_demands.default_case_category(c)
            frames = []
            for f in pr.frames:
                frames.append({
                    "name": f,
                    "height_in": colshaft_demands.column_height_in(pr.rows, [f]),
                    "n_rows": sum(1 for r in pr.rows if r.frame == f),
                    "base_end_guess": colshaft_demands.detect_base_end(pr.rows, [f], None, cats),
                })
            return json.dumps({
                "cases": [{"name": c, "count": counts.get(c, 0), "default_category": cats[c],
                           "frames": sorted(case_frames.get(c, ()))}
                          for c in pr.cases],
                "frames": frames,
                "units": pr.units,
                "warnings": list(pr.warnings),
                "n_envelope": pr.n_envelope,
                "n_rows": len(pr.rows),
            }, allow_nan=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    def run_colshaft(self, payload_json):
        """
        Called from JS: pywebview.api.run_colshaft(JSON.stringify(payload))
        Runs the whole Column-on-Shaft design; payload/result schema in
        colshaft_engine.run_colshaft.  Synchronous (pywebview runs it off the UI thread).
        """
        try:
            payload = json.loads(payload_json)
            return json.dumps(colshaft_engine.run_colshaft(payload), allow_nan=False)
        except Exception as e:
            return json.dumps({"error": str(e)})
