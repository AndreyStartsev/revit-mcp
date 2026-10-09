# -*- coding: utf-8 -*-
"""
Revit MCP Live Visual & 3D Spatial Dashboard Server
Features:
1. Real-time 2D visual captures & user markup stream
2. Interactive 3D Spatial Context Viewer (Three.js + OrbitControls):
   - Cylindrical 3D pipes (real diameter, smooth joints, metallic finish)
   - Sprinklers with directional spray cones and spray direction arrows (Pendent / Upright / Sidewall orientation)
   - Air Terminals & Diffusers with air throw vectors & grilles
   - MEP Connectors & active port routing
3. Live Element Selection & Parameter Inspector
4. Agent State & Dialogue Timeline Monitor
Port: 5055
"""

import os
import sys
import glob
import time
import json
import mimetypes
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import urllib.request
import threading

WORKSPACE_DIR = r"C:\Users\user49\.gemini\antigravity\scratch\revit-mcp"
BRAIN_BASE_DIR = r"C:\Users\user49\.gemini\antigravity\brain"
BRAIN_DIR = r"C:\Users\user49\.gemini\antigravity\brain\848c6833-ce77-4465-95cb-3696bcfd5766"
SCREENSHOTS_DIR = os.path.join(WORKSPACE_DIR, "screenshots")
PORT = 5055

if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

try:
    import send_prompt
except Exception:
    send_prompt = None

def get_current_conversation_id(port=None):
    if send_prompt:
        try:
            env_data = send_prompt.get_active_env()
            return send_prompt.get_target_conversation_id(env_data, port=port)
        except Exception:
            pass
    return None

def get_auth_token_for_port(port=40001):
    try:
        inst_dir = os.path.expanduser("~/.revit_mcp/instances")
        if port:
            inst_file = os.path.join(inst_dir, f"instance_{port}.json")
            if os.path.exists(inst_file):
                with open(inst_file, "r", encoding="utf-8") as f:
                    return json.load(f).get("auth_token", "")
        for p in glob.glob(os.path.join(inst_dir, "instance_*.json")):
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
                if not port or d.get("port") == port:
                    return d.get("auth_token", "")
    except Exception:
        pass
    return ""

_LIVE_USER_PROMPTS = []

def get_chat_history(conversation_id=None, port=None, limit=40):
    cid = conversation_id or get_current_conversation_id(port=port)
    if not cid:
        return {"success": False, "error": "No active conversation found", "messages": [], "conversation_id": None}

    full_path = os.path.join(BRAIN_BASE_DIR, cid, ".system_generated", "logs", "transcript_full.jsonl")
    compact_path = os.path.join(BRAIN_BASE_DIR, cid, ".system_generated", "logs", "transcript.jsonl")
    target_path = full_path if os.path.exists(full_path) else compact_path

    msgs = []
    if os.path.exists(target_path):
        try:
            with open(target_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if "USER_INPUT" not in line and "PLANNER_RESPONSE" not in line and "SYSTEM_MESSAGE" not in line:
                        continue
                    try:
                        d = json.loads(line)
                        t = d.get("type")
                        if t == "USER_INPUT":
                            c = d.get("content", "") or ""
                            if "<USER_REQUEST>" in c:
                                text = c.split("<USER_REQUEST>")[1].split("</USER_REQUEST>")[0].strip()
                            elif "<SYSTEM_MESSAGE>" in c or "not actually sent by the user" in c:
                                continue
                            else:
                                text = c.strip()
                            if text:
                                msgs.append({
                                    "role": "user",
                                    "text": text,
                                    "timestamp": d.get("created_at", ""),
                                    "step_index": d.get("step_index")
                                })
                        elif t == "SYSTEM_MESSAGE":
                            c = d.get("content", "") or ""
                            if "[Message]" in c and "content=" in c:
                                parts = c.split("content=", 1)
                                if len(parts) > 1:
                                    m_text = parts[1]
                                    if "</SYSTEM_MESSAGE>" in m_text:
                                        m_text = m_text.split("</SYSTEM_MESSAGE>")[0]
                                    m_text = m_text.strip()
                                    if m_text and not m_text.startswith("Task id "):
                                        msgs.append({
                                            "role": "user",
                                            "text": m_text,
                                            "timestamp": d.get("created_at", ""),
                                            "step_index": d.get("step_index")
                                        })
                        elif t == "PLANNER_RESPONSE":
                            c = d.get("content", "") or ""
                            if c.strip():
                                msgs.append({
                                    "role": "assistant",
                                    "text": c.strip(),
                                    "timestamp": d.get("created_at", ""),
                                    "step_index": d.get("step_index")
                                })
                    except Exception:
                        pass
        except Exception as e:
            return {"success": False, "error": str(e), "messages": [], "conversation_id": cid}

    # Merge recent live prompts dispatched through dashboard
    existing_texts = {m.get("text", "").strip() for m in msgs}
    for lp in _LIVE_USER_PROMPTS:
        if lp.get("text", "").strip() not in existing_texts:
            msgs.append(lp)

    return {"success": True, "conversation_id": cid, "messages": msgs[-limit:]}

def dispatch_antigravity_prompt(prompt_text, port=None, conv_id=None):
    if not prompt_text or not prompt_text.strip():
        return False, "Prompt is empty", None
    
    clean_prompt = prompt_text.strip()
    if not send_prompt:
        return False, "send_prompt module not available", None

    doc_title = None
    if not port:
        try:
            inst_dir = os.path.expanduser("~/.revit_mcp/instances")
            inst_files = glob.glob(os.path.join(inst_dir, "instance_*.json"))
            if inst_files:
                with open(inst_files[0], "r", encoding="utf-8") as f:
                    idata = json.load(f)
                    port = idata.get("port")
                    doc_title = idata.get("doc_title")
        except Exception:
            port = 40001
    else:
        try:
            inst_file = os.path.expanduser(f"~/.revit_mcp/instances/instance_{port}.json")
            if os.path.exists(inst_file):
                with open(inst_file, "r", encoding="utf-8") as f:
                    doc_title = json.load(f).get("doc_title")
        except Exception:
            pass

    success, msg = send_prompt.send_prompt(clean_prompt, port=port, doc_title=doc_title, conv_id=conv_id)
    
    if success:
        _LIVE_USER_PROMPTS.append({
            "role": "user",
            "text": clean_prompt,
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "step_index": None
        })
        if len(_LIVE_USER_PROMPTS) > 30:
            _LIVE_USER_PROMPTS.pop(0)

    if success and port:
        try:
            auth_token = get_auth_token_for_port(port)
            if auth_token:
                req_data = json.dumps({"busy": True}).encode("utf-8")
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/set_busy",
                    data=req_data,
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {auth_token}"}
                )
                urllib.request.urlopen(req, timeout=1.5)
        except Exception:
            pass

    conv_id = get_current_conversation_id(port=port)
    return success, msg, conv_id

def load_manual_archived_projects():
    with _ARCHIVE_LOCK:
        path = os.path.join(WORKSPACE_DIR, "manual_archived_projects.json")
        if not os.path.exists(path):
            path = os.path.join(BRAIN_DIR, "manual_archived_projects.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        if "archived_projects" in data and isinstance(data["archived_projects"], dict):
                            return data["archived_projects"]
                        return data
            except Exception as e:
                print(f"[Archive] Error loading manual_archived_projects.json: {e}")
        return {}

def save_manual_archived_projects(archived_map, action_entry=None):
    with _ARCHIVE_LOCK:
        path = os.path.join(WORKSPACE_DIR, "manual_archived_projects.json")
        brain_path = os.path.join(BRAIN_DIR, "manual_archived_projects.json")
        
        history = []
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old = json.load(f)
                    if isinstance(old, dict) and "history" in old and isinstance(old["history"], list):
                        history = old["history"]
            except Exception:
                pass
                
        if action_entry:
            history.append(action_entry)
            if len(history) > 300:
                history = history[-300:]
                
        payload = {
            "updated_at": datetime.now().isoformat(),
            "archived_projects": archived_map,
            "history": history
        }
        
        for p in [path, brain_path]:
            try:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"[Archive] Error saving to {p}: {e}")

