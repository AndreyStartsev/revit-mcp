# -*- coding: utf-8 -*-
"""
Revit MCP Server - Standard Model Context Protocol (MCP) Bridge for Autodesk Revit.
Exposes Revit automation, inspection, and execution tools to LLM agents (Claude Desktop, Cursor, Antigravity, etc.).
"""

import os
import sys
import json
import time
import socket
import tempfile
import urllib.request
import urllib.error
import traceback
from typing import Optional, Dict, Any, List

from mcp.server.mcpserver import MCPServer

CANDIDATE_PORTS = [40001, 40002, 40003, 40004, 40005, 40006, 40007, 40008, 40009, 40010]

DEFAULT_CACHE_DIR = os.path.join(tempfile.gettempdir(), "revit_mcp")
SAVE_DIR = os.environ.get("REVIT_MCP_CACHE_DIR", DEFAULT_CACHE_DIR)
SESSION_BINDING_FILE = os.path.join(SAVE_DIR, "session_binding.json")

_BOUND_PORT: Optional[int] = None
_BOUND_DOC: Optional[str] = None

server = MCPServer(
    name="revit-mcp",
    version="1.0.0",
    instructions="Provides direct tools to query, inspect, automate, and control Autodesk Revit models via pyRevit MCP with deterministic instance binding."
)


def _load_binding():
    global _BOUND_PORT, _BOUND_DOC
    if _BOUND_PORT:
        return
    if os.path.exists(SESSION_BINDING_FILE):
        try:
            with open(SESSION_BINDING_FILE, "r") as f:
                data = json.load(f)
                _BOUND_PORT = data.get("bound_port")
                _BOUND_DOC = data.get("bound_doc")
        except Exception:
            pass


def _save_binding(port: Optional[int], doc_title: Optional[str] = None):
    global _BOUND_PORT, _BOUND_DOC
    _BOUND_PORT = port
    _BOUND_DOC = doc_title
    try:
        if not os.path.exists(SAVE_DIR):
            os.makedirs(SAVE_DIR)
        with open(SESSION_BINDING_FILE, "w") as f:
            json.dump({"bound_port": port, "bound_doc": doc_title, "updated_at": time.time()}, f, indent=2)
    except Exception:
        pass


def _get_all_revit_instances() -> List[Dict[str, Any]]:
    """Scans candidate ports and returns a list of status dictionaries for all active Revit instances."""
    _load_binding()
    instances = []

    # Fast TCP pre-check
    open_ports = []
    for port in CANDIDATE_PORTS:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.04)
        if s.connect_ex(('127.0.0.1', port)) == 0:
            open_ports.append(port)
        s.close()

    for port in open_ports:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/status", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=0.6) as resp:
                if resp.status == 200:
                    body = resp.read().decode("utf-8")
                    try:
                        data = json.loads(body)
                        data["port"] = port
                        data["is_bound"] = (port == _BOUND_PORT)
                        instances.append(data)
                    except Exception:
                        instances.append({"status": "running", "port": port, "is_bound": (port == _BOUND_PORT)})
        except Exception:
            pass

    return instances


def _find_active_revit_port(target_port: Optional[int] = None, target_doc: Optional[str] = None) -> Optional[int]:
    """Finds and maintains a strict binding to a specific Revit instance."""
    if target_port:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{target_port}/api/status", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    _save_binding(target_port, data.get("doc_title"))
                    return target_port
        except Exception:
            pass
        return None

    instances = _get_all_revit_instances()
    if not instances:
        return None

    if target_doc:
        target_doc_lower = target_doc.strip().lower()
        for inst in instances:
            doc_title = str(inst.get("doc_title", "")).lower()
            doc_path = str(inst.get("doc_path", "")).lower()
            if target_doc_lower in doc_title or target_doc_lower in doc_path or doc_title in target_doc_lower:
                _save_binding(inst.get("port"), inst.get("doc_title"))
                return inst.get("port")
        return None

    _load_binding()
    global _BOUND_PORT
    if _BOUND_PORT:
        for inst in instances:
            if inst.get("port") == _BOUND_PORT:
                _save_binding(_BOUND_PORT, inst.get("doc_title"))
                return _BOUND_PORT

    chosen_port = instances[0].get("port")
    _save_binding(chosen_port, instances[0].get("doc_title"))
    return chosen_port


