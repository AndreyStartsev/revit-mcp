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
import urllib.request
import urllib.error
import traceback
from typing import Optional, Dict, Any, List

from mcp.server.mcpserver import MCPServer
from revit_mcp.client import load_auth_token_for_port
from revit_mcp.paths import (
    CACHE_DIR,
    INSTANCES_DIR,
    SCREENSHOTS_DIR,
    SESSION_BINDING_FILE,
    SERVER_LOG_FILE,
    LATEST_SCREENSHOT_PNG,
    LATEST_SCREENSHOT_JSON,
    LATEST_AGENT_SCREENSHOT_PNG,
    LATEST_AGENT_SCREENSHOT_JSON,
    LATEST_USER_SNIP_PNG,
    LATEST_USER_SNIP_JSON,
    LATEST_SELECTION_JSON,
    ensure_directories,
    is_pid_alive,
)

CANDIDATE_PORTS = [40001, 40002, 40003, 40004, 40005, 40006, 40007, 40008, 40009, 40010]

_BOUND_PORT: Optional[int] = None
_BOUND_DOC: Optional[str] = None
_PORT_DIAGNOSTICS: Dict[int, Dict[str, Any]] = {}
_RECONCILED_STALE_INSTANCES: List[Dict[str, Any]] = []

# Ensure cache directories exist on module import
ensure_directories()


def reconcile_instances() -> List[Dict[str, Any]]:
    """Cleans up stale instance_<port>.json files whose recorded PID is no longer running."""
    cleaned = []
    if not os.path.exists(INSTANCES_DIR):
        return cleaned

    for fname in os.listdir(INSTANCES_DIR):
        if fname.startswith("instance_") and fname.endswith(".json"):
            fpath = os.path.join(INSTANCES_DIR, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                pid = data.get("pid")
                if pid and not is_pid_alive(pid):
                    try:
                        os.remove(fpath)
                    except Exception:
                        pass
                    stale_info = {
                        "port": data.get("port"),
                        "dead_pid": pid,
                        "doc_title": data.get("doc_title"),
                        "cleaned_file": fname,
                        "reason": f"Process PID {pid} is no longer running (terminated or crashed without unregistering)"
                    }
                    cleaned.append(stale_info)
                    _RECONCILED_STALE_INSTANCES.append(stale_info)
            except Exception:
                pass
    return cleaned


def _get_request_headers(port: int) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = load_auth_token_for_port(port)
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-Auth-Token"] = token
    return headers


server = MCPServer(
    name="revit-mcp",
    version="2.0.0",
    instructions="Provides direct tools to query, inspect, automate, and control Autodesk Revit models via pyRevit MCP with deterministic instance binding."
)


def _load_binding():
    global _BOUND_PORT, _BOUND_DOC
    if _BOUND_PORT:
        return
    if os.path.exists(SESSION_BINDING_FILE):
        try:
            with open(SESSION_BINDING_FILE, "r", encoding="utf-8") as f:
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
        ensure_directories()
        with open(SESSION_BINDING_FILE, "w", encoding="utf-8") as f:
            json.dump({"bound_port": port, "bound_doc": doc_title, "updated_at": time.time()}, f, indent=2)
    except Exception:
        pass


def _get_all_revit_instances() -> List[Dict[str, Any]]:
    """Scans candidate ports and returns a list of status dictionaries for all active Revit instances."""
    _load_binding()
    reconcile_instances()
    instances = []

    # Fast TCP pre-check
    open_ports = []
    for port in CANDIDATE_PORTS:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.05)
        if s.connect_ex(('127.0.0.1', port)) == 0:
            open_ports.append(port)
            _PORT_DIAGNOSTICS[port] = {"tcp": "open"}
        else:
            _PORT_DIAGNOSTICS[port] = {"tcp": "closed"}
        s.close()

    for port in open_ports:
        token = load_auth_token_for_port(port)
        _PORT_DIAGNOSTICS[port]["auth_token_loaded"] = bool(token)
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/status", headers=_get_request_headers(port))
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                if resp.status == 200:
                    body = resp.read().decode("utf-8")
                    try:
                        data = json.loads(body)
                        data["port"] = port
                        data["is_bound"] = (port == _BOUND_PORT)
                        instances.append(data)
                        _PORT_DIAGNOSTICS[port]["status"] = "running"
                        _PORT_DIAGNOSTICS[port]["doc_title"] = data.get("doc_title")
                        _PORT_DIAGNOSTICS[port]["pid"] = data.get("pid")
                    except Exception:
                        instances.append({"status": "running", "port": port, "is_bound": (port == _BOUND_PORT)})
                        _PORT_DIAGNOSTICS[port]["status"] = "running"
        except urllib.error.HTTPError as he:
            _PORT_DIAGNOSTICS[port]["http_status"] = he.code
            if he.code == 401:
                _PORT_DIAGNOSTICS[port]["error"] = "401 Unauthorized: token mismatch or token missing in ~/.revit_mcp/instances/"
            else:
                _PORT_DIAGNOSTICS[port]["error"] = f"HTTP {he.code}: {he.reason}"
        except urllib.error.URLError as ue:
            _PORT_DIAGNOSTICS[port]["error"] = f"URLError: {ue.reason}"
        except socket.timeout:
            _PORT_DIAGNOSTICS[port]["error"] = "Request timed out"
        except Exception as ex:
            _PORT_DIAGNOSTICS[port]["error"] = str(ex)

    return instances


