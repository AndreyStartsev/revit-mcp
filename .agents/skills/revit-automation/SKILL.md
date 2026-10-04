---
name: revit-automation
description: >-
  Expert workflows for querying, inspecting, modifying, and automating Autodesk Revit BIM models via Revit API, pyRevit, and MCP.
---

# Revit Automation Skill

## Capabilities
1. **Live Model Inspection**:
   - Query active document (`revit_get_active_model`), view, elements, parameters, categories.
   - Inspect selection (`revit_get_selection`) and warnings (`revit_get_warnings`).
2. **Code Execution via Revit API**:
   - Execute Python code with `revit_execute_python`.
   - Access `doc`, `uidoc`, `uiapp`, `app`, and `response_data`.
3. **pyRevit Integration & Extension Tools**:
   - Smart Disconnect (`revit_smart_disconnect.py`): Cleanly remove pipe branches or sprinklers, automatically merging collinear main pipe segments into a continuous single pipe or turning Tees into Elbows to eliminate orphan open connectors.
   - Run any pyRevit pushbutton in `Exetnsion.extension` using `revit_run_script` or `revit_execute_python`.
4. **Visual Context & Screenshots**:
   - **User Markup/Snips**: `revit_get_latest_user_snip` reads `latest_user_snip.png` / `latest_user_snip.json` (contains user annotations/drawings, never overwritten by agent).
   - **Agent View Captures**: `revit_capture_screenshot` exports Revit view as `latest_agent_screenshot.png` / `latest_agent_screenshot.json` (`source: "agent"`).
   - **Latest Screenshot Info**: `revit_get_latest_screenshot` inspects the most recent screenshot with `source: "user" | "agent"`.


## Smart Disconnect Tool (Branch & Fitting Collapse)
When disconnecting sprinklers, branch pipes, or collapsing fittings:
- Do not leave orphan Tee fittings with disconnected open connectors.
- Detect neighbor pipes connected to the Tee:
  - If 2 neighbors are collinear: merge into 1 pipe, stretch curve between far ends, delete the second pipe and Tee, reconnect far ends.
  - If 2 neighbors are at an angle: delete Tee, create a `NewElbowFitting`.
- Available script module: `revit_smart_disconnect.py`.

## Sprinkler Autotrace Tool (Branch Construction & Sizing)
For automatic branch routing and connection of sprinklers to main supply pipes:
- Source algorithm: `G:\My Drive\Exetnsion.extension\ASTools.tab\Test.panel\Sprinkler autotrace.pushbutton\script.py` / `revit_sprinkler_trace.py`.
- Features:
  - Local Coordinate System (`CS1`) aligned with the main pipe axis.
  - Logical grouping (`create_logical_groups`) with outlier and twig handling (`MAX_TWIG_LENGTH_FEET ~ 2.0 m`).
  - Native Placeholder Graph (`Pipe.CreatePlaceholder`, `PlumbingUtils.ConnectPipePlaceholdersAtElbow`, `PlumbingUtils.ConnectPipePlaceholdersAtTee`).
  - Automatic NFPA Pipe Sizing traversal (`calculate_sprinkler_counts` + `sizing_table`).
  - Atomic conversion to physical Revit pipes and fittings via `PlumbingUtils.ConvertPipePlaceholders`.
- Available script module: `revit_sprinkler_trace.py`.

## Best Practices
- **Extension Safety**: Never modify `G:/My Drive/Exetnsion.extension` files in-place. Always copy files to the local workspace (`revit-mcp` or scratch) before editing or running customized versions.
- Always wrap modifications in `Transaction(doc, "Transaction Name")`.
- Attach an `IFailuresPreprocessor` with `DeleteAllWarnings()` to transactions to avoid blocking UI modals.
- **HUD Busy State**: Always invoke `revit_set_busy(busy=True)` as the very first tool call when initiating reasoning or execution, and `revit_set_busy(busy=False)` as the final tool call before presenting completed results.
- Extract parameters using `BuiltInParameter` when possible for language-independent reliability.
- Return structured JSON in `response_data` dictionary.