def _send_revit_execute(code: str, timeout: float = 60.0, target_port: Optional[int] = None, target_doc: Optional[str] = None) -> Dict[str, Any]:
    """Sends arbitrary Python code to the bound Revit execution endpoint."""
    port = _find_active_revit_port(target_port=target_port, target_doc=target_doc)
    if not port:
        return {
            "success": False,
            "error": "No active Revit server found. Please ensure Autodesk Revit is open and 'Start Server' in the Revit MCP panel is ON."
        }

    payload = {"code": code}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/execute",
        data=data,
        headers={"Content-Type": "application/json"}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read().decode("utf-8")
            res_dict = json.loads(resp_body)
            if isinstance(res_dict, dict):
                res_dict["executed_on_port"] = port
                res_dict["bound_port"] = _BOUND_PORT
                res_dict["bound_doc"] = _BOUND_DOC
            return res_dict
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
            err_dict = json.loads(err_body)
            if isinstance(err_dict, dict):
                err_dict["executed_on_port"] = port
                err_dict["bound_port"] = _BOUND_PORT
                err_dict["bound_doc"] = _BOUND_DOC
                if err_dict.get("is_modal_blocked"):
                    title = err_dict.get("modal_title") or "Modal Dialog"
                    err_dict["message"] = f"Revit UI is blocked by modal window ('{title}'). Please close or confirm the modal dialog in Revit."
            return err_dict
        except Exception:
            return {"success": False, "status_code": e.code, "error": str(e), "executed_on_port": port}
    except Exception as ex:
        return {"success": False, "error": str(ex), "executed_on_port": port}


# ==============================================================================
# MCP TOOLS
# ==============================================================================

