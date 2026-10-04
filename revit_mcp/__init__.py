# -*- coding: utf-8 -*-
"""
Revit MCP Package.
Model Context Protocol bridge for Autodesk Revit.
"""

from .client import RevitClient
try:
    from .server import server, main
except ImportError:
    server = None
    main = None

__version__ = "1.0.0"
__all__ = ["RevitClient", "server", "main"]
