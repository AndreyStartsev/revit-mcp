# -*- coding: utf-8 -*-
"""
Revit MCP Server - Autodesk Revit pyRevit Extension Script.
Starts an asynchronous HTTP server inside Autodesk Revit on port 40001 (or next free port),
allowing external AI agents (Claude, Cursor, Antigravity, etc.) to query and automate Revit via MCP.
"""

__title__ = "Revit MCP"
__author__ = "Open Source Contributors"
__context__ = "zero-doc"
__persistentengine__ = True

import sys
import os
import json
import time
import datetime
import traceback
import tempfile
import shutil
import uuid
import threading
from collections import deque

# Default shared cache directory
DEFAULT_CACHE_DIR = os.path.join(tempfile.gettempdir(), "revit_mcp")
SAVE_DIR = os.environ.get("REVIT_MCP_CACHE_DIR", DEFAULT_CACHE_DIR)
LOG_PATH = os.path.join(SAVE_DIR, "server.log")

def log_debug(msg):
    try:
        if not os.path.exists(SAVE_DIR):
            os.makedirs(SAVE_DIR)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_PATH, "a") as f:
            f.write("[{}] {}\n".format(ts, msg))
    except Exception:
        pass

log_debug("--- Revit MCP Script Triggered ---")

import clr
clr.AddReference("WindowsBase")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("System.Windows.Forms")

# .NET 8 / Revit 2025 & .NET Framework 4.8 / Revit 2023-2024 compatibility
for asm in ["System", "System.Net", "System.Net.HttpListener", "System.Net.Primitives", "System.Net.Requests", "System.Net.ServicePoint"]:
    try:
        clr.AddReference(asm)
    except Exception:
        pass

from System.Windows import (
    Window, WindowStyle, WindowStartupLocation, ResizeMode, Thickness, CornerRadius,
    GridLength, GridUnitType, FontWeights, HorizontalAlignment, VerticalAlignment, Visibility
)
from System.Windows.Controls import (
    Border, StackPanel, Button, TextBlock, TextBox, Grid, RowDefinition, ColumnDefinition, Orientation
)
from System.Windows.Media import SolidColorBrush, Color, Colors
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Input import Cursors
from System.Windows.Forms import Screen
from pyrevit import forms
from pyrevit.framework import wpf
import System

try:
    from System.Net import HttpListener
except Exception:
    try:
        import System.Reflection
        System.Reflection.Assembly.Load("System.Net.HttpListener")
        from System.Net import HttpListener
    except Exception:
        HttpListener = getattr(System.Net, "HttpListener", None)

from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType

DOMAIN_WINDOW_KEY = "Revit_MCP_Server_Window"
BASE_PORT = 40001


def get_registered_window(key):
    """Safely retrieves a modeless window across pyRevit 4.x, 5.x, and 7.x (.NET 8)."""
    try:
        if hasattr(forms, "check_modelesswindow"):
            return forms.check_modelesswindow(key)
    except Exception:
        pass
    try:
        from System import AppDomain
        return AppDomain.CurrentDomain.GetData(key)
    except Exception:
        return None


def set_registered_window(key, window):
    """Safely registers a modeless window across pyRevit 4.x, 5.x, and 7.x (.NET 8)."""
    try:
        if hasattr(forms, "set_modelesswindow"):
            forms.set_modelesswindow(key, window)
            return
    except Exception:
        pass
    try:
        from System import AppDomain
        AppDomain.CurrentDomain.SetData(key, window)
    except Exception:
        pass


def load_wpf_bitmap(file_path, width=32, height=32):
    try:
        if os.path.exists(file_path):
            bi = BitmapImage()
            bi.BeginInit()
            bi.UriSource = System.Uri(file_path, System.UriKind.Absolute)
            bi.DecodePixelWidth = width
            bi.DecodePixelHeight = height
            bi.CacheOption = BitmapCacheOption.OnLoad
            bi.EndInit()
            bi.Freeze()
            return bi
    except Exception as ex:
        log_debug("load_wpf_bitmap error: {}".format(ex))
    return None


def update_ribbon_button_icon(is_active):
    try:
        try:
            clr.AddReference("AdWindows")
        except Exception:
            pass
        import Autodesk.Windows as AdWin
        
        btn_dir = os.path.dirname(__file__)
        large_name = "on.png" if is_active else "off.png"
        small_name = "on.small.png" if is_active else "off.small.png"
        
        large_path = os.path.join(btn_dir, large_name)
        small_path = os.path.join(btn_dir, small_name)
        if not os.path.exists(small_path):
            small_path = large_path
            
        large_img = load_wpf_bitmap(large_path, 32, 32)
        small_img = load_wpf_bitmap(small_path, 16, 16)
        if not large_img:
            return
            
        ribbon = AdWin.ComponentManager.Ribbon
        if ribbon:
            for t in ribbon.Tabs:
                for p in t.Panels:
                    for item in p.Source.Items:
                        item_id = str(getattr(item, "Id", ""))
                        if "StartServer" in item_id or "RevitMCP" in item_id or "MCP" in item_id:
                            item.LargeImage = large_img
                            if hasattr(item, "Image"):
                                item.Image = small_img
    except Exception as ex:
        log_debug("update_ribbon_button_icon error: {}".format(ex))


