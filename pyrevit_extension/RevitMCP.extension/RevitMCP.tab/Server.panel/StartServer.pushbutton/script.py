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

# Default shared cache directory - prefer user home ~/.revit_mcp for reliable write permissions across Revit 2023-2027
DEFAULT_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".revit_mcp")
SAVE_DIR = os.environ.get("REVIT_MCP_CACHE_DIR") or DEFAULT_CACHE_DIR
LOG_PATH = os.path.join(SAVE_DIR, "server.log")

def log_debug(msg):
    try:
        if not os.path.exists(SAVE_DIR):
            os.makedirs(SAVE_DIR)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_PATH, "a") as f:
            f.write("[{}] {}\n".format(ts, msg))
    except Exception:
        try:
            fallback_dir = os.path.join(os.path.expanduser("~"), ".revit_mcp")
            if not os.path.exists(fallback_dir):
                os.makedirs(fallback_dir)
            with open(os.path.join(fallback_dir, "server.log"), "a") as f:
                ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
                    try:
                        self.window.start_blinking("select", prompt_msg, categories=cats, multiple=is_multiple, done_event=done_evt)
                    except Exception as ex:
                        log_debug("start_sel_ui error: {}".format(ex))
                if self.window:
                    action_cls = getattr(self.window, "_action_cls", None) or System.Action
                    self.window.Dispatcher.BeginInvoke(action_cls(start_sel_ui))

                if done_evt.WaitOne(timeout_sec * 1000):
                    res_data = self.window.active_request_result or {} if self.window else {}
                    self._write_response(response, {"success": True, "count": len(res_data.get("elements", [])), "data": res_data}, 200)
                else:
                    def stop_sel_ui():
                        try:
                            self.window.stop_blinking()
                            self.window.StatusText.Text = "Selection timed out"
                            b = self.window._brush(149, 165, 166)
                            if b: self.window.StatusText.Foreground = b
                        except Exception as ex:
                            log_debug("stop_sel_ui error: {}".format(ex))
                    if self.window:
                        action_cls = getattr(self.window, "_action_cls", None) or System.Action
                        self.window.Dispatcher.BeginInvoke(action_cls(stop_sel_ui))
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
                    try:
                        self.window.start_blinking("screenshot", prompt_msg, categories=None, done_event=done_evt)
                    except Exception as ex:
                        log_debug("start_snip_ui error: {}".format(ex))
                if self.window:
                    action_cls = getattr(self.window, "_action_cls", None) or System.Action
                    self.window.Dispatcher.BeginInvoke(action_cls(start_snip_ui))

                if done_evt.WaitOne(timeout_sec * 1000):
                    res_data = self.window.active_request_result or {} if self.window else {}
                    self._write_response(response, {"success": True, "data": res_data}, 200)
                else:
                    def stop_snip_ui():
                        try:
                            self.window.stop_blinking()
                            self.window.StatusText.Text = "Snip request timed out"
                            b = self.window._brush(149, 165, 166)
                            if b: self.window.StatusText.Foreground = b
                        except Exception as ex:
                            log_debug("stop_snip_ui error: {}".format(ex))
                    if self.window:
                        action_cls = getattr(self.window, "_action_cls", None) or System.Action
                        self.window.Dispatcher.BeginInvoke(action_cls(stop_snip_ui))
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
                        try:
                            if busy:
                                self.window.set_theme_busy(msg or "Agent is executing...", act or "Processing command...")
                            else:
                                self.window.set_theme_idle()
                                self.window.StatusText.Text = msg or "Ready for commands"
                                b_green = self.window._brush(46, 204, 113)
                                if b_green:
                                    self.window.StatusText.Foreground = b_green
                                    self.window.StatusIndicator.Fill = b_green
                                if act:
                                    self.window.ActivityText.Text = act
                                self.window.TimeText.Text = datetime.datetime.now().strftime("%H:%M:%S")
                        except Exception as ex:
                            log_debug("update_busy_ui error: {}".format(ex))
                    action_cls = getattr(self.window, "_action_cls", None) or System.Action
                    self.window.Dispatcher.BeginInvoke(action_cls(update_busy_ui))
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

        # Pre-create Revit ExternalEvent while inside standard Revit API execution context
        try:
            self.handler = RevitExecutionHandler(self)
            self.ext_event = ExternalEvent.Create(self.handler)
        except Exception as ex:
            log_debug("Failed to create ExternalEvent in __init__: {}".format(ex))

        # Cache WPF / .NET types on instance while module globals are alive in __main__
        try:
            self._brush_cls = SolidColorBrush
            self._color_cls = Color
            self._visibility_cls = Visibility
            self._action_cls = System.Action
        except Exception as ex:
            log_debug("Failed to cache types on window: {}".format(ex))

        self._init_controls()
        self._init_events()
        self._position_window()

    def _brush(self, r, g, b):
        """Safely creates a SolidColorBrush even if module-level globals are unbound."""
        try:
            brush_cls = getattr(self, "_brush_cls", None) or SolidColorBrush
            color_cls = getattr(self, "_color_cls", None) or Color
            return brush_cls(color_cls.FromRgb(r, g, b))
        except Exception:
            try:
                from System.Windows.Media import SolidColorBrush as _SBrush, Color as _Col
                return _SBrush(_Col.FromRgb(r, g, b))
            except Exception as ex:
                log_debug("_brush creation error: {}".format(ex))
                return None

    def _visibility(self, is_visible):
        """Safely resolves Visibility enum values."""
        try:
            vis_cls = getattr(self, "_visibility_cls", None) or Visibility
            return vis_cls.Visible if is_visible else vis_cls.Collapsed
        except Exception:
            try:
                from System.Windows import Visibility as _Vis
                return _Vis.Visible if is_visible else _Vis.Collapsed
            except Exception:
                return 0 if is_visible else 2

    def _dispatch(self, callback):
        """Safely invokes a callback on the UI Dispatcher."""
        try:
            action_cls = getattr(self, "_action_cls", None) or System.Action
            self.Dispatcher.BeginInvoke(action_cls(callback))
        except Exception as ex:
            log_debug("_dispatch error: {}".format(ex))

    def _init_controls(self):
        try:
            btn_dir = os.path.dirname(__file__)
            icon_path = os.path.join(btn_dir, "icon.png")
            if os.path.exists(icon_path):
                img = load_wpf_bitmap(icon_path, 24, 24)
                if img:
                    self.LogoIcon.Source = img
                    if hasattr(self, "CompactLogoIcon"):
                        self.CompactLogoIcon.Source = img
            self.set_theme_idle()
        except Exception as ex:
            log_debug("_init_controls error: {}".format(ex))

    def _init_events(self):
        try:
            self.HeaderBar.MouseLeftButtonDown += self._on_drag_window
            if hasattr(self, "CompactHeaderBar"):
                self.CompactHeaderBar.MouseLeftButtonDown += self._on_drag_window

            self.PinBtn.Click += self._on_pin_clicked
            if hasattr(self, "CompactPinBtn"):
                self.CompactPinBtn.Click += self._on_pin_clicked

            self.MinBtn.Click += self._on_min_clicked
            if hasattr(self, "CompactMinBtn"):
                self.CompactMinBtn.Click += self._on_min_clicked

            self.CloseButton.Click += self._on_close_clicked
            if hasattr(self, "CompactCloseBtn"):
                self.CompactCloseBtn.Click += self._on_close_clicked

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
        except Exception as ex:
            log_debug("_init_events error: {}".format(ex))

    def _on_close_clicked(self, sender, e):
        try:
            self.Close()
        except Exception as ex:
            log_debug("_on_close_clicked error: {}".format(ex))

    def _on_window_closed(self, sender, e):
        try:
            if self.http_server:
                self.http_server.stop()
        except Exception as ex:
            log_debug("_on_window_closed http stop error: {}".format(ex))
        try:
            set_registered_window(DOMAIN_WINDOW_KEY, None)
        except Exception as ex:
            log_debug("_on_window_closed unregister error: {}".format(ex))

    def _position_window(self):
        try:
            screen = Screen.PrimaryScreen.WorkingArea
            self.Left = screen.Right - self.Width - 24
            self.Top = screen.Bottom - self.Height - 48
        except Exception:
            try:
                self.WindowStartupLocation = WindowStartupLocation.CenterScreen
            except Exception:
                pass

    def _on_drag_window(self, sender, e):
        try:
            self.DragMove()
        except Exception as ex:
            log_debug("_on_drag_window error: {}".format(ex))

    def _on_pin_clicked(self, sender, e):
        try:
            self.is_pinned = not self.is_pinned
            self.Topmost = self.is_pinned
            color = self._brush(241, 196, 15) if self.is_pinned else self._brush(136, 136, 153)
            if color:
                self.PinBtn.Foreground = color
                if hasattr(self, "CompactPinBtn"):
                    self.CompactPinBtn.Foreground = color
        except Exception as ex:
            log_debug("_on_pin_clicked error: {}".format(ex))

    def _on_min_clicked(self, sender, e):
        try:
            self.is_compact = not self.is_compact
            vis_exp = self._visibility(not self.is_compact)
            vis_cmp = self._visibility(self.is_compact)
            if self.is_compact:
                self.ExpandedView.Visibility = vis_exp
                self.CompactView.Visibility = vis_cmp
                self.Width = 150
                self.Height = 150
            else:
                self.CompactView.Visibility = vis_cmp
                self.ExpandedView.Visibility = vis_exp
                self.Width = 440
                self.Height = 150
        except Exception as ex:
            log_debug("_on_min_clicked error: {}".format(ex))

    def set_theme_idle(self):
        try:
            b1 = self._brush(24, 24, 31)
            b2 = self._brush(47, 47, 61)
            b3 = self._brush(18, 18, 23)
            if b1: self.MainBorder.Background = b1
            if b2: self.MainBorder.BorderBrush = b2
            if b3: self.StatusCardBorder.Background = b3
        except Exception as ex:
            log_debug("set_theme_idle error: {}".format(ex))

    def set_theme_busy(self, status_msg="Agent is executing...", activity_msg="Processing command..."):
        try:
            b1 = self._brush(40, 42, 48)
            b2 = self._brush(85, 90, 102)
            b3 = self._brush(28, 30, 35)
            b_purple = self._brush(155, 89, 182)
            b_fg = self._brush(187, 143, 206)
            if b1: self.MainBorder.Background = b1
            if b2: self.MainBorder.BorderBrush = b2
            if b3: self.StatusCardBorder.Background = b3
            if b_purple:
                self.StatusIndicator.Fill = b_purple
                if hasattr(self, "CompactStatusIndicator"):
                    self.CompactStatusIndicator.Fill = b_purple
            self.StatusText.Text = status_msg
            if b_fg:
                self.StatusText.Foreground = b_fg
            self.ActivityText.Text = activity_msg
            self.TimeText.Text = datetime.datetime.now().strftime("%H:%M:%S")
        except Exception as ex:
            log_debug("set_theme_busy error: {}".format(ex))

    def notify_request_started(self, method, path):
        def update():
            try:
                self.request_count += 1
                self.RequestCountText.Text = "Requests: {}".format(self.request_count)
                self.set_theme_busy("Active: {} {}".format(method, path), "Processing request on port {}...".format(self.http_server.port if self.http_server else ""))
            except Exception as ex:
                log_debug("notify_request_started update error: {}".format(ex))
        self._dispatch(update)

    def notify_request_finished(self, status_code, duration_sec, path):
        def update():
            try:
                self.set_theme_idle()
                b_green = self._brush(46, 204, 113)
                if b_green:
                    self.StatusIndicator.Fill = b_green
                    if hasattr(self, "CompactStatusIndicator"):
                        self.CompactStatusIndicator.Fill = b_green
                    self.StatusText.Foreground = b_green
                self.StatusText.Text = "Ready for commands"
                ms = int(duration_sec * 1000)
                self.ActivityText.Text = "{} finished ({}ms, HTTP {})".format(path, ms, status_code)
                self.TimeText.Text = datetime.datetime.now().strftime("%H:%M:%S")
            except Exception as ex:
                log_debug("notify_request_finished update error: {}".format(ex))
        self._dispatch(update)

    def notify_request_error(self, err_msg):
        def update():
            try:
                self.set_theme_idle()
                b_red = self._brush(231, 76, 60)
                if b_red:
                    self.StatusIndicator.Fill = b_red
                    if hasattr(self, "CompactStatusIndicator"):
                        self.CompactStatusIndicator.Fill = b_red
                    self.StatusText.Foreground = b_red
                self.StatusText.Text = "Error"
                self.ActivityText.Text = str(err_msg)
                self.TimeText.Text = datetime.datetime.now().strftime("%H:%M:%S")
            except Exception as ex:
                log_debug("notify_request_error update error: {}".format(ex))
        self._dispatch(update)

    def start_modal_blinking(self, modal_title="Modal Dialog"):
        try:
            self.blinking_button = "modal"
            b_yellow = self._brush(241, 196, 15)
            if b_yellow:
                self.StatusIndicator.Fill = b_yellow
                self.StatusText.Foreground = b_yellow
            self.StatusText.Text = "WAITING: Modal Dialog Open"
            self.ActivityText.Text = "Revit is blocked by '{}'. Close it to resume.".format(modal_title or "dialog")
        except Exception as ex:
            log_debug("start_modal_blinking error: {}".format(ex))

    def stop_modal_blinking(self):
        try:
            if self.blinking_button == "modal":
                self.blinking_button = None
                b_green = self._brush(46, 204, 113)
                if b_green:
                    self.StatusIndicator.Fill = b_green
                    self.StatusText.Foreground = b_green
                self.StatusText.Text = "Ready for commands"
                self.ActivityText.Text = "Listening on 127.0.0.1:{}...".format(self.http_server.port if self.http_server else "")
        except Exception as ex:
            log_debug("stop_modal_blinking error: {}".format(ex))

    def start_blinking(self, target, prompt_msg, categories=None, multiple=False, done_event=None):
        try:
            self.stop_blinking()
            self.blinking_button = target
            self.active_request_event = done_event
            self.requested_categories = categories
            self.requested_multiple = multiple
            self.active_request_result = None

            if target == "select":
                self.StatusText.Text = "AGENT ASKS FOR SELECTION"
                b_purple = self._brush(155, 89, 182)
                if b_purple: self.StatusText.Foreground = b_purple
                mode_hint = "(Multiple + Finish)" if multiple else "(Click 1 Element)"
                self.ActivityText.Text = "{}: {}".format(mode_hint, prompt_msg)
            elif target == "screenshot":
                self.StatusText.Text = "AGENT ASKS FOR SCREENSHOT"
                b_blue = self._brush(52, 152, 219)
                if b_blue: self.StatusText.Foreground = b_blue
                self.ActivityText.Text = prompt_msg

            try:
                from System.Windows.Threading import DispatcherTimer
                self.blinking_timer = DispatcherTimer()
                self.blinking_timer.Interval = System.TimeSpan.FromMilliseconds(450)
                self.blinking_timer.Tick += self._on_blink_tick
                self.blinking_timer.Start()
            except Exception as ex:
                log_debug("DispatcherTimer start error: {}".format(ex))
        except Exception as top_ex:
            log_debug("start_blinking error: {}".format(top_ex))

    def _on_blink_tick(self, sender, e):
        try:
            self.blinking_state = not self.blinking_state
            if self.blinking_button == "select":
                btn = self.SelectBtn
                b = self._brush(241, 196, 15) if self.blinking_state else self._brush(142, 68, 173)
                if b: btn.Background = b
            elif self.blinking_button == "screenshot":
                btn = self.ScreenshotBtn
                b = self._brush(241, 196, 15) if self.blinking_state else self._brush(41, 128, 185)
                if b: btn.Background = b
        except Exception as ex:
            log_debug("_on_blink_tick error: {}".format(ex))

    def stop_blinking(self):
        try:
            if self.blinking_timer:
                self.blinking_timer.Stop()
                self.blinking_timer = None
            b_purple = self._brush(142, 68, 173)
            b_blue = self._brush(41, 128, 185)
            if b_purple: self.SelectBtn.Background = b_purple
            if b_blue: self.ScreenshotBtn.Background = b_blue
            self.blinking_button = None
        except Exception as ex:
            log_debug("stop_blinking error: {}".format(ex))

    def _on_select_clicked(self, sender, e):
        try:
            is_requested = (self.blinking_button == "select")
            cats = self.requested_categories
            multiple = self.requested_multiple if is_requested else False

            self.stop_blinking()
            self.StatusText.Text = "Selecting elements..."
            b_purple = self._brush(155, 89, 182)
            if b_purple:
                self.StatusText.Foreground = b_purple

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
                b_green = self._brush(46, 204, 113)
                if b_green:
                    self.StatusText.Foreground = b_green

            except Exception as ex:
                log_debug("Selection exception or cancel: {}".format(ex))
                self.StatusText.Text = "Selection canceled"
                b_gray = self._brush(149, 165, 166)
                if b_gray:
                    self.StatusText.Foreground = b_gray
                self.active_request_result = {"count": 0, "elements": [], "canceled": True}
            finally:
                if self.active_request_event:
                    try:
                        self.active_request_event.Set()
                    except:
                        pass
        except Exception as top_ex:
            log_debug("_on_select_clicked fatal error: {}".format(top_ex))

    def _on_screenshot_clicked(self, sender, e):
        try:
            self.stop_blinking()
            try:
                import snipper
                
                def on_snip_saved(meta):
                    try:
                        self.active_request_result = meta
                        self.StatusText.Text = "Snip saved"
                        b_green = self._brush(46, 204, 113)
                        if b_green:
                            self.StatusText.Foreground = b_green
                        if self.active_request_event:
                            try:
                                self.active_request_event.Set()
                            except:
                                pass
                    except Exception as snip_ex:
                        log_debug("on_snip_saved callback error: {}".format(snip_ex))

                snipper.launch_snipper(on_snip_saved)
            except Exception as ex:
                log_debug("Screenshot clicked error: {}".format(ex))
                self.StatusText.Text = "Snip error"
                b_red = self._brush(231, 76, 60)
                if b_red:
                    self.StatusText.Foreground = b_red
        except Exception as top_ex:
            log_debug("_on_screenshot_clicked top error: {}".format(top_ex))

    def _on_toggle_clicked(self, sender, e):
        try:
            if self.http_server and self.http_server.running:
                self.http_server.stop()
                self.http_server = None
                self.ToggleBtn.Content = "Start Server"
                b_green = self._brush(46, 204, 113)
                if b_green:
                    self.ToggleBtn.Background = b_green
                    if hasattr(self, "CompactToggleBtn"):
                        self.CompactToggleBtn.Background = b_green
                b_gray = self._brush(149, 165, 166)
                if b_gray:
                    self.StatusIndicator.Fill = b_gray
                    if hasattr(self, "CompactStatusIndicator"):
                        self.CompactStatusIndicator.Fill = b_gray
                    self.StatusText.Foreground = b_gray
                self.StatusText.Text = "Server Stopped"
                self.ActivityText.Text = "Click 'Start Server' to resume"
                update_ribbon_button_icon(False)
            else:
                self.start_server()
        except Exception as ex:
            log_debug("_on_toggle_clicked error: {}".format(ex))

    def start_server(self):
        try:
            if not getattr(self, "handler", None):
                self.handler = RevitExecutionHandler(self)
            if not getattr(self, "ext_event", None):
                self.ext_event = ExternalEvent.Create(self.handler)

            if self.http_server and getattr(self.http_server, "running", False):
                return

            self.http_server = AsyncHttpServer(BASE_PORT, self.handler, self.ext_event, self)
            self.http_server.start()

            self.PortBadge.Text = " :{}".format(self.http_server.port)
            self.ToggleBtn.Content = "Stop Server"
            b_red = self._brush(231, 76, 60)
            b_green = self._brush(46, 204, 113)
            if b_red:
                self.ToggleBtn.Background = b_red
                if hasattr(self, "CompactToggleBtn"):
                    self.CompactToggleBtn.Background = b_red
            if b_green:
                self.StatusIndicator.Fill = b_green
                if hasattr(self, "CompactStatusIndicator"):
                    self.CompactStatusIndicator.Fill = b_green
                self.StatusText.Foreground = b_green
            if hasattr(self, "CompactPortBadge"):
                self.CompactPortBadge.Text = ":{}".format(self.http_server.port)
            if hasattr(self, "CompactStatusText"):
                self.CompactStatusText.Text = "Ready"
                if b_green:
                    self.CompactStatusText.Foreground = b_green
            self.StatusText.Text = "Ready for commands"
            self.ActivityText.Text = "Listening on 127.0.0.1:{}...".format(self.http_server.port)
            update_ribbon_button_icon(True)
        except Exception as ex:
            log_debug("Failed to start server: {}".format(ex))
            self.StatusText.Text = "Failed to start"
            b_red = self._brush(231, 76, 60)
            if b_red:
                self.StatusText.Foreground = b_red
            self.ActivityText.Text = str(ex)
            update_ribbon_button_icon(False)