_CACHED_SEL_TS = ""
_CACHED_SEL_DATA = None

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Revit MCP • 3D Spatial & Visual Context Dashboard</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <!-- Three.js + OrbitControls -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    <style>
        :root {
            --bg-base: #0a0c10;
            --bg-surface: #11141d;
            --bg-card: #171b26;
            --bg-card-hover: #1e2333;
            --border-color: #23293d;
            --border-bright: #394263;
            --text-main: #e2e8f0;
            --text-dim: #94a3b8;
            --text-muted: #64748b;
            --accent-purple: #8b5cf6;
            --accent-gold: #f59e0b;
            --accent-cyan: #06b6d4;
            --accent-emerald: #10b981;
            --accent-rose: #f43f5e;
            --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: var(--bg-base);
            color: var(--text-main);
            font-family: var(--font-sans);
            line-height: 1.5;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            overflow-x: hidden;
        }

        header {
            background: linear-gradient(180deg, rgba(17,20,29,0.95) 0%, rgba(10,12,16,0.85) 100%);
            backdrop-filter: blur(12px);
            border-bottom: 1px solid var(--border-color);
            padding: 0.75rem 1.5rem;
            position: sticky;
            top: 0;
            z-index: 50;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .brand-group {
            display: flex;
            align-items: center;
            gap: 0.85rem;
        }

        .brand-icon {
            width: 32px;
            height: 32px;
            border-radius: 8px;
            background: linear-gradient(135deg, var(--accent-purple), var(--accent-cyan));
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            color: #fff;
            box-shadow: 0 0 16px rgba(139, 92, 246, 0.4);
        }

        .brand-title {
            font-size: 1.05rem;
            font-weight: 600;
            letter-spacing: -0.02em;
            display: flex;
            align-items: center;
            gap: 0.6rem;
        }

        .badge-live {
            font-size: 0.65rem;
            text-transform: uppercase;
            font-weight: 700;
            padding: 2px 7px;
            border-radius: 9999px;
            background: rgba(16, 185, 129, 0.15);
            color: var(--accent-emerald);
            border: 1px solid rgba(16, 185, 129, 0.3);
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }

        .badge-live::before {
            content: "";
            width: 6px;
            height: 6px;
            background-color: var(--accent-emerald);
            border-radius: 50%;
            box-shadow: 0 0 8px var(--accent-emerald);
            animation: pulse-dot 1.5s infinite;
        }

        @keyframes pulse-dot {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.4; transform: scale(0.85); }
        }

        .tabs-nav {
            display: flex;
            background: var(--bg-surface);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 2px;
            gap: 2px;
        }

        .tab-btn {
            background: transparent;
            border: none;
            color: var(--text-dim);
            font-size: 0.8rem;
            font-weight: 600;
            padding: 6px 14px;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.15s ease;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .tab-btn.active {
            background: var(--accent-purple);
            color: #fff;
            box-shadow: 0 2px 8px rgba(139, 92, 246, 0.3);
        }

        .header-meta {
            display: flex;
            align-items: center;
            gap: 1rem;
            font-size: 0.82rem;
            font-family: var(--font-mono);
        }

        .agent-status-tag {
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: 600;
            background: var(--bg-surface);
            border: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .status-idle { color: var(--accent-emerald); border-color: rgba(16,185,129,0.3); }
        .status-busy { color: var(--accent-gold); border-color: rgba(245,158,11,0.4); }

        main {
            padding: 1.25rem 1.5rem 80px 1.5rem;
            display: grid;
            grid-template-columns: 1fr 340px;
            gap: 1.25rem;
            flex: 1;
            max-width: 1920px;
            margin: 0 auto;
            width: 100%;
        }

        @media (max-width: 1200px) {
            main {
                grid-template-columns: 1fr;
            }
        }

        .panel {
            background: var(--bg-surface);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            box-shadow: 0 8px 24px rgba(0,0,0,0.3);
            position: relative;
        }

        .panel-header {
            padding: 0.75rem 1.25rem;
            background: rgba(23, 27, 38, 0.6);
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .panel-title {
            font-size: 0.95rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .panel-badge {
            font-size: 0.7rem;
            padding: 2px 8px;
            border-radius: 4px;
            background: var(--bg-card);
            color: var(--text-dim);
            font-family: var(--font-mono);
            border: 1px solid var(--border-color);
        }

        /* 3D Spatial Canvas Container */
        #three-container {
            width: 100%;
            height: 640px;
            background: radial-gradient(circle at center, #141824 0%, #07090e 100%);
            position: relative;
            outline: none;
            overflow: hidden;
        }

        .three-overlay {
            position: absolute;
            top: 12px;
            left: 12px;
            background: rgba(17, 20, 29, 0.88);
            backdrop-filter: blur(8px);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 8px 12px;
            font-size: 0.75rem;
            font-family: var(--font-mono);
            color: var(--text-dim);
            pointer-events: none;
            z-index: 10;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .three-controls-hint {
            position: absolute;
            bottom: 12px;
            right: 12px;
            background: rgba(17, 20, 29, 0.85);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 5px 12px;
            font-size: 0.72rem;
            color: var(--text-muted);
            pointer-events: none;
            z-index: 10;
        }

        /* Viewport Toolbar */
        .viewport-toolbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0.6rem 1.25rem;
            background: rgba(17, 20, 29, 0.95);
            border-bottom: 1px solid var(--border-color);
            gap: 1rem;
            flex-wrap: wrap;
        }

        .viewport-tools-group {
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }

        .vtool-btn {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            color: var(--text-dim);
            padding: 0.35rem 0.75rem;
            font-size: 0.75rem;
            font-weight: 600;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.18s ease;
            display: flex;
            align-items: center;
            gap: 0.35rem;
        }

        .vtool-btn:hover {
            background: var(--bg-card-hover);
            color: var(--text-main);
            border-color: var(--border-bright);
        }

        .vtool-btn.active {
            background: rgba(139, 92, 246, 0.25);
            color: #c4b5fd;
            border-color: var(--accent-purple);
            box-shadow: 0 0 10px rgba(139, 92, 246, 0.35);
        }

        .viewport-toggles {
            display: flex;
            align-items: center;
            gap: 0.85rem;
        }

        .toggle-pill {
            display: flex;
            align-items: center;
            gap: 0.4rem;
            font-size: 0.73rem;
            color: var(--text-muted);
            cursor: pointer;
            user-select: none;
        }

        .toggle-pill input[type="checkbox"] {
            accent-color: var(--accent-cyan);
            cursor: pointer;
        }

        .toggle-pill:hover {
            color: var(--text-main);
        }

        /* Elevation HUD Overlay */
        .elevation-hud-overlay {
            position: absolute;
            top: 12px;
            right: 12px;
            width: 285px;
            background: rgba(14, 18, 28, 0.94);
            backdrop-filter: blur(12px);
            border: 1px solid var(--border-bright);
            border-radius: 10px;
            padding: 10px 14px;
            font-family: var(--font-sans);
            z-index: 15;
            box-shadow: 0 8px 24px rgba(0,0,0,0.55);
            display: flex;
            flex-direction: column;
            gap: 6px;
            pointer-events: none;
        }

        .ehud-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid rgba(255,255,255,0.08);
            padding-bottom: 5px;
        }

        .ehud-title {
            font-size: 0.72rem;
            font-weight: 700;
            color: var(--text-dim);
            letter-spacing: 0.05em;
        }

        .ehud-badge {
            font-size: 0.65rem;
            font-weight: 700;
            padding: 1px 6px;
            border-radius: 4px;
            background: rgba(139, 92, 246, 0.25);
            color: #c4b5fd;
            border: 1px solid rgba(139, 92, 246, 0.4);
            font-family: var(--font-mono);
        }

        .ehud-grid {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .ehud-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.74rem;
        }

        .ehud-k {
            color: var(--text-muted);
        }

        .ehud-v {
            font-family: var(--font-mono);
            font-weight: 600;
            color: var(--text-main);
        }

        .highlight-lvl { color: #38bdf8; }
        .highlight-spk { color: #f43f5e; font-weight: 700; text-shadow: 0 0 8px rgba(244, 63, 94, 0.4); }
        .highlight-cl { color: #f59e0b; font-weight: 700; }

        .ehud-status {
            margin-top: 4px;
            padding: 5px 8px;
            background: rgba(6, 182, 212, 0.12);
            border: 1px solid rgba(6, 182, 212, 0.3);
            border-radius: 6px;
            font-size: 0.7rem;
            color: #67e8f9;
            font-weight: 500;
            text-align: center;
        }

        /* 2D Views Grid */
        .views-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.25rem;
            padding: 1.25rem;
        }

        @media (max-width: 768px) {
            .views-grid {
                grid-template-columns: 1fr;
            }
        }

        .image-card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            transition: all 0.2s ease;
        }

        .image-card:hover {
            border-color: var(--border-bright);
            box-shadow: 0 6px 20px rgba(0,0,0,0.4);
        }

        .image-card-header {
            padding: 0.65rem 0.9rem;
            background: rgba(10, 12, 16, 0.4);
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .card-tag {
            font-size: 0.72rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            padding: 2px 6px;
            border-radius: 4px;
        }

        .tag-agent { background: rgba(139, 92, 246, 0.2); color: #c4b5fd; border: 1px solid rgba(139,92,246,0.3); }
        .tag-user { background: rgba(245, 158, 11, 0.2); color: #fde68a; border: 1px solid rgba(245,158,11,0.3); }

        .image-viewport {
            height: 380px;
            background: #08090d;
            position: relative;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            cursor: zoom-in;
        }

        .image-viewport img {
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
            transition: transform 0.25s ease;
        }

        .image-viewport:hover img {
            transform: scale(1.02);
        }

        .image-meta-footer {
            padding: 0.65rem 0.9rem;
            font-size: 0.78rem;
            font-family: var(--font-mono);
            color: var(--text-dim);
            background: var(--bg-card);
            border-top: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        /* History Strip */
        .history-section {
            padding: 1.25rem;
            border-top: 1px solid var(--border-color);
        }

        .history-title {
            font-size: 0.82rem;
            font-weight: 600;
            margin-bottom: 0.75rem;
            color: var(--text-dim);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .history-scroll {
            display: flex;
            gap: 0.75rem;
            overflow-x: auto;
            padding-bottom: 0.5rem;
        }

        .history-scroll::-webkit-scrollbar {
            height: 6px;
        }

        .history-scroll::-webkit-scrollbar-thumb {
            background: var(--border-bright);
            border-radius: 4px;
        }

        .history-thumb {
            flex: 0 0 130px;
            height: 85px;
            background: #08090d;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            overflow: hidden;
            position: relative;
            cursor: pointer;
            transition: transform 0.15s ease, border-color 0.15s ease;
        }

        .history-thumb:hover {
            transform: translateY(-2px);
            border-color: var(--accent-purple);
        }

        .history-thumb img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }

        .history-thumb-time {
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            background: rgba(0,0,0,0.75);
            font-size: 0.65rem;
            padding: 2px 4px;
            font-family: var(--font-mono);
            text-align: center;
        }

        /* AGENT CONTEXT TAB STYLES */
        .context-mission-card {
            background: linear-gradient(135deg, rgba(139,92,246,0.12) 0%, rgba(6,182,212,0.08) 100%);
            border: 1px solid rgba(139, 92, 246, 0.35);
            border-radius: 10px;
            padding: 1.1rem;
            margin: 1.25rem;
            box-shadow: 0 4px 20px rgba(139, 92, 246, 0.1);
        }

        .mission-badge {
            font-size: 0.7rem;
            text-transform: uppercase;
            font-weight: 700;
            letter-spacing: 0.05em;
            padding: 3px 8px;
            border-radius: 4px;
            background: rgba(139, 92, 246, 0.25);
            color: #c4b5fd;
            border: 1px solid rgba(139, 92, 246, 0.4);
            display: inline-flex;
            align-items: center;
            gap: 5px;
            margin-bottom: 0.5rem;
        }

        .mission-title {
            font-size: 1.1rem;
            font-weight: 700;
            color: #fff;
            margin-bottom: 0.4rem;
        }

        .mission-purpose {
            font-size: 0.86rem;
            color: var(--text-dim);
            line-height: 1.5;
        }

        .context-grid-2col {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.25rem;
            padding: 0 1.25rem 1.25rem 1.25rem;
        }

        @media (max-width: 900px) {
            .context-grid-2col {
                grid-template-columns: 1fr;
            }
        }

        .context-subcard {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 1rem;
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
        }

        .context-subcard-header {
            font-size: 0.85rem;
            font-weight: 600;
            color: var(--text-main);
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 0.5rem;
        }

        .deduction-item {
            background: rgba(10, 12, 18, 0.5);
            border-left: 3px solid var(--accent-cyan);
            border-radius: 0 6px 6px 0;
            padding: 8px 12px;
            font-size: 0.82rem;
            line-height: 1.45;
            color: #cbd5e1;
        }

        .checklist-item {
            display: flex;
            align-items: flex-start;
            gap: 8px;
            font-size: 0.82rem;
            padding: 6px 8px;
            background: rgba(10, 12, 18, 0.4);
            border-radius: 6px;
            border: 1px solid var(--border-color);
        }

        .check-badge {
            font-size: 0.65rem;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 4px;
            text-transform: uppercase;
            font-family: var(--font-mono);
            flex-shrink: 0;
        }

        .check-confirmed { background: rgba(16, 185, 129, 0.2); color: #6ee7b7; border: 1px solid rgba(16, 185, 129, 0.4); }
        .check-pending { background: rgba(245, 158, 11, 0.2); color: #fde68a; border: 1px solid rgba(245, 158, 11, 0.4); }

        /* Sidebar Info */
        .sidebar {
            display: flex;
            flex-direction: column;
            gap: 1.25rem;
        }

        .info-card {
            background: var(--bg-surface);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.1rem;
        }

        .info-card h3 {
            font-size: 0.82rem;
            font-weight: 600;
            color: var(--text-dim);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.75rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .kv-table {
            width: 100%;
            font-size: 0.78rem;
            border-collapse: collapse;
        }

        .kv-table td {
            padding: 0.3rem 0;
            vertical-align: top;
        }

        .kv-label {
            color: var(--text-muted);
            width: 40%;
            font-weight: 500;
        }

        .kv-value {
            color: var(--text-main);
            font-family: var(--font-mono);
            word-break: break-all;
        }

        .selection-list {
            max-height: 280px;
            overflow-y: auto;
            font-family: var(--font-mono);
            font-size: 0.75rem;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .selection-item {
            background: var(--bg-card);
            padding: 6px 8px;
            border-radius: 4px;
            border: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            transition: background 0.15s ease;
        }

        .selection-item:hover {
            background: var(--bg-card-hover);
            border-color: var(--accent-purple);
        }

        .selection-id {
            color: var(--accent-cyan);
            font-weight: 600;
        }

        .selection-cat {
            color: var(--text-dim);
            font-size: 0.7rem;
        }

        /* 3D Legend */
        .legend-list {
            display: flex;
            flex-direction: column;
            gap: 8px;
            font-size: 0.75rem;
        }

        .legend-item {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .legend-color {
            width: 12px;
            height: 12px;
            border-radius: 3px;
        }

        /* Modal for full inspection */
        .modal {
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.85);
            backdrop-filter: blur(8px);
            z-index: 100;
            align-items: center;
            justify-content: center;
            padding: 2rem;
        }

        .modal.active {
            display: flex;
        }

        .modal-content {
            max-width: 90vw;
            max-height: 90vh;
            position: relative;
            display: flex;
            flex-direction: column;
            align-items: center;
        }

        .modal-img {
            max-width: 100%;
            max-height: 82vh;
            border-radius: 8px;
            box-shadow: 0 0 30px rgba(0,0,0,0.8);
            border: 1px solid var(--border-bright);
        }

        .modal-close {
            position: absolute;
            top: -2.5rem;
            right: 0;
            color: #fff;
            font-size: 1.5rem;
            cursor: pointer;
            background: transparent;
            border: none;
        }

        .tab-content {
            display: none;
        }
        .tab-content.active {
            display: block;
        }

        /* ================= CHAT & ANTIGRAVITY INTERACTION STYLES ================= */
        .chat-view-body {
            display: flex;
            flex-direction: column;
            height: calc(100vh - 160px);
            background: var(--bg-main);
            position: relative;
        }

        .chat-header-actions {
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .chat-conv-badge {
            font-size: 0.72rem;
            font-family: var(--font-mono);
            background: rgba(139, 92, 246, 0.15);
            color: #c4b5fd;
            border: 1px solid rgba(139, 92, 246, 0.3);
            padding: 3px 8px;
            border-radius: 6px;
        }

        .chat-refresh-btn {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-color);
            color: var(--text-dim);
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 0.72rem;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        .chat-refresh-btn:hover {
            color: #fff;
            border-color: var(--border-bright);
            background: rgba(255, 255, 255, 0.1);
        }

        .quick-chips-bar {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 10px 18px;
            background: rgba(15, 18, 25, 0.7);
            border-bottom: 1px solid var(--border-color);
            overflow-x: auto;
            flex-shrink: 0;
        }
        .quick-chips-bar::-webkit-scrollbar {
            height: 4px;
        }
        .quick-chips-bar::-webkit-scrollbar-thumb {
            background: var(--border-bright);
            border-radius: 2px;
        }

        .quick-chip-label {
            font-size: 0.72rem;
            font-weight: 700;
            color: var(--text-dim);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            white-space: nowrap;
        }

        .quick-chip {
            background: rgba(30, 36, 50, 0.7);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 14px;
            padding: 4px 12px;
            font-size: 0.75rem;
            color: #cbd5e1;
            white-space: nowrap;
            cursor: pointer;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            gap: 5px;
        }
        .quick-chip:hover {
            background: rgba(139, 92, 246, 0.2);
            border-color: rgba(139, 92, 246, 0.5);
            color: #fff;
            transform: translateY(-1px);
        }

        .chat-messages-container {
            flex: 1;
            overflow-y: auto;
            padding: 18px 22px;
            display: flex;
            flex-direction: column;
            gap: 16px;
            scroll-behavior: smooth;
        }

        .chat-msg-row {
            display: flex;
            width: 100%;
        }

        .chat-msg-row.user-row {
            justify-content: flex-end;
        }

        .chat-msg-row.assistant-row {
            justify-content: flex-start;
        }

        .chat-msg-bubble {
            max-width: 82%;
            border-radius: 12px;
            padding: 12px 16px;
            font-size: 0.88rem;
            line-height: 1.55;
            word-break: break-word;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
            position: relative;
        }

        .user-row .chat-msg-bubble {
            background: linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%);
            color: #ffffff;
            border-bottom-right-radius: 3px;
            border: 1px solid rgba(255, 255, 255, 0.15);
        }

        .assistant-row .chat-msg-bubble {
            background: var(--bg-card);
            color: #e2e8f0;
            border-bottom-left-radius: 3px;
            border: 1px solid var(--border-color);
        }

        .chat-msg-meta {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 6px;
            font-size: 0.7rem;
            font-family: var(--font-mono);
            opacity: 0.75;
        }

        .chat-msg-body {
            font-size: 0.86rem;
        }
        .chat-msg-body p {
            margin: 0 0 8px 0;
        }
        .chat-msg-body p:last-child {
            margin-bottom: 0;
        }
        .chat-msg-body code {
            font-family: var(--font-mono);
            background: rgba(0, 0, 0, 0.35);
            padding: 2px 5px;
            border-radius: 4px;
            font-size: 0.82rem;
            color: #67e8f9;
        }
        .chat-msg-body pre {
            background: rgba(10, 12, 16, 0.85);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 10px;
            overflow-x: auto;
            margin: 8px 0;
        }
        .chat-msg-body pre code {
            background: transparent;
            padding: 0;
            color: #a7f3d0;
        }
        .chat-msg-body ul, .chat-msg-body ol {
            margin: 4px 0 8px 20px;
            padding: 0;
        }
        .chat-msg-body li {
            margin-bottom: 4px;
        }

        .chat-thinking-indicator {
            display: flex;
            align-items: center;
            gap: 10px;
            background: rgba(139, 92, 246, 0.08);
            border: 1px dashed rgba(139, 92, 246, 0.35);
            border-radius: 10px;
            padding: 12px 18px;
            color: #c4b5fd;
            font-size: 0.82rem;
            max-width: 380px;
            animation: pulseThinking 2s infinite ease-in-out;
        }
        @keyframes pulseThinking {
            0%, 100% { opacity: 0.65; transform: scale(1); }
            50% { opacity: 1; transform: scale(1.01); }
        }

        .thinking-dots {
            display: inline-flex;
            gap: 4px;
        }
        .thinking-dot {
            width: 6px;
            height: 6px;
            background: #a78bfa;
            border-radius: 50%;
            animation: bounceDot 1.4s infinite ease-in-out both;
        }
        .thinking-dot:nth-child(1) { animation-delay: -0.32s; }
        .thinking-dot:nth-child(2) { animation-delay: -0.16s; }
        @keyframes bounceDot {
            0%, 80%, 100% { transform: scale(0); }
            40% { transform: scale(1); }
        }

        .chat-composer-container {
            padding: 12px 20px 16px 20px;
            background: rgba(15, 18, 25, 0.95);
            border-top: 1px solid var(--border-color);
            flex-shrink: 0;
        }

        .composer-wrapper {
            display: flex;
            gap: 10px;
            background: #0d1017;
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 8px 12px;
            transition: border-color 0.2s ease, box-shadow 0.2s ease;
        }
        .composer-wrapper:focus-within {
            border-color: var(--accent-purple);
            box-shadow: 0 0 12px rgba(139, 92, 246, 0.25);
        }

        #chat-textarea {
            flex: 1;
            background: transparent;
            border: none;
            outline: none;
            color: #fff;
            font-family: inherit;
            font-size: 0.88rem;
            resize: none;
            min-height: 44px;
            max-height: 160px;
            line-height: 1.45;
        }
        #chat-textarea::placeholder {
            color: #64748b;
        }

        .composer-controls {
            display: flex;
            align-items: flex-end;
            gap: 6px;
        }

        .composer-btn-secondary {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-color);
            color: var(--text-dim);
            border-radius: 8px;
            width: 36px;
            height: 36px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s ease;
        }
        .composer-btn-secondary:hover {
            color: #fff;
            background: rgba(255, 255, 255, 0.1);
        }

        .composer-btn-primary {
            background: linear-gradient(135deg, #8b5cf6 0%, #6366f1 100%);
            border: none;
            color: #fff;
            font-weight: 600;
            font-size: 0.84rem;
            border-radius: 8px;
            padding: 0 16px;
            height: 36px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 6px;
            transition: all 0.2s ease;
            box-shadow: 0 2px 8px rgba(139, 92, 246, 0.4);
        }
        .composer-btn-primary:hover {
            filter: brightness(1.1);
            transform: translateY(-1px);
        }
        .composer-btn-primary:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }

        .composer-hint {
            display: flex;
            align-items: center;
            margin-top: 6px;
            font-size: 0.72rem;
            color: var(--text-dim);
        }

        /* Floating Quick Prompt Dock across all tabs */
        .quick-prompt-dock {
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 90;
            width: calc(100% - 40px);
            max-width: 680px;
            pointer-events: none;
            transition: all 0.3s ease;
        }
        .quick-dock-inner {
            display: flex;
            align-items: center;
            gap: 10px;
            background: rgba(14, 18, 26, 0.88);
            backdrop-filter: blur(14px);
            border: 1px solid rgba(139, 92, 246, 0.4);
            border-radius: 30px;
            padding: 6px 14px 6px 16px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.6), 0 0 15px rgba(139, 92, 246, 0.2);
            transition: all 0.25s ease;
            pointer-events: auto;
        }
        .quick-dock-inner:focus-within {
            border-color: #a855f7;
            box-shadow: 0 10px 35px rgba(0, 0, 0, 0.8), 0 0 22px rgba(168, 85, 247, 0.4);
            transform: scale(1.01);
        }
        .quick-dock-icon {
            font-size: 1rem;
            color: #c084fc;
        }
        #quick-dock-input {
            flex: 1;
            background: transparent;
            border: none;
            outline: none;
            color: #fff;
            font-size: 0.85rem;
            font-family: inherit;
        }
        #quick-dock-input::placeholder {
            color: #94a3b8;
        }
        .quick-dock-send-btn {
            background: linear-gradient(135deg, #8b5cf6, #3b82f6);
            border: none;
            color: #fff;
            border-radius: 20px;
            padding: 5px 14px;
            font-size: 0.78rem;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 5px;
            transition: all 0.2s ease;
        }
        .quick-dock-send-btn:hover {
            filter: brightness(1.15);
        }
        .quick-dock-expand-btn {
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.1);
            color: #cbd5e1;
            border-radius: 50%;
            width: 28px;
            height: 28px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 0.82rem;
            transition: all 0.2s ease;
        }
        .quick-dock-expand-btn:hover {
            background: rgba(139, 92, 246, 0.3);
            color: #fff;
        }
    </style>
</head>
<body>

    <header>
        <div class="brand-group">
            <div class="brand-icon">📐</div>
            <div>
                <div class="brand-title">
                    Revit MCP 3D & Visual Dashboard
                    <span class="badge-live">Live Sync</span>
                </div>
            </div>
        </div>

        <div class="tabs-nav">
            <button id="tab-btn-3d" class="tab-btn active" onclick="switchTab('3d')">
                <span>🧊</span> 3D Spatial Context
            </button>
            <button id="tab-btn-intent" class="tab-btn" onclick="switchTab('intent')">
                <span>🎯</span> Agent Mission & Intent
            </button>
            <button id="tab-btn-2d" class="tab-btn" onclick="switchTab('2d')">
                <span>🖼️</span> 2D Captures & Snips
            </button>
            <button id="tab-btn-table" class="tab-btn" onclick="switchTab('table')">
                <span>📊</span> Таблица спринклеров (213)
            </button>
            <button id="tab-btn-chat" class="tab-btn" onclick="switchTab('chat')">
                <span>💬</span> Antigravity Chat
            </button>
        </div>

        <div class="header-meta">
            <div id="agent-status" class="agent-status-tag status-idle">
                <span>●</span> <span id="agent-status-text">Agent Idle</span>
            </div>
            <div id="active-model-title" style="color: var(--text-dim);">Model: Loading...</div>
        </div>
    </header>

    <main>
        <div class="panel">
            <!-- TAB 1: 3D Spatial Viewer -->
            <div id="tab-view-3d" class="tab-content active">
                <div class="panel-header">
                    <div class="panel-title">
                        <span>🧊</span> 3D Spatial Context (Pipes, Sprinklers, Ceilings & Clearances)
                    </div>
                    <div class="panel-badge" id="3d-element-count">3D Objects: 0</div>
                </div>

                <div class="viewport-toolbar">
                    <div class="viewport-tools-group">
                        <button class="vtool-btn active" id="btn-view-iso" onclick="setCameraPreset('iso')">🧊 3D Обзор</button>
                        <button class="vtool-btn" id="btn-view-top" onclick="setCameraPreset('top')">📐 План пола (2D Top)</button>
                        <button class="vtool-btn" id="btn-view-front" onclick="setCameraPreset('front')">📏 Фасад Z (Высоты)</button>
                        <button class="vtool-btn" id="btn-view-focus" onclick="setCameraPreset('focus')">🎯 Фокус спринклера</button>
                    </div>
                    <div class="viewport-toggles">
                        <label class="toggle-pill"><input type="checkbox" id="toggle-floor" checked onchange="toggleLayer('floor', this.checked)"> <span>Плита пола</span></label>
                        <label class="toggle-pill"><input type="checkbox" id="toggle-ceiling" checked onchange="toggleLayer('ceiling', this.checked)"> <span>Потолок/Карниз</span></label>
                        <label class="toggle-pill"><input type="checkbox" id="toggle-spray" checked onchange="toggleLayer('spray', this.checked)"> <span>Факел Sidewall</span></label>
                        <label class="toggle-pill"><input type="checkbox" id="toggle-dims" checked onchange="toggleLayer('dims', this.checked)"> <span>Привязки стен</span></label>
                    </div>
                </div>

                <div id="three-container">
                    <div class="three-overlay">
                        <div><strong>Active Document</strong>: <span id="three-model-label">SPR_Rasko</span></div>
                        <div><strong>Spatial Center</strong>: <span id="three-bounds-label">--</span></div>
                    </div>

                    <div class="elevation-hud-overlay">
                        <div class="ehud-header">
                            <span class="ehud-title">📍 ВЫСОТНЫЙ АНАЛИЗ (Z)</span>
                            <span class="ehud-badge" id="hud-level-badge">Level 24</span>
                        </div>
                        <div class="ehud-grid">
                            <div class="ehud-item">
                                <span class="ehud-k">Базовый Уровень:</span>
                                <span class="ehud-v highlight-lvl" id="hud-ref-level">Level 24 (76.90 м)</span>
                            </div>
                            <div class="ehud-item">
                                <span class="ehud-k">Плита пола (0.00):</span>
                                <span class="ehud-v" id="hud-floor-elev">0 мм (Абс: 76.90 м)</span>
                            </div>
                            <div class="ehud-item">
                                <span class="ehud-k">Спринклер Sidewall:</span>
                                <span class="ehud-v highlight-spk" id="hud-spk-elev">+2400 мм (Абс: 79.30 м)</span>
                            </div>
                            <div class="ehud-item">
                                <span class="ehud-k">Подвесной карниз:</span>
                                <span class="ehud-v highlight-cl" id="hud-cl-elev">+2300 мм (Абс: 79.20 м)</span>
                            </div>
                            <div class="ehud-item">
                                <span class="ehud-k">Плита перекрытия:</span>
                                <span class="ehud-v" id="hud-slab-elev">+2900 мм (Абс: 79.80 м)</span>
                            </div>
                        </div>
                        <div class="ehud-status" id="hud-status-pill">🎯 На кромке карниза (Δz = +100 мм)</div>
                    </div>

                    <div class="three-controls-hint">
                        🖱️ Left Click: Rotate | Right Click: Pan | Scroll: Zoom
                    </div>
                </div>
            </div>

            <!-- TAB 2: Agent Mission & Intent Audit -->
            <div id="tab-view-intent" class="tab-content">
                <div class="panel-header">
                    <div class="panel-title">
                        <span>🧠</span> Active Agent Context Mission & Verification
                    </div>
                    <div class="panel-badge" id="context-audit-badge">ACTIVE AUDIT</div>
                </div>

                <div class="context-mission-card">
                    <div class="mission-badge">🎯 Current Task Mission</div>
                    <div class="mission-title" id="intent-task-mission">Анализ высотных привязок спринклеров к подвесным потолкам и карнизным нишам (Этаж 39)</div>
                    <div class="mission-purpose" id="intent-purpose-text">Определить отметку монтажа спринклеров (Offset +2400 мм) относительно основного потолка (+2400 мм) и опускных ниш/карнизов (+2300 мм), проверить подключение к магистрали FPW 47 и выявить перепады отметок.</div>
                </div>

                <div class="context-grid-2col">
                    <!-- Agent Deductions -->
                    <div class="context-subcard">
                        <div class="context-subcard-header">
                            <span>🔍 Инженерные выводы агента</span>
                            <span class="panel-badge" id="deductions-count">4 пункта</span>
                        </div>
                        <div id="intent-deductions-list" style="display: flex; flex-direction: column; gap: 8px;">
                            <!-- Populated dynamically -->
                        </div>
                    </div>

                    <!-- Verification Checklist -->
                    <div class="context-subcard">
                        <div class="context-subcard-header">
                            <span>✅ Чеклист верификации инженера</span>
                            <span class="panel-badge">Audit</span>
                        </div>
                        <div id="intent-checklist" style="display: flex; flex-direction: column; gap: 8px;">
                            <!-- Populated dynamically -->
                        </div>
                    </div>
                </div>
            </div>

            <!-- TAB 3: 2D Views & Captures -->
            <div id="tab-view-2d" class="tab-content">
                <div class="panel-header">
                    <div class="panel-title">
                        <span>🖼️</span> 2D Live Visual Buffers
                    </div>
                    <div class="panel-badge" id="last-sync-time">Sync: Just now</div>
                </div>

                <div class="views-grid">
                    <!-- Agent View Capture -->
                    <div class="image-card">
                        <div class="image-card-header">
                            <span class="card-tag tag-agent">🤖 Agent View Capture</span>
                            <span id="agent-cap-time" style="font-size: 0.72rem; color: var(--text-dim); font-family: var(--font-mono);">--:--:--</span>
                        </div>
                        <div class="image-viewport" onclick="openModal('/api/image/agent')">
                            <img id="agent-cap-img" src="/api/image/agent" alt="Agent Revit Capture" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'400\\' height=\\'300\\'><rect fill=\\'%23141721\\' width=\\'100%25\\' height=\\'100%25\\'/><text fill=\\'%2364748b\\' x=\\'50%25\\' y=\\'50%25\\' text-anchor=\\'middle\\' font-family=\\'sans-serif\\'>No Agent Capture Yet</text></svg>'">
                        </div>
                        <div class="image-meta-footer">
                            <span id="agent-view-name">View: --</span>
                            <span id="agent-view-type">Type: --</span>
                        </div>
                    </div>

                    <!-- User Markup / Snip -->
                    <div class="image-card">
                        <div class="image-card-header">
                            <span class="card-tag tag-user">✍️ User Snip & Markup</span>
                            <span id="user-snip-time" style="font-size: 0.72rem; color: var(--text-dim); font-family: var(--font-mono);">--:--:--</span>
                        </div>
                        <div class="image-viewport" onclick="openModal('/api/image/user')">
                            <img id="user-snip-img" src="/api/image/user" alt="User Snip & Markup" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'400\\' height=\\'300\\'><rect fill=\\'%23141721\\' width=\\'100%25\\' height=\\'100%25\\'/><text fill=\\'%2364748b\\' x=\\'50%25\\' y=\\'50%25\\' text-anchor=\\'middle\\' font-family=\\'sans-serif\\'>No User Markup Snip</text></svg>'">
                        </div>
                        <div class="image-meta-footer">
                            <span id="user-snip-res">Res: --</span>
                            <span id="user-snip-type">Input: User Markup</span>
                        </div>
                    </div>
                </div>
            </div>

            <!-- TAB 4: Sprinklers Audit Table -->
            <div id="tab-view-table" class="tab-content">
                <div class="panel-header">
                    <div class="panel-title">
                        <span>📊</span> Ведомость аудита настенных спринклеров (Sidewall)
                    </div>
                    <div class="panel-badge" id="table-badge-summary">Всего: 213 • Ошибок: 78</div>
                </div>

                <div style="padding: 1rem 1.25rem; display: flex; flex-direction: column; gap: 0.85rem;">
                    <!-- Filters Toolbar -->
                    <div style="display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; background: #171b26; padding: 0.65rem 1rem; border-radius: 8px; border: 1px solid #23293d; font-size: 0.8rem;">
                        <span style="color: #94a3b8; font-weight: 600;">Фильтры:</span>
                        <select id="filter-level" onchange="applyTableFilters()" style="background: #11141d; color: #e2e8f0; border: 1px solid #23293d; border-radius: 6px; padding: 4px 8px;">
                            <option value="ALL">Все этажи (7)</option>
                            <option value="24C">Level 24C (27)</option>
                            <option value="24-B">Level 24-B (29)</option>
                            <option value="25C">Level 25C (17)</option>
                            <option value="25-B">Level 25-B (17)</option>
                            <option value="10">Level 10 (40)</option>
                            <option value="05">Level 05 (41)</option>
                            <option value="01">Level 01 (42)</option>
                        </select>

                        <select id="filter-status" onchange="applyTableFilters()" style="background: #11141d; color: #e2e8f0; border: 1px solid #23293d; border-radius: 6px; padding: 4px 8px;">
                            <option value="ALL">Все статусы (213)</option>
                            <option value="FAIL">⚠️ Только с замечаниями (78)</option>
                            <option value="FRONT_FAIL">🚨 Недолет вперед (13)</option>
                            <option value="OK">✅ Полное соответствие (135)</option>
                        </select>

                        <input type="text" id="filter-search" oninput="applyTableFilters()" placeholder="Поиск по ID или типу..." style="background: #11141d; color: #e2e8f0; border: 1px solid #23293d; border-radius: 6px; padding: 4px 10px; min-width: 180px;">

                        <span style="margin-left: auto; color: #64748b; font-size: 0.75rem; font-family: monospace;">
                            💡 Кликните по строке спринклера для выделения и зума в Revit
                        </span>
                    </div>

                    <!-- Scrollable Table -->
                    <div style="max-height: 540px; overflow-y: auto; border: 1px solid #23293d; border-radius: 8px;">
                        <table style="width: 100%; border-collapse: collapse; font-size: 0.78rem; text-align: left;">
                            <thead style="position: sticky; top: 0; background: #171b26; z-index: 10; border-bottom: 2px solid #394263;">
                                <tr style="color: #94a3b8; font-family: monospace; font-size: 0.72rem; text-transform: uppercase;">
                                    <th style="padding: 10px 12px; vertical-align: top; width: 110px;">
                                        <div style="margin-bottom: 6px; display: flex; align-items: center; justify-content: space-between; cursor: pointer;" onclick="sortTableBy('id')">
                                            <span>🎯 ID <span id="sort-icon-id">↕</span></span>
                                        </div>
                                        <input type="text" id="th-filter-id" oninput="applyTableFilters()" placeholder="Фильтр..." style="width: 100%; background: #11141d; color: #06b6d4; border: 1px solid #23293d; border-radius: 4px; padding: 3px 6px; font-size: 0.72rem; font-family: monospace;">
                                    </th>
                                    <th style="padding: 10px 12px; vertical-align: top; width: 110px;">
                                        <div style="margin-bottom: 6px; display: flex; align-items: center; justify-content: space-between; cursor: pointer;" onclick="sortTableBy('level')">
                                            <span>🏢 Этаж <span id="sort-icon-level">↕</span></span>
                                        </div>
                                        <select id="th-filter-level" onchange="applyTableFilters()" style="width: 100%; background: #11141d; color: #e2e8f0; border: 1px solid #23293d; border-radius: 4px; padding: 3px 4px; font-size: 0.72rem;">
                                            <option value="ALL">Все</option>
                                            <option value="24C">24C</option>
                                            <option value="24-B">24-B</option>
                                            <option value="25C">25C</option>
                                            <option value="25-B">25-B</option>
                                            <option value="10">10</option>
                                            <option value="05">05</option>
                                            <option value="01">01</option>
                                        </select>
                                    </th>
                                    <th style="padding: 10px 12px; vertical-align: top; width: 170px;">
                                        <div style="margin-bottom: 6px; display: flex; align-items: center; justify-content: space-between; cursor: pointer;" onclick="sortTableBy('type')">
                                            <span>🏷️ Тип <span id="sort-icon-type">↕</span></span>
                                        </div>
                                        <select id="th-filter-type" onchange="applyTableFilters()" style="width: 100%; background: #11141d; color: #e2e8f0; border: 1px solid #23293d; border-radius: 4px; padding: 3px 4px; font-size: 0.72rem;">
                                            <option value="ALL">Все типы</option>
                                            <option value="Sidewall recessed">Sidewall recessed</option>
                                            <option value="Sidewall EC recessed">Sidewall EC recessed</option>
                                            <option value="Sidewall">Sidewall (стандарт)</option>
                                        </select>
                                    </th>
                                    <th style="padding: 10px 12px; vertical-align: top;">
                                        <div style="margin-bottom: 6px; display: flex; align-items: center; justify-content: space-between; cursor: pointer;" onclick="sortTableBy('front')">
                                            <span>📐 Выброс перед (Стена / Зона) <span id="sort-icon-front">↕</span></span>
                                        </div>
                                        <select id="th-filter-front" onchange="applyTableFilters()" style="width: 100%; background: #11141d; color: #e2e8f0; border: 1px solid #23293d; border-radius: 4px; padding: 3px 4px; font-size: 0.72rem;">
                                            <option value="ALL">Все расстояния</option>
                                            <option value="FRONT_FAIL">🚨 Недолет (вылет &lt; стены)</option>
                                            <option value="FRONT_OK">✅ Покрывает противоположную стену</option>
                                        </select>
                                    </th>
                                    <th style="padding: 10px 12px; vertical-align: top;">
                                        <div style="margin-bottom: 6px; display: flex; align-items: center; justify-content: space-between; cursor: pointer;" onclick="sortTableBy('left')">
                                            <span>👈 Слева (Стена / Смежный) <span id="sort-icon-left">↕</span></span>
                                        </div>
                                        <select id="th-filter-left" onchange="applyTableFilters()" style="width: 100%; background: #11141d; color: #e2e8f0; border: 1px solid #23293d; border-radius: 4px; padding: 3px 4px; font-size: 0.72rem;">
                                            <option value="ALL">Все условия слева</option>
                                            <option value="GAP">⚠️ Разрыв / зазор слева</option>
                                            <option value="OK">✅ Закрыто (стена или спринклер)</option>
                                        </select>
                                    </th>
                                    <th style="padding: 10px 12px; vertical-align: top;">
                                        <div style="margin-bottom: 6px; display: flex; align-items: center; justify-content: space-between; cursor: pointer;" onclick="sortTableBy('right')">
                                            <span>👉 Справа (Стена / Смежный) <span id="sort-icon-right">↕</span></span>
                                        </div>
                                        <select id="th-filter-right" onchange="applyTableFilters()" style="width: 100%; background: #11141d; color: #e2e8f0; border: 1px solid #23293d; border-radius: 4px; padding: 3px 4px; font-size: 0.72rem;">
                                            <option value="ALL">Все условия справа</option>
                                            <option value="GAP">⚠️ Разрыв / зазор справа</option>
                                            <option value="OK">✅ Закрыто (стена или спринклер)</option>
                                        </select>
                                    </th>
                                    <th style="padding: 10px 12px; vertical-align: top; width: 105px; text-align: center;">
                                        <div style="margin-bottom: 6px; display: flex; align-items: center; justify-content: center; gap: 4px; cursor: pointer;" onclick="sortTableBy('status')">
                                            <span>Расчет <span id="sort-icon-status">↕</span></span>
                                        </div>
                                        <select id="th-filter-status" onchange="applyTableFilters()" style="width: 100%; background: #11141d; color: #e2e8f0; border: 1px solid #23293d; border-radius: 4px; padding: 3px 4px; font-size: 0.72rem;">
                                            <option value="ALL">Все</option>
                                            <option value="FAIL">⚠️ FAIL (78)</option>
                                            <option value="OK">✅ OK (135)</option>
                                        </select>
                                    </th>
                                    <th style="padding: 10px 12px; vertical-align: top; width: 135px; text-align: center;">
                                        <div style="margin-bottom: 6px; display: flex; align-items: center; justify-content: center; gap: 4px; cursor: pointer;" onclick="sortTableBy('approval')">
                                            <span>👤 Аппрув <span id="sort-icon-approval">↕</span></span>
                                        </div>
                                        <select id="th-filter-approval" onchange="applyTableFilters()" style="width: 100%; background: #11141d; color: #e2e8f0; border: 1px solid #23293d; border-radius: 4px; padding: 3px 4px; font-size: 0.72rem;">
                                            <option value="ALL">Все</option>
                                            <option value="APPROVED">✅ Одобрено</option>
                                            <option value="REJECTED">❌ Отклонено</option>
                                            <option value="PENDING">⏳ На проверке</option>
                                        </select>
                                    </th>
                                </tr>
                            </thead>
                            <tbody id="sprinklers-table-body">
                                <!-- Populated dynamically -->
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- TAB 5: Antigravity Interactive Chat & Task Assistant -->
            <div id="tab-view-chat" class="tab-content">
                <div class="panel-header">
                    <div class="panel-title">
                        <span>💬</span> Antigravity Live Interaction & Task Assistant
                    </div>
                    <div class="chat-header-actions">
                        <span class="chat-conv-badge" id="chat-conv-id-badge">Session: Active</span>
                        <button class="chat-refresh-btn" onclick="fetchChatHistory(true)" title="Refresh Chat">🔄 Refresh</button>
                    </div>
                </div>

                <div class="chat-view-body">
                    <!-- Quick Action Chips -->
                    <div class="quick-chips-bar">
                        <div class="quick-chip-label">Quick Actions:</div>
                        <button class="quick-chip" onclick="applyQuickPrompt('Inspect active Revit model and report status')">📋 Model Status</button>
                        <button class="quick-chip" onclick="applyQuickPrompt('Take screenshot of current view and analyze MEP elements')">📸 Snip & Inspect</button>
                        <button class="quick-chip" onclick="applyQuickPrompt('Audit sprinkler clearances and wall distances')">🔍 Audit Clearances</button>
                        <button class="quick-chip" onclick="applyQuickPrompt('Show currently selected element details and parameters')">📐 Inspect Selection</button>
                        <button class="quick-chip" onclick="applyQuickPrompt('Focus 3D spatial viewer on selected sprinkler')">🧊 Focus 3D View</button>
                    </div>

                    <!-- Chat Messages Area -->
                    <div class="chat-messages-container" id="chat-messages-container">
                        <div class="chat-empty-state" id="chat-loading-placeholder" style="text-align: center; color: var(--text-dim); margin-top: 40px;">
                            <div style="font-size: 2rem; margin-bottom: 8px;">⏳</div>
                            <div style="font-weight: 600; color: #fff;">Connecting to Antigravity transcript...</div>
                        </div>
                    </div>

                    <!-- Chat Input Area -->
                    <div class="chat-composer-container">
                        <div class="composer-wrapper">
                            <textarea id="chat-textarea" placeholder="Type prompt or instruction for Antigravity... (Press Enter to send, Shift+Enter for new line)" rows="2" onkeydown="handleChatKeyDown(event)"></textarea>
                            <div class="composer-controls">
                                <button class="composer-btn-secondary" onclick="clearChatInput()" title="Clear text">✖</button>
                                <button class="composer-btn-primary" id="btn-chat-send" onclick="sendChatFromInput()">
                                    <span id="chat-send-icon">🚀</span>
                                    <span id="chat-send-text">Send Prompt</span>
                                </button>
                            </div>
                        </div>
                        <div class="composer-hint">
                            <span>💡 Connected to Antigravity Language Server API</span>
                            <span id="chat-feedback-msg" style="margin-left: auto; font-size: 0.75rem;"></span>
                        </div>
                    </div>
                </div>
            </div>

            <!-- History Strip -->
            <div class="history-section">
                <div class="history-title">Recent Captures History</div>
                <div class="history-scroll" id="history-reel">
                    <!-- Populated dynamically -->
                </div>
            </div>
        </div>

        <!-- Sidebar Information -->
        <div class="sidebar">
            <!-- 3D Legend & Layers -->
            <div class="info-card">
                <h3>3D Visualization Layers</h3>
                <div class="legend-list">
                    <div class="legend-item">
                        <div class="legend-color" style="background: #f43f5e;"></div>
                        <span>🔴 Sprinklers (Spray Direction Arrow)</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color" style="background: #06b6d4;"></div>
                        <span>⭕ Circular Pipes (Cylindrical Mesh)</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color" style="background: #a855f7;"></div>
                        <span>🟣 Air Terminals / Diffusers</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color" style="background: #10b981;"></div>
                        <span>🟢 MEP Connectors & Ports</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color" style="background: #3b82f6;"></div>
                        <span>🔵 Room Boundary & Volume</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color" style="background: #f59e0b;"></div>
                        <span>🟡 Target Selection / Dimensions</span>
                    </div>
                </div>
            </div>

            <!-- Active Selected Elements -->
            <div class="info-card">
                <h3>
                    <span>Context Selection</span>
                    <span class="panel-badge" id="sel-count">0 items</span>
                </h3>
                <div class="selection-list" id="selection-items">
                    <div style="color: var(--text-muted); text-align: center; padding: 1.5rem 0;">No active selection</div>
                </div>
            </div>

            <!-- Session & Model Details -->
            <div class="info-card">
                <h3>Session & Model</h3>
                <table class="kv-table">
                    <tr>
                        <td class="kv-label">Revit Doc:</td>
                        <td class="kv-value" id="info-doc-title">--</td>
                    </tr>
                    <tr>
                        <td class="kv-label">Bound Port:</td>
                        <td class="kv-value" id="info-port">--</td>
                    </tr>
                    <tr>
                        <td class="kv-label">Agent State:</td>
                        <td class="kv-value" id="info-agent-state">Idle</td>
                    </tr>
                    <tr>
                        <td class="kv-label">Latest Capture:</td>
                        <td class="kv-value" id="info-latest-time">--</td>
                    </tr>
                </table>
            </div>
        </div>
    </main>

    <!-- Modal for Zoom -->
    <div class="modal" id="imageModal" onclick="closeModal()">
        <div class="modal-content" onclick="event.stopPropagation()">
            <button class="modal-close" onclick="closeModal()">&times;</button>
            <img class="modal-img" id="modal-image" src="" alt="Zoomed View">
        </div>
    </div>

    <script>
        function switchTab(tabId) {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

            const dock = document.getElementById('quick-prompt-dock');

            if (tabId === '3d') {
                document.getElementById('tab-btn-3d').classList.add('active');
                document.getElementById('tab-view-3d').classList.add('active');
                if (window.onWindowResize3D) window.onWindowResize3D();
                if (dock) dock.style.display = 'block';
            } else if (tabId === 'intent') {
                document.getElementById('tab-btn-intent').classList.add('active');
                document.getElementById('tab-view-intent').classList.add('active');
                if (dock) dock.style.display = 'block';
            } else if (tabId === 'table') {
                document.getElementById('tab-btn-table').classList.add('active');
                document.getElementById('tab-view-table').classList.add('active');
                renderAuditTable();
                if (dock) dock.style.display = 'block';
            } else if (tabId === 'chat') {
                document.getElementById('tab-btn-chat').classList.add('active');
                document.getElementById('tab-view-chat').classList.add('active');
                if (dock) dock.style.display = 'none';
                fetchChatHistory(true);
            } else {
                document.getElementById('tab-btn-2d').classList.add('active');
                document.getElementById('tab-view-2d').classList.add('active');
                if (dock) dock.style.display = 'block';
            }
        }

        function openModal(src) {
            const modal = document.getElementById('imageModal');
            const img = document.getElementById('modal-image');
            img.src = src + '?t=' + Date.now();
            modal.classList.add('active');
        }

        function closeModal() {
            document.getElementById('imageModal').classList.remove('active');
        }

        function formatTs(ts) {
            if (!ts) return '--:--:--';
            if (ts.length === 15 && ts.includes('_')) {
                const timePart = ts.split('_')[1];
                return timePart.substring(0,2) + ':' + timePart.substring(2,4) + ':' + timePart.substring(4,6);
            }
            return ts;
        }

        // ================= Three.js 3D Spatial Context Engine =================
        let scene, camera, renderer, controls;
        let elementsGroup;
        let layerFloor, layerCeiling, layerSpray, layerDims;
        const layersVisible = { floor: true, ceiling: true, spray: true, dims: true };
        let currentPreset = 'iso';
        let sceneCenter = new THREE.Vector3(0, 0, 0);
        let targetSpkPos = null;
        let last3DHash = "";

        function toggleLayer(name, visible) {
            layersVisible[name] = visible;
            if (name === 'floor' && layerFloor) layerFloor.visible = visible;
            if (name === 'ceiling' && layerCeiling) layerCeiling.visible = visible;
            if (name === 'spray' && layerSpray) layerSpray.visible = visible;
            if (name === 'dims' && layerDims) layerDims.visible = visible;
        }

        function setCameraPreset(preset) {
            currentPreset = preset;
            document.querySelectorAll('.vtool-btn').forEach(b => b.classList.remove('active'));
            const activeBtn = document.getElementById('btn-view-' + preset);
            if (activeBtn) activeBtn.classList.add('active');

            if (!camera || !controls) return;

            if (preset === 'top') {
                // 2D Floor Plan view looking straight down on XZ plane
                camera.position.set(sceneCenter.x, sceneCenter.y + 7.5, sceneCenter.z + 0.001);
                controls.target.copy(sceneCenter);
            } else if (preset === 'front') {
                // Front Elevation Z view looking horizontally
                camera.position.set(sceneCenter.x, sceneCenter.y + 0.3, sceneCenter.z + 6.8);
                controls.target.copy(sceneCenter);
            } else if (preset === 'focus' && targetSpkPos) {
                // Focus tightly on sprinkler head
                camera.position.set(targetSpkPos.x + 1.2, targetSpkPos.y + 0.6, targetSpkPos.z + 1.2);
                controls.target.copy(targetSpkPos);
            } else {
                // Isometric 45 deg
                camera.position.set(sceneCenter.x + 4.5, sceneCenter.y + 3.8, sceneCenter.z + 4.5);
                controls.target.copy(sceneCenter);
            }
            controls.update();
        }

        // Helper: Create Anti-Aliased High-DPI Text Sprite Badge in 3D
        function makeTextSprite(message, opts = {}) {
            const font = opts.font || "bold 26px 'JetBrains Mono', monospace";
            const color = opts.color || "#ffffff";
            const bgColor = opts.bgColor || "rgba(15, 23, 42, 0.88)";
            const borderColor = opts.borderColor || (opts.color ? opts.color : "rgba(56, 189, 248, 0.6)");

            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');
            ctx.font = font;
            const metrics = ctx.measureText(message);
            const textWidth = metrics.width;
            const padX = 18;
            const padY = 12;
            canvas.width = Math.ceil(textWidth + padX * 2);
            canvas.height = 54;

            ctx.font = font;
            ctx.fillStyle = bgColor;
            ctx.strokeStyle = borderColor;
            ctx.lineWidth = 3;

            // Rounded rectangle
            const r = 8;
            ctx.beginPath();
            ctx.moveTo(r, 0);
            ctx.lineTo(canvas.width - r, 0);
            ctx.quadraticCurveTo(canvas.width, 0, canvas.width, r);
            ctx.lineTo(canvas.width, canvas.height - r);
            ctx.quadraticCurveTo(canvas.width, canvas.height, canvas.width - r, canvas.height);
            ctx.lineTo(r, canvas.height);
            ctx.quadraticCurveTo(0, canvas.height, 0, canvas.height - r);
            ctx.lineTo(0, r);
            ctx.quadraticCurveTo(0, 0, r, 0);
            ctx.closePath();
            ctx.fill();
            ctx.stroke();

            ctx.fillStyle = color;
            ctx.textBaseline = "middle";
            ctx.fillText(message, padX, canvas.height * 0.5);

            const texture = new THREE.CanvasTexture(canvas);
            const spriteMat = new THREE.SpriteMaterial({ map: texture, depthTest: false, transparent: true });
            const sprite = new THREE.Sprite(spriteMat);
            const scaleFactor = opts.scale || 0.0024;
            sprite.scale.set(canvas.width * scaleFactor, canvas.height * scaleFactor, 1);
            return sprite;
        }

        function init3DViewer() {
            const container = document.getElementById('three-container');
            const width = container.clientWidth;
            const height = container.clientHeight || 640;

            scene = new THREE.Scene();
            scene.background = new THREE.Color(0x0a0c10);

            camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 5000);
            camera.position.set(0, 10, 16);

            renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
            renderer.setSize(width, height);
            renderer.setPixelRatio(window.devicePixelRatio);
            renderer.shadowMap.enabled = true;
            container.appendChild(renderer.domElement);

            controls = new THREE.OrbitControls(camera, renderer.domElement);
            controls.enableDamping = true;
            controls.dampingFactor = 0.05;

            // Lights
            const ambientLight = new THREE.AmbientLight(0xffffff, 0.75);
            scene.add(ambientLight);

            const dirLight1 = new THREE.DirectionalLight(0xffffff, 0.85);
            dirLight1.position.set(25, 45, 25);
            scene.add(dirLight1);

            const dirLight2 = new THREE.DirectionalLight(0x8b5cf6, 0.35);
            dirLight2.position.set(-25, -20, -25);
            scene.add(dirLight2);

            // Grid & Axes
            const gridHelper = new THREE.GridHelper(30, 30, 0x8b5cf6, 0x23293d);
            gridHelper.position.y = -0.01;
            scene.add(gridHelper);

            const axesHelper = new THREE.AxesHelper(2.5);
            scene.add(axesHelper);

            elementsGroup = new THREE.Group();
            scene.add(elementsGroup);

            layerFloor = new THREE.Group();
            layerCeiling = new THREE.Group();
            layerSpray = new THREE.Group();
            layerDims = new THREE.Group();

            elementsGroup.add(layerFloor);
            elementsGroup.add(layerCeiling);
            elementsGroup.add(layerSpray);
            elementsGroup.add(layerDims);

            window.onWindowResize3D = function() {
                if (!container || !renderer || !camera) return;
                const w = container.clientWidth;
                const h = container.clientHeight || 640;
                camera.aspect = w / h;
                camera.updateProjectionMatrix();
                renderer.setSize(w, h);
            };
            window.addEventListener('resize', window.onWindowResize3D);

            animate3D();
        }

        function animate3D() {
            requestAnimationFrame(animate3D);
            if (controls) controls.update();
            if (renderer && scene && camera) renderer.render(scene, camera);
        }

        // Revit (mm) to Three.js (meters, Revit Z is Up)
        function revitToThree(x_mm, y_mm, z_mm, origin_mm) {
            const scale = 0.001; // mm to meters
            const ox = origin_mm ? origin_mm[0] : 0;
            const oy = origin_mm ? origin_mm[1] : 0;
            const oz = origin_mm ? origin_mm[2] : 0;
            return new THREE.Vector3(
                (x_mm - ox) * scale,
                (z_mm - oz) * scale,
                -(y_mm - oy) * scale
            );
        }

        // Helper: Create 3D Cylindrical Pipe Mesh between two 3D points
        function createCircularPipe(p1, p2, diameter_mm, colorHex) {
            const radius = Math.max((diameter_mm ? diameter_mm * 0.5 * 0.001 : 0.025), 0.015); // in meters
            const distance = p1.distanceTo(p2);
            if (distance < 0.001) return null;

            const geom = new THREE.CylinderGeometry(radius, radius, distance, 24, 1, false);
            const mat = new THREE.MeshStandardMaterial({
                color: colorHex || 0x06b6d4,
                metalness: 0.65,
                roughness: 0.25
            });
            const mesh = new THREE.Mesh(geom, mat);

            // Position at midpoint
            mesh.position.copy(p1).add(p2).multiplyScalar(0.5);

            // Align cylinder with vector p1 -> p2
            const dir = new THREE.Vector3().subVectors(p2, p1).normalize();
            const defaultDir = new THREE.Vector3(0, 1, 0); // cylinder default orientation
            const quaternion = new THREE.Quaternion().setFromUnitVectors(defaultDir, dir);
            mesh.setRotationFromQuaternion(quaternion);

            return mesh;
        }

        // Helper: Create Sprinkler with directional spray arrow & cone
        function createSprinklerMesh(pos, sprayDirVec, familyName) {
            const group = new THREE.Group();
            group.position.copy(pos);

            const isSidewall = (familyName || "").toLowerCase().includes("sidewall");
            const isUpright = (familyName || "").toLowerCase().includes("upright");

            // Sprinkler Core Body (Brass/Red)
            const bodyGeom = new THREE.CylinderGeometry(0.04, 0.06, 0.12, 16);
            const bodyMat = new THREE.MeshStandardMaterial({ color: 0xf59e0b, metalness: 0.8, roughness: 0.2 });
            const bodyMesh = new THREE.Mesh(bodyGeom, bodyMat);
            group.add(bodyMesh);

            // Deflector Head
            const defGeom = new THREE.CylinderGeometry(0.09, 0.09, 0.02, 16);
            const defMat = new THREE.MeshStandardMaterial({ color: 0xf43f5e, metalness: 0.6, roughness: 0.3 });
            const defMesh = new THREE.Mesh(defGeom, defMat);
            defMesh.position.y = -0.06;
            group.add(defMesh);

            // Spray Direction Vector (Default Pendent = Downward [0, -1, 0])
            let dir = new THREE.Vector3(0, -1, 0);
            if (sprayDirVec) {
                // Spray vector in Three coords: (X_revit, Z_revit, -Y_revit)
                dir = new THREE.Vector3(sprayDirVec.x, sprayDirVec.z, -sprayDirVec.y).normalize();
            } else if (isUpright) {
                dir = new THREE.Vector3(0, 1, 0); // Upright sprays Up
            } else if (isSidewall) {
                dir = new THREE.Vector3(0, 0, -1); // Sidewall sprays forward into room (+Y in Revit)
            }

            // Directional Spray Arrow (Compact 0.35m)
            const arrowLength = 0.35;
            const arrowColor = 0xf43f5e;
            const arrowHelper = new THREE.ArrowHelper(dir, new THREE.Vector3(0, 0, 0), arrowLength, arrowColor, 0.12, 0.08);
            group.add(arrowHelper);

            // Sidewall / Extended Coverage 3D Spray Zone Box
            if (isSidewall) {
                // Zone depth (throw) = 4.3m to 6.8m, width (lateral) = 3.0m to 5.5m, height = 0.6m
                const throwDepth = (familyName && familyName.toLowerCase().includes("ec")) ? 6.7 : 4.3;
                const lateralWidth = (familyName && familyName.toLowerCase().includes("ec")) ? 5.5 : 4.3;
                const zoneHeight = 0.6;

                const zoneGeom = new THREE.BoxGeometry(lateralWidth, zoneHeight, throwDepth);
                const zoneMat = new THREE.MeshStandardMaterial({
                    color: 0x38bdf8,
                    transparent: true,
                    opacity: 0.18,
                    roughness: 0.4,
                    metalness: 0.1,
                    depthWrite: false,
                    side: THREE.DoubleSide
                });
                const zoneMesh = new THREE.Mesh(zoneGeom, zoneMat);
                
                // Position zone in front of sprinkler along spray vector
                const forwardOffset = dir.clone().multiplyScalar(throwDepth * 0.5);
                zoneMesh.position.copy(forwardOffset);
                zoneMesh.position.y -= zoneHeight * 0.5;

                // Align rotation to dir
                const defaultDir = new THREE.Vector3(0, 0, -1);
                const rotQuat = new THREE.Quaternion().setFromUnitVectors(defaultDir, dir);
                zoneMesh.setRotationFromQuaternion(rotQuat);
                group.add(zoneMesh);

                // Zone Wireframe Edges
                const zoneEdges = new THREE.EdgesGeometry(zoneGeom);
                const zoneLine = new THREE.LineSegments(zoneEdges, new THREE.LineBasicMaterial({
                    color: 0x0284c7,
                    transparent: true,
                    opacity: 0.85,
                    linewidth: 2
                }));
                zoneLine.position.copy(zoneMesh.position);
                zoneLine.rotation.copy(zoneMesh.rotation);
                group.add(zoneLine);
            }

            return group;
        }

        // Helper: Create Ceiling Plane in 3D
        function createCeilingPlane(z_mm, origin_mm, colorHex, opacity, width_m, height_m) {
            const scale = 0.001;
            const oz = origin_mm ? origin_mm[2] : 0;
            const planeZ = (z_mm - oz) * scale;
            const w = width_m || 16;
            const h = height_m || 16;

            const geom = new THREE.PlaneGeometry(w, h, 8, 8);
            const mat = new THREE.MeshBasicMaterial({
                color: colorHex || 0x10b981,
                transparent: true,
                opacity: opacity || 0.22,
                side: THREE.DoubleSide
            });
            const mesh = new THREE.Mesh(geom, mat);
            mesh.rotation.x = Math.PI * 0.5;
            mesh.position.set(0, planeZ, 0);

            const edges = new THREE.EdgesGeometry(geom);
            const wire = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({
                color: colorHex || 0x10b981,
                transparent: true,
                opacity: 0.65
            }));
            wire.rotation.x = Math.PI * 0.5;
            wire.position.set(0, planeZ, 0);

            const group = new THREE.Group();
            group.add(mesh);
            group.add(wire);
            return group;
        }

        function isPointInPoly(pt, poly) {
            if (!poly || poly.length < 3) return false;
            let inside = false;
            const x = pt[0], y = pt[1];
            for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
                const xi = poly[i][0], yi = poly[i][1];
                const xj = poly[j][0], yj = poly[j][1];
                const intersect = ((yi > y) !== (yj > y)) &&
                    (x < (xj - xi) * (y - yi) / (yj - yi) + xi);
                if (intersect) inside = !inside;
            }
            return inside;
        }

        function findRoomForPoint(pt_mm, rooms) {
            if (!rooms || rooms.length === 0 || !pt_mm) return null;
            for (const rm of rooms) {
                if (rm.loops_mm && rm.loops_mm.length > 0) {
                    for (const loop of rm.loops_mm) {
                        if (isPointInPoly(pt_mm, loop)) return rm;
                    }
                }
            }
            return rooms[0];
        }

        function update3DScene(elements, activeModelName, rawSelectionData, agentContextData) {
            if (!elementsGroup) return;

            while (elementsGroup.children.length > 0) {
                const obj = elementsGroup.children[0];
                elementsGroup.remove(obj);
            }

            // Fresh scene layers attached directly to elementsGroup
            layerFloor = new THREE.Group();
            layerCeiling = new THREE.Group();
            layerSpray = new THREE.Group();
            layerDims = new THREE.Group();

            layerFloor.visible = (layersVisible.floor !== false);
            layerCeiling.visible = (layersVisible.ceiling !== false);
            layerSpray.visible = (layersVisible.spray !== false);
            layerDims.visible = (layersVisible.dims !== false);

            elementsGroup.add(layerFloor);
            elementsGroup.add(layerCeiling);
            elementsGroup.add(layerSpray);
            elementsGroup.add(layerDims);

            const hasElements = (elements && elements.length > 0);
            const hasRooms = (rawSelectionData && rawSelectionData.rooms && rawSelectionData.rooms.length > 0);
            if (!hasElements && !hasRooms) {
                document.getElementById('3d-element-count').textContent = '3D Objects: 0';
                return;
            }

            // Compute spatial bounding center
            let minX = Infinity, minY = Infinity, minZ = Infinity;
            let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
            let validCount = 0;

            if (hasElements) {
                elements.forEach(el => {
                    if (el.location_mm) {
                        minX = Math.min(minX, el.location_mm[0]);
                        minY = Math.min(minY, el.location_mm[1]);
                        minZ = Math.min(minZ, el.location_mm[2]);
                        maxX = Math.max(maxX, el.location_mm[0]);
                        maxY = Math.max(maxY, el.location_mm[1]);
                        maxZ = Math.max(maxZ, el.location_mm[2]);
                        validCount++;
                    } else if (el.bbox_mm && el.bbox_mm.min && el.bbox_mm.max) {
                        minX = Math.min(minX, el.bbox_mm.min[0]);
                        minY = Math.min(minY, el.bbox_mm.min[1]);
                        minZ = Math.min(minZ, el.bbox_mm.min[2]);
                        maxX = Math.max(maxX, el.bbox_mm.max[0]);
                        maxY = Math.max(maxY, el.bbox_mm.max[1]);
                        maxZ = Math.max(maxZ, el.bbox_mm.max[2]);
                        validCount++;
                    }
                });
            }

            // Also bound enclosing rooms
            if (hasRooms) {
                rawSelectionData.rooms.forEach(rm => {
                    if (rm.loops_mm) {
                        rm.loops_mm.forEach(loop => {
                            loop.forEach(pt => {
                                minX = Math.min(minX, pt[0]);
                                minY = Math.min(minY, pt[1]);
                                maxX = Math.max(maxX, pt[0]);
                                maxY = Math.max(maxY, pt[1]);
                                validCount++;
                            });
                        });
                    }
                    if (rm.z_min_mm !== undefined) {
                        minZ = Math.min(minZ, rm.z_min_mm);
                        maxZ = Math.max(maxZ, rm.z_min_mm + (rm.height_mm || 2500));
                        validCount++;
                    }
                });
            }

            const origin_mm = (validCount > 0) ? [
                (minX + maxX) * 0.5,
                (minY + maxY) * 0.5,
                (minZ + maxZ) * 0.5
            ] : [0,0,0];

            document.getElementById('three-bounds-label').textContent = 
                validCount > 0 ? `Center: [${origin_mm[0].toFixed(0)}, ${origin_mm[1].toFixed(0)}, ${origin_mm[2].toFixed(0)}] mm` : 'Center Origin';

            let count3D = 0;

            // 0. Render Ceiling & Niche Planes from Agent Context Markers
            if (agentContextData && agentContextData.spatial_visual_markers && agentContextData.spatial_visual_markers.ceiling_planes) {
                agentContextData.spatial_visual_markers.ceiling_planes.forEach(cp => {
                    const col = cp.color === '#10b981' ? 0x10b981 : (cp.color === '#f59e0b' ? 0xf59e0b : 0x3b82f6);
                    const planeMesh = createCeilingPlane(cp.z_mm, origin_mm, col, cp.opacity || 0.22, 16, 16);
                    if (planeMesh) {
                        elementsGroup.add(planeMesh);
                        count3D++;
                    }
                });
            }

            // 0.1 Render Highlighted Reference Walls (Target vs Column Snap)
            if (agentContextData && agentContextData.highlighted_walls && agentContextData.highlighted_walls.length > 0) {
                agentContextData.highlighted_walls.forEach(hw => {
                    if (hw.bbox_min_mm && hw.bbox_max_mm) {
                        const minPt = revitToThree(hw.bbox_min_mm[0], hw.bbox_min_mm[1], hw.bbox_min_mm[2], origin_mm);
                        const maxPt = revitToThree(hw.bbox_max_mm[0], hw.bbox_max_mm[1], hw.bbox_max_mm[2], origin_mm);

                        const szX = Math.max(Math.abs(maxPt.x - minPt.x), 0.08);
                        const szY = Math.max(Math.abs(maxPt.y - minPt.y), 0.08);
                        const szZ = Math.max(Math.abs(maxPt.z - minPt.z), 0.08);

                        const wGeom = new THREE.BoxGeometry(szX, szY, szZ);
                        const colInt = parseInt(hw.color.replace('#', '0x'), 16);
                        const wMat = new THREE.MeshStandardMaterial({
                            color: colInt,
                            transparent: true,
                            opacity: hw.opacity || 0.45,
                            metalness: 0.2,
                            roughness: 0.6,
                            side: THREE.DoubleSide
                        });
                        const wMesh = new THREE.Mesh(wGeom, wMat);
                        wMesh.position.set(
                            (minPt.x + maxPt.x) * 0.5,
                            (minPt.y + maxPt.y) * 0.5,
                            (minPt.z + maxPt.z) * 0.5
                        );
                        elementsGroup.add(wMesh);

                        // Glowing wireframe
                        const wEdges = new THREE.EdgesGeometry(wGeom);
                        const wireCol = hw.wireframe_color ? parseInt(hw.wireframe_color.replace('#', '0x'), 16) : colInt;
                        const wLine = new THREE.LineSegments(wEdges, new THREE.LineBasicMaterial({
                            color: wireCol,
                            linewidth: 2,
                            transparent: true,
                            opacity: 0.95
                        }));
                        wLine.position.copy(wMesh.position);
                        elementsGroup.add(wLine);

                        count3D++;
                    }
                });
            }

            if (hasElements) {
                elements.forEach(el => {
                    const cat = (el.category || "").toLowerCase();
                    const fam = (el.family || el.name || "").toLowerCase();

                    // 1. SPRINKLER ELEMENTS -> Direction strictly determined from Connector
                    if (cat.includes("sprinkler") || fam.includes("sprinkler")) {
                        let spPos = null;
                        if (el.location_mm) {
                            spPos = revitToThree(el.location_mm[0], el.location_mm[1], el.location_mm[2], origin_mm);
                        } else if (el.bbox_mm && el.bbox_mm.min && el.bbox_mm.max) {
                            const midX = (el.bbox_mm.min[0] + el.bbox_mm.max[0]) * 0.5;
                            const midY = (el.bbox_mm.min[1] + el.bbox_mm.max[1]) * 0.5;
                            const midZ = (el.bbox_mm.min[2] + el.bbox_mm.max[2]) * 0.5;
                            spPos = revitToThree(midX, midY, midZ, origin_mm);
                        }

                        if (spPos) {
                            let sprayVec = null;
                            
                            // 1. Check MEP Connector direction first (Spray is opposite to connector inlet vector)
                            if (el.connectors && el.connectors.length > 0) {
                                const conn = el.connectors[0];
                                if (conn.direction) {
                                    sprayVec = { 
                                        x: -conn.direction[0], 
                                        y: -conn.direction[1], 
                                        z: -conn.direction[2] 
                                    };
                                } else if (conn.origin_mm && el.location_mm) {
                                    const dx = el.location_mm[0] - conn.origin_mm[0];
                                    const dy = el.location_mm[1] - conn.origin_mm[1];
                                    const dz = el.location_mm[2] - conn.origin_mm[2];
                                    const len = Math.sqrt(dx*dx + dy*dy + dz*dz);
                                    if (len > 0.001) {
                                        sprayVec = { x: dx/len, y: dy/len, z: dz/len };
                                    }
                                }
                            }

                            // 2. Fallback to orientation transform if no connector vector
                            if (!sprayVec && el.orientation && el.orientation.basis_z) {
                                sprayVec = { x: el.orientation.basis_z[0], y: el.orientation.basis_z[1], z: el.orientation.basis_z[2] };
                            }

                            const spMesh = createSprinklerMesh(spPos, sprayVec, el.family || el.name);
                            elementsGroup.add(spMesh);
                            count3D++;
                        }
                    }

                    // 2. CIRCULAR PIPES & CURVES -> True Cylindrical 3D Tube Mesh
                    else if (cat.includes("pipe") || el.curve_start_mm) {
                        let p1, p2, dia;
                        if (el.curve_start_mm && el.curve_end_mm) {
                            p1 = revitToThree(el.curve_start_mm[0], el.curve_start_mm[1], el.curve_start_mm[2], origin_mm);
                            p2 = revitToThree(el.curve_end_mm[0], el.curve_end_mm[1], el.curve_end_mm[2], origin_mm);
                            dia = el.diameter_mm || 32;
                        } else if (el.bbox_mm && el.bbox_mm.min && el.bbox_mm.max) {
                            const dx = Math.abs(el.bbox_mm.max[0] - el.bbox_mm.min[0]);
                            const dy = Math.abs(el.bbox_mm.max[1] - el.bbox_mm.min[1]);
                            const dz = Math.abs(el.bbox_mm.max[2] - el.bbox_mm.min[2]);
                            
                            if (dx >= dy && dx >= dz) {
                                p1 = revitToThree(el.bbox_mm.min[0], (el.bbox_mm.min[1]+el.bbox_mm.max[1])*0.5, (el.bbox_mm.min[2]+el.bbox_mm.max[2])*0.5, origin_mm);
                                p2 = revitToThree(el.bbox_mm.max[0], (el.bbox_mm.min[1]+el.bbox_mm.max[1])*0.5, (el.bbox_mm.min[2]+el.bbox_mm.max[2])*0.5, origin_mm);
                                dia = Math.max(dy, dz);
                            } else if (dy >= dx && dy >= dz) {
                                p1 = revitToThree((el.bbox_mm.min[0]+el.bbox_mm.max[0])*0.5, el.bbox_mm.min[1], (el.bbox_mm.min[2]+el.bbox_mm.max[2])*0.5, origin_mm);
                                p2 = revitToThree((el.bbox_mm.max[0]+el.bbox_mm.min[0])*0.5, el.bbox_mm.max[1], (el.bbox_mm.min[2]+el.bbox_mm.max[2])*0.5, origin_mm);
                                dia = Math.max(dx, dz);
                            } else {
                                p1 = revitToThree((el.bbox_mm.min[0]+el.bbox_mm.max[0])*0.5, (el.bbox_mm.min[1]+el.bbox_mm.max[1])*0.5, el.bbox_mm.min[2], origin_mm);
                                p2 = revitToThree((el.bbox_mm.min[0]+el.bbox_mm.max[0])*0.5, (el.bbox_mm.min[1]+el.bbox_mm.max[1])*0.5, el.bbox_mm.max[2], origin_mm);
                                dia = Math.max(dx, dy);
                            }
                        }

                        if (p1 && p2) {
                            const pipeMesh = createCircularPipe(p1, p2, dia, 0x06b6d4);
                            if (pipeMesh) {
                                elementsGroup.add(pipeMesh);
                                count3D++;
                            }
                        }
                    }

                    // 3. AIR TERMINALS / DIFFUSERS / EQUIPMENT -> Volumetric 3D Box with Directional Throw
                    else if (cat.includes("air") || cat.includes("terminal") || cat.includes("diffuser") || cat.includes("duct")) {
                        if (el.bbox_mm && el.bbox_mm.min && el.bbox_mm.max) {
                            const minPt = revitToThree(el.bbox_mm.min[0], el.bbox_mm.min[1], el.bbox_mm.min[2], origin_mm);
                            const maxPt = revitToThree(el.bbox_mm.max[0], el.bbox_mm.max[1], el.bbox_mm.max[2], origin_mm);

                            const sizeX = Math.max(Math.abs(maxPt.x - minPt.x), 0.2);
                            const sizeY = Math.max(Math.abs(maxPt.y - minPt.y), 0.2);
                            const sizeZ = Math.max(Math.abs(maxPt.z - minPt.z), 0.2);

                            const geom = new THREE.BoxGeometry(sizeX, sizeY, sizeZ);
                            const mat = new THREE.MeshStandardMaterial({
                                color: 0xa855f7,
                                roughness: 0.3,
                                metalness: 0.4,
                                transparent: true,
                                opacity: 0.85
                            });
                            const mesh = new THREE.Mesh(geom, mat);
                            mesh.position.set(
                                (minPt.x + maxPt.x) * 0.5,
                                (minPt.y + maxPt.y) * 0.5,
                                (minPt.z + maxPt.z) * 0.5
                            );
                            elementsGroup.add(mesh);

                            const edges = new THREE.EdgesGeometry(geom);
                            const line = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.4 }));
                            mesh.add(line);

                            const throwDir = new THREE.Vector3(0, -1, 0);
                            const throwArrow = new THREE.ArrowHelper(throwDir, mesh.position, 0.65, 0xa855f7, 0.2, 0.12);
                            elementsGroup.add(throwArrow);

                            count3D++;
                        }
                    }

                    // 4. OTHER BOUNDED ELEMENTS
                    else if (el.bbox_mm && el.bbox_mm.min && el.bbox_mm.max) {
                        const minPt = revitToThree(el.bbox_mm.min[0], el.bbox_mm.min[1], el.bbox_mm.min[2], origin_mm);
                        const maxPt = revitToThree(el.bbox_mm.max[0], el.bbox_mm.max[1], el.bbox_mm.max[2], origin_mm);

                        const sizeX = Math.max(Math.abs(maxPt.x - minPt.x), 0.15);
                        const sizeY = Math.max(Math.abs(maxPt.y - minPt.y), 0.15);
                        const sizeZ = Math.max(Math.abs(maxPt.z - minPt.z), 0.15);

                        const geom = new THREE.BoxGeometry(sizeX, sizeY, sizeZ);
                        const mat = new THREE.MeshStandardMaterial({
                            color: 0xf59e0b,
                            roughness: 0.3,
                            metalness: 0.2,
                            transparent: true,
                            opacity: 0.65
                        });
                        const mesh = new THREE.Mesh(geom, mat);
                        mesh.position.set(
                            (minPt.x + maxPt.x) * 0.5,
                            (minPt.y + maxPt.y) * 0.5,
                            (minPt.z + maxPt.z) * 0.5
                        );
                        elementsGroup.add(mesh);
                        count3D++;
                    }

                    // 4.1 POINT ELEMENTS (Room Tags, Point Markers without BBox)
                    else if (el.location_mm) {
                        const pt = revitToThree(el.location_mm[0], el.location_mm[1], el.location_mm[2], origin_mm);
                        const tagGroup = new THREE.Group();
                        tagGroup.position.copy(pt);
                        
                        const pinGeom = new THREE.OctahedronGeometry(0.18);
                        const pinMat = new THREE.MeshStandardMaterial({
                            color: 0xa855f7,
                            roughness: 0.2,
                            metalness: 0.8
                        });
                        const pinMesh = new THREE.Mesh(pinGeom, pinMat);
                        tagGroup.add(pinMesh);

                        const label = (el.category ? el.category + ': ' : '') + (el.family || el.name || el.type || ('ID ' + el.id));
                        const tagSprite = makeTextSprite(label, { color: '#c084fc', scale: 0.0020 });
                        tagSprite.position.set(0, 0.35, 0);
                        tagGroup.add(tagSprite);

                        elementsGroup.add(tagGroup);
                        count3D++;
                    }

                    // MEP Connectors
                    if (el.connectors && el.connectors.length > 0) {
                        el.connectors.forEach(conn => {
                            if (conn.origin_mm) {
                                const cPt = revitToThree(conn.origin_mm[0], conn.origin_mm[1], conn.origin_mm[2], origin_mm);
                                const cGeom = new THREE.OctahedronGeometry(0.06);
                                const cMat = new THREE.MeshBasicMaterial({ color: 0x10b981 });
                                const cMesh = new THREE.Mesh(cGeom, cMat);
                                cMesh.position.copy(cPt);
                                elementsGroup.add(cMesh);
                            }
                        });
                    }
                });
            }

            // 5. ENCLOSING ROOM GEOMETRY, FLOOR SLAB, OVERHEAD SLAB & 2D PROJECTIONS
            if (rawSelectionData && rawSelectionData.rooms && rawSelectionData.rooms.length > 0) {
                rawSelectionData.rooms.forEach(rm => {
                    if (rm.loops_mm && rm.loops_mm.length > 0) {
                        rm.loops_mm.forEach(loop => {
                            if (loop.length >= 3) {
                                const shape = new THREE.Shape();
                                const scale = 0.001;
                                const ox = origin_mm[0];
                                const oy = origin_mm[1];
                                const oz = origin_mm[2];

                                shape.moveTo((loop[0][0] - ox) * scale, (loop[0][1] - oy) * scale);
                                for (let i = 1; i < loop.length; i++) {
                                    shape.lineTo((loop[i][0] - ox) * scale, (loop[i][1] - oy) * scale);
                                }
                                shape.closePath();

                                const roomZBase = (rm.z_min_mm ? (rm.z_min_mm - oz) * scale : -1.5);
                                const hFull = Math.max((rm.height_mm ? rm.height_mm * scale : 2.9), 2.4);
                                const slabZ = roomZBase + hFull;

                                // 5.1 Solid 2D Floor Slab with rich slate material & glowing border
                                const floorGeom = new THREE.ShapeGeometry(shape);
                                floorGeom.rotateX(-Math.PI * 0.5);
                                const floorMat = new THREE.MeshStandardMaterial({
                                    color: 0x0f172a,
                                    roughness: 0.85,
                                    metalness: 0.15,
                                    side: THREE.DoubleSide
                                });
                                const floorMesh = new THREE.Mesh(floorGeom, floorMat);
                                floorMesh.position.set(0, roomZBase, 0);
                                layerFloor.add(floorMesh);

                                // Floor Perimeter Border line in bright cyan
                                const borderPts = [];
                                loop.forEach(pt => {
                                    borderPts.push(new THREE.Vector3((pt[0] - ox) * scale, roomZBase + 0.005, -(pt[1] - oy) * scale));
                                });
                                borderPts.push(borderPts[0]);
                                const borderGeom = new THREE.BufferGeometry().setFromPoints(borderPts);
                                const borderLine = new THREE.Line(borderGeom, new THREE.LineBasicMaterial({ color: 0x38bdf8, linewidth: 3 }));
                                layerFloor.add(borderLine);

                                // Room Name/Number Label Badge on Floor
                                let rMidX = 0, rMidY = 0;
                                loop.forEach(pt => { rMidX += pt[0]; rMidY += pt[1]; });
                                rMidX = (rMidX / loop.length - ox) * scale;
                                rMidY = -(rMidY / loop.length - oy) * scale;

                                const roomLabel = (rm.number ? rm.number + ' ' : '') + (rm.name || 'Room') + ' (H=' + Math.round(rm.height_mm || 2500) + ' мм)';
                                const rmTag = makeTextSprite('🏠 ' + roomLabel, {
                                    color: '#60a5fa',
                                    bgColor: 'rgba(15, 23, 42, 0.9)',
                                    scale: 0.0022
                                });
                                rmTag.position.set(rMidX, roomZBase + 0.04, rMidY);
                                layerFloor.add(rmTag);

                                // 5.2 Dynamic 3D Room Translucent Volume
                                const extrudeSettingsMain = { depth: hFull, bevelEnabled: false };
                                const roomGeomMain = new THREE.ExtrudeGeometry(shape, extrudeSettingsMain);
                                roomGeomMain.rotateX(-Math.PI * 0.5);
                                const roomMat = new THREE.MeshStandardMaterial({
                                    color: 0x1e3a8a,
                                    transparent: true,
                                    opacity: 0.10,
                                    side: THREE.DoubleSide,
                                    depthWrite: false,
                                    roughness: 0.9
                                });
                                const roomMesh = new THREE.Mesh(roomGeomMain, roomMat);
                                roomMesh.position.set(0, roomZBase, 0);
                                layerFloor.add(roomMesh);

                                // Room Wireframe Edges
                                const roomEdges = new THREE.EdgesGeometry(roomGeomMain);
                                const roomLine = new THREE.LineSegments(roomEdges, new THREE.LineBasicMaterial({
                                    color: 0x3b82f6,
                                    transparent: true,
                                    opacity: 0.45,
                                    linewidth: 1
                                }));
                                roomLine.position.set(0, roomZBase, 0);
                                layerFloor.add(roomLine);

                                count3D += 3;

                                // 5.3 Concrete Slab Overhead Top Plane
                                const hasSuspendedCeilings = (rm.ceilings && rm.ceilings.length > 0);
                                const slabGeom = new THREE.ShapeGeometry(shape);
                                slabGeom.rotateX(-Math.PI * 0.5);
                                const slabMat = new THREE.MeshStandardMaterial({
                                    color: 0x1e293b,
                                    transparent: true,
                                    opacity: hasSuspendedCeilings ? 0.12 : 0.28,
                                    side: THREE.DoubleSide,
                                    roughness: 0.8
                                });
                                const slabMesh = new THREE.Mesh(slabGeom, slabMat);
                                slabMesh.position.set(0, slabZ, 0);
                                layerCeiling.add(slabMesh);

                                const slabBorderPts = [];
                                loop.forEach(pt => {
                                    slabBorderPts.push(new THREE.Vector3((pt[0] - ox) * scale, slabZ, -(pt[1] - oy) * scale));
                                });
                                slabBorderPts.push(slabBorderPts[0]);
                                const slabBorderLine = new THREE.Line(new THREE.BufferGeometry().setFromPoints(slabBorderPts), new THREE.LineBasicMaterial({
                                    color: hasSuspendedCeilings ? 0x475569 : 0x94a3b8,
                                    linewidth: 2
                                }));
                                layerCeiling.add(slabBorderLine);

                                const slabLabelText = hasSuspendedCeilings
                                    ? 'Плита перекрытия +' + Math.round(rm.height_mm || 2900) + ' мм'
                                    : 'Плита перекрытия +' + Math.round(rm.height_mm || 2900) + ' мм (открытый потолок)';
                                const slabTag = makeTextSprite(slabLabelText, {
                                    color: '#94a3b8',
                                    scale: 0.0020
                                });
                                slabTag.position.set(rMidX, slabZ + 0.15, rMidY);
                                layerCeiling.add(slabTag);
                                count3D += 2;

                                // 5.4 Suspended Ceilings & Soffits (3D Slabs + 2D Floor Footprint)
                                if (hasSuspendedCeilings) {
                                    rm.ceilings.forEach(cl => {
                                        if (cl.bbox_mm && cl.bbox_mm.min && cl.bbox_mm.max) {
                                            const cMin = cl.bbox_mm.min;
                                            const cMax = cl.bbox_mm.max;
                                            const clX = ((cMin[0] + cMax[0]) * 0.5 - ox) * scale;
                                            const clZ = -((cMin[1] + cMax[1]) * 0.5 - oy) * scale;
                                            const clY = (cl.z_elev_mm - oz) * scale;
                                            const clW = Math.max(Math.abs(cMax[0] - cMin[0]) * scale, 0.2);
                                            const clD = Math.max(Math.abs(cMax[1] - cMin[1]) * scale, 0.2);

                                            // 3D Ceiling Slab
                                            const clGeom = new THREE.PlaneGeometry(clW, clD);
                                            const clColor = cl.is_cornice ? 0xf59e0b : 0x10b981;
                                            const clMat = new THREE.MeshStandardMaterial({
                                                color: clColor,
                                                transparent: true,
                                                opacity: 0.35,
                                                side: THREE.DoubleSide,
                                                roughness: 0.4
                                            });
                                            const clMesh = new THREE.Mesh(clGeom, clMat);
                                            clMesh.rotation.x = Math.PI * 0.5;
                                            clMesh.position.set(clX, clY, clZ);
                                            layerCeiling.add(clMesh);

                                            // 3D Ceiling Edges
                                            const clEdges = new THREE.EdgesGeometry(clGeom);
                                            const clWire = new THREE.LineSegments(clEdges, new THREE.LineBasicMaterial({ color: clColor, linewidth: 2 }));
                                            clWire.rotation.x = Math.PI * 0.5;
                                            clWire.position.set(clX, clY, clZ);
                                            layerCeiling.add(clWire);

                                            // 3D Tag
                                            const clTag = makeTextSprite(cl.is_cornice ? 'Карниз (ниша) +' + Math.round(cl.rel_z_mm) + ' мм' : 'Подвесной потолок +' + Math.round(cl.rel_z_mm) + ' мм', {
                                                color: cl.is_cornice ? '#fbbf24' : '#34d399',
                                                scale: 0.0022
                                            });
                                            clTag.position.set(clX, clY + 0.15, clZ);
                                            layerCeiling.add(clTag);

                                            // 2D Projection Footprint on Floor
                                            const cFloorPts = [
                                                new THREE.Vector3((cMin[0] - ox) * scale, roomZBase + 0.015, -(cMin[1] - oy) * scale),
                                                new THREE.Vector3((cMax[0] - ox) * scale, roomZBase + 0.015, -(cMin[1] - oy) * scale),
                                                new THREE.Vector3((cMax[0] - ox) * scale, roomZBase + 0.015, -(cMax[1] - oy) * scale),
                                                new THREE.Vector3((cMin[0] - ox) * scale, roomZBase + 0.015, -(cMax[1] - oy) * scale),
                                                new THREE.Vector3((cMin[0] - ox) * scale, roomZBase + 0.015, -(cMin[1] - oy) * scale)
                                            ];
                                            const cFloorGeom = new THREE.BufferGeometry().setFromPoints(cFloorPts);
                                            const cFloorLine = new THREE.Line(cFloorGeom, new THREE.LineDashedMaterial({
                                                color: clColor,
                                                dashSize: 0.15,
                                                gapSize: 0.08,
                                                linewidth: 2
                                            }));
                                            cFloorLine.computeLineDistances();
                                            layerCeiling.add(cFloorLine);

                                            // Floor projection label
                                            const cFloorTag = makeTextSprite('Проекция карниза: ' + Math.round(cl.coverage_ratio*100) + '% комнаты', {
                                                color: '#f59e0b',
                                                scale: 0.0020
                                            });
                                            cFloorTag.position.set(clX, roomZBase + 0.05, clZ);
                                            layerCeiling.add(cFloorTag);

                                            count3D += 2;
                                        }
                                    });
                                }
                            }
                        });
                    }
                });
            }

            // 6. SPRINKLER 2D DROP LINES, TARGET RINGS & SIDEWALL SPRAY COVERAGE
            const spElems = (elements || []).filter(el => (el.category || "").toLowerCase().includes("sprinkler") || (el.family || "").toLowerCase().includes("sprinkler"));
            const allRooms = (rawSelectionData && rawSelectionData.rooms && rawSelectionData.rooms.length > 0) ? rawSelectionData.rooms : [];

            if (spElems.length > 0 && allRooms.length > 0) {
                const ox = origin_mm[0];
                const oy = origin_mm[1];
                const oz = origin_mm[2];
                const scale = 0.001;

                spElems.forEach((sp, idx) => {
                    if (!sp.location_mm) return;
                    const spPos = revitToThree(sp.location_mm[0], sp.location_mm[1], sp.location_mm[2], origin_mm);
                    targetSpkPos = spPos.clone();

                    const currentRoom = findRoomForPoint(sp.location_mm, allRooms) || allRooms[0];
                    const roomZBase = (currentRoom.z_min_mm ? (currentRoom.z_min_mm - oz) * scale : -1.5);

                    // Compute current room boundary bounds
                    let rMinX = Infinity, rMaxX = -Infinity, rMinY = Infinity, rMaxY = -Infinity;
                    if (currentRoom.loops_mm) {
                        currentRoom.loops_mm.forEach(l => {
                            l.forEach(pt => {
                                rMinX = Math.min(rMinX, pt[0]);
                                rMaxX = Math.max(rMaxX, pt[0]);
                                rMinY = Math.min(rMinY, pt[1]);
                                rMaxY = Math.max(rMaxY, pt[1]);
                            });
                        });
                    }

                    const floorLandingPos = new THREE.Vector3(spPos.x, roomZBase + 0.01, spPos.z);

                    // 6.1 Vertical Dashed Drop Line from Sprinkler down to Floor
                    const dropGeom = new THREE.BufferGeometry().setFromPoints([spPos, floorLandingPos]);
                    const dropMat = new THREE.LineDashedMaterial({
                        color: 0x06b6d4,
                        dashSize: 0.12,
                        gapSize: 0.06,
                        linewidth: 2
                    });
                    const dropLine = new THREE.Line(dropGeom, dropMat);
                    dropLine.computeLineDistances();
                    layerDims.add(dropLine);

                    // Height Tag at midpoint
                    const hDistMm = Math.round(sp.location_mm[2] - currentRoom.z_min_mm);
                    const hTag = makeTextSprite('H = ' + hDistMm + ' мм (к полу)', {
                        color: '#38bdf8',
                        scale: 0.0022
                    });
                    hTag.position.set(spPos.x + 0.22, (spPos.y + roomZBase) * 0.5, spPos.z);
                    layerDims.add(hTag);

                    // 6.2 Floor Landing Target Rings & Crosshair
                    const ringGeom1 = new THREE.RingGeometry(0.12, 0.15, 32);
                    ringGeom1.rotateX(-Math.PI * 0.5);
                    const ringMat1 = new THREE.MeshBasicMaterial({ color: 0x06b6d4, side: THREE.DoubleSide });
                    const ringMesh1 = new THREE.Mesh(ringGeom1, ringMat1);
                    ringMesh1.position.copy(floorLandingPos);
                    layerFloor.add(ringMesh1);

                    const ringGeom2 = new THREE.RingGeometry(0.30, 0.33, 32);
                    ringGeom2.rotateX(-Math.PI * 0.5);
                    const ringMat2 = new THREE.MeshBasicMaterial({ color: 0x0ea5e9, transparent: true, opacity: 0.65, side: THREE.DoubleSide });
                    const ringMesh2 = new THREE.Mesh(ringGeom2, ringMat2);
                    ringMesh2.position.copy(floorLandingPos);
                    layerFloor.add(ringMesh2);

                    const floorCoordTag = makeTextSprite('2D Проекция [' + sp.location_mm[0].toFixed(0) + ', ' + sp.location_mm[1].toFixed(0) + ']', {
                        color: '#67e8f9',
                        scale: 0.0018
                    });
                    floorCoordTag.position.set(floorLandingPos.x, floorLandingPos.y + 0.08, floorLandingPos.z + 0.42);
                    layerFloor.add(floorCoordTag);

                    // 6.3 Sidewall Spray Pattern on Floor Plane (South throw)
                    const isSidewall = (sp.family || "").toLowerCase().includes("sidewall");
                    if (isSidewall && rMinX < Infinity) {
                        const throwDepthMm = Math.abs(sp.location_mm[1] - rMinY);
                        const throwDepthM = throwDepthMm * scale;
                        const roomWidthM = (rMaxX - rMinX) * scale;
                        const sprayHalfW = Math.min(roomWidthM * 0.5, 2.0);

                        const sprayShape = new THREE.Shape();
                        sprayShape.moveTo(spPos.x, spPos.z);
                        sprayShape.lineTo(spPos.x - sprayHalfW, spPos.z + throwDepthM);
                        sprayShape.lineTo(spPos.x + sprayHalfW, spPos.z + throwDepthM);
                        sprayShape.closePath();

                        const sprayGeom = new THREE.ShapeGeometry(sprayShape);
                        sprayGeom.rotateX(-Math.PI * 0.5);
                        const sprayMat = new THREE.MeshStandardMaterial({
                            color: 0x06b6d4,
                            transparent: true,
                            opacity: 0.20,
                            roughness: 0.3,
                            side: THREE.DoubleSide
                        });
                        const sprayMesh = new THREE.Mesh(sprayGeom, sprayMat);
                        sprayMesh.position.set(0, roomZBase + 0.012, 0);
                        layerSpray.add(sprayMesh);

                        // Concentric water ripple arcs
                        for (let arcR = 0.8; arcR <= throwDepthM; arcR += 0.8) {
                            const arcCurve = new THREE.EllipseCurve(
                                spPos.x, spPos.z,
                                arcR, arcR,
                                Math.PI * 0.15, Math.PI * 0.85,
                                false, 0
                            );
                            const arcPts2D = arcCurve.getPoints(24);
                            const arcPts3D = arcPts2D.map(p => new THREE.Vector3(p.x, roomZBase + 0.014, p.y));
                            const arcGeom = new THREE.BufferGeometry().setFromPoints(arcPts3D);
                            const arcLine = new THREE.Line(arcGeom, new THREE.LineBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.6 }));
                            layerSpray.add(arcLine);
                        }

                        const sprayTag = makeTextSprite('Факел Sidewall: вылет ' + Math.round(throwDepthMm) + ' мм (норма <= 4600)', {
                            color: '#06b6d4',
                            scale: 0.0020
                        });
                        sprayTag.position.set(spPos.x, roomZBase + 0.1, spPos.z + throwDepthM * 0.55);
                        layerSpray.add(sprayTag);
                    }

                    // 6.4 Dynamic Wall Distance Dimension Lines
                    if (rMinX < Infinity) {
                        const distN = Math.abs(rMaxY - sp.location_mm[1]);
                        const distS = Math.abs(sp.location_mm[1] - rMinY);
                        const distW = Math.abs(sp.location_mm[0] - rMinX);
                        const distE = Math.abs(rMaxX - sp.location_mm[0]);

                        const dimMat = new THREE.LineDashedMaterial({ color: 0xf59e0b, dashSize: 0.12, gapSize: 0.06, linewidth: 2 });

                        // To North Wall (Mounting Wall)
                        const nPt = revitToThree(sp.location_mm[0], rMaxY, sp.location_mm[2], origin_mm);
                        const nLine = new THREE.Line(new THREE.BufferGeometry().setFromPoints([spPos, nPt]), dimMat);
                        nLine.computeLineDistances();
                        layerDims.add(nLine);
                        const nTag = makeTextSprite(Math.round(distN) + ' мм (монтаж)', { color: '#f59e0b', scale: 0.0019 });
                        nTag.position.set(spPos.x, spPos.y + 0.15, (spPos.z + nPt.z) * 0.5);
                        layerDims.add(nTag);

                        // To South Wall (Opposite Facade)
                        const sPt = revitToThree(sp.location_mm[0], rMinY, sp.location_mm[2], origin_mm);
                        const sLine = new THREE.Line(new THREE.BufferGeometry().setFromPoints([spPos, sPt]), dimMat);
                        sLine.computeLineDistances();
                        layerDims.add(sLine);
                        const sTag = makeTextSprite(Math.round(distS) + ' мм (до противоположной стены)', { color: '#f59e0b', scale: 0.0019 });
                        sTag.position.set(spPos.x, spPos.y + 0.15, (spPos.z + sPt.z) * 0.5);
                        layerDims.add(sTag);

                        // To West Wall
                        const wPt = revitToThree(rMinX, sp.location_mm[1], sp.location_mm[2], origin_mm);
                        const wLine = new THREE.Line(new THREE.BufferGeometry().setFromPoints([spPos, wPt]), dimMat);
                        wLine.computeLineDistances();
                        layerDims.add(wLine);
                        const wTag = makeTextSprite(Math.round(distW) + ' мм', { color: '#22d3ee', scale: 0.0019 });
                        wTag.position.set((spPos.x + wPt.x) * 0.5, spPos.y + 0.15, spPos.z);
                        layerDims.add(wTag);

                        // To East Wall
                        const ePt = revitToThree(rMaxX, sp.location_mm[1], sp.location_mm[2], origin_mm);
                        const eLine = new THREE.Line(new THREE.BufferGeometry().setFromPoints([spPos, ePt]), dimMat);
                        eLine.computeLineDistances();
                        layerDims.add(eLine);
                        const eTag = makeTextSprite(Math.round(distE) + ' мм', { color: '#22d3ee', scale: 0.0019 });
                        eTag.position.set((spPos.x + ePt.x) * 0.5, spPos.y + 0.15, spPos.z);
                        layerDims.add(eTag);
                    }

                    count3D += 6;
                });
            }

            // 6.5 Update Floating Elevation HUD (Always updated if room exists)
            if (allRooms.length > 0) {
                const primaryRoom = allRooms[0];
                const primarySpk = spElems.length > 0 ? spElems[0] : null;
                const refLvlElev = primaryRoom.ref_level_elev_mm || 76900;

                document.getElementById('hud-ref-level').textContent = (primaryRoom.ref_level_name || '24') + ' (' + (refLvlElev * 0.001).toFixed(2) + ' м)';
                document.getElementById('hud-floor-elev').textContent = '0 мм (Абс: ' + (primaryRoom.z_min_mm * 0.001).toFixed(2) + ' м)';

                if (primarySpk && primarySpk.location_mm) {
                    const relSpkZ = Math.round(primarySpk.location_mm[2] - refLvlElev);
                    document.getElementById('hud-spk-elev').textContent = '+' + relSpkZ + ' мм (Абс: ' + (primarySpk.location_mm[2] * 0.001).toFixed(2) + ' м)';

                    if (primaryRoom.ceilings && primaryRoom.ceilings.length > 0) {
                        const c0 = primaryRoom.ceilings[0];
                        document.getElementById('hud-cl-elev').textContent = '+' + Math.round(c0.rel_z_mm) + ' мм (Абс: ' + (c0.z_elev_mm * 0.001).toFixed(2) + ' м)';
                        const deltaZ = relSpkZ - Math.round(c0.rel_z_mm);
                        document.getElementById('hud-status-pill').textContent = c0.is_cornice ? ('🎯 На кромке карниза (Δz = ' + (deltaZ >= 0 ? '+' : '') + deltaZ + ' мм)') : ('🎯 Подвесной потолок (Δz = ' + (deltaZ >= 0 ? '+' : '') + deltaZ + ' мм)');
                    } else {
                        document.getElementById('hud-cl-elev').textContent = 'Отсутствует (открытая плита)';
                        const slabZRel = Math.round(primaryRoom.height_mm || 2900);
                        const deltaSlab = slabZRel - relSpkZ;
                        document.getElementById('hud-status-pill').textContent = '🎯 Монтаж под плиту (' + deltaSlab + ' мм до плиты)';
                    }
                } else {
                    document.getElementById('hud-spk-elev').textContent = 'Не выбран';
                    if (primaryRoom.ceilings && primaryRoom.ceilings.length > 0) {
                        const c0 = primaryRoom.ceilings[0];
                        document.getElementById('hud-cl-elev').textContent = '+' + Math.round(c0.rel_z_mm) + ' мм';
                        document.getElementById('hud-status-pill').textContent = c0.is_cornice ? 'Карниз (ниша)' : 'Подвесной потолок';
                    } else {
                        document.getElementById('hud-cl-elev').textContent = 'Отсутствует (открытая плита)';
                        document.getElementById('hud-status-pill').textContent = 'Зона помещения (открытый потолок)';
                    }
                }

                const relSlabZ = Math.round((primaryRoom.z_max_mm || (primaryRoom.z_min_mm + (primaryRoom.height_mm || 2900))) - refLvlElev);
                document.getElementById('hud-slab-elev').textContent = '+' + relSlabZ + ' мм (Абс: ' + ((primaryRoom.z_max_mm || 79800) * 0.001).toFixed(2) + ' м)';
            }

            document.getElementById('3d-element-count').textContent = `3D Objects: ${count3D}`;
            if (activeModelName) document.getElementById('three-model-label').textContent = activeModelName;
        }

        // ================= Dashboard Refresh Polling Loop =================
        let lastAgentTs = '';
        let lastUserTs = '';

        async function refreshDashboard() {
            try {
                const res = await fetch('/api/state');
                if (!res.ok) return;
                const data = await res.json();

                // Update Status
                const statusDiv = document.getElementById('agent-status');
                const statusText = document.getElementById('agent-status-text');
                const isBusy = data.status && data.status.busy;
                window.currentAgentStatus = isBusy ? 'busy' : 'idle';
                if (isBusy) {
                    statusDiv.className = 'agent-status-tag status-busy';
                    statusText.textContent = 'Agent Processing...';
                    document.getElementById('info-agent-state').textContent = 'Processing';
                } else {
                    statusDiv.className = 'agent-status-tag status-idle';
                    statusText.textContent = 'Agent Ready (Idle)';
                    document.getElementById('info-agent-state').textContent = 'Idle';
                }

                // Update Model Info
                const docTitle = data.active_model || (data.agent_meta && data.agent_meta.doc_title) || 'Active Revit Session';
                document.getElementById('active-model-title').textContent = 'Model: ' + docTitle;
                document.getElementById('info-doc-title').textContent = docTitle;
                document.getElementById('info-port').textContent = data.bound_port || '40001 (Auto)';

                // Update Agent Context & Intent
                if (data.agent_context) {
                    const ctx = data.agent_context;
                    if (ctx.task_mission) document.getElementById('intent-task-mission').textContent = ctx.task_mission;
                    if (ctx.intent_purpose) document.getElementById('intent-purpose-text').textContent = ctx.intent_purpose;
                    if (ctx.status) document.getElementById('context-audit-badge').textContent = ctx.status;

                    if (ctx.agent_deductions && ctx.agent_deductions.length > 0) {
                        document.getElementById('deductions-count').textContent = ctx.agent_deductions.length + ' insights';
                        document.getElementById('intent-deductions-list').innerHTML = ctx.agent_deductions.map(d => `
                            <div class="deduction-item">${d}</div>
                        `).join('');
                    }

                    if (ctx.verification_checklist && ctx.verification_checklist.length > 0) {
                        document.getElementById('intent-checklist').innerHTML = ctx.verification_checklist.map(c => `
                            <div class="checklist-item">
                                <span class="check-badge ${c.status === 'CONFIRMED' ? 'check-confirmed' : 'check-pending'}">${c.status}</span>
                                <span>${c.item}</span>
                            </div>
                        `).join('');
                    }
                }

                // Update Agent Capture
                if (data.agent_meta) {
                    if (data.agent_meta.timestamp !== lastAgentTs) {
                        lastAgentTs = data.agent_meta.timestamp;
                        document.getElementById('agent-cap-img').src = '/api/image/agent?t=' + Date.now();
                        document.getElementById('agent-cap-time').textContent = formatTs(data.agent_meta.timestamp);
                        document.getElementById('agent-view-name').textContent = 'View: ' + (data.agent_meta.view_name || 'Active');
                        document.getElementById('agent-view-type').textContent = 'Type: ' + (data.agent_meta.view_type || 'FloorPlan');
                        document.getElementById('info-latest-time').textContent = formatTs(data.agent_meta.timestamp);
                    }
                }

                // Update User Snip
                if (data.user_meta) {
                    if (data.user_meta.timestamp !== lastUserTs) {
                        lastUserTs = data.user_meta.timestamp;
                        document.getElementById('user-snip-img').src = '/api/image/user?t=' + Date.now();
                        document.getElementById('user-snip-time').textContent = formatTs(data.user_meta.timestamp);
                        if (data.user_meta.width && data.user_meta.height) {
                            document.getElementById('user-snip-res').textContent = data.user_meta.width + 'x' + data.user_meta.height + ' px';
                        }
                    }
                }

                // Update Selection & 3D Objects
                const selContainer = document.getElementById('selection-items');
                if (data.selection && data.selection.elements && data.selection.elements.length > 0) {
                    const selElements = data.selection.elements;
                    document.getElementById('sel-count').textContent = selElements.length + ' items';
                    selContainer.innerHTML = selElements.map(el => {
                        const p = el.parameters || {};
                        const lvlName = p['Level'] || p['Host'] || el.level_name || '';
                        const rawElev = p['Elevation from Level'] || p['Offset from Host'] || '';
                        const offsetStr = rawElev ? ` • Elev: +${rawElev} mm` : '';
                        const levelStr = lvlName ? ` • Lvl: ${lvlName.replace('Level : ', '')}` : '';
                        return `
                            <div class="selection-item" onclick="selectElementInRevit(${el.id})">
                                <div class="selection-id-row">
                                    <span class="selection-id">🎯 #${el.id || el}</span>
                                    <span class="selection-cat">${el.category || 'Element'}</span>
                                </div>
                                <div class="selection-meta">${el.family || el.name || 'Component'}${levelStr}${offsetStr}</div>
                            </div>
                        `;
                    }).join('');

                    if (data.selection && data.selection.rooms && data.selection.rooms.length > 0) {
                        data.selection.rooms.forEach(rm => {
                            const rmLvl = rm.ref_level_name ? ` (Lvl ${rm.ref_level_name})` : '';
                            const flStr = (rm.rel_z_min_mm !== undefined && rm.rel_z_min_mm !== null) ? `Floor: ${rm.rel_z_min_mm >= 0 ? '+' : ''}${rm.rel_z_min_mm} mm` : '';
                            const clStr = (rm.rel_z_max_mm !== undefined && rm.rel_z_max_mm !== null) ? `Ceiling: ${rm.rel_z_max_mm >= 0 ? '+' : ''}${rm.rel_z_max_mm} mm` : '';
                            const elevDetails = (flStr || clStr) ? ` • ${flStr} / ${clStr}` : '';
                            selContainer.innerHTML += `
                                <div class="selection-item" onclick="selectElementInRevit(${rm.id})" style="border-left: 3px solid #3b82f6; background: rgba(59, 130, 246, 0.08);">
                                    <div class="selection-id-row">
                                        <span class="selection-id">🏠 Room #${rm.id}</span>
                                        <span class="selection-cat" style="color: #60a5fa;">${rm.number ? rm.number + ' • ' : ''}${rm.name || 'Room'}</span>
                                    </div>
                                    <div class="selection-meta" style="color: #94a3b8;">H: ${rm.height_mm} mm${rmLvl}${elevDetails}</div>
                                </div>
                            `;
                        });
                    }

                    // Check hash for 3D update
                    const newHash = JSON.stringify(data.selection) + JSON.stringify(data.agent_context || {});
                    if (newHash !== last3DHash) {
                        last3DHash = newHash;
                        update3DScene(selElements, docTitle, data.selection, data.agent_context);
                    }
                } else {
                    document.getElementById('sel-count').textContent = '0 items';
                    selContainer.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 1.5rem 0;">No active selection</div>';
                }

                // Update History Reel
                if (data.history && data.history.length > 0) {
                    const historyReel = document.getElementById('history-reel');
                    historyReel.innerHTML = data.history.map(item => `
                        <div class="history-thumb" onclick="openModal('/api/image/file?path=${encodeURIComponent(item.filename)}')">
                            <img src="/api/image/file?path=${encodeURIComponent(item.filename)}" loading="lazy">
                            <div class="history-thumb-time">${item.time}</div>
                        </div>
                    `).join('');
                }

                document.getElementById('last-sync-time').textContent = 'Sync: ' + new Date().toLocaleTimeString();

                const chatTab = document.getElementById('tab-view-chat');
                if (chatTab && chatTab.classList.contains('active')) {
                    fetchChatHistory(false);
                }

            } catch (err) {
                console.error("Dashboard refresh error:", err);
            }
        }

        async function selectElementInRevit(elementId) {
            if (!elementId) return;
            try {
                const toast = document.createElement('div');
                toast.style.position = 'fixed';
                toast.style.bottom = '20px';
                toast.style.right = '20px';
                toast.style.background = '#8b5cf6';
                toast.style.color = '#fff';
                toast.style.padding = '8px 16px';
                toast.style.borderRadius = '6px';
                toast.style.fontFamily = 'var(--font-mono)';
                toast.style.fontSize = '0.8rem';
                toast.style.zIndex = '9999';
                toast.style.boxShadow = '0 4px 12px rgba(0,0,0,0.5)';
                toast.textContent = `Selecting #${elementId} in Revit...`;
                document.body.appendChild(toast);

                const res = await fetch(`/api/select_element?id=${elementId}`);
                if (res.ok) {
                    toast.style.background = '#10b981';
                    toast.textContent = `Selected #${elementId} in Revit!`;
                } else {
                    toast.style.background = '#f43f5e';
                    toast.textContent = `Failed to select #${elementId}`;
                }
                setTimeout(() => toast.remove(), 2500);
            } catch (err) {
                console.error("selectElementInRevit error:", err);
            }
        }

        // Initialize 3D Viewer and Refresh Poller
        window.addEventListener('DOMContentLoaded', () => {
            init3DViewer();
            refreshDashboard();
            setInterval(refreshDashboard, 1000);
        });

        // ================= Sprinkler Audit Table Logic =================
        let allAuditData = [];

        async function fetchAuditTableData() {
            if (allAuditData.length > 0) return;
            try {
                const res = await fetch('/api/audit_table');
                if (res.ok) {
                    allAuditData = await res.json();
                    renderAuditTable();
                }
            } catch (err) {
                console.error('Failed to fetch audit table:', err);
            }
        }

        function applyTableFilters() {
            renderAuditTable();
        }

        let sortColumn = 'level';
        let sortDirection = 1; // 1 = asc, -1 = desc

        function sortTableBy(col) {
            if (sortColumn === col) {
                sortDirection = -sortDirection;
            } else {
                sortColumn = col;
                sortDirection = 1;
            }

            // Update icons
            ['id', 'level', 'type', 'front', 'left', 'right', 'status', 'approval'].forEach(c => {
                const el = document.getElementById('sort-icon-' + c);
                if (el) {
                    if (c === sortColumn) {
                        el.textContent = sortDirection === 1 ? '▲' : '▼';
                        el.style.color = '#06b6d4';
                    } else {
                        el.textContent = '↕';
                        el.style.color = '#94a3b8';
                    }
                }
            });

            renderAuditTable();
        }

        async function setApproval(elemId, status) {
            try {
                // Update locally immediately for instantaneous UI response
                const it = allAuditData.find(x => x.id === elemId);
                if (it) {
                    it.approval_status = status;
                    it.approval_time = new Date().toLocaleTimeString();
                }
                renderAuditTable();

                const res = await fetch('/api/set_approval', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id: elemId, status: status })
                });
                if (res.ok) {
                    const toast = document.createElement('div');
                    toast.style.position = 'fixed';
                    toast.style.bottom = '20px';
                    toast.style.right = '20px';
                    toast.style.background = status === 'APPROVED' ? '#10b981' : (status === 'REJECTED' ? '#f43f5e' : '#64748b');
                    toast.style.color = '#fff';
                    toast.style.padding = '8px 16px';
                    toast.style.borderRadius = '6px';
                    toast.style.fontFamily = 'monospace';
                    toast.style.fontSize = '0.8rem';
                    toast.style.zIndex = '9999';
                    toast.textContent = `Спринклер #${elemId}: ${status === 'APPROVED' ? 'ОДОБРЕНО ЧЕЛОВЕКОМ' : (status === 'REJECTED' ? 'ОТКЛОНЕНО' : 'СБРОШЕНО')}`;
                    document.body.appendChild(toast);
                    setTimeout(() => toast.remove(), 2500);
                }
            } catch (err) {
                console.error("Failed to set approval:", err);
            }
        }

        function renderAuditTable() {
            if (!allAuditData || allAuditData.length === 0) {
                fetchAuditTableData();
                return;
            }

            // Top toolbar / Global search
            const globalSearch = (document.getElementById('filter-search')?.value || '').toLowerCase().trim();

            // Header Filters
            const idFilter = (document.getElementById('th-filter-id')?.value || '').toLowerCase().trim();
            const lvlFilter = document.getElementById('th-filter-level')?.value || 'ALL';
            const typeFilter = document.getElementById('th-filter-type')?.value || 'ALL';
            const frontFilter = document.getElementById('th-filter-front')?.value || 'ALL';
            const leftFilter = document.getElementById('th-filter-left')?.value || 'ALL';
            const rightFilter = document.getElementById('th-filter-right')?.value || 'ALL';
            const statusFilter = document.getElementById('th-filter-status')?.value || 'ALL';
            const approvalFilter = document.getElementById('th-filter-approval')?.value || 'ALL';

            // Sync top selects if user used header or vice versa
            const topLvl = document.getElementById('filter-level');
            if (topLvl && lvlFilter !== 'ALL' && topLvl.value !== lvlFilter) topLvl.value = lvlFilter;
            const topStatus = document.getElementById('filter-status');
            if (topStatus && statusFilter !== 'ALL' && topStatus.value !== statusFilter) topStatus.value = statusFilter;

            const tbody = document.getElementById('sprinklers-table-body');
            if (!tbody) return;

            let filtered = allAuditData.filter(item => {
                // ID filter
                if (idFilter && !String(item.id).includes(idFilter)) return false;

                // Level filter
                if (lvlFilter !== 'ALL' && item.level !== lvlFilter) return false;

                // Type filter
                if (typeFilter !== 'ALL' && item.type !== typeFilter) return false;

                // Front filter
                if (frontFilter === 'FRONT_FAIL' && item.front_ok) return false;
                if (frontFilter === 'FRONT_OK' && !item.front_ok) return false;

                // Left filter
                if (leftFilter === 'GAP' && item.left_ok) return false;
                if (leftFilter === 'OK' && !item.left_ok) return false;

                // Right filter
                if (rightFilter === 'GAP' && item.right_ok) return false;
                if (rightFilter === 'OK' && !item.right_ok) return false;

                // Status filter (Calculation)
                if (statusFilter === 'FAIL' && item.all_ok) return false;
                if (statusFilter === 'OK' && !item.all_ok) return false;

                // Approval filter (Human)
                const appr = item.approval_status || 'PENDING';
                if (approvalFilter !== 'ALL' && appr !== approvalFilter) return false;

                // Global search
                if (globalSearch) {
                    const idStr = String(item.id);
                    const typeStr = (item.type || '').toLowerCase();
                    const lvlStr = (item.level || '').toLowerCase();
                    if (!idStr.includes(globalSearch) && !typeStr.includes(globalSearch) && !lvlStr.includes(globalSearch)) {
                        return false;
                    }
                }
                return true;
            });

            // Sorting
            filtered.sort((a, b) => {
                let vA, vB;
                if (sortColumn === 'id') {
                    vA = a.id;
                    vB = b.id;
                } else if (sortColumn === 'level') {
                    vA = a.level;
                    vB = b.level;
                } else if (sortColumn === 'type') {
                    vA = a.type;
                    vB = b.type;
                } else if (sortColumn === 'front') {
                    vA = a.front_dist || 0;
                    vB = b.front_dist || 0;
                } else if (sortColumn === 'left') {
                    vA = a.left_ok ? 1 : 0;
                    vB = b.left_ok ? 1 : 0;
                } else if (sortColumn === 'right') {
                    vA = a.right_ok ? 1 : 0;
                    vB = b.right_ok ? 1 : 0;
                } else if (sortColumn === 'status') {
                    vA = a.all_ok ? 1 : 0;
                    vB = b.all_ok ? 1 : 0;
                } else if (sortColumn === 'approval') {
                    vA = a.approval_status || 'PENDING';
                    vB = b.approval_status || 'PENDING';
                }
                if (vA < vB) return -sortDirection;
                if (vA > vB) return sortDirection;
                return 0;
            });

            const approvedCount = allAuditData.filter(x => x.approval_status === 'APPROVED').length;
            const rejectedCount = allAuditData.filter(x => x.approval_status === 'REJECTED').length;

            document.getElementById('table-badge-summary').textContent = 
                'Показано: ' + filtered.length + ' из ' + allAuditData.length + 
                ' (Ошибок: ' + allAuditData.filter(x => !x.all_ok).length + 
                ' | Одобрено человеком: ' + approvedCount + (rejectedCount ? ' | Отклонено: ' + rejectedCount : '') + ')';

            tbody.innerHTML = filtered.map(item => {
                const isFail = !item.all_ok;
                const frontFail = !item.front_ok;
                const rowBg = isFail ? 'background: rgba(244, 63, 94, 0.05);' : '';
                const badge = isFail 
                    ? '<span style="background: rgba(244, 63, 94, 0.2); color: #f43f5e; border: 1px solid rgba(244,63,94,0.3); padding: 2px 8px; border-radius: 4px; font-weight: 600;">FAIL</span>'
                    : '<span style="background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid rgba(16,185,129,0.3); padding: 2px 8px; border-radius: 4px; font-weight: 600;">OK</span>';

                let frontDesc = '';
                if (item.front_dist) {
                    if (frontFail) {
                        frontDesc = '<span style="color: #f43f5e; font-weight: 600;">🚨 ' + item.front_dist + ' мм > ' + item.max_reach + ' мм</span>';
                    } else {
                        frontDesc = '<span style="color: #10b981;">✓ ' + item.front_dist + ' мм / ' + item.max_reach + ' мм</span>';
                    }
                } else {
                    frontDesc = '<span style="color: #94a3b8;">--</span>';
                }

                const leftDesc = item.left_ok 
                    ? '<span style="color: #cbd5e1;">' + (item.left_status || 'OK') + '</span>'
                    : '<span style="color: #f59e0b; font-weight: 500;">⚠️ ' + (item.left_status || 'Разрыв') + '</span>';

                const rightDesc = item.right_ok 
                    ? '<span style="color: #cbd5e1;">' + (item.right_status || 'OK') + '</span>'
                    : '<span style="color: #f59e0b; font-weight: 500;">⚠️ ' + (item.right_status || 'Разрыв') + '</span>';

                // Human Review Button / Dropdown
                const apprStatus = item.approval_status || 'PENDING';
                let apprColor = '#64748b';
                let apprBg = 'rgba(100, 116, 139, 0.15)';
                let apprBorder = 'rgba(100, 116, 139, 0.3)';
                if (apprStatus === 'APPROVED') {
                    apprColor = '#10b981';
                    apprBg = 'rgba(16, 185, 129, 0.2)';
                    apprBorder = 'rgba(16, 185, 129, 0.4)';
                } else if (apprStatus === 'REJECTED') {
                    apprColor = '#f43f5e';
                    apprBg = 'rgba(244, 63, 94, 0.2)';
                    apprBorder = 'rgba(244, 63, 94, 0.4)';
                }

                const approvalControl = `
                    <div style="display: flex; gap: 4px; align-items: center; justify-content: center;" onclick="event.stopPropagation()">
                        <select onchange="setApproval(${item.id}, this.value)" style="background: ${apprBg}; color: ${apprColor}; border: 1px solid ${apprBorder}; border-radius: 4px; padding: 2px 4px; font-size: 0.72rem; font-weight: 600; cursor: pointer;">
                            <option value="PENDING" ${apprStatus === 'PENDING' ? 'selected' : ''}>⏳ Проверка</option>
                            <option value="APPROVED" ${apprStatus === 'APPROVED' ? 'selected' : ''}>✅ Одобрен</option>
                            <option value="REJECTED" ${apprStatus === 'REJECTED' ? 'selected' : ''}>❌ Отклонён</option>
                        </select>
                    </div>
                `;

                return `
                    <tr style="border-bottom: 1px solid #23293d; cursor: pointer; transition: background 0.15s ease; ${rowBg}" 
                        onmouseover="this.style.background='#1e2333'" 
                        onmouseout="this.style.background='${isFail ? 'rgba(244, 63, 94, 0.05)' : 'transparent'}'"
                        onclick="selectElementInRevit(${item.id})">
                        <td style="padding: 8px 12px; font-family: monospace; color: #06b6d4; font-weight: 600;">🎯 #${item.id}</td>
                        <td style="padding: 8px 12px; font-family: monospace; font-weight: 600;">${item.level}</td>
                        <td style="padding: 8px 12px; color: #e2e8f0;">${item.type}</td>
                        <td style="padding: 8px 12px; font-family: monospace;">${frontDesc}</td>
                        <td style="padding: 8px 12px; font-size: 0.75rem;">${leftDesc}</td>
                        <td style="padding: 8px 12px; font-size: 0.75rem;">${rightDesc}</td>
                        <td style="padding: 8px 12px; text-align: center;">${badge}</td>
                        <td style="padding: 8px 12px; text-align: center;">${approvalControl}</td>
                    </tr>
                `;
            }).join('');
        }

        // ================= Antigravity Chat & Interaction Logic =================
        let isSendingPrompt = false;
        let lastChatHash = '';
        let activeChatPollingInterval = null;
        let pendingOptimisticPrompts = [];
        window.currentConversationId = '';

        function applyQuickPrompt(promptText) {
            const ta = document.getElementById('chat-textarea');
            if (ta) {
                ta.value = promptText;
                ta.focus();
            }
            sendChatFromInput();
        }

        async function sendChatFromInput() {
            const ta = document.getElementById('chat-textarea');
            if (!ta) return;
            const text = ta.value.trim();
            if (!text || isSendingPrompt) return;

            ta.value = '';
            await dispatchPromptToAntigravity(text);
        }

        function handleChatKeyDown(event) {
            if ((event.key === 'Enter' || event.keyCode === 13) && !event.shiftKey) {
                event.preventDefault();
                sendChatFromInput();
            }
        }

        function clearChatInput() {
            const ta = document.getElementById('chat-textarea');
            if (ta) ta.value = '';
        }

        async function sendQuickDockPrompt() {
            const input = document.getElementById('quick-dock-input');
            if (!input) return;
            const text = input.value.trim();
            if (!text || isSendingPrompt) return;

            input.value = '';
            switchTab('chat');
            setTimeout(() => {
                dispatchPromptToAntigravity(text);
            }, 60);
        }

        function handleQuickDockKeyDown(event) {
            if (event.key === 'Enter' || event.keyCode === 13) {
                event.preventDefault();
                sendQuickDockPrompt();
            }
        }

        async function dispatchPromptToAntigravity(promptText) {
            isSendingPrompt = true;
            const sendBtn = document.getElementById('btn-chat-send');
            const sendIcon = document.getElementById('chat-send-icon');
            const sendText = document.getElementById('chat-send-text');
            const feedback = document.getElementById('chat-feedback-msg');

            if (sendBtn) sendBtn.disabled = true;
            if (sendIcon) sendIcon.innerText = '⏳';
            if (sendText) sendText.innerText = 'Sending...';
            if (feedback) {
                feedback.innerText = 'Transmitting to Antigravity...';
                feedback.style.color = '#a78bfa';
            }

            appendOptimisticUserMessage(promptText);

            const safetyTimeout = setTimeout(() => {
                isSendingPrompt = false;
                if (sendBtn) sendBtn.disabled = false;
                if (sendIcon) sendIcon.innerText = '🚀';
                if (sendText) sendText.innerText = 'Send Prompt';
            }, 10000);

            try {
                const resp = await fetch('/api/send_prompt', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        prompt: promptText,
                        conversation_id: window.currentConversationId || ''
                    })
                });
                const res = await resp.json();
                if (res.success) {
                    if (res.conversation_id) {
                        window.currentConversationId = res.conversation_id;
                    }
                    if (feedback) {
                        feedback.innerText = 'Prompt delivered. Antigravity is processing.';
                        feedback.style.color = '#10b981';
                    }
                    startAggressiveChatPolling();
                } else {
                    if (feedback) {
                        feedback.innerText = 'Error: ' + (res.error || res.message || 'Failed to send');
                        feedback.style.color = '#f43f5e';
                    }
                }
            } catch (e) {
                if (feedback) {
                    feedback.innerText = 'Network error sending prompt';
                    feedback.style.color = '#f43f5e';
                }
            } finally {
                clearTimeout(safetyTimeout);
                isSendingPrompt = false;
                if (sendBtn) sendBtn.disabled = false;
                if (sendIcon) sendIcon.innerText = '🚀';
                if (sendText) sendText.innerText = 'Send Prompt';
                setTimeout(() => {
                    if (feedback && feedback.innerText.includes('delivered')) {
                        feedback.innerText = '';
                    }
                }, 5000);
            }
        }

        function startAggressiveChatPolling() {
            if (activeChatPollingInterval) clearInterval(activeChatPollingInterval);
            let pollsLeft = 20;
            activeChatPollingInterval = setInterval(async () => {
                pollsLeft--;
                await fetchChatHistory(false);
                if (pollsLeft <= 0) {
                    clearInterval(activeChatPollingInterval);
                    activeChatPollingInterval = null;
                }
            }, 1000);
        }

        function appendOptimisticUserMessage(text) {
            const container = document.getElementById('chat-messages-container');
            if (!container) return;

            const now = new Date();
            const timeStr = now.toTimeString().split(' ')[0];
            pendingOptimisticPrompts.push({
                text: text,
                timeStr: timeStr,
                timestamp: now.toISOString()
            });

            const placeholder = document.getElementById('chat-loading-placeholder');
            if (placeholder) placeholder.remove();

            const row = document.createElement('div');
            row.className = 'chat-msg-row user-row optimistic-user-row';

            row.innerHTML = `
                <div class="chat-msg-bubble">
                    <div class="chat-msg-meta">
                        <span style="color: #fde68a; font-weight: 700;">YOU</span>
                        <span>•</span>
                        <span>${timeStr}</span>
                        <span>•</span>
                        <span style="color: #67e8f9;">Sending...</span>
                    </div>
                    <div class="chat-msg-body">
                        ${renderMarkdown(text)}
                    </div>
                </div>
            `;
            container.appendChild(row);

            if (!document.getElementById('chat-thinking-row')) {
                const thinkRow = document.createElement('div');
                thinkRow.id = 'chat-thinking-row';
                thinkRow.className = 'chat-msg-row assistant-row';
                thinkRow.innerHTML = `
                    <div class="chat-thinking-indicator">
                        <div class="thinking-dots">
                            <div class="thinking-dot"></div>
                            <div class="thinking-dot"></div>
                            <div class="thinking-dot"></div>
                        </div>
                        <span>Antigravity is thinking & processing your request...</span>
                    </div>
                `;
                container.appendChild(thinkRow);
            }

            container.scrollTop = container.scrollHeight;
        }

        function renderMarkdown(md) {
            if (!md) return '';
            let out = md
                .split('&').join('&amp;')
                .split('<').join('&lt;')
                .split('>').join('&gt;');

            // Code blocks
            out = out.replace(new RegExp('```([\\s\\S]*?)```', 'g'), function(match, code) {
                return '<pre><code>' + code.trim() + '</code></pre>';
            });

            // Inline code
            out = out.replace(new RegExp('`([^`]+)`', 'g'), '<code>$1</code>');

            // Bold
            out = out.replace(new RegExp('\\*\\*([^*]+)\\*\\*', 'g'), '<strong>$1</strong>');

            // Italic
            out = out.replace(new RegExp('\\*([^*]+)\\*', 'g'), '<em>$1</em>');

            // Headers
            out = out.replace(/^### (.*$)/gim, '<div style="font-size: 0.95rem; font-weight: 700; color: #fff; margin: 8px 0 4px 0;">$1</div>');
            out = out.replace(/^## (.*$)/gim, '<div style="font-size: 1.05rem; font-weight: 700; color: #c4b5fd; margin: 10px 0 5px 0;">$1</div>');

            // Bullet points
            out = out.replace(/^\\s*[-*]\\s+(.*)$/gim, '<div style="display: flex; gap: 6px; margin: 2px 0;"><span style="color: #a78bfa;">&bull;</span><span>$1</span></div>');

            // Convert newlines to br outside pre
            const parts = out.split(/(<pre>[\\s\\S]*?<\\/pre>)/);
            for (let i = 0; i < parts.length; i += 2) {
                parts[i] = parts[i].split(String.fromCharCode(10)).join('<br>');
            }
            return parts.join('');
        }

        async function fetchChatHistory(forceScroll = false) {
            const container = document.getElementById('chat-messages-container');
            if (!container) return;

            try {
                const resp = await fetch('/api/chat_history');
                if (!resp.ok) return;
                const data = await resp.json();
                if (!data.success) return;

                const msgs = data.messages || [];
                const cid = data.conversation_id || '';
                if (cid) {
                    window.currentConversationId = cid;
                }
                const badge = document.getElementById('chat-conv-id-badge');
                if (badge && cid) {
                    badge.innerText = 'Session: ' + cid.substring(0, 8);
                    badge.title = 'Conversation ID: ' + cid;
                }

                // Filter out pending optimistic prompts that have now landed in msgs
                const serverTexts = new Set(msgs.map(m => (m.text || '').trim()));
                pendingOptimisticPrompts = pendingOptimisticPrompts.filter(p => !serverTexts.has(p.text.trim()));

                const newHash = JSON.stringify(msgs.map(m => (m.timestamp || '') + (m.text || '').length)) + JSON.stringify(pendingOptimisticPrompts);
                if (newHash === lastChatHash && !forceScroll) {
                    return;
                }
                lastChatHash = newHash;

                const isNearBottom = (container.scrollHeight - container.scrollTop - container.clientHeight) < 140;

                if (msgs.length === 0 && pendingOptimisticPrompts.length === 0) {
                    container.innerHTML = `
                        <div class="chat-empty-state" style="text-align: center; color: var(--text-dim); margin-top: 40px;">
                            <div style="font-size: 2rem; margin-bottom: 8px;">💬</div>
                            <div style="font-weight: 600; color: #fff; margin-bottom: 4px;">No messages in this session yet</div>
                            <div style="font-size: 0.8rem;">Type an instruction or question below to start collaborating with Antigravity!</div>
                        </div>
                    `;
                    return;
                }

                let html = '';
                for (const m of msgs) {
                    const isUser = m.role === 'user';
                    const roleName = isUser ? 'YOU' : 'ANTIGRAVITY';
                    const roleColor = isUser ? '#fde68a' : '#c4b5fd';
                    let tStr = m.timestamp || '';
                    if (tStr.includes('T')) {
                        tStr = tStr.split('T')[1].split('.')[0].replace('Z', '');
                    }

                    html += `
                        <div class="chat-msg-row ${isUser ? 'user-row' : 'assistant-row'}">
                            <div class="chat-msg-bubble">
                                <div class="chat-msg-meta">
                                    <span style="color: ${roleColor}; font-weight: 700;">${roleName}</span>
                                    <span>•</span>
                                    <span>${tStr}</span>
                                </div>
                                <div class="chat-msg-body">
                                    ${renderMarkdown(m.text)}
                                </div>
                            </div>
                        </div>
                    `;
                }

                // Render pending optimistic prompts that are still awaiting log persistence
                for (const op of pendingOptimisticPrompts) {
                    html += `
                        <div class="chat-msg-row user-row optimistic-user-row">
                            <div class="chat-msg-bubble">
                                <div class="chat-msg-meta">
                                    <span style="color: #fde68a; font-weight: 700;">YOU</span>
                                    <span>•</span>
                                    <span>${op.timeStr}</span>
                                    <span>•</span>
                                    <span style="color: #67e8f9;">Sending...</span>
                                </div>
                                <div class="chat-msg-body">
                                    ${renderMarkdown(op.text)}
                                </div>
                            </div>
                        </div>
                    `;
                }

                const lastMsg = msgs[msgs.length - 1];
                const isAgentBusy = window.currentAgentStatus === 'busy' || pendingOptimisticPrompts.length > 0 || (lastMsg && lastMsg.role === 'user');
                if (isAgentBusy) {
                    html += `
                        <div class="chat-msg-row assistant-row" id="chat-thinking-row">
                            <div class="chat-thinking-indicator">
                                <div class="thinking-dots">
                                    <div class="thinking-dot"></div>
                                    <div class="thinking-dot"></div>
                                    <div class="thinking-dot"></div>
                                </div>
                                <span>Antigravity is analyzing model & processing...</span>
                            </div>
                        </div>
                    `;
                }

                container.innerHTML = html;

                if (forceScroll || isNearBottom) {
                    container.scrollTop = container.scrollHeight;
                }
            } catch (e) {
                // silent
            }
        }
    </script>

    <!-- Global Floating Quick Prompt Dock -->
    <div class="quick-prompt-dock" id="quick-prompt-dock">
        <div class="quick-dock-inner">
            <span class="quick-dock-icon">⚡</span>
            <input type="text" id="quick-dock-input" placeholder="Ask Antigravity or type a command... (Enter to send)" onkeydown="handleQuickDockKeyDown(event)" />
            <button class="quick-dock-send-btn" id="btn-quick-dock-send" onclick="sendQuickDockPrompt()">
                <span>Send</span> ➔
            </button>
            <button class="quick-dock-expand-btn" onclick="switchTab('chat')" title="Open Antigravity Chat">💬</button>
        </div>
    </div>
</body>
</html>
"""

class DashboardHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/chat_history":
            qs = parse_qs(parsed.query)
            cid = qs.get("conversation_id", [""])[0] or None
            try:
                limit = int(qs.get("limit", [40])[0])
            except Exception:
                limit = 40
            state = self.get_full_state()
            port = state.get("bound_port") or 40001
            history = get_chat_history(conversation_id=cid, port=port, limit=limit)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(json.dumps(history, ensure_ascii=False).encode("utf-8"))
            return

        elif path == "/api/archived_projects":
            archived = load_manual_archived_projects()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "archived_projects": archived}, ensure_ascii=False).encode("utf-8"))
            return

        elif path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
            return

        elif path == "/api/audit_table":
            audit_file = os.path.join(WORKSPACE_DIR, "all_sidewall_audit.json")
            approvals_file = os.path.join(WORKSPACE_DIR, "manual_approvals.json")
            approvals = {}
            if os.path.exists(approvals_file):
                try:
                    with open(approvals_file, "r", encoding="utf-8") as af:
                        approvals = json.load(af)
                except Exception:
                    approvals = {}

            if os.path.exists(audit_file):
                with open(audit_file, "r", encoding="utf-8") as f:
                    audit_items = json.load(f)
                
                for item in audit_items:
                    eid_str = str(item.get("id"))
                    appr_info = approvals.get(eid_str)
                    if appr_info:
                        item["approval_status"] = appr_info.get("status", "PENDING")
                        item["approval_comment"] = appr_info.get("comment", "")
                        item["approval_time"] = appr_info.get("timestamp", "")
                    else:
                        item["approval_status"] = "PENDING"
                        item["approval_comment"] = ""
                        item["approval_time"] = ""

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(audit_items).encode("utf-8"))
                return
            self.send_response(404)
            self.end_headers()
            return

        elif path == "/api/open_folder":
            query = parse_qs(parsed.query)
            target = query.get("path", [""])[0]
            if target:
                try:
                    import subprocess
                    target = os.path.normpath(target)
                    if os.path.exists(target):
                        os.startfile(target)
                    else:
                        subprocess.Popen(["explorer.exe", target])
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, "opened": target}).encode("utf-8"))
                    return
                except Exception as ex:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(ex)}).encode("utf-8"))
                    return
            self.send_response(400)
            self.end_headers()
            return

        elif path == "/api/state":
            state = self.get_full_state()
            data_bytes = json.dumps(state).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data_bytes)
            return

        elif path == "/api/image/agent":
            img_path = os.path.join(WORKSPACE_DIR, "latest_agent_screenshot.png")
            if not os.path.exists(img_path):
                img_path = os.path.join(WORKSPACE_DIR, "latest_screenshot.png")
            self.serve_file(img_path)
            return

        elif path == "/api/image/user":
            img_path = os.path.join(WORKSPACE_DIR, "latest_user_snip.png")
            self.serve_file(img_path)
            return

        elif path == "/api/image/file":
            qs = parse_qs(parsed.query)
            fname = qs.get("path", [""])[0]
            if fname:
                clean_name = os.path.basename(fname)
                full_path = os.path.join(SCREENSHOTS_DIR, clean_name)
                self.serve_file(full_path)
                return
            self.send_response(404)
            self.end_headers()
            return

        elif path == "/api/select_element":
            qs = parse_qs(parsed.query)
            eid_str = qs.get("id", [""])[0]
            if eid_str and eid_str.isdigit():
                eid = int(eid_str)
                state = self.get_full_state()
                port = state.get("bound_port") or 40001
                import urllib.request
                sel_code = f"""
import System
from Autodesk.Revit.DB import ElementId
elem_list = System.Collections.Generic.List[ElementId]()
try:
    eid_val = System.Int64({eid})
    elem_list.Add(ElementId(eid_val))
except Exception:
    elem_list.Add(ElementId(int({eid})))
uidoc.Selection.SetElementIds(elem_list)
uidoc.ShowElements(elem_list)
response_data['selected_id'] = {eid}
"""
                try:
                    auth_token = get_auth_token_for_port(port)
                    req_headers = {"Content-Type": "application/json"}
                    if auth_token:
                        req_headers["Authorization"] = f"Bearer {auth_token}"
                    req_data = json.dumps({"code": sel_code}).encode("utf-8")
                    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/execute", data=req_data, headers=req_headers)
                    with urllib.request.urlopen(req, timeout=3.0) as resp:
                        res = json.loads(resp.read().decode("utf-8"))
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        self.wfile.write(json.dumps({"success": True, "selected_id": eid}).encode("utf-8"))
                        return
                except Exception as ex:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(ex)}).encode("utf-8"))
                    return
            self.send_response(400)
            self.end_headers()
            return

        elif path in ["/portfolio", "/acc", "/dashboard", "/acc_portfolio_dashboard.html"]:
            self.serve_file(os.path.join(WORKSPACE_DIR, "index.html"))
            return

        elif any(path.endswith(ext) for ext in [".js", ".json", ".csv", ".html"]):
            local_target = os.path.join(WORKSPACE_DIR, os.path.basename(path))
            if os.path.exists(local_target):
                self.serve_file(local_target)
                return
            self.send_response(404)
            self.end_headers()
            return

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/send_prompt":
            content_length = int(self.headers.get("Content-Length", 0))
            raw_bytes = self.rfile.read(content_length)
            try:
                post_body = raw_bytes.decode("utf-8")
            except Exception:
                try:
                    post_body = raw_bytes.decode("cp1251")
                except Exception:
                    post_body = raw_bytes.decode("utf-8", errors="replace")
            try:
                payload = json.loads(post_body)
                prompt_text = payload.get("prompt", "").strip()
                port = payload.get("port")
                target_conv_id = payload.get("conversation_id")
                if not port:
                    state = self.get_full_state()
                    port = state.get("bound_port") or 40001

                success, msg, conv_id = dispatch_antigravity_prompt(prompt_text, port=port, conv_id=target_conv_id)
                self.send_response(200 if success else 400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": success,
                    "message": msg,
                    "conversation_id": conv_id
                }, ensure_ascii=False).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

        elif path == "/api/set_approval":
            content_length = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_length).decode("utf-8")
            try:
                payload = json.loads(post_body)
                elem_id = str(payload.get("id"))
                status = payload.get("status", "PENDING")
                comment = payload.get("comment", "")
                
                approvals_file = os.path.join(WORKSPACE_DIR, "manual_approvals.json")
                approvals = {}
                if os.path.exists(approvals_file):
                    try:
                        with open(approvals_file, "r", encoding="utf-8") as f:
                            approvals = json.load(f)
                    except Exception:
                        approvals = {}
                
                approvals[elem_id] = {
                    "status": status,
                    "comment": comment,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                
                with open(approvals_file, "w", encoding="utf-8") as f:
                    json.dump(approvals, f, indent=2, ensure_ascii=False)
                    
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "approvals": approvals}).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

        elif path == "/api/archive_project":
            content_length = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_length).decode("utf-8")
            try:
                payload = json.loads(post_body)
                pid = str(payload.get("project_id", "")).strip()
                if not pid:
                    self.send_response(400)
                    self.end_headers()
                    return
                archived = load_manual_archived_projects()
                now_str = datetime.now().isoformat()
                archived[pid] = {
                    "project_id": pid,
                    "project_name": payload.get("project_name", ""),
                    "archived_at": payload.get("archived_at", now_str),
                    "archived_by": payload.get("archived_by", "Unknown User"),
                    "archived_by_email": payload.get("archived_by_email", "")
                }
                action_entry = {
                    "action": "ARCHIVE",
                    "project_id": pid,
                    "project_name": payload.get("project_name", ""),
                    "timestamp": now_str,
                    "user": payload.get("archived_by", "Unknown User"),
                    "email": payload.get("archived_by_email", "")
                }
                save_manual_archived_projects(archived, action_entry)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "project_id": pid, "archived_projects": archived}, ensure_ascii=False).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

        elif path == "/api/unarchive_project":
            content_length = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_length).decode("utf-8")
            try:
                payload = json.loads(post_body)
                pid = str(payload.get("project_id", "")).strip()
                if not pid:
                    self.send_response(400)
                    self.end_headers()
                    return
                archived = load_manual_archived_projects()
                p_name = ""
                if pid in archived:
                    p_name = archived[pid].get("project_name", "")
                    del archived[pid]
                now_str = datetime.now().isoformat()
                action_entry = {
                    "action": "RESTORE",
                    "project_id": pid,
                    "project_name": p_name or payload.get("project_name", ""),
                    "timestamp": now_str,
                    "user": payload.get("unarchived_by", "Unknown User"),
                    "email": payload.get("unarchived_by_email", "")
                }
                save_manual_archived_projects(archived, action_entry)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "project_id": pid, "archived_projects": archived}, ensure_ascii=False).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

        self.send_response(404)
        self.end_headers()

    def serve_file(self, file_path):
        if os.path.exists(file_path):
            try:
                mime_type, _ = mimetypes.guess_type(file_path)
                if not mime_type:
                    mime_type = "image/png"
                with open(file_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                self.wfile.write(content)
                return
            except Exception:
                pass
        self.send_response(404)
        self.end_headers()

    def get_full_state(self):
        state = {
            "status": {},
            "agent_meta": {},
            "user_meta": {},
            "selection": {},
            "agent_context": {},
            "bound_port": None,
            "active_model": None,
            "history": []
        }

        # Status
        status_file = os.path.join(WORKSPACE_DIR, "antigravity_status.json")
        if os.path.exists(status_file):
            try:
                with open(status_file, "r", encoding="utf-8") as f:
                    state["status"] = json.load(f)
            except Exception:
                pass

        # Agent Context & Intent
        ctx_file = os.path.join(WORKSPACE_DIR, "agent_context_intent.json")
        if os.path.exists(ctx_file):
            try:
                with open(ctx_file, "r", encoding="utf-8") as f:
                    state["agent_context"] = json.load(f)
            except Exception:
                pass

        # Agent Meta
        agent_json = os.path.join(WORKSPACE_DIR, "latest_agent_screenshot.json")
        if os.path.exists(agent_json):
            try:
                with open(agent_json, "r", encoding="utf-8") as f:
                    state["agent_meta"] = json.load(f)
                    if state["agent_meta"].get("doc_title"):
                        state["active_model"] = state["agent_meta"]["doc_title"]
            except Exception:
                pass

        # User Snip Meta
        user_json = os.path.join(WORKSPACE_DIR, "latest_user_snip.json")
        if os.path.exists(user_json):
            try:
                with open(user_json, "r", encoding="utf-8") as f:
                    state["user_meta"] = json.load(f)
            except Exception:
                pass

        # Session Binding
        binding_json = os.path.join(WORKSPACE_DIR, "session_binding.json")
        if os.path.exists(binding_json):
            try:
                with open(binding_json, "r", encoding="utf-8") as f:
                    bdata = json.load(f)
                    state["bound_port"] = bdata.get("bound_port")
                    if bdata.get("bound_doc"):
                        state["active_model"] = bdata["bound_doc"]
            except Exception:
                pass

        # Latest Selection
        sel_json = os.path.join(WORKSPACE_DIR, "latest_selection.json")
        if os.path.exists(sel_json):
            try:
                with open(sel_json, "r", encoding="utf-8") as f:
                    sel_data = json.load(f)

                # Cache enriched selection by timestamp to avoid hitting Revit on every 1-second browser poll!
                global _CACHED_SEL_TS, _CACHED_SEL_DATA
                sel_ts = sel_data.get("timestamp", "")
                if sel_ts and sel_ts == _CACHED_SEL_TS and _CACHED_SEL_DATA:
                    state["selection"] = _CACHED_SEL_DATA
                    return state

                raw_elems = sel_data.get("elements", [])
                if raw_elems:
                    eids = [e.get("id") for e in raw_elems if e.get("id") and not e.get("is_linked")]
                    if eids:
                        import urllib.request
                        port = state.get("bound_port") or 40001
                        
                        # 1. Geometry query
                        geom_code = f"""
import sys
reg_dir = r"c:\\Users\\user49\\.gemini\\antigravity\\scratch\\revit-mcp\\endpoints"
if reg_dir not in sys.path:
    sys.path.append(reg_dir)
import registry
res = registry.dispatch("get_geometry", doc, uidoc, {{"element_ids": {repr(eids)}}})
for k, v in res.items():
    response_data[k] = v
"""
                        try:
                            auth_token = get_auth_token_for_port(port)
                            req_headers = {"Content-Type": "application/json"}
                            if auth_token:
                                req_headers["Authorization"] = f"Bearer {auth_token}"
                            req_data = json.dumps({"code": geom_code}).encode("utf-8")
                            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/execute", data=req_data, headers=req_headers)
                            with urllib.request.urlopen(req, timeout=3.5) as resp:
                                g_res = json.loads(resp.read().decode("utf-8"))
                                g_data = g_res.get("data", g_res)
                                if g_data.get("elements"):
                                    geom_map = {g["id"]: g for g in g_data["elements"]}
                                    for el in raw_elems:
                                        eid = el.get("id")
                                        if eid in geom_map:
                                            g_info = geom_map[eid]
                                            el["connectors"] = g_info.get("connectors", [])
                                            el["orientation"] = g_info.get("orientation", {})
                                            if g_info.get("location_type") == "Point" and g_info.get("location"):
                                                el["location_mm"] = g_info["location"]
                                            elif g_info.get("location_type") == "Curve" and g_info.get("location"):
                                                el["curve_start_mm"] = g_info["location"].get("start_mm")
                                                el["curve_end_mm"] = g_info["location"].get("end_mm")
                        except Exception:
                            pass

                        # 2. Room boundaries query
                        room_code = f"""
from Autodesk.Revit.DB import FilteredElementCollector, RevitLinkInstance, SpatialElementBoundaryOptions, BuiltInCategory, BuiltInParameter, XYZ, ElementId
FEET_TO_MM = 304.8
rooms_out = []
try:
    elem_info = []
    for eid in {repr(eids)}:
        elem = doc.GetElement(ElementId(eid))
        if elem and elem.Location and hasattr(elem.Location, "Point"):
            lvl = doc.GetElement(elem.LevelId) if (hasattr(elem, "LevelId") and elem.LevelId != ElementId.InvalidElementId) else None
            lvl_name = lvl.Name if lvl else ""
            lvl_elev = round(lvl.Elevation * FEET_TO_MM, 1) if lvl else None
            elem_info.append({{"pt": elem.Location.Point, "level_name": lvl_name, "level_elev_mm": lvl_elev}})
            
    all_docs = [(doc, None)]
    for link in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        ldoc = link.GetLinkDocument()
        if ldoc:
            all_docs.append((ldoc, link.GetTotalTransform()))
            
    b_opt = SpatialElementBoundaryOptions()
    found_room_ids = set()
    
    for einfo in elem_info:
        pt = einfo["pt"]
        ref_lvl_name = einfo["level_name"]
        ref_lvl_elev = einfo["level_elev_mm"]
        for rdoc, tr in all_docs:
            q_pt = tr.Inverse.OfPoint(pt) if tr else pt
            room_candidates = list(FilteredElementCollector(rdoc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType())
            if not room_candidates:
                room_candidates = list(FilteredElementCollector(rdoc).OfCategory(BuiltInCategory.OST_MEPSpaces).WhereElementIsNotElementType())
                
            matched_rm = None
            offsets = [
                XYZ(0, 0, 0),
                XYZ(0, 0, -1.64),
                XYZ(0, 0, -3.28),
                XYZ(0, 0, -4.92),
                XYZ(0, 0, -6.56),
                XYZ(0, 0, -8.2),
                XYZ(0.65, 0, -3.28),
                XYZ(-0.65, 0, -3.28),
                XYZ(0, 0.65, -3.28),
                XYZ(0, -0.65, -3.28),
                XYZ(1.3, 0, -3.28),
                XYZ(-1.3, 0, -3.28),
                XYZ(0, 1.3, -3.28),
                XYZ(0, -1.3, -3.28)
            ]
            for r in room_candidates:
                if r.Area > 0.01:
                    for off in offsets:
                        test_pt = XYZ(q_pt.X + off.X, q_pt.Y + off.Y, q_pt.Z + off.Z)
                        if r.IsPointInRoom(test_pt):
                            matched_rm = r
                            break
                    if matched_rm:
                        break
            
            if matched_rm:
                if matched_rm.Id.IntegerValue not in found_room_ids:
                    found_room_ids.add(matched_rm.Id.IntegerValue)
                    loops = []
                    for seg_list in matched_rm.GetBoundarySegments(b_opt):
                        loop_pts = []
                        for seg in seg_list:
                            c = seg.GetCurve()
                            p0 = tr.OfPoint(c.GetEndPoint(0)) if tr else c.GetEndPoint(0)
                            loop_pts.append([round(p0.X * FEET_TO_MM, 1), round(p0.Y * FEET_TO_MM, 1), round(p0.Z * FEET_TO_MM, 1)])
                        if loop_pts:
                            loops.append(loop_pts)
                    
                    bb = matched_rm.get_BoundingBox(None)
                    if bb and tr:
                        min_pt_host = tr.OfPoint(bb.Min)
                        max_pt_host = tr.OfPoint(bb.Max)
                        z_min = min_pt_host.Z * FEET_TO_MM
                        z_max_bb = max_pt_host.Z * FEET_TO_MM
                    elif bb:
                        z_min = bb.Min.Z * FEET_TO_MM
                        z_max_bb = bb.Max.Z * FEET_TO_MM
                    else:
                        z_min = pt.Z * FEET_TO_MM - 2750
                        z_max_bb = pt.Z * FEET_TO_MM

                    if not ref_lvl_name and matched_rm.Level:
                        ref_lvl_name = matched_rm.Level.Name
                        ref_lvl_elev = round(matched_rm.Level.Elevation * FEET_TO_MM, 1)
                    
                    matched_ceilings = []
                    # Compute room 2D bounding box
                    rm_x_coords = [p[0] for l in loops for p in l]
                    rm_y_coords = [p[1] for l in loops for p in l]
                    r_min_x = min(rm_x_coords) if rm_x_coords else (pt.X * FEET_TO_MM - 2000)
                    r_max_x = max(rm_x_coords) if rm_x_coords else (pt.X * FEET_TO_MM + 2000)
                    r_min_y = min(rm_y_coords) if rm_y_coords else (pt.Y * FEET_TO_MM - 2000)
                    r_max_y = max(rm_y_coords) if rm_y_coords else (pt.Y * FEET_TO_MM + 2000)
                    room_area_approx = max((r_max_x - r_min_x) * (r_max_y - r_min_y), 1.0)
                    
                    spk_x_mm = pt.X * FEET_TO_MM
                    spk_y_mm = pt.Y * FEET_TO_MM

                    overhead_z = None
                    for subdoc, sub_tr in all_docs:
                        for cl in FilteredElementCollector(subdoc).OfCategory(BuiltInCategory.OST_Ceilings).WhereElementIsNotElementType():
                            cl_bb = cl.get_BoundingBox(None)
                            if cl_bb:
                                c_pmin = sub_tr.OfPoint(cl_bb.Min) if sub_tr else cl_bb.Min
                                c_pmax = sub_tr.OfPoint(cl_bb.Max) if sub_tr else cl_bb.Max
                                cl_min_x = c_pmin.X * FEET_TO_MM
                                cl_max_x = c_pmax.X * FEET_TO_MM
                                cl_min_y = c_pmin.Y * FEET_TO_MM
                                cl_max_y = c_pmax.Y * FEET_TO_MM
                                cl_min_z = c_pmin.Z * FEET_TO_MM
                                cl_max_z = c_pmax.Z * FEET_TO_MM
                                if z_min + 1000 <= cl_min_z <= z_min + 4500:
                                    if overhead_z is None or cl_min_z < overhead_z:
                                        overhead_z = cl_min_z
                                    if not (cl_max_x < r_min_x or cl_min_x > r_max_x or cl_max_y < r_min_y or cl_min_y > r_max_y):
                                        inter_min_x = max(cl_min_x, r_min_x)
                                        inter_max_x = min(cl_max_x, r_max_x)
                                        inter_min_y = max(cl_min_y, r_min_y)
                                        inter_max_y = min(cl_max_y, r_max_y)
                                        inter_area = max(0.0, inter_max_x - inter_min_x) * max(0.0, inter_max_y - inter_min_y)
                                        coverage_ratio = round(inter_area / room_area_approx, 2)
                                        is_cornice = (coverage_ratio < 0.70)
                                        in_proj = (cl_min_x <= spk_x_mm <= cl_max_x and cl_min_y <= spk_y_mm <= cl_max_y)
                                        matched_ceilings.append({{
                                            "id": cl.Id.IntegerValue,
                                            "name": cl.Name,
                                            "z_elev_mm": round(cl_min_z, 1),
                                            "rel_z_mm": round(cl_min_z - ref_lvl_elev, 1) if ref_lvl_elev is not None else None,
                                            "coverage_ratio": coverage_ratio,
                                            "is_cornice": is_cornice,
                                            "sprinkler_in_projection": in_proj,
                                            "bbox_mm": {{
                                                "min": [round(inter_min_x, 1), round(inter_min_y, 1), round(cl_min_z, 1)],
                                                "max": [round(inter_max_x, 1), round(inter_max_y, 1), round(cl_max_z, 1)]
                                            }}
                                        }})
                                        
                        for fl in FilteredElementCollector(subdoc).OfCategory(BuiltInCategory.OST_Floors).WhereElementIsNotElementType():
                            fl_bb = fl.get_BoundingBox(None)
                            if fl_bb:
                                fl_min_z = (sub_tr.OfPoint(fl_bb.Min).Z if sub_tr else fl_bb.Min.Z) * FEET_TO_MM
                                if z_min + 1500 <= fl_min_z <= z_min + 5000:
                                    if overhead_z is None or fl_min_z < overhead_z:
                                        overhead_z = fl_min_z
                    
                    room_h_mm = (matched_rm.UnboundedHeight * FEET_TO_MM) if (hasattr(matched_rm, "UnboundedHeight") and matched_rm.UnboundedHeight > 1.0) else 2800.0
                    if overhead_z is None or overhead_z <= z_min + 1000:
                        overhead_z = z_min + room_h_mm
                    
                    height_mm = round(overhead_z - z_min, 1)
                    z_max = round(overhead_z, 1)

                    rel_z_min = round(z_min - ref_lvl_elev, 1) if ref_lvl_elev is not None else None
                    rel_z_max = round(z_max - ref_lvl_elev, 1) if ref_lvl_elev is not None else None
                    
                    r_name = matched_rm.get_Parameter(BuiltInParameter.ROOM_NAME).AsString() if matched_rm.get_Parameter(BuiltInParameter.ROOM_NAME) else matched_rm.Name
                    r_num = matched_rm.get_Parameter(BuiltInParameter.ROOM_NUMBER).AsString() if matched_rm.get_Parameter(BuiltInParameter.ROOM_NUMBER) else ""
                    
                    rooms_out.append({{
                        "id": matched_rm.Id.IntegerValue,
                        "name": str(r_name) if r_name else "Room",
                        "number": str(r_num) if r_num else "",
                        "loops_mm": loops,
                        "z_min_mm": round(z_min, 1),
                        "z_max_mm": round(z_max, 1),
                        "height_mm": height_mm,
                        "ref_level_name": ref_lvl_name,
                        "ref_level_elev_mm": ref_lvl_elev,
                        "rel_z_min_mm": rel_z_min,
                        "rel_z_max_mm": rel_z_max,
                        "ceilings": matched_ceilings
                    }})
                break
    response_data['rooms'] = rooms_out
except Exception as rx:
    response_data['room_err'] = str(rx)
"""
                        try:
                            auth_token = get_auth_token_for_port(port)
                            req_headers = {"Content-Type": "application/json"}
                            if auth_token:
                                req_headers["Authorization"] = f"Bearer {auth_token}"
                            req_rdata = json.dumps({"code": room_code}).encode("utf-8")
                            req_r = urllib.request.Request(f"http://127.0.0.1:{port}/api/execute", data=req_rdata, headers=req_headers)
                            with urllib.request.urlopen(req_r, timeout=3.5) as rresp:
                                r_res = json.loads(rresp.read().decode("utf-8"))
                                r_data = r_res.get("data", r_res)
                                if r_data.get("rooms"):
                                    sel_data["rooms"] = r_data["rooms"]
                        except Exception:
                            pass

                state["selection"] = sel_data
                _CACHED_SEL_TS = sel_ts
                _CACHED_SEL_DATA = sel_data
            except Exception:
                pass

        # History Reel (latest 15 screenshots)
        if os.path.exists(SCREENSHOTS_DIR):
            try:
                files = glob.glob(os.path.join(SCREENSHOTS_DIR, "*.png"))
                files.sort(key=os.path.getmtime, reverse=True)
                for f in files[:15]:
                    bname = os.path.basename(f)
                    t_str = ""
                    parts = bname.replace(".png", "").split("_")
                    if len(parts) >= 3:
                        raw_time = parts[-1]
                        if len(raw_time) == 6:
                            t_str = f"{raw_time[0:2]}:{raw_time[2:4]}:{raw_time[4:6]}"
                    if not t_str:
                        t_str = time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(f)))
                    state["history"].append({
                        "filename": bname,
                        "time": t_str
                    })
            except Exception:
                pass

        return state

    def log_message(self, format, *args):
        return


def start_server(port=PORT):
    from http.server import ThreadingHTTPServer
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer(("0.0.0.0", port), DashboardHandler)
    server.daemon_threads = True
    print(f"Revit MCP Live Visual & 3D Dashboard running at http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    start_server(PORT)