SCREENSHOT_PYTHON_CODE = r"""
import os
import tempfile
import shutil
import datetime
import json
from Autodesk.Revit.DB import ImageExportOptions, ExportRange, ImageFileType, ImageResolution, ZoomFitType

active_view = doc.ActiveView if doc else None
if not doc or not active_view:
    response_data['error'] = "No active document or view"
    response_data['screenshot_saved'] = False
else:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_dir = tempfile.gettempdir()
    prefix = "revit_shot_{}".format(ts)
    base_path = os.path.join(temp_dir, prefix)

    opts = ImageExportOptions()
    opts.ExportRange = ExportRange.VisibleRegionOfCurrentView
    opts.FilePath = base_path
    opts.HLRandWFViewsFileType = ImageFileType.PNG
    opts.ShadowViewsFileType = ImageFileType.PNG
    opts.ImageResolution = ImageResolution.DPI_150
    opts.ZoomType = ZoomFitType.FitToPage
    opts.PixelSize = 1920

    doc.ExportImage(opts)

    exported = None
    for f in os.listdir(temp_dir):
        if f.startswith(prefix) and f.endswith(".png"):
            exported = os.path.join(temp_dir, f)
            break
    if not exported and os.path.exists(base_path + ".png"):
        exported = base_path + ".png"

    if exported and os.path.exists(exported):
        save_dir = os.environ.get("REVIT_MCP_CACHE_DIR", os.path.join(tempfile.gettempdir(), "revit_mcp"))
        screenshots_dir = os.path.join(save_dir, "screenshots")
        if not os.path.exists(screenshots_dir):
            try:
                os.makedirs(screenshots_dir)
            except:
                pass

        latest_path = os.path.join(save_dir, "latest_screenshot.png")
        latest_meta_path = os.path.join(save_dir, "latest_screenshot.json")
        agent_path = os.path.join(save_dir, "latest_agent_screenshot.png")
        agent_meta_path = os.path.join(save_dir, "latest_agent_screenshot.json")
        timestamped_path = os.path.join(screenshots_dir, "agent_capture_{}.png".format(ts))

        shutil.copy2(exported, agent_path)
        shutil.copy2(exported, latest_path)
        shutil.copy2(exported, timestamped_path)

        meta = {
            "source": "agent",
            "captured_by": "agent",
            "type": "agent_view_export",
            "timestamp": ts,
            "doc_title": doc.Title if doc else "",
            "doc_path": doc.PathName if doc else "",
            "view_name": active_view.Name if active_view else "",
            "view_type": str(active_view.ViewType) if active_view else "",
            "file_path": agent_path,
            "latest_screenshot_path": latest_path,
            "history_path": timestamped_path,
            "width": 1920,
            "resolution": "150 DPI",
            "description": "Automated Revit active view capture"
        }
        with open(agent_meta_path, "w") as jf:
            json.dump(meta, jf, indent=2)
        with open(latest_meta_path, "w") as jf:
            json.dump(meta, jf, indent=2)

        response_data['screenshot_saved'] = True
        response_data['file_path'] = agent_path
        response_data['metadata'] = meta
    else:
        response_data['error'] = "ExportImage completed but output file not found"
        response_data['screenshot_saved'] = False
"""


class CategorySelectionFilter(ISelectionFilter):
    """Filters user interactive selection by category names or BuiltInCategories."""
    def __init__(self, doc, allowed_categories=None):
        self.doc = doc
        self.allowed = []
        if allowed_categories:
            for c in allowed_categories:
                self.allowed.append(str(c).lower().replace(" ", "").replace("ost_", ""))

    def AllowElement(self, element):
        if not self.allowed:
            return True
        if not element or not element.Category:
            return False
        cat_name = element.Category.Name.lower().replace(" ", "")
        built_in = str(getattr(element.Category, "BuiltInCategory", "")).lower().replace("ost_", "")
        for target in self.allowed:
            if target in cat_name or target in built_in:
                return True
        return False

    def AllowReference(self, reference, position):
        if not self.allowed:
            return True
        try:
            elem = self.doc.GetElement(reference)
            return self.AllowElement(elem)
        except Exception:
            return True


def get_revit_modal_status(hud_hwnd=0):
    """Detects whether Revit's main UI thread is currently blocked by a modal dialog."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        cur_pid = System.Diagnostics.Process.GetCurrentProcess().Id

        revit_main_hwnd = 0
        try:
            import Autodesk.Windows as AdWin
            revit_main_hwnd = int(getattr(AdWin.ComponentManager, "ApplicationWindow", 0))
        except Exception:
            pass

        if not revit_main_hwnd:
            revit_main_hwnd = int(System.Diagnostics.Process.GetCurrentProcess().MainWindowHandle)

        if not revit_main_hwnd:
            return False, ""

        active_wnd = user32.GetActiveWindow()
        if active_wnd and active_wnd != revit_main_hwnd:
            if active_wnd != hud_hwnd:
                length = user32.GetWindowTextLengthW(active_wnd)
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(active_wnd, buf, length + 1)
                title = buf.value
                # If window is visible and enabled
                if user32.IsWindowVisible(active_wnd) and user32.IsWindowEnabled(active_wnd):
                    return True, title

        is_main_enabled = bool(user32.IsWindowEnabled(revit_main_hwnd))
        if not is_main_enabled:
            return True, "Modal Dialog"

        return False, ""
    except Exception:
        return False, ""


def is_current_process_foreground():
    try:
        import ctypes
        user32 = ctypes.windll.user32
        fg_hwnd = user32.GetForegroundWindow()
        if not fg_hwnd:
            return False
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(fg_hwnd, ctypes.byref(pid))
        cur_pid = System.Diagnostics.Process.GetCurrentProcess().Id
        return bool(pid.value == cur_pid)
    except Exception:
        return False


class ExecutionTask(object):
    """Encapsulates a single execution request with its own synchronization event and result holder."""
    def __init__(self, code):
        try:
            self.task_id = uuid.uuid4().hex[:8]
        except Exception:
            self.task_id = System.Guid.NewGuid().ToString("N")[:8]
        self.code = code
        self.done_event = System.Threading.ManualResetEvent(False)
        self.result = None


class RevitExecutionHandler(IExternalEventHandler):
    """Thread-safe execution handler that processes a FIFO queue of execution tasks on Revit's UI thread."""
    def __init__(self, window=None):
        self.window = window
        self._lock = threading.Lock()
        self._queue = deque()

    def enqueue(self, code):
        """Enqueues code to run and returns an ExecutionTask with its own done_event."""
        task = ExecutionTask(code)
        with self._lock:
            self._queue.append(task)
        return task

    def clear(self):
        """Clears pending tasks and unblocks waiting threads on shutdown."""
        with self._lock:
            while self._queue:
                task = self._queue.popleft()
                task.result = {"success": False, "error": "Server stopped"}
                try:
                    task.done_event.Set()
                except Exception:
                    pass

    def Execute(self, uiapp):
        """Processes all queued tasks sequentially on the Revit UI thread."""
        while True:
            task = None
            with self._lock:
                if self._queue:
                    task = self._queue.popleft()
            if not task:
                break

            try:
                log_debug("Executing remote task {} in Revit UI thread...".format(task.task_id))
                doc = uiapp.ActiveUIDocument.Document if uiapp.ActiveUIDocument else None
                uidoc = uiapp.ActiveUIDocument
                app = uiapp.Application

                response_data = {}
                scope = {
                    'uiapp': uiapp,
                    'app': app,
                    'uidoc': uidoc,
                    'doc': doc,
                    'response_data': response_data,
                    '__builtins__': __builtins__
                }

                exec(task.code, scope)
                
                result_data = scope.get('response_data', response_data)
                task.result = {
                    "success": True,
                    "data": result_data,
                    "message": "Execution finished successfully",
                    "task_id": task.task_id
                }
                log_debug("Task {} finished successfully.".format(task.task_id))
            except Exception as ex:
                tb = traceback.format_exc()
                task.result = {
                    "success": False,
                    "error": str(ex),
                    "traceback": tb,
                    "task_id": task.task_id
                }
                log_debug("Task {} error: {}\n{}".format(task.task_id, ex, tb))
            except:
                task.result = {
                    "success": False,
                    "error": "Native unhandled exception during script execution.",
                    "task_id": task.task_id
                }
                log_debug("Task {} native unhandled exception.".format(task.task_id))
            finally:
                try:
                    task.done_event.Set()
                except Exception:
                    pass

    def GetName(self):
        return "Revit MCP Remote Execution Handler"


