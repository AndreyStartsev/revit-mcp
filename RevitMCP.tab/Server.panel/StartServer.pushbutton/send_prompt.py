# -*- coding: utf-8 -*-
"""
Antigravity Prompt Dispatcher
Discovers live language_server.exe parameters and dispatches user prompts from Revit HUD to Antigravity.
Supports strict 1-to-1 mapping between Revit instance (port) and Antigravity conversation.
"""
import os
import sys
import json
import subprocess
import re
import time

SAVE_DIR = r"C:\Users\user49\.gemini\antigravity\scratch\revit-mcp"
CONV_DIR = r"C:\Users\user49\.gemini\antigravity\conversations"
ENV_FILE = os.path.join(SAVE_DIR, "antigravity_env.json")
MAPPING_FILE = os.path.join(SAVE_DIR, "instance_conversation_mapping.json")
LS_EXE = r"C:\Users\user49\AppData\Local\Programs\antigravity\resources\bin\language_server.exe"

def discover_live_antigravity_env():
    """Dynamically queries running language_server.exe processes to obtain live port and csrf_token."""
    cmd = ["powershell", "-NoProfile", "-Command", 
           "Get-CimInstance Win32_Process -Filter \"Name like '%language_server%'\" | ForEach-Object { $_.ProcessId.ToString() + '|||' + $_.CommandLine }"]
    try:
        res = subprocess.check_output(cmd, text=True).strip().splitlines()
    except Exception:
        return None

    for line in res:
        if not line or "|||" not in line:
            continue
        parts = line.split("|||", 1)
        pid = int(parts[0].strip())
        cmdline = parts[1]
        
        m_csrf = re.search(r"--csrf_token\s+([\w\-]+)", cmdline)
        csrf_token = m_csrf.group(1) if m_csrf else ""
        
        try:
            net_out = subprocess.check_output(f"netstat -ano | findstr {pid}", shell=True, text=True)
            ports = re.findall(r"127\.0\.0\.1:(\d+)\s+0\.0\.0\.0:0\s+LISTENING", net_out)
            if not ports:
                ports = re.findall(r":(\d+)\s+.*LISTENING", net_out)
            ports = [int(p) for p in ports]
            ports.sort()
            if ports:
                # Return highest listening port
                return {
                    "ANTIGRAVITY_LS_ADDRESS": f"localhost:{ports[-1]}",
                    "ANTIGRAVITY_CSRF_TOKEN": csrf_token,
                    "pid": pid
                }
        except Exception:
            pass
    return None

def get_active_env(force_refresh=False):
    env_data = {}
    if os.path.exists(ENV_FILE) and not force_refresh:
        try:
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                env_data = json.load(f)
            if env_data.get("ANTIGRAVITY_LS_ADDRESS") and env_data.get("ANTIGRAVITY_CSRF_TOKEN"):
                return env_data
        except Exception:
            pass
            
    # Refresh with live process detection if missing or server restarted
    live_info = discover_live_antigravity_env()
    if live_info:
        env_data["ANTIGRAVITY_LS_ADDRESS"] = live_info["ANTIGRAVITY_LS_ADDRESS"]
        env_data["ANTIGRAVITY_CSRF_TOKEN"] = live_info["ANTIGRAVITY_CSRF_TOKEN"]
        try:
            if not os.path.exists(SAVE_DIR):
                os.makedirs(SAVE_DIR)
            with open(ENV_FILE, "w", encoding="utf-8") as f:
                json.dump(env_data, f, indent=2)
        except Exception:
            pass

    return env_data

