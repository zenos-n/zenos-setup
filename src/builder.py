import json
import re
import os
import subprocess
import shutil
import tempfile
from datetime import datetime

# --- behavior mapping config ---

BEHAVIORS = {
    "base": [
        (["legacy", "system", "nixos", "distroName"], '"ZenOS"'),
        (["legacy", "system", "nixos", "distroId"], '"zenos"'),
    ],
    "user": [
        (["users", "{username}", "legacy", "isNormalUser"], "true"),
        (["users", "{username}", "legacy", "initialPassword"], '"{password}"'),
        (["users", "{username}", "legacy", "extraGroups"], '[ "wheel" ]'),
        (["users", "{username}", "legacy", "home-manager", "home", "stateVersion"], '"26.05"'),
    ],
    "network": [
        (["legacy", "networking", "hostName"], '"{hostname}"'),
    ],
    "desktop_gnome": [
        (["desktops", "gnome", "enable"], "true"),
    ],
    "gnome_tiling": [
        (["desktops", "gnome", "extensions", "tiling", "enable"], "true"),
    ],
    "theme": [
        (["zenos", "theme", "darkMode"], "{dark_mode}"),
        (["zenos", "theme", "accent"], '"{accent}"'),
    ],
    "app": [
        (["programs", "{app_name}", "enable"], "true"),
    ],
    "app_gnome_theme": [
        (["programs", "{app_name}", "gnomeTheme"], "true"),
    ],
    "disko_auto": [
        (["disko", "devices", "disk", "main", "device"], '"{device}"'),
        (["zenos", "installer", "autoFormat"], "true"),
    ],
    "online_install": [
        (["zenos", "installer", "online", "enable"], "true"),
        (["zenos", "installer", "online", "flake"], '"{flake}"'),
        (["zenos", "installer", "online", "host"], '"{host}"'),
    ],
    "oobe_trigger": [
        (["zenos", "oobe", "enable"], "true"),
    ],
}

# --- merger logic ---

INDENT_SIZE = 2

def find_end_of_assignment(text, start_pos):
    depth = 0
    for i in range(start_pos, len(text)):
        if text[i] == '{': depth += 1
        elif text[i] == '}': depth -= 1
        if depth == 0 and text[i] == ';':
            return i
    return -1

def find_key_in_immediate_scope(key, text):
    escaped_key = re.escape(key)
    key_regex = re.compile(rf"(^|[\s\{{\n;\.])({escaped_key})(\s*[\.=;]|\s|$)")
    
    for match in key_regex.finditer(text):
        depth = 0
        match_start = match.start()
        for i in range(match_start):
            if text[i] == '{': depth += 1
            elif text[i] == '}': depth -= 1
        
        if depth == 0:
            k = match.group(2)
            actual_idx = match_start + match.group(0).find(k)
            return {"key": k, "index": actual_idx, "length": len(k)}
    return None

def strip_disko_config(text):
    """finds and removes any top-level disko attribute assignment."""
    match = find_key_in_immediate_scope("disko", text)
    if not match:
        return text
    
    end_idx = find_end_of_assignment(text, match["index"] + match["length"])
    if end_idx == -1:
        return text
        
    return text[:match["index"]] + text[end_idx + 1:]

def count_immediate_assignments(text):
    depth = 0
    count = 0
    in_assign = False
    for char in text:
        if char == '{': depth += 1
        elif char == '}': depth -= 1
        elif depth == 0:
            if re.match(r"[a-zA-Z0-9_<>\.-]", char) and not in_assign:
                count += 1
                in_assign = True
            elif char == ';':
                in_assign = False
    return count

def format_nix(text):
    depth = 0
    cleaned = re.sub(r';\s*;', ';', text)
    cleaned = re.sub(r'\{\s*;', '{', cleaned)
    cleaned = re.sub(r';\s*\}', ';}', cleaned)
    
    structured = cleaned.replace('{ ', '{\n').replace('}', '\n}').replace(';', ';\n')
    lines = [l.strip() for l in structured.split('\n') if l.strip() and l.strip() != ';']
    
    result = []
    for line in lines:
        if line.startswith('}') or line.startswith('};'):
            depth -= 1
        result.append(" " * (max(0, depth * INDENT_SIZE)) + line)
        if line.endswith('{'):
            depth += 1
            
    return "\n".join(result)

