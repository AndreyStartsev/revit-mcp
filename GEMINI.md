# Autodesk Revit MCP Assistant — Agent Guidelines (Google Antigravity)

You are connected to an Autodesk Revit instance via the Model Context Protocol (MCP) bridge (`revit-mcp`).
These guidelines define operational rules, transaction patterns, and interactive workflow protocols for autonomous BIM engineering.

## 1. Environment & Architecture
- **MCP Server Name**: `revit` (defined in `revit_mcp/server.py`).
- **Communication Protocol**:
  - Agent to Bridge: stdio (MCP JSON-RPC).
  - Bridge to Revit: Local HTTP JSON endpoints (`127.0.0.1:40001`..`40010`).
  - Revit Execution: Thread-safe FIFO queue executed on the Revit UI thread via pyRevit `ExternalEvent`.
- **Active Model Discovery**: Always check connection health and the active document via `revit_ping` or `revit_get_active_model`.

## 2. Core Execution Rules
1. **Revit API Execution (`revit_execute_python`)**:
   - Variables available in global scope: `doc` (Document), `uidoc` (UIDocument), `uiapp` (UIApplication), `app` (Application).
   - Write return values to the dictionary: `response_data['key'] = value`.
   - Wrap any model modifications inside transactions:
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
   - Always wrap complex queries in `try...except` and provide clear diagnostic error messages.

2. **Dialog & Failure Preprocessing**:
   - Suppress modal warning dialogs during automated batch modifications by implementing `IFailuresPreprocessor`:
     ```python
     from Autodesk.Revit.DB import IFailuresPreprocessor, FailureProcessingResult

     class WarningSwallower(IFailuresPreprocessor):
         def PreprocessFailures(self, failuresAccessor):
             failuresAccessor.DeleteAllWarnings()
             return FailureProcessingResult.Continue
     ```
   - Attach the preprocessor to transaction failure options before committing:
     ```python
     options = t.GetFailureHandlingOptions()
     options.SetFailuresPreprocessor(WarningSwallower())
     t.SetFailureHandlingOptions(options)
     ```

3. **Element Spatial Integrity**:
   - **NEVER** rotate, translate, or mutate the spatial orientation or position of existing MEP or architectural elements unless explicitly instructed by the user.
   - Dynamic annotations and dimension lines must align with the existing vector of the elements.

4. **Coordinate & Level Normalization**:
   - In BIM models and MEP coordination, never rely on absolute world Z coordinates in isolation.
   - Normalize vertical elevations relative to the element's host Level ($Z_{\text{rel}} = Z_{\text{world}} - Z_{\text{host\_level}}$).
   - When inspecting linked architectural models, always apply the link instance's `TotalTransform` (`tr.OfPoint(...)`) to bring geometry into host model space.

## 3. Visual Panel & HUD Lifecycle
The floating Revit HUD indicates the agent's real-time state directly inside Autodesk Revit:
- **Idle / Ready**: Panel has a dark/black background (waiting for user input).
- **Busy / Processing**: Panel has a gray background (agent is actively reasoning, querying, or modifying the model).
- **Lifecycle Invariants**:
  - **Start with Busy**: The agent MUST invoke `revit_set_busy(busy=True)` as its very first tool action upon receiving a user request or initiating task execution. This immediately turns the Revit HUD gray, clearly informing the user that the agent is actively thinking and processing.
  - **End with Ready**: The agent MUST invoke `revit_set_busy(busy=False)` as its very final tool action immediately before presenting the completed response to the user, ensuring the panel transitions back to Black/Ready state.

## 4. Multimodal & Interactive Workflows
1. **Interactive Element Selection (`revit_request_user_selection`)**:
   - When you need the user to identify an element, call `revit_request_user_selection(prompt="...", categories=[...], multiple=False)`.
   - The Revit HUD button `Pick Elements` will flash to alert the user.
   - For a single element (`multiple=False`), the user clicks once in Revit and the selection completes immediately without pressing "Finish".
   - For multiple elements (`multiple=True`), the user clicks elements and clicks "Finish".
2. **Visual Markup & Screen Snip (`revit_request_user_snip`)**:
   - When you need visual clarification or user annotations, call `revit_request_user_snip(prompt="...")`.
   - The HUD button `Snip & Draw` flashes, allowing the user to circle or draw arrows on the view.
   - The annotated image is saved to `latest_user_snip.png` and can be retrieved via `revit_get_latest_user_snip`.
3. **Automated View Inspection (`revit_capture_screenshot`)**:
   - When you need to inspect the current 2D/3D view autonomously, call `revit_capture_screenshot`.
   - The high-resolution image is saved to `latest_agent_screenshot.png` and never overwrites user-drawn markups.

## 5. Multi-Instance Management
- Multiple running Revit instances run on ports `40001`, `40002`, etc.
- Use `revit_list_instances` to inspect available instances.
- Use `revit_set_active_instance(port=...)` or specify `target_port` / `target_doc` in tool arguments to ensure operations target the desired document deterministically.