def get_conversation_title(cid, log_path, doc=""):
    if not os.path.exists(log_path):
        return cid[:8]
        
    doc_name = doc or ""
    user_prompts = []
    
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "SPR_Rasko" in line: doc_name = "SPR_Rasko"
                elif "FP_BAR" in line: doc_name = "FP_BAR"
                
                if '"type":"USER_INPUT"' in line or '"type": "USER_INPUT"' in line:
                    try:
                        d = json.loads(line)
                        if d.get("type") == "USER_INPUT":
                            c = d.get("content", "")
                            if "<USER_REQUEST>" in c:
                                c = c.split("<USER_REQUEST>")[1].split("</USER_REQUEST>")[0].strip()
                            elif "<SYSTEM_MESSAGE>" in c or "not actually sent by the user" in c:
                                continue
                            clean = " ".join(c.replace("\n", " ").replace("\r", " ").replace("`", "").split())
                            if len(clean) >= 6 and clean.lower() not in ["пинг", "ping", "test", "понг", "да", "нет", "снова", "не сработало"]:
                                user_prompts.append(clean)
                    except:
                        pass
    except:
        pass
        
    chosen = ""
    if user_prompts:
        for p in reversed(user_prompts[-5:]):
            if len(p) > 15:
                chosen = p
                break
        if not chosen:
            chosen = user_prompts[-1]
            
    if not chosen:
        chosen = cid[:8]
        
    if len(chosen) > 38:
        chosen = chosen[:36] + "..."
        
    if doc_name and doc_name not in chosen:
        return f"{doc_name}: {chosen}"
    return chosen

def find_active_revit_conversations(doc_title=None):
    if not os.path.exists(CONV_DIR):
        return []
    brain_dir = r"C:\Users\user49\.gemini\antigravity\brain"
    import glob
    dbs = glob.glob(os.path.join(CONV_DIR, "*.db"))
    revit_list = []
    
    for db in dbs:
        cid = os.path.splitext(os.path.basename(db))[0]
        mtime = os.path.getmtime(db)
        wal = db + "-wal"
        if os.path.exists(wal):
            mtime = max(mtime, os.path.getmtime(wal))
            
        log_path = os.path.join(brain_dir, cid, ".system_generated", "logs", "transcript.jsonl")
        is_revit = False
        conv_doc = ""
        last_user_time = ""
        
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if "revit-mcp" in line or "revit_" in line or "Revit" in line or "SPR_Rasko" in line or "FP_BAR" in line or "ревит" in line:
                            is_revit = True
                        if "SPR_Rasko" in line: conv_doc = "SPR_Rasko"
                        elif "FP_BAR" in line: conv_doc = "FP_BAR"
                        if "USER_INPUT" in line:
                            try:
                                d = json.loads(line)
                                if d.get("type") == "USER_INPUT":
                                    last_user_time = d.get("created_at", "")
                            except:
                                pass
            except:
                pass
                
        if not is_revit and os.path.exists(MAPPING_FILE):
            try:
                with open(MAPPING_FILE, "r", encoding="utf-8") as f:
                    m = json.load(f)
                    if cid in m.get("conversations", {}):
                        is_revit = True
                        conv_doc = m["conversations"][cid].get("bound_doc", "")
            except:
                pass

        doc_matches = False
        if doc_title and conv_doc and doc_title.lower() in conv_doc.lower():
            doc_matches = True

        if is_revit:
            title = get_conversation_title(cid, log_path, conv_doc or doc_title)
            revit_list.append({
                "cid": cid,
                "mtime": mtime,
                "user_time": last_user_time,
                "doc": conv_doc,
                "doc_matches": doc_matches,
                "title": title
            })
            
    # Sort with document match priority, then most recent user interaction
    if doc_title:
        revit_list.sort(key=lambda x: (1 if x.get("doc_matches") else 0, x["user_time"] or "", x["mtime"]), reverse=True)
    else:
        revit_list.sort(key=lambda x: (x["user_time"] or "", x["mtime"]), reverse=True)
    return revit_list

