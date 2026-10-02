# -*- coding: utf-8 -*-
"""
Revit Client - Lightweight Python HTTP client for Revit MCP server.
Enables programmatic interaction with Autodesk Revit over local HTTP.
"""

import json
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List


class RevitClient:
    """Client for communicating directly with Revit HTTP server."""

    def __init__(self, host: str = "127.0.0.1", port: int = 40001, timeout: float = 60.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.base_url = f"http://{self.host}:{self.port}"

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = None
        headers = {"Content-Type": "application/json"}
        
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        req_timeout = timeout if timeout is not None else self.timeout

        try:
            with urllib.request.urlopen(req, timeout=req_timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8")
                return json.loads(err_body)
            except Exception:
                return {"success": False, "status_code": e.code, "error": str(e)}
        except Exception as ex:
            return {"success": False, "error": str(ex)}

    def ping(self) -> Dict[str, Any]:
        """Checks connection to the Revit server."""
        return self._request("GET", "/api/status", timeout=2.0)

    def get_status(self) -> Dict[str, Any]:
        """Retrieves active document and Revit state."""
        return self._request("GET", "/api/status")

    def check_modal(self) -> Dict[str, Any]:
        """Checks if Revit is currently blocked by a modal dialog."""
        return self._request("GET", "/api/check_modal")

    def execute_python(self, code: str, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Executes arbitrary Python code inside Revit on the main UI thread."""
        return self._request("POST", "/api/execute", payload={"code": code}, timeout=timeout)

    def capture_screenshot(self) -> Dict[str, Any]:
        """Exports the active Revit view as a PNG screenshot."""
        return self._request("POST", "/api/screenshot")

    def request_user_selection(self, prompt: str = "Select elements", categories: Optional[List[str]] = None, multiple: bool = False, timeout: int = 90) -> Dict[str, Any]:
        """Prompts user to select element(s) in Revit."""
        return self._request("POST", "/api/request_user_selection", payload={
            "prompt": prompt,
            "categories": categories,
            "multiple": multiple,
            "timeout": timeout
        }, timeout=float(timeout + 5))

    def request_user_snip(self, prompt: str = "Snip screen area", timeout: int = 90) -> Dict[str, Any]:
        """Prompts user to snip screen area and annotate."""
        return self._request("POST", "/api/request_user_snip", payload={
            "prompt": prompt,
            "timeout": timeout
        }, timeout=float(timeout + 5))

    def set_busy(self, busy: bool = True, message: Optional[str] = None, activity: Optional[str] = None) -> Dict[str, Any]:
        """Sets the busy indicator on the Revit HUD."""
        return self._request("POST", "/api/set_busy", payload={
            "busy": busy,
            "message": message,
            "activity": activity
        })
