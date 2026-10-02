# -*- coding: utf-8 -*-
"""
Quick connection and execution test for Revit MCP.
Run this script to verify that your Revit instance is reachable and working.
"""

import sys
import os
import json
import argparse

# Ensure parent directory is in sys.path when running script directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from revit_mcp.client import RevitClient


def run_test(port=None):
    print("========================================")
    print(" Revit MCP - Connection Self-Test")
    print("========================================")
    
    ports_to_try = [port] if port else [40001, 40002, 40003, 40004, 40005, 40000]
    client = None
    status = None

    for p in ports_to_try:
        c = RevitClient(port=p)
        st = c.ping()
        if st and st.get("status") == "running":
            client = c
            status = st
            break

    if not client:
        print(f"[-] Could not connect to Revit on ports: {ports_to_try}")
        print("Please verify that:")
        print(" 1. Autodesk Revit is running.")
        print(" 2. The 'Revit MCP' extension is installed in pyRevit.")
        print(" 3. The server button in Revit is turned ON (Green status).")
        sys.exit(1)

    print(f"[+] Connected successfully! Revit Version: {status.get('revit_version')}")
    print(f"    Document: {status.get('doc_title')}")
    print(f"    View: {status.get('active_view')}")
    print(f"    Port: {status.get('port')}")

    # 2. Check modal dialog
    modal_info = client.check_modal()
    if modal_info.get("is_modal_blocked"):
        print(f"[!] Warning: Revit UI thread is currently blocked by modal dialog '{modal_info.get('modal_title')}'.")
    else:
        print("[+] UI Thread is free (no modal dialogs blocking).")

    # 3. Simple execution test
    print("\nTesting remote Python execution in Revit UI thread...")
    code = """
response_data['math_test'] = 2 + 2
response_data['doc_title'] = doc.Title if doc else 'No Document'
"""
    res = client.execute_python(code)
    if res.get("success"):
        print(f"[+] Execution succeeded! Data returned: {json.dumps(res.get('data'), indent=2)}")
    else:
        print(f"[-] Execution failed: {res}")
        sys.exit(1)

    print("\n[+] All tests passed successfully! Revit MCP is ready for AI agents.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Revit MCP connection.")
    parser.add_argument("--port", type=int, default=None, help="Target Revit MCP port (default: auto-scan 40001..40005)")
    args = parser.parse_args()
    run_test(port=args.port)