def main():
    # Cross-version modeless window pattern (pyRevit 4.x / 5.x / 7.x / .NET 8)
    win = get_registered_window(DOMAIN_WINDOW_KEY)
    if win:
        try:
            # Hot-reload updated methods onto existing window instance
            for method_name in ["start_server", "_on_toggle_clicked", "_brush", "_visibility", "_dispatch", "_on_close_clicked"]:
                if hasattr(RevitServerWindow, method_name):
                    setattr(win, method_name, getattr(RevitServerWindow, method_name).__get__(win, RevitServerWindow))

            # If ExternalEvent wasn't created yet or was lost, we are inside standard Revit API execution right now in main()!
            if not getattr(win, "handler", None):
                win.handler = RevitExecutionHandler(win)
            if not getattr(win, "ext_event", None):
                win.ext_event = ExternalEvent.Create(win.handler)
            if not win.IsVisible:
                win.Show()
            win.Activate()
            # If server is stopped, restart it safely on ribbon click
            if not win.http_server or not getattr(win.http_server, "running", False):
                win.start_server()
            return
        except Exception as ex:
            log_debug("Error activating existing window in main: {}".format(ex))
            set_registered_window(DOMAIN_WINDOW_KEY, None)

    xaml_path = os.path.join(os.path.dirname(__file__), "ui.xaml")
    window = RevitServerWindow(xaml_path)
    set_registered_window(DOMAIN_WINDOW_KEY, window)
    window.start_server()
    window.Show()


if __name__ == "__main__":
    main()