@server.tool()
def revit_ping(port: Optional[int] = None, doc_name: Optional[str] = None) -> str:
    """Checks connection health of the Revit MCP Server and reports the active instance."""
    target_port = _find_active_revit_port(target_port=port, target_doc=doc_name)
    if not target_port:
        return json.dumps({
            "status": "offline",
            "error": "No active Revit instance found. Open Revit and start 'Revit MCP' from ribbon."
        }, indent=2)

    try:
        req = urllib.request.Request(f"http://127.0.0.1:{target_port}/api/status", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            data["ping"] = "pong"
            data["bound_port"] = target_port
            return json.dumps(data, indent=2)
    except Exception as ex:
        return json.dumps({"status": "error", "message": str(ex), "port": target_port}, indent=2)


@server.tool()
def revit_list_instances() -> str:
    """Lists all currently active Autodesk Revit instances across all ports and indicates which instance is bound."""
    instances = _get_all_revit_instances()
    return json.dumps({
        "count": len(instances),
        "bound_port": _BOUND_PORT,
        "bound_doc": _BOUND_DOC,
        "instances": instances
    }, indent=2)


@server.tool()
def revit_set_active_instance(port: Optional[int] = None, doc_name: Optional[str] = None) -> str:
    """Binds this session to a specific Revit instance/model (by port or document title).
    All subsequent operations will execute on this instance.
    """
    if not port and not doc_name:
        return json.dumps({"error": "Must provide either port (e.g. 40001) or doc_name (e.g. 'Project1.rvt')"}, indent=2)

    chosen_port = _find_active_revit_port(target_port=port, target_doc=doc_name)
    if not chosen_port:
        return json.dumps({
            "success": False,
            "error": f"Instance with port={port} or doc_name='{doc_name}' not found."
        }, indent=2)

    return json.dumps({
        "success": True,
        "message": f"Successfully bound session to Revit instance on port {chosen_port}",
        "bound_port": chosen_port,
        "bound_doc": _BOUND_DOC
    }, indent=2)


@server.tool()
def revit_get_active_model(port: Optional[int] = None, doc_name: Optional[str] = None) -> str:
    """Retrieves metadata about the currently open model in the bound Revit instance (title, file path, active view, level)."""
    code = """
import os
from Autodesk.Revit.DB import FilteredElementCollector, Level, View3D

doc_info = {}
if doc:
    doc_info['title'] = doc.Title
    doc_info['path'] = doc.PathName
    doc_info['is_family'] = doc.IsFamilyDocument
    doc_info['is_workshared'] = doc.IsWorkshared
    doc_info['is_modified'] = doc.IsModified
    
    view = doc.ActiveView
    if view:
        doc_info['active_view'] = {
            'id': view.Id.IntegerValue if hasattr(view.Id, 'IntegerValue') else view.Id.Value,
            'name': view.Name,
            'view_type': str(view.ViewType),
            'scale': getattr(view, 'Scale', 100),
            'is_3d': isinstance(view, View3D)
        }
        if hasattr(view, 'GenLevel') and view.GenLevel:
            doc_info['active_view']['level'] = {
                'id': view.GenLevel.Id.IntegerValue if hasattr(view.GenLevel.Id, 'IntegerValue') else view.GenLevel.Id.Value,
                'name': view.GenLevel.Name,
                'elevation_ft': view.GenLevel.Elevation,
                'elevation_mm': round(view.GenLevel.Elevation * 304.8, 1)
            }
            
    # Levels summary
    levels = FilteredElementCollector(doc).OfClass(Level).ToElements()
    doc_info['levels'] = [
        {
            'id': l.Id.IntegerValue if hasattr(l.Id, 'IntegerValue') else l.Id.Value,
            'name': l.Name,
            'elevation_mm': round(l.Elevation * 304.8, 1)
        } for l in levels
    ]
response_data['model'] = doc_info
"""
    res = _send_revit_execute(code, target_port=port, target_doc=doc_name)
    return json.dumps(res, indent=2)


@server.tool()
def revit_execute_python(code: str, port: Optional[int] = None, doc_name: Optional[str] = None) -> str:
    """Executes arbitrary Python code inside Autodesk Revit on the main UI thread.
    
    Provides:
      - doc: Active Revit Document
      - uidoc: Active UIDocument
      - uiapp: UIApplication
      - app: Application
      - response_data: Dict to store return values (e.g. response_data['my_key'] = ...)
    
    Always wrap model modifications in a Transaction:
      t = Transaction(doc, 'Action Name')
      t.Start()
      ...
      t.Commit()
    """
    res = _send_revit_execute(code, target_port=port, target_doc=doc_name)
    return json.dumps(res, indent=2)


@server.tool()
def revit_get_selection(port: Optional[int] = None, doc_name: Optional[str] = None) -> str:
    """Retrieves information about currently selected elements in the bound Revit document."""
    code = """
sel_ids = uidoc.Selection.GetElementIds() if uidoc else []
elements = []

for eid in sel_ids:
    el = doc.GetElement(eid)
    if not el:
        continue
    int_id = eid.IntegerValue if hasattr(eid, 'IntegerValue') else eid.Value
    cat_name = el.Category.Name if el.Category else "Unknown"
    el_name = getattr(el, 'Name', '')
    
    # Extract core parameters
    params = {}
    for p in el.Parameters:
        try:
            if p.HasValue:
                p_name = p.Definition.Name
                val = p.AsValueString() or p.AsString()
                if val is None:
                    if str(p.StorageType) == 'Double':
                        val = p.AsDouble()
                    elif str(p.StorageType) == 'Integer':
                        val = p.AsInteger()
                params[p_name] = val
        except Exception:
            pass
            
    elements.append({
        'id': int_id,
        'category': cat_name,
        'name': el_name,
        'parameters': params
    })

response_data['selection_count'] = len(elements)
response_data['elements'] = elements
"""
    res = _send_revit_execute(code, target_port=port, target_doc=doc_name)
    return json.dumps(res, indent=2)


@server.tool()
def revit_get_element_geometry(element_ids: Optional[List[int]] = None, port: Optional[int] = None, doc_name: Optional[str] = None) -> str:
    """Retrieves high-precision geometric summary (exact mm bounding box, location, rotation, level elevation) for elements."""
    code = f"""
import math
from Autodesk.Revit.DB import ElementId, LocationPoint, LocationCurve

target_ids = {element_ids or '[]'}
if not target_ids and uidoc:
    target_ids = [eid.IntegerValue if hasattr(eid, 'IntegerValue') else eid.Value for eid in uidoc.Selection.GetElementIds()]

results = []
view = doc.ActiveView

for tid in target_ids:
    el = doc.GetElement(ElementId(tid))
    if not el:
        continue
        
    info = {{'id': tid, 'name': getattr(el, 'Name', ''), 'category': el.Category.Name if el.Category else ''}}
    
    # BoundingBox
    bbox = el.get_BoundingBox(view) or el.get_BoundingBox(None)
    if bbox:
        info['bbox_mm'] = {{
            'min': [round(bbox.Min.X * 304.8, 1), round(bbox.Min.Y * 304.8, 1), round(bbox.Min.Z * 304.8, 1)],
            'max': [round(bbox.Max.X * 304.8, 1), round(bbox.Max.Y * 304.8, 1), round(bbox.Max.Z * 304.8, 1)],
            'size': [
                round((bbox.Max.X - bbox.Min.X) * 304.8, 1),
                round((bbox.Max.Y - bbox.Min.Y) * 304.8, 1),
                round((bbox.Max.Z - bbox.Min.Z) * 304.8, 1)
            ]
        }}
        
    # Location
    loc = el.Location
    if isinstance(loc, LocationPoint):
        pt = loc.Point
        info['location_mm'] = [round(pt.X * 304.8, 1), round(pt.Y * 304.8, 1), round(pt.Z * 304.8, 1)]
        info['rotation_deg'] = round(math.degrees(loc.Rotation), 2) if hasattr(loc, 'Rotation') else 0.0
    elif isinstance(loc, LocationCurve):
        c = loc.Curve
        p0 = c.GetEndPoint(0)
        p1 = c.GetEndPoint(1)
        info['start_mm'] = [round(p0.X * 304.8, 1), round(p0.Y * 304.8, 1), round(p0.Z * 304.8, 1)]
        info['end_mm'] = [round(p1.X * 304.8, 1), round(p1.Y * 304.8, 1), round(p1.Z * 304.8, 1)]
        info['length_mm'] = round(c.Length * 304.8, 1)
        
    results.append(info)

response_data['elements'] = results
"""
    res = _send_revit_execute(code, target_port=port, target_doc=doc_name)
    return json.dumps(res, indent=2)


@server.tool()
def revit_get_warnings(port: Optional[int] = None, doc_name: Optional[str] = None) -> str:
    """Retrieves all active model warnings from the bound Revit instance."""
    code = """
warnings_data = []
if doc:
    warnings = doc.GetWarnings()
    for w in warnings:
        elem_ids = [eid.IntegerValue if hasattr(eid, 'IntegerValue') else eid.Value for eid in w.GetFailingElements()]
        warnings_data.append({
            'description': w.GetDescriptionText(),
            'severity': str(w.GetSeverity()),
            'failing_elements': elem_ids
        })
response_data['count'] = len(warnings_data)
response_data['warnings'] = warnings_data
"""
    res = _send_revit_execute(code, target_port=port, target_doc=doc_name)
    return json.dumps(res, indent=2)


@server.tool()
def revit_capture_screenshot(port: Optional[int] = None, doc_name: Optional[str] = None) -> str:
    """Triggers and captures a high-resolution screenshot of the currently active view in Revit."""
    target_port = _find_active_revit_port(target_port=port, target_doc=doc_name)
    if not target_port:
        return json.dumps({"status": "error", "message": "No active Revit instance found"}, indent=2)

    try:
        req = urllib.request.Request(f"http://127.0.0.1:{target_port}/api/screenshot", data=b"{}", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60.0) as resp:
            body = resp.read().decode("utf-8")
            return body
    except Exception as ex:
        return json.dumps({"status": "error", "message": str(ex)}, indent=2)


@server.tool()
def revit_get_latest_screenshot() -> str:
    """Retrieves metadata and file path of the most recently captured screenshot or user snip."""
    latest_meta = os.path.join(SAVE_DIR, "latest_screenshot.json")
    if os.path.exists(latest_meta):
        try:
            with open(latest_meta, "r") as f:
                return json.dumps(json.load(f), indent=2)
        except Exception as ex:
            return json.dumps({"error": f"Failed to read screenshot metadata: {str(ex)}"}, indent=2)
    return json.dumps({"status": "not_found", "message": "No screenshot captured yet."}, indent=2)


@server.tool()
def revit_request_user_selection(prompt: str, categories: Optional[List[str]] = None, multiple: bool = False, timeout: int = 90, port: Optional[int] = None, doc_name: Optional[str] = None) -> str:
    """Proactively requests the user in Autodesk Revit to select elements.
    The HUD button 'Pick Elements' will flash and wait for user clicks.
    
    Args:
        prompt: Instruction shown to user in Revit HUD (e.g. 'Select the room boundary').
        categories: Optional list of category names to restrict selection (e.g. ['Rooms', 'Walls']).
        multiple: If False, single click picks element instantly. If True, user picks multiple elements and clicks 'Finish'.
        timeout: Maximum seconds to wait (default 90).
    """
    target_port = _find_active_revit_port(target_port=port, target_doc=doc_name)
    if not target_port:
        return json.dumps({"success": False, "error": "No active Revit instance found"}, indent=2)

    payload = {
        "prompt": prompt,
        "categories": categories,
        "multiple": multiple,
        "timeout": timeout
    }
    data = json.dumps(payload).encode("utf-8")
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{target_port}/api/request_user_selection", data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=float(timeout + 5)) as resp:
            return resp.read().decode("utf-8")
    except Exception as ex:
        return json.dumps({"success": False, "error": str(ex)}, indent=2)


@server.tool()
def revit_request_user_snip(prompt: str, timeout: int = 90, port: Optional[int] = None, doc_name: Optional[str] = None) -> str:
    """Proactively requests the user in Autodesk Revit to snip a region on screen and add drawings/annotations."""
    target_port = _find_active_revit_port(target_port=port, target_doc=doc_name)
    if not target_port:
        return json.dumps({"success": False, "error": "No active Revit instance found"}, indent=2)

    payload = {"prompt": prompt, "timeout": timeout}
    data = json.dumps(payload).encode("utf-8")
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{target_port}/api/request_user_snip", data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=float(timeout + 5)) as resp:
            return resp.read().decode("utf-8")
    except Exception as ex:
        return json.dumps({"success": False, "error": str(ex)}, indent=2)


@server.tool()
def revit_set_busy(busy: bool = True, message: Optional[str] = None, activity: Optional[str] = None, port: Optional[int] = None, doc_name: Optional[str] = None) -> str:
    """Sets the visual busy indicator and background color of the Revit MCP HUD."""
    target_port = _find_active_revit_port(target_port=port, target_doc=doc_name)
    if not target_port:
        return json.dumps({"success": False, "error": "No active Revit instance found"}, indent=2)

    payload = {"busy": busy, "message": message, "activity": activity}
    data = json.dumps(payload).encode("utf-8")
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{target_port}/api/set_busy", data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.read().decode("utf-8")
    except Exception as ex:
        return json.dumps({"success": False, "error": str(ex)}, indent=2)


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