class AsyncHttpServer(object):
    """Asynchronous HTTP server hosted inside Autodesk Revit."""
    def __init__(self, port, handler, ext_event, window):
        self.port = port
        self.handler = handler
        self.ext_event = ext_event
        self.window = window
        self.listener = None
        self.running = False
        try:
            self.auth_token = uuid.uuid4().hex
        except Exception:
            self.auth_token = System.Guid.NewGuid().ToString("N")
        env_token = os.environ.get("REVIT_MCP_AUTH_TOKEN")
        if env_token:
            self.auth_token = env_token.strip()

    def get_status_info(self):
        cur_doc = None
        cur_view = None
        ver = "Revit"
        doc_title = "No Document"
        doc_path = ""
        view_name = ""
        is_family = False
        try:
            from pyrevit import revit
            cur_doc = getattr(revit, "doc", None)
            cur_view = getattr(revit, "active_view", None)
            if hasattr(revit, "HOST_APP") and hasattr(revit.HOST_APP, "version"):
                ver = str(revit.HOST_APP.version)
            if cur_doc:
                doc_title = str(cur_doc.Title)
                doc_path = str(cur_doc.PathName)
                is_family = bool(cur_doc.IsFamilyDocument)
            if cur_view:
                view_name = str(cur_view.Name)
        except Exception:
            pass

        cur_pid = System.Diagnostics.Process.GetCurrentProcess().Id
        is_fg = is_current_process_foreground()

        return {
            "status": "running",
            "port": self.port,
            "pid": cur_pid,
            "revit_version": ver,
            "doc_title": doc_title,
            "doc_path": doc_path,
            "active_view": view_name,
            "is_family_doc": is_family,
            "is_foreground": is_fg,
            "auth_token": self.auth_token,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    def _register_instance_file(self):
        info = self.get_status_info()
        candidate_dirs = [
            os.path.join(SAVE_DIR, "instances"),
            os.path.join(os.path.expanduser("~"), ".revit_mcp", "instances")
        ]
        for inst_dir in candidate_dirs:
            try:
                if not os.path.exists(inst_dir):
                    os.makedirs(inst_dir)
                inst_path = os.path.join(inst_dir, "instance_{}.json".format(self.port))
                with open(inst_path, "w") as f:
                    json.dump(info, f, indent=2)
            except Exception as ex:
                log_debug("_register_instance_file error in {}: {}".format(inst_dir, ex))

    def _unregister_instance_file(self):
        candidate_dirs = [
            os.path.join(SAVE_DIR, "instances"),
            os.path.join(os.path.expanduser("~"), ".revit_mcp", "instances")
        ]
        for inst_dir in candidate_dirs:
            try:
                inst_path = os.path.join(inst_dir, "instance_{}.json".format(self.port))
                if os.path.exists(inst_path):
                    os.remove(inst_path)
            except Exception as ex:
                log_debug("_unregister_instance_file error in {}: {}".format(inst_dir, ex))

    def start(self):
        hl_class = HttpListener
        if hl_class is None:
            hl_class = getattr(System.Net, "HttpListener", None)
        if hl_class is None:
            raise Exception("System.Net.HttpListener is not available in this .NET runtime.")
        
        # Test candidate ports starting from requested port
        candidate = self.port
        started = False
        last_ex = None
        
        for p in range(candidate, candidate + 10):
            try:
                l = hl_class()
                l.Prefixes.Add("http://127.0.0.1:{}/".format(p))
                l.Start()
                self.listener = l
                self.port = p
                started = True
                break
            except Exception as ex:
                last_ex = ex
                continue

        if not started:
            raise Exception("Failed to bind any port in range {}-{}: {}".format(candidate, candidate + 9, last_ex))

        self.running = True
        self._register_instance_file()
        log_debug("AsyncHttpServer started on http://127.0.0.1:{}/".format(self.port))
        self._listen_async()

    def _listen_async(self):
        if self.running and self.listener and getattr(self.listener, "IsListening", False):
            try:
                self.listener.BeginGetContext(System.AsyncCallback(self._on_context), None)
            except Exception as ex:
                log_debug("BeginGetContext notice: {}".format(ex))

    def _on_context(self, async_result):
        if not self.running or not self.listener or not getattr(self.listener, "IsListening", False):
            return

        self._listen_async()

        try:
            context = self.listener.EndGetContext(async_result)
            self._process_request(context)
        except Exception as ex:
            log_debug("EndGetContext notice: {}".format(ex))

    def _process_request(self, context):
        t_start = time.time()
        path = ""
        method = ""
        try:
            request = context.Request
            response = context.Response

            # SECURITY: Do NOT include Access-Control-Allow-Origin: *
            # Deleting all CORS headers prevents arbitrary web pages from making cross-origin requests.

            method = request.HttpMethod.upper()
            path = request.Url.AbsolutePath.lower()
            log_debug("Received HTTP {} to: {}".format(method, path))

            # Reject CORS preflight requests
            if method == "OPTIONS":
                response.StatusCode = 405
                response.Close()
                return

            # Shared secret authentication verification
            auth_header = request.Headers.Get("Authorization") or request.Headers.Get("X-Auth-Token") or ""
            token = ""
            if auth_header.lower().startswith("bearer "):
                token = auth_header[7:].strip()
            else:
                token = auth_header.strip()

            if not token and request.Url.Query:
                q = request.Url.Query.lstrip("?")
                for pair in q.split("&"):
                    if pair.startswith("token="):
                        token = pair.split("=", 1)[1]
                        break

            if self.auth_token and token != self.auth_token:
                log_debug("Unauthorized request to {} from {}".format(path, request.RemoteEndPoint))
                self._write_response(response, {
                    "success": False,
                    "error": "Unauthorized: Missing or invalid authentication token. Pass 'Authorization: Bearer <token>'."
                }, 401)
                if self.window:
                    self.window.notify_request_finished(401, time.time() - t_start, path)
                return

            if self.window:
                self.window.notify_request_started(method, path)

            hud_hwnd = 0
            if self.window:
                try:
                    from System.Windows.Interop import WindowInteropHelper
                    helper = WindowInteropHelper(self.window)
                    hud_hwnd = int(helper.Handle)
                except Exception:
                    pass

            if path in ["/api/check_modal", "/api/check_modal/"]:
                is_blocked, modal_title = get_revit_modal_status(hud_hwnd=hud_hwnd)
                if is_blocked and self.window:
                    def trigger_modal():
                        self.window.start_modal_blinking(modal_title)
                    self.window.Dispatcher.BeginInvoke(System.Action(trigger_modal))
                elif not is_blocked and self.window and self.window.blinking_button == "modal":
                    def untrigger_modal():
                        self.window.stop_modal_blinking()
                    self.window.Dispatcher.BeginInvoke(System.Action(untrigger_modal))

                self._write_response(response, {
                    "success": True,
                    "is_modal_blocked": is_blocked,
                    "modal_title": modal_title
                }, 200)
                if self.window:
                    self.window.notify_request_finished(200, time.time() - t_start, "check_modal")
                return

            if path in ["/api/execute", "/api/execute/"] and method == "POST":
                is_blocked, modal_title = get_revit_modal_status(hud_hwnd=hud_hwnd)
                if is_blocked:
                    log_debug("Pre-flight: Revit UI is blocked by modal dialog '{}'".format(modal_title))
                    if self.window:
                        def trigger_modal():
                            self.window.start_modal_blinking(modal_title)
                        self.window.Dispatcher.BeginInvoke(System.Action(trigger_modal))
                    
                    err_msg = "Revit UI thread is blocked by a modal dialog ('{}'). Please close or confirm the modal dialog in Revit to proceed.".format(modal_title or "Modal Dialog")
                    self._write_response(response, {
                        "success": False,
                        "is_modal_blocked": True,
                        "modal_title": modal_title,
                        "error": err_msg
                    }, 423) # 423 Locked
                    if self.window:
                        self.window.notify_request_finished(423, time.time() - t_start, path)
                    return

                reader = System.IO.StreamReader(request.InputStream, request.ContentEncoding)
                body_str = reader.ReadToEnd()
                reader.Close()

                try:
                    req_json = json.loads(body_str)
                    code = req_json.get("code", "")
                except Exception as json_err:
                    self._write_response(response, {"success": False, "error": "Invalid JSON: " + str(json_err)}, 400)
                    if self.window:
                        self.window.notify_request_finished(400, time.time() - t_start, path)
                    return

                task = self.handler.enqueue(code)
                self.ext_event.Raise()

                if task.done_event.WaitOne(60000):
                    res_data = task.result or {}
                    status_code = 200 if res_data.get("success") else 500
                    self._write_response(response, res_data, status_code)
                else:
                    log_debug("Task {} execution timed out (60s).".format(task.task_id))
                    status_code = 504
                    self._write_response(response, {
                        "success": False,
                        "error": "Execution timed out (60s)",
                        "task_id": task.task_id
                    }, 504)

                if self.window:
                    self.window.notify_request_finished(status_code, time.time() - t_start, path)

            elif path in ["/api/screenshot", "/api/screenshot/"]:
                is_blocked, modal_title = get_revit_modal_status(hud_hwnd=hud_hwnd)
                if is_blocked:
                    if self.window:
                        def trigger_modal():
                            self.window.start_modal_blinking(modal_title)
                        self.window.Dispatcher.BeginInvoke(System.Action(trigger_modal))
                    
                    err_msg = "Revit UI thread is blocked by a modal dialog ('{}'). Please close or confirm the modal dialog in Revit to proceed.".format(modal_title or "Modal Dialog")
                    self._write_response(response, {
                        "success": False,
                        "is_modal_blocked": True,
                        "modal_title": modal_title,
                        "error": err_msg
                    }, 423)
                    if self.window:
                        self.window.notify_request_finished(423, time.time() - t_start, "screenshot")
                    return

                task = self.handler.enqueue(SCREENSHOT_PYTHON_CODE)
                self.ext_event.Raise()

                if task.done_event.WaitOne(60000):
                    res_data = task.result or {}
                    status_code = 200 if res_data.get("success") else 500
                    self._write_response(response, res_data, status_code)
                else:
                    status_code = 504
                    self._write_response(response, {
                        "success": False,
                        "error": "Screenshot timed out (60s)",
                        "task_id": task.task_id
                    }, 504)

                if self.window:
                    self.window.notify_request_finished(status_code, time.time() - t_start, "screenshot")

            elif path in ["/api/request_user_selection", "/api/request_user_selection/"] and method == "POST":
                reader = System.IO.StreamReader(request.InputStream, request.ContentEncoding)
                body_str = reader.ReadToEnd()
                reader.Close()
                req_json = {}
                try:
                    if body_str:
                        req_json = json.loads(body_str)
                except:
                    pass
                is_multiple = bool(req_json.get("multiple", False) or req_json.get("allow_multiple", False))
                prompt_msg = req_json.get("prompt", "Please select elements in model")
                cats = req_json.get("categories", None)
                timeout_sec = int(req_json.get("timeout", 90))

                done_evt = System.Threading.ManualResetEvent(False)
                def start_sel_ui():
                    self.window.start_blinking("select", prompt_msg, categories=cats, multiple=is_multiple, done_event=done_evt)
                self.window.Dispatcher.BeginInvoke(System.Action(start_sel_ui))

                if done_evt.WaitOne(timeout_sec * 1000):
                    res_data = self.window.active_request_result or {}
                    self._write_response(response, {"success": True, "count": len(res_data.get("elements", [])), "data": res_data}, 200)
                else:
                    def stop_sel_ui():
                        self.window.stop_blinking()
                        self.window.StatusText.Text = "Selection timed out"
                        self.window.StatusText.Foreground = SolidColorBrush(Color.FromRgb(149, 165, 166))
                    self.window.Dispatcher.BeginInvoke(System.Action(stop_sel_ui))
                    self._write_response(response, {"success": False, "status": "timeout", "message": "User selection request timed out ({}s)".format(timeout_sec)}, 408)

                if self.window:
                    self.window.notify_request_finished(200, time.time() - t_start, "request_user_selection")

            elif path in ["/api/request_user_snip", "/api/request_user_snip/"] and method == "POST":
                reader = System.IO.StreamReader(request.InputStream, request.ContentEncoding)
                body_str = reader.ReadToEnd()
                reader.Close()
                req_json = {}
                try:
                    if body_str:
                        req_json = json.loads(body_str)
                except:
                    pass
                prompt_msg = req_json.get("prompt", "Please provide screenshot / markup")
                timeout_sec = int(req_json.get("timeout", 90))

                done_evt = System.Threading.ManualResetEvent(False)
                def start_snip_ui():
                    self.window.start_blinking("screenshot", prompt_msg, categories=None, done_event=done_evt)
                self.window.Dispatcher.BeginInvoke(System.Action(start_snip_ui))

                if done_evt.WaitOne(timeout_sec * 1000):
                    res_data = self.window.active_request_result or {}
                    self._write_response(response, {"success": True, "data": res_data}, 200)
                else:
                    def stop_snip_ui():
                        self.window.stop_blinking()
                        self.window.StatusText.Text = "Snip request timed out"
                        self.window.StatusText.Foreground = SolidColorBrush(Color.FromRgb(149, 165, 166))
                    self.window.Dispatcher.BeginInvoke(System.Action(stop_snip_ui))
                    self._write_response(response, {"success": False, "status": "timeout", "message": "User snip request timed out ({}s)".format(timeout_sec)}, 408)

                if self.window:
                    self.window.notify_request_finished(200, time.time() - t_start, "request_user_snip")

            elif path in ["/api/set_busy", "/api/set_busy/"] and method == "POST":
                reader = System.IO.StreamReader(request.InputStream, request.ContentEncoding)
                body_str = reader.ReadToEnd()
                reader.Close()
                req_json = {}
                try:
                    if body_str:
                        req_json = json.loads(body_str)
                except:
                    pass
                busy = bool(req_json.get("busy", True))
                msg = req_json.get("message", None)
                act = req_json.get("activity", None)
                if self.window:
                    def update_busy_ui():
                        if busy:
                            self.window.set_theme_busy(msg or "Agent is executing...", act or "Processing command...")
                        else:
                            self.window.set_theme_idle()
                            self.window.StatusText.Text = msg or "Ready for commands"
                            self.window.StatusText.Foreground = SolidColorBrush(Color.FromRgb(46, 204, 113))
                            self.window.StatusIndicator.Fill = SolidColorBrush(Color.FromRgb(46, 204, 113))
                            if act:
                                self.window.ActivityText.Text = act
                            self.window.TimeText.Text = datetime.datetime.now().strftime("%H:%M:%S")
                    self.window.Dispatcher.BeginInvoke(System.Action(update_busy_ui))
                self._write_response(response, {"success": True, "busy": busy}, 200)

            elif path in ["/api/status", "/api/status/", "/"]:
                self._write_response(response, self.get_status_info(), 200)
                if self.window:
                    self.window.notify_request_finished(200, time.time() - t_start, "status")

            else:
                self._write_response(response, {"error": "Not Found"}, 404)
                if self.window:
                    self.window.notify_request_finished(404, time.time() - t_start, path)

        except Exception as ex:
            log_debug("process_request error: {}".format(ex))
            if self.window:
                self.window.notify_request_error(str(ex))
            try:
                self._write_response(context.Response, {"success": False, "error": str(ex)}, 500)
            except:
                pass

    def _write_response(self, response, data_dict, status_code=200):
        try:
            response.StatusCode = status_code
            try:
                json_str = json.dumps(data_dict, ensure_ascii=False, default=str)
            except Exception as jerr:
                log_debug("_write_response json.dumps error: {}".format(jerr))
                json_str = json.dumps({"success": False, "error": "Serialization error: " + str(jerr)})
            buffer = System.Text.Encoding.UTF8.GetBytes(json_str)
            response.ContentLength64 = buffer.Length
            output = response.OutputStream
            output.Write(buffer, 0, buffer.Length)
            output.Close()
        except Exception as ex:
            log_debug("_write_response error: {}".format(ex))
        finally:
            try:
                response.Close()
            except:
                pass

    def stop(self):
        log_debug("Stopping AsyncHttpServer...")
        self.running = False
        self._unregister_instance_file()
        if self.handler:
            try:
                self.handler.clear()
            except Exception:
                pass
        if self.listener:
            try:
                if getattr(self.listener, "IsListening", False):
                    self.listener.Stop()
            except:
                pass
            try:
                self.listener.Close()
            except:
                pass
            self.listener = None
        log_debug("AsyncHttpServer stopped cleanly.")


class RevitServerWindow(forms.WPFWindow):
    """Floating HUD for Revit MCP server status and interactions."""
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        self.http_server = None
        self.handler = None
        self.ext_event = None
        self.request_count = 0
        self.is_pinned = False
        self.is_compact = False

        self.blinking_timer = None
        self.blinking_button = None
        self.blinking_state = False
        self.active_request_result = None
        self.active_request_event = None
        self.requested_categories = None
        self.requested_multiple = False

        self._init_controls()
        self._init_events()
        self._position_window()

    def _init_controls(self):
        btn_dir = os.path.dirname(__file__)
        icon_path = os.path.join(btn_dir, "icon.png")
        if os.path.exists(icon_path):
            img = load_wpf_bitmap(icon_path, 24, 24)
            if img:
                self.LogoIcon.Source = img
                if hasattr(self, "CompactLogoIcon"):
                    self.CompactLogoIcon.Source = img

        self.set_theme_idle()

    def _init_events(self):
        self.HeaderBar.MouseLeftButtonDown += self._on_drag_window
        if hasattr(self, "CompactHeaderBar"):
            self.CompactHeaderBar.MouseLeftButtonDown += self._on_drag_window

        self.PinBtn.Click += self._on_pin_clicked
        if hasattr(self, "CompactPinBtn"):
            self.CompactPinBtn.Click += self._on_pin_clicked

        self.MinBtn.Click += self._on_min_clicked
        if hasattr(self, "CompactMinBtn"):
            self.CompactMinBtn.Click += self._on_min_clicked

        self.CloseButton.Click += lambda s, e: self.Hide()
        if hasattr(self, "CompactCloseBtn"):
            self.CompactCloseBtn.Click += lambda s, e: self.Hide()

        self.Closed += self._on_window_closed

        self.ToggleBtn.Click += self._on_toggle_clicked
        if hasattr(self, "CompactToggleBtn"):
            self.CompactToggleBtn.Click += self._on_toggle_clicked

        self.SelectBtn.Click += self._on_select_clicked
        if hasattr(self, "CompactSelectBtn"):
            self.CompactSelectBtn.Click += self._on_select_clicked

        self.ScreenshotBtn.Click += self._on_screenshot_clicked
        if hasattr(self, "CompactScreenshotBtn"):
            self.CompactScreenshotBtn.Click += self._on_screenshot_clicked

    def _on_window_closed(self, sender, e):
        try:
            if self.http_server:
                self.http_server.stop()
        except Exception:
            pass
        set_registered_window(DOMAIN_WINDOW_KEY, None)

    def _position_window(self):
        try:
            screen = Screen.PrimaryScreen.WorkingArea
            self.Left = screen.Right - self.Width - 24
            self.Top = screen.Bottom - self.Height - 48
        except Exception:
            self.WindowStartupLocation = WindowStartupLocation.CenterScreen

    def _on_drag_window(self, sender, e):
        try:
            self.DragMove()
        except Exception:
            pass

    def _on_pin_clicked(self, sender, e):
        self.is_pinned = not self.is_pinned
        self.Topmost = self.is_pinned
        color = SolidColorBrush(Color.FromRgb(241, 196, 15)) if self.is_pinned else SolidColorBrush(Color.FromRgb(136, 136, 153))
        self.PinBtn.Foreground = color
        if hasattr(self, "CompactPinBtn"):
            self.CompactPinBtn.Foreground = color

    def _on_min_clicked(self, sender, e):
        self.is_compact = not self.is_compact
        if self.is_compact:
            self.ExpandedView.Visibility = Visibility.Collapsed
            self.CompactView.Visibility = Visibility.Visible
            self.Width = 140
            self.Height = 75
        else:
            self.CompactView.Visibility = Visibility.Collapsed
            self.ExpandedView.Visibility = Visibility.Visible
            self.Width = 440
            self.Height = 150

    def set_theme_idle(self):
        self.MainBorder.Background = SolidColorBrush(Color.FromRgb(24, 24, 31))
        self.MainBorder.BorderBrush = SolidColorBrush(Color.FromRgb(47, 47, 61))
        self.StatusCardBorder.Background = SolidColorBrush(Color.FromRgb(18, 18, 23))

    def set_theme_busy(self, status_msg="Agent is executing...", activity_msg="Processing command..."):
        self.MainBorder.Background = SolidColorBrush(Color.FromRgb(40, 42, 48))
        self.MainBorder.BorderBrush = SolidColorBrush(Color.FromRgb(85, 90, 102))
        self.StatusCardBorder.Background = SolidColorBrush(Color.FromRgb(28, 30, 35))
        self.StatusIndicator.Fill = SolidColorBrush(Color.FromRgb(155, 89, 182)) # Purple
        if hasattr(self, "CompactStatusIndicator"):
            self.CompactStatusIndicator.Fill = SolidColorBrush(Color.FromRgb(155, 89, 182))
        self.StatusText.Text = status_msg
        self.StatusText.Foreground = SolidColorBrush(Color.FromRgb(187, 143, 206))
        self.ActivityText.Text = activity_msg
        self.TimeText.Text = datetime.datetime.now().strftime("%H:%M:%S")

    def notify_request_started(self, method, path):
        def update():
            self.request_count += 1
            self.RequestCountText.Text = "Requests: {}".format(self.request_count)
            self.set_theme_busy("Active: {} {}".format(method, path), "Processing request on port {}...".format(self.http_server.port if self.http_server else ""))
        self.Dispatcher.BeginInvoke(System.Action(update))

    def notify_request_finished(self, status_code, duration_sec, path):
        def update():
            self.set_theme_idle()
            self.StatusIndicator.Fill = SolidColorBrush(Color.FromRgb(46, 204, 113))
            if hasattr(self, "CompactStatusIndicator"):
                self.CompactStatusIndicator.Fill = SolidColorBrush(Color.FromRgb(46, 204, 113))
            self.StatusText.Text = "Ready for commands"
            self.StatusText.Foreground = SolidColorBrush(Color.FromRgb(46, 204, 113))
            ms = int(duration_sec * 1000)
            self.ActivityText.Text = "{} finished ({}ms, HTTP {})".format(path, ms, status_code)
            self.TimeText.Text = datetime.datetime.now().strftime("%H:%M:%S")
        self.Dispatcher.BeginInvoke(System.Action(update))

    def notify_request_error(self, err_msg):
        def update():
            self.set_theme_idle()
            self.StatusIndicator.Fill = SolidColorBrush(Color.FromRgb(231, 76, 60))
            if hasattr(self, "CompactStatusIndicator"):
                self.CompactStatusIndicator.Fill = SolidColorBrush(Color.FromRgb(231, 76, 60))
            self.StatusText.Text = "Error"
            self.StatusText.Foreground = SolidColorBrush(Color.FromRgb(231, 76, 60))
            self.ActivityText.Text = str(err_msg)
            self.TimeText.Text = datetime.datetime.now().strftime("%H:%M:%S")
        self.Dispatcher.BeginInvoke(System.Action(update))

    def start_modal_blinking(self, modal_title="Modal Dialog"):
        self.blinking_button = "modal"
        self.StatusIndicator.Fill = SolidColorBrush(Color.FromRgb(241, 196, 15)) # Yellow
        self.StatusText.Text = "WAITING: Modal Dialog Open"
        self.StatusText.Foreground = SolidColorBrush(Color.FromRgb(241, 196, 15))
        self.ActivityText.Text = "Revit is blocked by '{}'. Close it to resume.".format(modal_title or "dialog")

    def stop_modal_blinking(self):
        if self.blinking_button == "modal":
            self.blinking_button = None
            self.StatusIndicator.Fill = SolidColorBrush(Color.FromRgb(46, 204, 113))
            self.StatusText.Text = "Ready for commands"
            self.StatusText.Foreground = SolidColorBrush(Color.FromRgb(46, 204, 113))
            self.ActivityText.Text = "Listening on 127.0.0.1:{}...".format(self.http_server.port if self.http_server else "")

    def start_blinking(self, target, prompt_msg, categories=None, multiple=False, done_event=None):
        self.stop_blinking()
        self.blinking_button = target
        self.active_request_event = done_event
        self.requested_categories = categories
        self.requested_multiple = multiple
        self.active_request_result = None

        if target == "select":
            self.StatusText.Text = "AGENT ASKS FOR SELECTION"
            self.StatusText.Foreground = SolidColorBrush(Color.FromRgb(155, 89, 182))
            mode_hint = "(Multiple + Finish)" if multiple else "(Click 1 Element)"
            self.ActivityText.Text = "{}: {}".format(mode_hint, prompt_msg)
        elif target == "screenshot":
            self.StatusText.Text = "AGENT ASKS FOR SCREENSHOT"
            self.StatusText.Foreground = SolidColorBrush(Color.FromRgb(52, 152, 219))
            self.ActivityText.Text = prompt_msg

        from System.Windows.Threading import DispatcherTimer
        self.blinking_timer = DispatcherTimer()
        self.blinking_timer.Interval = System.TimeSpan.FromMilliseconds(450)
        self.blinking_timer.Tick += self._on_blink_tick
        self.blinking_timer.Start()

    def _on_blink_tick(self, sender, e):
        self.blinking_state = not self.blinking_state
        if self.blinking_button == "select":
            btn = self.SelectBtn
            gold = Color.FromRgb(241, 196, 15)
            purple = Color.FromRgb(142, 68, 173)
            btn.Background = SolidColorBrush(gold if self.blinking_state else purple)
        elif self.blinking_button == "screenshot":
            btn = self.ScreenshotBtn
            gold = Color.FromRgb(241, 196, 15)
            blue = Color.FromRgb(41, 128, 185)
            btn.Background = SolidColorBrush(gold if self.blinking_state else blue)

    def stop_blinking(self):
        if self.blinking_timer:
            self.blinking_timer.Stop()
            self.blinking_timer = None
        self.SelectBtn.Background = SolidColorBrush(Color.FromRgb(142, 68, 173))
        self.ScreenshotBtn.Background = SolidColorBrush(Color.FromRgb(41, 128, 185))
        self.blinking_button = None

    def _on_select_clicked(self, sender, e):
        is_requested = (self.blinking_button == "select")
        cats = self.requested_categories
        multiple = self.requested_multiple if is_requested else False

        self.stop_blinking()
        self.StatusText.Text = "Selecting elements..."
        self.StatusText.Foreground = SolidColorBrush(Color.FromRgb(155, 89, 182))

        try:
            from pyrevit import revit
            doc = revit.doc
            uidoc = revit.uidoc
            if not doc or not uidoc:
                self.StatusText.Text = "No active document"
                return

            filt = CategorySelectionFilter(doc, cats)
            elements_data = []

            if multiple:
                refs = uidoc.Selection.PickObjects(ObjectType.Element, filt, "Select elements and click Finish")
                for r in refs:
                    el = doc.GetElement(r)
                    if el:
                        elements_data.append({
                            "id": el.Id.IntegerValue if hasattr(el.Id, "IntegerValue") else el.Id.Value,
                            "name": getattr(el, "Name", ""),
                            "category": el.Category.Name if el.Category else ""
                        })
            else:
                ref = uidoc.Selection.PickObject(ObjectType.Element, filt, "Select 1 element in model")
                if ref:
                    el = doc.GetElement(ref)
                    if el:
                        elements_data.append({
                            "id": el.Id.IntegerValue if hasattr(el.Id, "IntegerValue") else el.Id.Value,
                            "name": getattr(el, "Name", ""),
                            "category": el.Category.Name if el.Category else ""
                        })

            res = {
                "count": len(elements_data),
                "elements": elements_data,
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self.active_request_result = res
            self.StatusText.Text = "Selected {} elements".format(len(elements_data))
            self.StatusText.Foreground = SolidColorBrush(Color.FromRgb(46, 204, 113))

        except Exception as ex:
            log_debug("Selection exception or cancel: {}".format(ex))
            self.StatusText.Text = "Selection canceled"
            self.StatusText.Foreground = SolidColorBrush(Color.FromRgb(149, 165, 166))
            self.active_request_result = {"count": 0, "elements": [], "canceled": True}
        finally:
            if self.active_request_event:
                try:
                    self.active_request_event.Set()
                except:
                    pass

    def _on_screenshot_clicked(self, sender, e):
        self.stop_blinking()
        try:
            import snipper
            
            def on_snip_saved(meta):
                self.active_request_result = meta
                self.StatusText.Text = "Snip saved"
                self.StatusText.Foreground = SolidColorBrush(Color.FromRgb(46, 204, 113))
                if self.active_request_event:
                    try:
                        self.active_request_event.Set()
                    except:
                        pass

            snipper.launch_snipper(on_snip_saved)
        except Exception as ex:
            log_debug("Screenshot clicked error: {}".format(ex))
            self.StatusText.Text = "Snip error"
            self.StatusText.Foreground = SolidColorBrush(Color.FromRgb(231, 76, 60))

    def _on_toggle_clicked(self, sender, e):
        if self.http_server and self.http_server.running:
            self.http_server.stop()
            self.http_server = None
            self.ToggleBtn.Content = "Start Server"
            self.ToggleBtn.Background = SolidColorBrush(Color.FromRgb(46, 204, 113)) # Green
            if hasattr(self, "CompactToggleBtn"):
                self.CompactToggleBtn.Background = SolidColorBrush(Color.FromRgb(46, 204, 113))
            self.StatusIndicator.Fill = SolidColorBrush(Color.FromRgb(149, 165, 166))
            if hasattr(self, "CompactStatusIndicator"):
                self.CompactStatusIndicator.Fill = SolidColorBrush(Color.FromRgb(149, 165, 166))
            self.StatusText.Text = "Server Stopped"
            self.StatusText.Foreground = SolidColorBrush(Color.FromRgb(149, 165, 166))
            self.ActivityText.Text = "Click 'Start Server' to resume"
            update_ribbon_button_icon(False)
        else:
            self.start_server()

    def start_server(self):
        try:
            self.handler = RevitExecutionHandler(self)
            self.ext_event = ExternalEvent.Create(self.handler)
            self.http_server = AsyncHttpServer(BASE_PORT, self.handler, self.ext_event, self)
            self.http_server.start()

            self.PortBadge.Text = " :{}".format(self.http_server.port)
            self.ToggleBtn.Content = "Stop Server"
            self.ToggleBtn.Background = SolidColorBrush(Color.FromRgb(231, 76, 60)) # Red
            if hasattr(self, "CompactToggleBtn"):
                self.CompactToggleBtn.Background = SolidColorBrush(Color.FromRgb(231, 76, 60))
            self.StatusIndicator.Fill = SolidColorBrush(Color.FromRgb(46, 204, 113))
            if hasattr(self, "CompactStatusIndicator"):
                self.CompactStatusIndicator.Fill = SolidColorBrush(Color.FromRgb(46, 204, 113))
            self.StatusText.Text = "Ready for commands"
            self.StatusText.Foreground = SolidColorBrush(Color.FromRgb(46, 204, 113))
            self.ActivityText.Text = "Listening on 127.0.0.1:{}...".format(self.http_server.port)
            update_ribbon_button_icon(True)
        except Exception as ex:
            log_debug("Failed to start server: {}".format(ex))
            self.StatusText.Text = "Failed to start"
            self.StatusText.Foreground = SolidColorBrush(Color.FromRgb(231, 76, 60))
            self.ActivityText.Text = str(ex)
            update_ribbon_button_icon(False)


def main():
    # Cross-version modeless window pattern (pyRevit 4.x / 5.x / 7.x / .NET 8)
    win = get_registered_window(DOMAIN_WINDOW_KEY)
    if win:
        try:
            if not win.IsVisible:
                win.Show()
            win.Activate()
            return
        except Exception:
            set_registered_window(DOMAIN_WINDOW_KEY, None)

    xaml_path = os.path.join(os.path.dirname(__file__), "ui.xaml")
    window = RevitServerWindow(xaml_path)
    set_registered_window(DOMAIN_WINDOW_KEY, window)
    window.start_server()
    window.Show()


if __name__ == "__main__":
    main()
