# Revit MCP Assistant - Agent Guidelines

You are connected to an Autodesk Revit instance via the Model Context Protocol (MCP) bridge.

## Environment Context
- **Active Revit Model**: Query dynamically via `revit_get_active_model` or `revit_ping`.
- **MCP Server Name**: `revit`
- **Revit Server Endpoints**: Candidate ports `40001` through `40010` on `http://127.0.0.1`.
- **Execution Architecture**: Thread-safe FIFO queue executed on the Revit UI thread via pyRevit `ExternalEvent`, secured by shared secret token authentication (`auth_token`).

## Critical Rules
1. **Language & Code Rules**:
   - Source code, comments, string literals, and UI layouts (XAML, WPF buttons) MUST be written in **English**.
   - User chat communication can be in Russian.
2. **Revit API Execution & Transaction Safety**:
   - When executing Python code in Revit via `revit_execute_python`:
     - Access `doc`, `uidoc`, `uiapp`, `app`.
     - Write return values to `response_data['my_key'] = ...`.
     - Wrap any model modifications inside transactions with rollback on failure:
       ```python
       from Autodesk.Revit.DB import Transaction
       t = Transaction(doc, "Descriptive Action Name")
       t.Start()
       try:
           # modifications here
           t.Commit()
       except Exception as ex:
           t.RollBack()
           raise ex
       ```
     - Suppress modal warning dialogs during batch operations by attaching an `IFailuresPreprocessor`:
       ```python
       from Autodesk.Revit.DB import IFailuresPreprocessor, FailureProcessingResult

       class WarningSwallower(IFailuresPreprocessor):
           def PreprocessFailures(self, failuresAccessor):
               failuresAccessor.DeleteAllWarnings()
               return FailureProcessingResult.Continue

       options = t.GetFailureHandlingOptions()
       options.SetFailuresPreprocessor(WarningSwallower())
       t.SetFailureHandlingOptions(options)
       ```
     - Wrap heavy queries in `try...except` and return descriptive diagnostic error messages.
3. **Threading & .NET 8 / Revit 2025 Compatibility**:
   - Avoid dynamic anonymous Python lambdas inside .NET `ThreadStart` delegates.
   - Use `System.Threading.ManualResetEvent` for thread synchronization.
4. **Visual Context & Screenshots Distinction**:
   - **User Markup / Snip**: When the user draws or snips context in Revit ("Snip & Markup"), query via `revit_get_latest_user_snip` (`latest_user_snip.png` / `latest_user_snip.json`). This file is dedicated to user input and is never overwritten by agent automated captures.
   - **Agent View Capture**: When the agent needs to inspect the current Revit view dynamically, trigger `revit_capture_screenshot` (`latest_agent_screenshot.png` / `latest_agent_screenshot.json`, with `"source": "agent"`).
   - **Unified Latest**: `revit_get_latest_screenshot` inspects the most recent screenshot and clearly indicates `"source": "user"` or `"source": "agent"`.
5. **Interactive User Requests & HUD Button Handling**:
   - **Request Elements**: When the agent needs the user to select elements:
     - **Single Element (`multiple=False`, default)**: e.g. picking a single room, sprinkler, or pipe. The user clicks once in Revit and the tool instantly returns without needing to press "Finish".
     - **Multiple Elements (`multiple=True`)**: e.g. picking multiple clashing elements or a list of diffusers. The user clicks several elements and presses "Finish".
     - Call `revit_request_user_selection(prompt="...", categories=["Sprinklers"], multiple=False)`. The Revit HUD button `Pick Elements` will flash gold/purple, display "(Click 1)" or "(Select multiple + Finish)", enforce `BuiltInCategory` filters on both host and linked models, and return the picked elements.
   - **Request Visual Snip**: When the agent needs the user to draw/circle something on screen, call `revit_request_user_snip(prompt="...")`. The `Snip & Draw` button will flash gold/blue and wait for the user to complete their drawing.
6. **Element Integrity & Strict No Auto-Rotation Rule**:
   - **NEVER** rotate, translate, or mutate the spatial orientation or position of existing MEP elements (sprinklers, diffusers, pipes, equipment) during dimensioning, analysis, or annotation workflows. Elements must remain exactly as modeled.
   - Dimension lines must dynamically align to the element's existing orientation vector, or group only parallel elements together.
   - Always attach an `IFailuresPreprocessor` to annotation transactions to handle non-parallel reference failures cleanly without prompting modal blocking dialogs in Revit.
