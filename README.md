# Revit MCP Bridge for Google Antigravity

[![Google Antigravity](https://img.shields.io/badge/AI%20Agent-Google%20Antigravity-4285F4?logo=google&logoColor=white)](https://deepmind.google/)
[![Autodesk Revit](https://img.shields.io/badge/Autodesk%20Revit-2020--2026-orange.svg)](https://www.autodesk.com/products/revit/)
[![pyRevit](https://img.shields.io/badge/pyRevit-4.8%2B-green.svg)](https://pyrevitlabs.notion.site/)
[![MCP](https://img.shields.io/badge/MCP-1.0%2B-purple.svg)](https://modelcontextprotocol.io/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A dedicated, high-performance **Model Context Protocol (MCP)** bridge engineered natively for **Google Antigravity** (and compatible with Claude Desktop, Cursor, Cline, and Windsurf) to connect autonomous AI agents with **Autodesk Revit**.

> **Communication-First Architecture:** This standalone variant delivers a pure, rock-solid communication layer for Revit automation — free of external voice/speech-to-text models, audio recording, or bloated dependencies. All multimodal interaction (visual markup, view inspection, interactive element selection) happens directly through the MCP protocol and Antigravity's multimodal reasoning engine.

---

## 🚀 Built for Google Antigravity

Antigravity operates as an autonomous BIM engineering assistant with continuous feedback loops directly inside Autodesk Revit:

```
┌────────────────────────────────────────────────────────┐
│              Google Antigravity AI Agent               │
│       (Autonomous BIM Coding & Multimodal Vision)      │
└───────────────────────────┬────────────────────────────┘
                            │ stdio (MCP JSON-RPC)
┌───────────────────────────▼────────────────────────────┐
│              Revit MCP Server Bridge (Python)          │
│                    revit_mcp/server.py                 │
└───────────────────────────┬────────────────────────────┘
                            │ HTTP / JSON (127.0.0.1:40001+)
┌───────────────────────────▼────────────────────────────┐
│               Autodesk Revit (pyRevit)                 │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Revit MCP Floating HUD (Visual State & Control) │  │
│  │  - 🎯 Interactive Pick Elements (User Input)     │  │
│  │  - ✂️ Screen Snip & Visual Markup (Multimodal)   │  │
│  │  - 🛡️ Modal Dialog Lock Detection                │  │
│  │  - 🚦 Live Busy/Idle State Indicator             │  │
│  └────────────────────────┬─────────────────────────┘  │
│                           │ ExternalEvent              │
│  ┌────────────────────────▼─────────────────────────┐  │
│  │  Revit Main UI Thread Execution Engine           │  │
│  │  (doc, uidoc, uiapp, app, Transactions)          │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

### Key Antigravity Agent Capabilities

1. **Two-Way Interactive User Requests**:
   - **🎯 Interactive Element Picking (`revit_request_user_selection`)**: When Antigravity needs the user to designate a specific element (e.g., room boundary, clashing pipe, equipment), the Revit HUD button flashes gold/purple. The user clicks the element in Revit, and its ID, category, and metadata are immediately returned to Antigravity without manual typing.
   - **✂️ Visual Snip & Markup (`revit_request_user_snip`)**: Antigravity can ask the user to visually circle or annotate areas of interest. The user draws arrows/boxes using the built-in screen snipper, and the annotated image is piped straight into Antigravity's vision context.
2. **Visual Busy State Lifecycle (`revit_set_busy`)**:
   - The Revit HUD panel turns Gray while Antigravity is processing or executing transactions, and switches back to Green when Antigravity is done and awaiting user input.
3. **Modal Dialog Safety**:
   - If a modal window opens in Revit (e.g. warning dialog or file dialog), Revit MCP immediately detects it via Win32 API and returns `HTTP 423 Locked`, alerting Antigravity instead of hanging the agent indefinitely.
4. **Deterministic Multi-Instance Binding**:
   - Running multiple Revit versions or multiple documents concurrently? Each instance binds to an incremental port (`40001`, `40002`, ...), and Antigravity locks its session strictly to the target model without accidental cross-project execution.

---

## 🌟 Features

- ⚡ **Direct Revit API Execution**: Run arbitrary Python scripts on the Revit main UI thread safely using `ExternalEvent`. Access `doc`, `uidoc`, `uiapp`, and `app`.
- 🔄 **Multi-Instance Support**: Multiple open Revit models automatically receive incremental ports (`40001`, `40002`, ...).
- 🎯 **Interactive Element Selection**: AI agents can ask the user to pick elements in Revit (`revit_request_user_selection`).
- ✂️ **Visual Screen Snip & Markup**: Prompt the user to snip screen regions and annotate them with arrows, boxes, and freehand sketches (`revit_request_user_snip`).
- 🛡️ **Modal Dialog Protection**: Win32 detection checks whether Revit is blocked by a modal dialog, reporting HTTP 423 Locked instead of freezing requests indefinitely.
- 📸 **Automated High-Res Screenshots**: Capture the active Revit view as a PNG image directly into the agent's context.
- 🪟 **Minimal Floating HUD**: Clean WPF window displaying server status, active port, request counter, latency, pin (always-on-top), and compact minimize mode.

---

## 🚀 Quick Start

### Step 1: Install the pyRevit Extension

You can install the RevitMCP extension into pyRevit centrally using any of the methods below:

#### Option A: Central CLI Installation (Recommended — 1 Command)
Run in PowerShell / Command Prompt:
```bash
pyrevit extend ui RevitMCP https://github.com/AndreyStartsev/revit-mcp.git
```
To update in the future:
```bash
pyrevit extensions update RevitMCP
```

#### Option B: Central pyRevit Extension Manager (GUI)
Register the repository source centrally in pyRevit:
```bash
pyrevit extensions sources add https://raw.githubusercontent.com/AndreyStartsev/revit-mcp/main/pyrevit_source.json
```
Now open Autodesk Revit, navigate to **pyRevit > Settings > Extensions**, select **RevitMCP**, and click **Install**.

> 💡 *Official pyRevit catalog submission: [Pull Request #3719](https://github.com/pyrevitlabs/pyRevit/pull/3719) is currently open in `pyrevitlabs/pyRevit` (see details in [PYREVIT_PROPOSAL.md](PYREVIT_PROPOSAL.md)).*

#### Option C: Manual Installation
Clone or copy this repository directly into your pyRevit extensions folder:
```powershell
# Default pyRevit extension directory:
git clone https://github.com/AndreyStartsev/revit-mcp.git "%APPDATA%\pyRevit\Extensions\RevitMCP.extension"
```

Once installed, click the **Revit MCP** button on the ribbon tab to start the server. The floating HUD will appear and display **Ready for commands** on `127.0.0.1:40001`.

---

### Step 2: Install the Python MCP Server

Clone this repository and install dependencies:

```bash
git clone https://github.com/AndreyStartsev/revit-mcp.git
cd revit-mcp

# Install dependencies or install in editable mode
pip install -e .
```

Verify connection to Revit:
```bash
python tests/test_connection.py
```

---

### Step 3: Connect & Activate Your AI Agent

#### 🤖 Google Antigravity (Primary & Fully Supported)

Google Antigravity is the primary, first-class autonomous agent environment designed to work seamlessly with Revit MCP out-of-the-box.

##### 1. Register the MCP Server in Antigravity
Open or create your global Antigravity MCP configuration:
- **Windows**: `%USERPROFILE%\.gemini\config\mcp_config.json` (or your workspace MCP configuration)

Add the `revit` server entry:
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
*(If you are running in a dedicated virtual environment or pyRevit CPython, specify the full path to `python.exe`)*.

##### 2. Automatic Agent Guidelines (`GEMINI.md`)
Antigravity automatically discovers and ingests [`GEMINI.md`](GEMINI.md) from the root of this workspace. This equips the agent with:
- **Visual HUD State Tracking**: The agent automatically invokes `revit_set_busy(busy=True)` at the very start of its reasoning to turn the floating HUD gray, and calls `revit_set_busy(busy=False)` upon completing its response.
- **Strict Transaction Handling**: Safe wrapping in `Transaction(doc, ...)`, rollback on errors, and suppression of modal blocking dialogs via `IFailuresPreprocessor`.
- **Multimodal Interaction**: Native capability to trigger interactive element selection (`revit_request_user_selection`) and visual markup requests (`revit_request_user_snip`).
- **Coordinate & Level Normalization**: Relative elevation anchoring ($Z_{\text{rel}} = Z_{\text{world}} - Z_{\text{host\_level}}$) and linked model transform handling.
- **Spatial Integrity**: Strict protection against unauthorized element movement or rotation.

##### 3. Activate & Verify in Antigravity Chat
1. Launch Autodesk Revit and open your project.
2. Click the **Revit MCP** button on the ribbon tab to launch the server and floating HUD (displays `Ready` on `127.0.0.1:40001`).
3. In Antigravity chat, send a verification prompt:
   > *"Check the active Revit model, report connection status, and list available views."*
4. You will see the floating HUD turn **Gray** while Antigravity reasons and executes tools, and return to **Dark/Ready** when the response is delivered.

---

#### 💡 Advice for Other Agentic Systems (Claude Desktop, Cursor, Cline, Windsurf)

While this bridge is optimized natively for Google Antigravity, it complies with the open Model Context Protocol standard and can be connected to other MCP clients:

1. **Client Configuration**:
   - **Claude Desktop** (`%APPDATA%\Claude\claude_desktop_config.json` on Windows):
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
   - **Cursor** (`.cursor/mcp.json`) / **Cline** / **Windsurf**:
     Add the same `mcpServers` definition into your client's MCP configuration settings.

2. **System Prompt / Rules Porting**:
   - Other clients do not automatically read `GEMINI.md`. To achieve the same reliability:
     - **Cursor**: Copy the rules from [`GEMINI.md`](GEMINI.md) into your `.cursorrules` or `.cursor/rules/revit.mdc`.
     - **Claude Desktop**: Append the rules into Project Custom Instructions or your initial prompt.
     - **Cline / Windsurf**: Add the rules into your `.clinerules` or workspace instructions.
   - **Critical Rule to Include**: Instruct the agent to always wrap Revit API modifications in `Transaction(doc, ...)` and attach an `IFailuresPreprocessor` so modal dialogs don't freeze the client.

3. **Multimodal Capabilities**:
   - For visual tools (`revit_capture_screenshot` and `revit_request_user_snip`), ensure your agent is configured with a vision-capable multimodal model (e.g., Claude 3.5 Sonnet, GPT-4o, or Gemini 1.5 Pro).

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

When using `revit_execute_python`, you write standard Revit API Python code. Always use transactions when modifying the model:

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
        param.Set("Verified by Antigravity")
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

## 🔒 Security & Concurrency Architecture

- **Shared Secret Authentication**: On startup, Revit MCP generates a cryptographically random session token (`auth_token`). All incoming HTTP API requests require `Authorization: Bearer <token>` or `X-Auth-Token`.
- **Zero CORS Vulnerability**: By design, all `Access-Control-Allow-*` CORS headers are removed, ensuring web browsers cannot perform cross-origin script executions from malicious websites.
- **Thread-Safe FIFO Execution Queue**: Remote commands are enqueued in a thread-safe FIFO queue (`collections.deque` protected by locks). Each request awaits its own `ManualResetEvent`, eliminating race conditions when multiple agents or subagents query Revit concurrently.
- **Cross-Version pyRevit & .NET 8 Compatibility**: Modeless window management and external event handling are verified across pyRevit 4.x, 5.x, and 7.x on .NET Framework 4.8 and modern .NET 8 (Revit 2023–2027).

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
