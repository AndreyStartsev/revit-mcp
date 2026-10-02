# -*- coding: utf-8 -*-
"""
Revit MCP Package.
Model Context Protocol bridge for Autodesk Revit.
"""

from .client import RevitClient
from .server import server, main

__version__ = "1.0.0"
__all__ = ["RevitClient", "server", "main"]