def _find_active_revit_port(target_port: Optional[int] = None, target_doc: Optional[str] = None) -> Optional[int]:
    """Finds and maintains a strict binding to a specific Revit instance."""
    if target_port:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{target_port}/api/status", headers=_get_request_headers(target_port))
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    _save_binding(target_port, data.get("doc_title"))
                    return target_port
        except Exception as ex:
            _PORT_DIAGNOSTICS[target_port] = {"target_port": target_port, "error": str(ex)}
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


def _send_revit_execute(code: str, engine: Optional[str] = "cpython", timeout: float = 60.0, target_port: Optional[int] = None, target_doc: Optional[str] = None) -> Dict[str, Any]:
    """Sends arbitrary Python code to the bound Revit execution endpoint."""
    port = _find_active_revit_port(target_port=target_port, target_doc=target_doc)
    if not port:
        # Check diagnostic details across probed ports to provide an actionable explanation
        unauth_ports = [p for p, d in _PORT_DIAGNOSTICS.items() if d.get("http_status") == 401]
        timeout_ports = [p for p, d in _PORT_DIAGNOSTICS.items() if "timed out" in str(d.get("error", "")).lower()]
        open_ports = [p for p, d in _PORT_DIAGNOSTICS.items() if d.get("tcp") == "open"]

        if unauth_ports:
            return {
                "success": False,
                "error": f"Active Revit listener found on port(s) {unauth_ports}, but request was rejected (401 Unauthorized). "
                         f"Check that authentication token in ~/.revit_mcp/instances/instance_{unauth_ports[0]}.json is valid."
            }
        elif timeout_ports:
            return {
                "success": False,
                "error": f"Revit listener found on port(s) {timeout_ports}, but connection timed out."
            }
        elif open_ports:
            return {
                "success": False,
                "error": f"TCP port(s) {open_ports} are open, but /api/status failed: {[_PORT_DIAGNOSTICS[p].get('error') for p in open_ports]}"
            }
        return {
            "success": False,
            "error": "No active Revit server found on candidate ports 40001..40010. Please ensure Autodesk Revit is open and 'Start Server' in the Revit MCP panel is ON."
        }

    payload: Dict[str, Any] = {"code": code}
    if engine:
        payload["engine"] = engine

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/execute",
        data=data,
        headers=_get_request_headers(port)
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read().decode("utf-8")
            res_dict = json.loads(resp_body)
            if isinstance(res_dict, dict):
                res_dict["executed_on_port"] = port
                res_dict["bound_port"] = _BOUND_PORT
                res_dict["bound_doc"] = _BOUND_DOC
                if engine and "engine" not in res_dict:
                    res_dict["engine"] = engine
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
def revit_diagnose() -> str:
    """Performs deep, non-invasive system diagnostic of the Revit MCP environment.
    Reports:
      - Extension loaded status
      - Live vs stale instance files and PIDs
      - Active TCP listeners on candidate ports
      - Auth token status (loaded / missing / mismatch)
      - Last lines of server.log
      - Actionable remediation advice
    Does NOT touch the active Revit model.
    """
    ensure_directories()
    reconciled_stale = reconcile_instances()

    report: Dict[str, Any] = {
        "status": "healthy",
        "cache_dir": CACHE_DIR,
        "bound_port": _BOUND_PORT,
        "bound_doc": _BOUND_DOC,
        "reconciled_stale_instances": reconciled_stale,
        "candidate_ports_checked": CANDIDATE_PORTS,
        "instances_found": [],
        "port_checks": {},
        "server_log_tail": [],
        "remediations": []
    }

    # Inspect instances directory
    registered_files = []
    if os.path.exists(INSTANCES_DIR):
        for fname in os.listdir(INSTANCES_DIR):
            if fname.startswith("instance_") and fname.endswith(".json"):
                fpath = os.path.join(INSTANCES_DIR, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        idata = json.load(f)
                        pid = idata.get("pid")
                        idata["pid_alive"] = is_pid_alive(pid) if pid else False
                        idata["file"] = fname
                        registered_files.append(idata)
                except Exception as ex:
                    registered_files.append({"file": fname, "error": str(ex)})
    report["instances_found"] = registered_files

    # Port checks
    active_ports = []
    for port in CANDIDATE_PORTS:
        diag: Dict[str, Any] = {"port": port, "tcp": "closed", "http_status": None, "auth_token_loaded": False}
        token = load_auth_token_for_port(port)
        diag["auth_token_loaded"] = bool(token)

        # TCP socket check
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.06)
        is_open = (s.connect_ex(('127.0.0.1', port)) == 0)
        s.close()

        if is_open:
            diag["tcp"] = "open"
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{port}/api/status", headers=_get_request_headers(port))
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    diag["http_status"] = resp.status
                    if resp.status == 200:
                        body = json.loads(resp.read().decode("utf-8"))
                        diag["doc_title"] = body.get("doc_title")
                        diag["pid"] = body.get("pid")
                        active_ports.append(port)
            except urllib.error.HTTPError as he:
                diag["http_status"] = he.code
                diag["error"] = f"HTTP {he.code}: {he.reason}"
                if he.code == 401:
                    diag["error"] = "401 Unauthorized: Auth token mismatch or missing"
            except Exception as ex:
                diag["error"] = str(ex)
        report["port_checks"][port] = diag

    # Read last 25 lines of server.log
    if os.path.exists(SERVER_LOG_FILE):
        try:
            with open(SERVER_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                report["server_log_tail"] = [l.rstrip() for l in lines[-25:]]
        except Exception:
            pass

    # Determine status & actionable remediations
    if active_ports:
        report["status"] = "healthy"
        report["active_ports"] = active_ports
    else:
        unauth_ports = [p for p, d in report["port_checks"].items() if d.get("http_status") == 401]
        open_err_ports = [p for p, d in report["port_checks"].items() if d.get("tcp") == "open"]
        if unauth_ports:
            report["status"] = "needs_attention"
            report["remediations"].append(
                f"Active listener found on port(s) {unauth_ports}, but requests were rejected (401 Unauthorized). "
                "Check that the RevitMCP extension has written its auth token to ~/.revit_mcp/instances/."
            )
        elif open_err_ports:
            report["status"] = "needs_attention"
            report["remediations"].append(
                f"Port(s) {open_err_ports} have open TCP sockets but /api/status failed. See port_checks details."
            )
        else:
            report["status"] = "offline"
            report["remediations"].append(
                "No active Revit MCP listener detected on ports 40001..40010. "
                "Ensure Autodesk Revit is running, open the RevitMCP tab on the ribbon, and click 'Start Server'."
            )

    return json.dumps(report, indent=2)


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
        req = urllib.request.Request(f"http://127.0.0.1:{target_port}/api/status", headers=_get_request_headers(target_port))
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
    doc_info['path'] = doc.PathName or ''
    doc_info['is_family'] = doc.IsFamilyDocument
    doc_info['is_modified'] = doc.IsModified
    
    # Active View info
    active_view = doc.ActiveView
    if active_view:
        doc_info['active_view'] = {
            'id': active_view.Id.IntegerValue if hasattr(active_view.Id, 'IntegerValue') else active_view.Id.Value,
            'name': active_view.Name,
            'view_type': str(active_view.ViewType),
            'scale': active_view.Scale,
            'is_3d': isinstance(active_view, View3D)
        }
        if hasattr(active_view, 'GenLevel') and active_view.GenLevel:
            doc_info['active_view']['level'] = {
                'id': active_view.GenLevel.Id.IntegerValue if hasattr(active_view.GenLevel.Id, 'IntegerValue') else active_view.GenLevel.Id.Value,
                'name': active_view.GenLevel.Name,
                'elevation_ft': active_view.GenLevel.Elevation,
                'elevation_mm': round(active_view.GenLevel.Elevation * 304.8, 1)
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
def revit_execute_python(code: str, engine: Optional[str] = "cpython", port: Optional[int] = None, doc_name: Optional[str] = None) -> str:
    """Executes arbitrary Python code inside Autodesk Revit on the main UI thread.
    
    Args:
        code: Python script string to execute.
        engine: Preferred execution runtime ('cpython' or 'ironpython'). Default is 'cpython' when available.
        port: Optional target instance port.
        doc_name: Optional target document title.

    Provides in execution scope:
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
    res = _send_revit_execute(code, engine=engine, target_port=port, target_doc=doc_name)
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
def revit_get_latest_selection(port: Optional[int] = None, doc_name: Optional[str] = None) -> str:
    """Retrieves the most recent user element selection.
    First checks the cached interactive user selection (~/.revit_mcp/latest_selection.json);
    if not present, falls back to active view selection via Revit API.
    """
    ensure_directories()
    if os.path.exists(LATEST_SELECTION_JSON):
        try:
            with open(LATEST_SELECTION_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data and data.get("elements"):
                    return json.dumps(data, indent=2)
        except Exception:
            pass
    return revit_get_selection(port=port, doc_name=doc_name)


@server.tool()
def revit_get_element_geometry(element_ids: Optional[List[int]] = None, port: Optional[int] = None, doc_name: Optional[str] = None) -> str:
    """Retrieves high-precision geometric summary (exact mm bounding box, location, rotation, level elevation) for elements."""
    target_ids_json = json.dumps(element_ids or [])
    code = """
import math
from Autodesk.Revit.DB import ElementId, LocationPoint, LocationCurve

target_ids = {TARGET_IDS}
if not target_ids and uidoc:
    target_ids = [eid.IntegerValue if hasattr(eid, 'IntegerValue') else eid.Value for eid in uidoc.Selection.GetElementIds()]

results = []
view = doc.ActiveView

for tid in target_ids:
    el = doc.GetElement(ElementId(tid))
    if not el:
        continue
        
    info = {'id': tid, 'name': getattr(el, 'Name', ''), 'category': el.Category.Name if el.Category else ''}
    
    # BoundingBox
    bbox = el.get_BoundingBox(view) or el.get_BoundingBox(None)
    if bbox:
        info['bbox_mm'] = {
            'min': [round(bbox.Min.X * 304.8, 1), round(bbox.Min.Y * 304.8, 1), round(bbox.Min.Z * 304.8, 1)],
            'max': [round(bbox.Max.X * 304.8, 1), round(bbox.Max.Y * 304.8, 1), round(bbox.Max.Z * 304.8, 1)],
            'size': [
                round((bbox.Max.X - bbox.Min.X) * 304.8, 1),
                round((bbox.Max.Y - bbox.Min.Y) * 304.8, 1),
                round((bbox.Max.Z - bbox.Min.Z) * 304.8, 1)
            ]
        }
        
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
""".replace("{TARGET_IDS}", target_ids_json)

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
        req = urllib.request.Request(f"http://127.0.0.1:{target_port}/api/screenshot", data=b"{}", headers=_get_request_headers(target_port))
        with urllib.request.urlopen(req, timeout=60.0) as resp:
            body = resp.read().decode("utf-8")
            return body
    except Exception as ex:
        return json.dumps({"status": "error", "message": str(ex)}, indent=2)


@server.tool()
def revit_get_latest_screenshot() -> str:
    """Retrieves metadata and file path of the most recently captured screenshot or user snip.
    Checks unified cache in ~/.revit_mcp/ and clearly indicates source ('user' or 'agent').
    """
    ensure_directories()
    candidates = [
        (LATEST_SCREENSHOT_JSON, LATEST_SCREENSHOT_PNG),
        (LATEST_USER_SNIP_JSON, LATEST_USER_SNIP_PNG),
        (LATEST_AGENT_SCREENSHOT_JSON, LATEST_AGENT_SCREENSHOT_PNG),
    ]
    for meta_file, img_file in candidates:
        if os.path.exists(meta_file):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    data["image_file"] = img_file
                    return json.dumps(data, indent=2)
            except Exception as ex:
                return json.dumps({"error": f"Failed to read screenshot metadata: {str(ex)}"}, indent=2)
    return json.dumps({"status": "not_found", "message": "No screenshot captured yet."}, indent=2)


@server.tool()
def revit_get_latest_user_snip() -> str:
    """Retrieves metadata and file path for the most recent manual user snip or markup drawing.
    This is dedicated to user-provided visual context and is never overwritten by agent automated captures.
    """
    ensure_directories()
    if os.path.exists(LATEST_USER_SNIP_JSON):
        try:
            with open(LATEST_USER_SNIP_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
                data["image_file"] = LATEST_USER_SNIP_PNG
                return json.dumps(data, indent=2)
        except Exception as ex:
            return json.dumps({"error": f"Failed to read user snip metadata: {str(ex)}"}, indent=2)
    return json.dumps({"status": "not_found", "message": "No user snip captured yet."}, indent=2)


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
        req = urllib.request.Request(f"http://127.0.0.1:{target_port}/api/request_user_selection", data=data, headers=_get_request_headers(target_port))
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
        req = urllib.request.Request(f"http://127.0.0.1:{target_port}/api/request_user_snip", data=data, headers=_get_request_headers(target_port))
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
        req = urllib.request.Request(f"http://127.0.0.1:{target_port}/api/set_busy", data=data, headers=_get_request_headers(target_port))
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.read().decode("utf-8")
    except Exception as ex:
        return json.dumps({"success": False, "error": str(ex)}, indent=2)


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
