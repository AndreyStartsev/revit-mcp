# Proposal: Add RevitMCP to pyRevit Official Extensions Directory

> 🎉 **Active Pull Request:** [pyrevitlabs/pyRevit#3719](https://github.com/pyrevitlabs/pyRevit/pull/3719) has been submitted to the official pyRevit repository!

This document contains the proposal and Pull Request format to centrally register **RevitMCP** into the official [pyRevit Extensions Directory](https://github.com/pyrevitlabs/pyRevit/blob/master/extensions/extensions.json).

---

## 1. Pull Request for `pyrevitlabs/pyRevit`

### Target Repository & File
- **Repository**: `https://github.com/pyrevitlabs/pyRevit`
- **Branch**: `master` (or `develop` depending on active contribution guidelines)
- **Target File**: `extensions/extensions.json`

### Proposed JSON Entry
Add the following object to the `"extensions"` array in `extensions/extensions.json`:

```json
{
  "builtin": "False",
  "type": "extension",
  "rocket_mode_compatible": "True",
  "name": "RevitMCP",
  "description": "Model Context Protocol (MCP) Bridge for Google Antigravity & AI agents to inspect, query, and automate Autodesk Revit.",
  "author": "Andrey Startsev",
  "author_profile": "https://github.com/AndreyStartsev",
  "url": "https://github.com/AndreyStartsev/revit-mcp.git",
  "website": "https://github.com/AndreyStartsev/revit-mcp",
  "image": "",
  "dependencies": []
}
```

---

### PR Title
```text
feat(extensions): add RevitMCP extension (Google Antigravity & MCP bridge)
```

### PR Body / Description
```markdown
### Summary
Proposing to add **RevitMCP** to the official pyRevit Extensions Directory (`extensions/extensions.json`).

### About RevitMCP
- **Repository**: https://github.com/AndreyStartsev/revit-mcp
- **Author**: Andrey Startsev (https://github.com/AndreyStartsev)
- **License**: MIT
- **Target**: Autodesk Revit 2020 – 2026 via pyRevit

### What does it do?
RevitMCP provides a standardized Model Context Protocol (MCP) bridge connecting Autodesk Revit with **Google Antigravity** and other AI agents (Claude Desktop, Cursor, Cline).

Key features:
1. **Direct UI Thread Python Execution**: Safe execution via `ExternalEvent` with access to `doc`, `uidoc`, `uiapp`, `app`, and `Transaction` support.
2. **Two-Way Agent Feedback**:
   - `revit_request_user_selection`: Prompts the user in Revit to pick elements, returning IDs and categories to the AI agent.
   - `revit_request_user_snip`: Prompts the user to visually snip screen regions and annotate them with arrows/boxes for multimodal AI inspection.
3. **Modal Dialog Protection**: Win32 detection alerts agents with HTTP 423 Locked when a modal dialog is open, preventing UI hangs.
4. **Deterministic Multi-Instance Ports**: Automatically assigns ports (`40001`..`40010`) when multiple Revit sessions are open.
5. **Lightweight Floating HUD**: Minimal WPF status window with pin (always on top) and compact mode. Zero audio/speech bloat.

### Verification
- Tested on Revit 2023, 2024, 2025, 2026 with pyRevit 4.8+.
- Compatible with pyRevit Rocket Mode (`rocket_mode_compatible: True`).
```

---

## 2. One-Command Installation (Available Today)

Users do not need to wait for the PR to be merged to install RevitMCP centrally. They can install it right now using the pyRevit CLI:

```bash
pyrevit extend ui RevitMCP https://github.com/AndreyStartsev/revit-mcp.git
```

To update in the future:
```bash
pyrevit extensions update RevitMCP
```

---

## 3. Custom Source Installation (via Extensions Manager GUI)

Users or enterprise BIM teams can also register this repository as a custom extension source in pyRevit:

```bash
pyrevit extensions sources add https://raw.githubusercontent.com/AndreyStartsev/revit-mcp/main/pyrevit_source.json
```

Once added, **RevitMCP** will immediately appear in the **pyRevit Extensions Manager** dialog inside Autodesk Revit (`pyRevit > Settings > Extensions`).
