# -*- coding: utf-8 -*-
"""
Example: Query model elements by category with parameter inspection.
"""

from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory

category_target = BuiltInCategory.OST_Walls

collector = FilteredElementCollector(doc).OfCategory(category_target).WhereElementIsNotElementType()
elements_list = []

for elem in collector:
    eid = elem.Id.IntegerValue if hasattr(elem.Id, "IntegerValue") else elem.Id.Value
    name = getattr(elem, "Name", "")
    
    # Get Length parameter if available
    len_param = elem.LookupParameter("Length")
    len_mm = round(len_param.AsDouble() * 304.8, 1) if len_param else None

    elements_list.append({
        "id": eid,
        "name": name,
        "length_mm": len_mm
    })

response_data["count"] = len(elements_list)
response_data["elements"] = elements_list[:50] # Top 50 elements