def merge_path(path_parts, rest, value="..."):
    if not path_parts: return rest
    key = path_parts[0]
    remaining = path_parts[1:]
    match = find_key_in_immediate_scope(key, rest)
    
    if not match:
        new_line = ".".join(path_parts) + f" = {value};"
        return rest + ("\n" if rest.strip() else "") + new_line

    k_end = match["index"] + match["length"]
    rem_rest = rest[k_end:]
    
    dot_match = re.match(r"^\s*\.([a-zA-Z0-9_<>-]+)", rem_rest)
    if dot_match:
        s_idx = find_end_of_assignment(rest, k_end)
        a_end = len(rest) if s_idx == -1 else s_idx + 1
        dot_pos = k_end + rem_rest.find('.')
        if dot_match.group(1) != (remaining[0] if remaining else None):
            existing_val = rest[dot_pos + 1 : s_idx].strip()
            new_assign = f"{key} = {{ {existing_val}; {'.'.join(remaining)} = {value}; }};"
            return rest[:match["index"]] + new_assign + rest[a_end:]
        inner_merged = merge_path(remaining, rest[dot_pos + 1 : a_end].strip(), value)
        return rest[:dot_pos + 1] + inner_merged + rest[a_end:]

    block_match = re.match(r"^\s*=\s*\{", rem_rest)
    if block_match:
        o_idx = k_end + rem_rest.find('{')
        c_idx = -1
        d = 0
        for i in range(o_idx, len(rest)):
            if rest[i] == '{': d += 1
            elif rest[i] == '}': d -= 1
            if d == 0:
                c_idx = i
                break
        if c_idx != -1:
            inner = rest[o_idx + 1 : c_idx]
            updated = merge_path(remaining, inner, value)
            if count_immediate_assignments(updated) == 1:
                return rest[:match["index"]] + f"{key}.{updated.strip()}" + rest[c_idx + 1:]
            return rest[:o_idx + 1] + updated + rest[c_idx:]

    semi_match = re.match(r"^\s*(=[^;]*)?;", rem_rest)
    if semi_match:
        if not remaining:
            existing = semi_match.group(1)
            if existing and "[" in existing and "[" in value:
                clean_old = existing.replace("=", "").replace("[", "").replace("]", "").strip()
                clean_new = value.replace("[", "").replace("]", "").strip()
                new_val = f"[ {clean_old} {clean_new} ]"
                s_idx = find_end_of_assignment(rest, k_end)
                return rest[:match["index"]] + f"{key} = {new_val};" + rest[s_idx + 1:]
            s_idx = find_end_of_assignment(rest, k_end)
            return rest[:match["index"]] + f"{key} = {value};" + rest[s_idx + 1:]
        s_idx = find_end_of_assignment(rest, k_end)
        return rest[:match["index"]] + f"{key}.{'.'.join(remaining)} = {value};" + rest[s_idx + 1:]
    return rest

# --- builder logic ---

def apply_behavior(config_str, behavior_key, **kwargs):
    for path_template, val_template in BEHAVIORS.get(behavior_key, []):
        path = [p.format(**kwargs) for p in path_template]
        val = val_template.format(**kwargs)
        config_str = merge_path(path, config_str, val)
    return config_str

def process_installer_payload(json_data):
    pages = {p["id"]: p for p in json_data.get("pages", [])}
    is_oobe = json_data.get("oobe", False)
    is_online = "online" in pages and pages["online"].get("method") == "online"
    
    # logic for downloading and patching existing config
    if is_online:
        o_page = pages["online"]
        flake_url = o_page["flake"]
        host_name = o_page["host"]
        
        tmp_dir = tempfile.mkdtemp()
        try:
            # git clone the flake
            subprocess.run(["git", "clone", flake_url, tmp_dir], check=True, capture_output=True)
            config_path = os.path.join(tmp_dir, "hosts", host_name, "host.zcfg")
            
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = f.read()
                
                # patch: remove existing disko, add new disko auto-setup
                config = strip_disko_config(config)
                if "disks" in pages:
                    d = pages["disks"]
                    if d.get("mode") == "auto":
                        config = apply_behavior(config, "disko_auto", device=f'/dev/{d["disks"][0]}')
                
                return f"# patched online config for {host_name}\n" + format_nix(config)
            else:
                # fallback if host file doesn't exist in the remote repo
                config = apply_behavior("", "online_install", flake=flake_url, host=host_name)
        finally:
            shutil.rmtree(tmp_dir)

    # --- default local install logic ---
    config = ""
    config = apply_behavior(config, "base")
    if "user" in pages:
        config = apply_behavior(config, "user", username=pages["user"]["username"], password=pages["user"]["password"])
    if "computer_name" in pages:
        config = apply_behavior(config, "network", hostname=pages["computer_name"]["hostname"])
    if "desktop" in pages:
        d = pages["desktop"]
        if d.get("install_de") and d.get("desktop_environment") == "gnome":
            config = apply_behavior(config, "desktop_gnome")
            if d.get("gnome_options", {}).get("tiling"):
                config = apply_behavior(config, "gnome_tiling")
    if "theme" in pages:
        t = pages["theme"]
        dark_val = str(t.get("dark_mode", True)).lower()
        config = apply_behavior(config, "theme", dark_mode=dark_val, accent=t.get("accent", "purple"))
    if "software" in pages:
        for app in pages["software"].get("apps", []):
            if not app.get("enabled"): continue
            config = apply_behavior(config, "app", app_name=app["app"])
            if "gnome_theme" in app.get("extraOptions", []):
                config = apply_behavior(config, "app_gnome_theme", app_name=app["app"])
    if "disks" in pages:
        d = pages["disks"]
        if d.get("mode") == "auto":
            config = apply_behavior(config, "disko_auto", device=f'/dev/{d["disks"][0]}')

    mode = "oobe" if is_oobe else ("long" if pages.get("disks", {}).get("mode") == "manual" else "short")
    metadata = f"# generated by zenos-installer\n# date: {datetime.now().strftime('%Y-%m-%d')}\n# mode: {mode}\n\n"
    return metadata + format_nix(config)

if __name__ == "__main__":
    # test payload for online mode
    test_payload = {
      "oobe": False,
      "pages": [
        {
          "id": "disks", "mode": "auto", "disks": ["sda"]
        },
        {
          "id": "online",
          "flake": "https://github.com/zenos-n/zenos-config", # assuming public for testing
          "host": "debug",
          "method": "online"
        }
      ]
    }
    # result = process_installer_payload(test_payload)
    # print(result)

