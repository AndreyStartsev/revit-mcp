# -*- coding: utf-8 -*-
"""
Example: Query basic project information, levels, and linked models.
Can be sent to Revit via revit_execute_python.
"""

from Autodesk.Revit.DB import FilteredElementCollector, Level, RevitLinkInstance

info = {}
if doc:
    info["title"] = doc.Title
    info["path"] = doc.PathName
    info["is_family"] = doc.IsFamilyDocument
    
    # Collect levels
    levels = FilteredElementCollector(doc).OfClass(Level).ToElements()
    info["levels"] = [
        {
            "id": l.Id.IntegerValue if hasattr(l.Id, "IntegerValue") else l.Id.Value,
            "name": l.Name,
            "elevation_mm": round(l.Elevation * 304.8, 1)
        } for l in levels
    ]
    
    # Collect links
    links = FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements()
    info["links"] = [
        {
            "id": l.Id.IntegerValue if hasattr(l.Id, "IntegerValue") else l.Id.Value,
            "name": l.Name
        } for l in links
    ]

response_data["project_info"] = info