def get_target_conversation_id(env_data, port=None, doc_title=None):
    if port and os.path.exists(MAPPING_FILE):
        try:
            with open(MAPPING_FILE, "r", encoding="utf-8") as f:
                mapping = json.load(f)
                port_info = mapping.get("ports", {}).get(str(port))
                if port_info and port_info.get("conversation_id"):
                    cached_doc = port_info.get("doc_title", "")
                    if not doc_title or not cached_doc or doc_title.lower() in cached_doc.lower() or cached_doc.lower() in doc_title.lower():
                        return port_info["conversation_id"]
        except Exception:
            pass

    revit_convs = find_active_revit_conversations(doc_title=doc_title)
    if revit_convs:
        cid = revit_convs[0]["cid"]
        if port:
            try:
                mapping = {"ports": {}, "conversations": {}}
                if os.path.exists(MAPPING_FILE):
                    with open(MAPPING_FILE, "r", encoding="utf-8") as f:
                        mapping = json.load(f)
                if not mapping.get("ports"): mapping["ports"] = {}
                if not mapping.get("conversations"): mapping["conversations"] = {}
                mapping["ports"][str(port)] = {"conversation_id": cid, "doc_title": doc_title or "", "updated_at": time.time()}
                mapping["conversations"][cid] = {"bound_port": int(port), "bound_doc": doc_title or "", "updated_at": time.time()}
                with open(MAPPING_FILE, "w", encoding="utf-8") as f:
                    json.dump(mapping, f, indent=2)
            except Exception:
                pass
        return cid

    return env_data.get("ANTIGRAVITY_CONVERSATION_ID")

def send_prompt(prompt_text, port=None, doc_title=None, conv_id=None):
    if not prompt_text:
        return False, "Prompt is empty"

    env_data = get_active_env(force_refresh=False)
    if not conv_id:
        conv_id = get_target_conversation_id(env_data, port=port, doc_title=doc_title)

    if not os.path.exists(LS_EXE):
        return False, f"language_server.exe not found at {LS_EXE}"

    my_env = os.environ.copy()
    my_env.update(env_data)

    if conv_id:
        cmd = [LS_EXE, "agentapi", "send-message", conv_id, prompt_text]
    else:
        cmd = [LS_EXE, "agentapi", "new-conversation", prompt_text]

    try:
        p = subprocess.run(
            cmd,
            env=my_env,
            capture_output=True,
            text=True,
            encoding="utf-8"
        )
        if p.returncode == 0:
            return True, "OK"
        else:
            # Retry once with refreshed live env
            env_data = get_active_env(force_refresh=True)
            my_env = os.environ.copy()
            my_env.update(env_data)
            p = subprocess.run(
                cmd,
                env=my_env,
                capture_output=True,
                text=True,
                encoding="utf-8"
            )
            if p.returncode == 0:
                return True, "OK"
            err_msg = (p.stderr or p.stdout or f"Exit code {p.returncode}").strip()
            return False, err_msg
    except Exception as ex:
        return False, str(ex)

def main():
    prompt_text = ""
    prompt_file = os.path.join(SAVE_DIR, "pending_prompt.txt")
    port = None
    doc_name = None
    explicit_conv = None
    
    args = sys.argv[1:]
    clean_args = []
    i = 0
    while i < len(args):
        if args[i] == "--port" and i + 1 < len(args):
            try: port = int(args[i+1])
            except: pass
            i += 2
        elif args[i] == "--doc" and i + 1 < len(args):
            doc_name = args[i+1]
            i += 2
        elif args[i] == "--conv" and i + 1 < len(args):
            explicit_conv = args[i+1]
            i += 2
        else:
            clean_args.append(args[i])
            i += 1

    if clean_args and os.path.exists(clean_args[0]):
        with open(clean_args[0], "r", encoding="utf-8-sig") as f:
            prompt_text = f.read().strip()
    elif clean_args:
        prompt_text = " ".join(clean_args)
    elif os.path.exists(prompt_file):
        with open(prompt_file, "r", encoding="utf-8-sig") as f:
            prompt_text = f.read().strip()
        try:
            os.remove(prompt_file)
        except:
            pass
    else:
        prompt_text = sys.stdin.read().strip()

    success, msg = send_prompt(prompt_text, port=port, doc_title=doc_name, conv_id=explicit_conv)
    out = {"success": success, "message": msg}
    sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
