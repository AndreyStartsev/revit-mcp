# -*- coding: utf-8 -*-
"""
Example: Batch parameter update with transaction management.
"""

from Autodesk.Revit.DB import Transaction, FilteredElementCollector, BuiltInCategory

t = Transaction(doc, "Batch Parameter Update via MCP")
t.Start()

updated_count = 0
try:
    # Example: update 'Comments' parameter on selected or target elements
    collector = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Walls).WhereElementIsNotElementType()
    for elem in collector:
        param = elem.LookupParameter("Comments")
        if param and not param.IsReadOnly:
            param.Set("Reviewed by AI Agent")
            updated_count += 1
            if updated_count >= 10:
                break
    t.Commit()
    response_data["success"] = True
    response_data["updated_count"] = updated_count
except Exception as ex:
    t.RollBack()
    response_data["success"] = False
    response_data["error"] = str(ex)
