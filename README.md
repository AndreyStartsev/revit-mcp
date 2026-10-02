# Revit MCP Bridge

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Revit](https://img.shields.io/badge/Autodesk%20Revit-2020--2026-orange.svg)](https://www.autodesk.com/products/revit/)
[![pyRevit](https://img.shields.io/badge/pyRevit-4.8%2B-green.svg)](https://pyrevitlabs.notion.site/)
[![MCP](https://img.shields.io/badge/MCP-1.0%2B-purple.svg)](https://modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A lightweight, dedicated **Model Context Protocol (MCP)** bridge connecting **Autodesk Revit** with modern AI agents and LLM clients (such as **Claude Desktop**, **Cursor**, **Antigravity**, **Cline**, and others).

> **Pure Communication Focus:** This standalone variant contains **strictly communication and execution tools** (Revit API execution, element queries, view screenshots, interactive selection, and visual snips). It is free of third-party voice models, local Whisper dependencies, or speech-to-text overhead.

---

## 🌟 Features

- ⚡ **Direct Revit API Execution**: Run arbitrary Python scripts on the Revit main UI thread safely using `ExternalEvent`. Access `doc`, `uidoc`, `uiapp`, and `app`.
- 🔄 **Multi-Instance Support**: Multiple open Revit models automatically receive incremental ports (`40001`, `40002`, ...). MCP sessions deterministically bind to specific models.
- 🎯 **Interactive Element Selection**: AI agents can ask the user to pick elements in Revit (`revit_request_user_selection`), flashing the HUD button and returning picked IDs and categories.
- ✂️ **Visual Screen Snip & Markup**: Prompt the user to snip screen regions and annotate them with arrows, boxes, and freehand sketches (`revit_request_user_snip`).
- 🛡️ **Modal Dialog Protection**: Win32 detection checks whether Revit is blocked by a modal dialog, reporting HTTP 423 Locked instead of freezing requests indefinitely.
- 📸 **Automated High-Res Screenshots**: Capture the active Revit view as a PNG image directly into the agent's context.
- 🪟 **Minimal Floating HUD**: Clean WPF window displaying server status, active port, request counter, latency, pin (always-on-top), and compact minimize mode.

---

## 🏗️ Architecture

```
┌───────────────────────────────────────┐
│     AI Agent / LLM Client             │
│  (Claude Desktop / Cursor / etc.)     │
└──────────────────┬────────────────────┘
                   │ stdio (JSON-RPC)
┌──────────────────▼────────────────────┐
│      Revit MCP Server (Python)        │
│          revit_mcp/server.py          │
└──────────────────┬────────────────────┘
                   │ HTTP / JSON (127.0.0.1:40001+)
┌──────────────────▼────────────────────┐
│      Autodesk Revit (pyRevit)         │
│   ┌────────────────────────────────┐  │
│   │ AsyncHttpServer (HttpListener) │  │
│   └──────────────┬─────────────────┘  │
│                  │ ExternalEvent      │
│   ┌──────────────▼─────────────────┐  │
│   │  Revit Main UI Thread Execution │  │
│   │  (doc, uidoc, uiapp, app)      │  │
│   └────────────────────────────────┘  │
└───────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Step 1: Install the pyRevit Extension

1. Ensure [pyRevit](https://github.com/eirannejad/pyRevit) is installed in Autodesk Revit.
2. Copy or symlink the folder `pyrevit_extension/RevitMCP.extension` into your pyRevit extensions directory:
   ```powershell
   # Default pyRevit extension directory:
   %APPDATA%\pyRevit\Extensions\RevitMCP.extension
   ```
   Or attach it via pyRevit CLI:
   ```bash
   pyrevit extend ui RevitMCP path/to/pyrevit_extension/RevitMCP.extension
   ```
3. In Revit, click the **Revit MCP** button on the ribbon tab to start the server. The floating HUD will appear and display **Ready for commands** on `127.0.0.1:40001`.

---

### Step 2: Install the Python MCP Server

Clone this repository and install dependencies:

```bash
git clone https://github.com/your-username/revit-mcp.git
cd revit-mcp

# Install dependencies or install in editable mode
pip install -e .
```

Verify connection to Revit:
```bash
python tests/test_connection.py
```

---

### Step 3: Configure Your AI Client

#### Claude Desktop
Add to `%APPDATA%\Claude\claude_desktop_config.json` (Windows) or `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "revit": {
      "command": "python",
      "args": ["-m", "revit_mcp"]
    }
  }
}
```

#### Cursor (.cursor/mcp.json)
```json
{
  "mcpServers": {
    "revit": {
      "command": "python",
      "args": ["-m", "revit_mcp"]
    }
  }
}
```

---

## 🛠️ Available MCP Tools

| Tool | Description |
|------|-------------|
| `revit_ping` | Checks connection health and reports the active Revit instance and document. |
| `revit_list_instances` | Lists all active Revit instances across ports `40001`..`40010`. |
| `revit_set_active_instance` | Binds the session to a specific instance by port or model name. |
| `revit_get_active_model` | Retrieves metadata about the active model (title, path, view, levels). |
| `revit_execute_python` | Executes arbitrary Python in Revit via Revit API (`doc`, `uidoc`, `uiapp`, `app`). |
| `revit_get_selection` | Returns currently selected elements, categories, and parameters. |
| `revit_get_element_geometry` | Retrieves exact bounding boxes (mm), locations, rotations, and levels. |
| `revit_get_warnings` | Retrieves all active model warnings and failing element IDs. |
| `revit_capture_screenshot` | Captures an automated high-resolution PNG of the active Revit view. |
| `revit_get_latest_screenshot` | Retrieves metadata and file path of the most recent screenshot or snip. |
| `revit_request_user_selection` | Prompts user in Revit to click element(s) with optional category filtering. |
| `revit_request_user_snip` | Prompts user to snip screen area and annotate with built-in markup tools. |
| `revit_set_busy` | Controls the visual busy indicator and theme color in the Revit HUD. |

---

## 💡 Python Execution Pattern

When using `revit_execute_python`, you write code as if you were running inside pyRevit. Always use transactions when modifying the model:

```python
from Autodesk.Revit.DB import Transaction, FilteredElementCollector, BuiltInCategory

# 1. Access objects in scope: doc, uidoc, uiapp, app
collector = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Walls).WhereElementIsNotElementType()

# 2. Modify with Transaction
t = Transaction(doc, "Set Comments")
t.Start()
for wall in collector:
    param = wall.LookupParameter("Comments")
    if param and not param.IsReadOnly:
        param.Set("Verified by MCP")
t.Commit()

# 3. Return results via response_data
response_data["wall_count"] = collector.GetElementCount()
response_data["status"] = "Success"
```

---

## 🖥️ Direct Python Client

If you want to communicate with Revit without an MCP client (for testing or automation scripts), use the included `RevitClient`:

```python
from revit_mcp import RevitClient

client = RevitClient(port=40001)

# Health check
print(client.ping())

# Execute code
res = client.execute_python("""
response_data['doc_title'] = doc.Title if doc else 'No Document'
""")
print(res['data'])
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