7. **Visual Panel Busy State Lifecycle**:
   - The Revit Antigravity HUD panel indicates whether the agent is active (Gray background) or ready/idle (Black background).
   - **Start with Busy**: The agent MUST invoke `revit_set_busy(busy=True)` as its very first tool action upon receiving a user request or initiating task execution. This immediately turns the Revit HUD gray, clearly informing the user that the agent is actively thinking and processing.
   - **End with Ready**: Always invoke `revit_set_busy(busy=False)` as the final tool call before presenting your completed response to the user so the panel transitions back to Black exactly when you are done.
8. **Step-by-Step Multi-Phase Workflow Discipline (Zero Step-Skipping Invariant)**:
   - In complex multi-phase workflows (such as `revit-model-setup`):
     - The agent MUST NEVER skip, bundle, or jump over any workflow phase.
     - At every interactive phase (`[INTERACTIVE]`), the agent MUST STOP calling tools, output the step banner `[MODEL SETUP: STEP X/11 — <NAME>]`, state the current status, give explicit user instructions or questions, and WAIT for user response.
     - The agent MUST NOT proceed to Step N+1 until Step N is completed and confirmed by user action or explicit automated verification.
9. **Extension File Preservation & Strict Local-Copy Rule**:
   - **NEVER** edit, overwrite, or modify files located in an external source extension directory directly.
   - If changes, tests, or adaptations are required, **ALWAYS** copy the relevant script/module into the local workspace (`revit-mcp` or scratch directory) and modify/execute it locally.
10. **Automated User Context Tracking & Multi-Instance Processed State Invariant**:
   - **Per-Instance & Model Isolation**:
     - State in `processed_context_state.json` is partitioned by model/instance (`doc_title` / `port`), ensuring operations in one model (e.g. `SPR_Rasko` on :40001) never collide with or overwrite context tracking for another model (e.g. `FP_BAR` on :40002).
   - **Verification on Every Request**:
     - At every turn/request involving Revit model operations or user queries:
       - Check `revit_get_latest_user_snip` and `revit_get_latest_selection` for the targeted instance.
       - Compare their `timestamp` against the instance-specific entry in `~/.revit_mcp/processed_context_state.json`.
       - If a new user snip or element selection is detected (timestamp > last processed for this model), immediately inspect and use it as primary task context.
       - If context was cleared (`exists: false` or empty), treat gracefully as a clean slate.
       - Once processed, update `processed_context_state.json` for that specific model/port to mark it as completed.
11. **Common Level Elevation Referencing Invariant (Z-Coordinate Normalization)**:
   - In MEP design and spatial reasoning, absolute world Z coordinates must **NEVER** be used in isolation for engineering decisions, coverage analysis, clearance checks, or user reporting, because linked architectural models often have different survey points, shared coordinates, or link vertical origins.
   - **Single Common Level Baseline**:
     - All vertical coordinates must be normalized and designated relative to the element's host Level:
       $$Z_{\text{rel}} = Z_{\text{world}} - Z_{\text{host\_level}}$$
     - Always explicitly state the reference Level name and relative elevation (e.g. `Level 24 (+2300 mm)`).
     - When analyzing room heights and ceiling limits from linked models:
       - **ALWAYS** apply the link instance's `TotalTransform` (`tr.OfPoint(...)`) to bring the room bounding box and boundary curves into host space.
       - Normalize room floor and ceiling elevations against the same common reference Level (e.g. `Floor: -600 mm (slab) / 0 mm (finish)`, `Ceiling: +2300 mm`).
       - Never allow room heights to span arbitrary link coordinate deltas (such as 40m shifts).
12. **Strict Human Approval for Git / GitHub Communication**:
   - If any comment, review, question, issue, or response from a human user/maintainer is detected on Git or GitHub (e.g., Pull Requests, Issues, Discussions, Code Reviews):
   - The agent **MUST NEVER** reply, post comments, or communicate on Git/GitHub autonomously without explicit prior review and approval from the USER in chat.
   - Whenever a human message or review is found on GitHub, the agent must report it to the user, prepare a proposed response draft, and **WAIT** for the user's explicit consent before publishing anything.
13. **Direct HTTP Bridge Fallback**:
   - If MCP tools (`revit_*`) are not directly registered or exposed in the agent's current session:
     - The agent **MUST NOT** fail or abort.
     - Instead, interact directly with the running Revit instance via its local REST HTTP bridge:
       - Discover active instances, ports, and Bearer `auth_token` from JSON files in `~/.revit_mcp/instances/` (`C:\Users\<user>\.revit_mcp\instances\`).
       - Send requests with `Authorization: Bearer <auth_token>`:
         - Remote Python execution: `POST http://127.0.0.1:<port>/api/execute` with payload `{"code": "..."}`.
         - Visual busy state: `POST http://127.0.0.1:<port>/api/set_busy` with payload `{"busy": true/false}`.
         - Agent screenshot: `POST http://127.0.0.1:<port>/api/screenshot`.


