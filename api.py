"""
pywebview JS↔Python bridge.
Exposes `calculate` and `calculate_pt` methods that the JS frontend calls.
"""
import json
import os
import webview
import calc_engine
import pt_engine


class Api:
    def __init__(self):
        self.window = None  # set by app.py after create_window

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
        """Save project data to a user-chosen .aashto.json file."""
        try:
            result = self.window.create_file_dialog(
                dialog_type=webview.SAVE_DIALOG,
                save_filename='project.aashto.json',
                file_types=('AASHTO Project (*.aashto.json)',)
            )
            if not result:
                return json.dumps({"cancelled": True})
            filepath = result if isinstance(result, str) else result[0]
            if not filepath.endswith('.aashto.json'):
                filepath += '.aashto.json'
            # Validate JSON before writing
            json.loads(project_json)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(project_json)
            return json.dumps({"path": filepath})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def load_project(self):
        """Open a file dialog and return the project JSON contents."""
        try:
            result = self.window.create_file_dialog(
                dialog_type=webview.OPEN_DIALOG,
                file_types=('AASHTO Project (*.aashto.json)',)
            )
            if not result:
                return json.dumps({"cancelled": True})
            filepath = result if isinstance(result, str) else result[0]
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            # Validate JSON
            data = json.loads(content)
            if 'version' not in data or 'sections' not in data:
                return json.dumps({"error": "Invalid project file: missing 'version' or 'sections'"})
            return content
        except json.JSONDecodeError:
            return json.dumps({"error": "File is not valid JSON"})
        except Exception as e:
            return json.dumps({"error": str(e)})
