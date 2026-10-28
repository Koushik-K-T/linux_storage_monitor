from flask import Flask, jsonify, render_template, request, send_file
from pathlib import Path
from datetime import datetime
import csv
import io
import json
import platform
import re
import shutil
import subprocess
import time

APP_DIR = Path(__file__).resolve().parent
LOG_DIR = APP_DIR / "logs"
REPORT_DIR = APP_DIR / "reports"
CONFIG_PATH = APP_DIR / "config.json"
LOG_PATH = LOG_DIR / "storage_monitor.log"

LOG_DIR.mkdir(exist_ok=True)
REPORT_DIR.mkdir(exist_ok=True)

DEFAULT_CONFIG = {"warning": 80, "critical": 90}
INODE_BYTES = 256
if not CONFIG_PATH.exists():
    CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2))

app = Flask(__name__)

ALLOWED_COMMANDS = {
    "disk": (["df", "-P", "-T"], "Disk space (df -P -T, adaptive MB/GB values)"),
    "inode": (["df", "-i"], "Inode usage (df -i)"),
    "devices": (["lsblk", "-b", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS"], "Block devices (lsblk, adaptive MB/GB sizes)"),
    "mounts": (["findmnt", "-D"], "Mounted filesystems (findmnt -D)"),
    "root": (["df", "-P", "-T", "/"], "Root filesystem (df -P -T /, adaptive MB/GB values)"),
}

def run_command(args, timeout=8):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        output = (result.stdout or "") + (result.stderr or "")
        return {"ok": result.returncode == 0, "output": output.strip() or "(No output)", "returncode": result.returncode}
    except FileNotFoundError:
        return {"ok": False, "output": f"Command not found: {args[0]}", "returncode": 127}
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "Command timed out.", "returncode": 124}

def get_config():
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
        warning = int(cfg.get("warning", 80))
        critical = int(cfg.get("critical", 90))
        if not (1 <= warning < critical <= 100):
            raise ValueError()
        return {"warning": warning, "critical": critical}
    except Exception:
        return DEFAULT_CONFIG.copy()

def append_log(message):
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {message}\n")

def parse_disk_data():
    result = run_command(["df", "-P", "-T"])
    filesystems = []
    if not result["ok"]:
        return filesystems
    lines = result["output"].splitlines()
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 7:
            continue
        filesystem, fstype, size, used, avail, percent, mount = parts[:7]
        try:
            usage = int(percent.rstrip("%"))
        except ValueError:
            continue
        filesystems.append({
            "filesystem": filesystem,
            "type": fstype,
            "size": size,
            "used": used,
            "available": avail,
            "percent": usage,
            "mount": mount,
            "size_display": format_df_blocks(size),
            "used_display": format_df_blocks(used),
            "available_display": format_df_blocks(avail),
        })
    return filesystems

def parse_inode_data():
    result = run_command(["df", "-Pi"])
    inodes = []
    if not result["ok"]:
        return inodes
    lines = result["output"].splitlines()
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        filesystem, total, used, free, percent, mount = parts[:6]
        try:
            usage = int(percent.rstrip("%"))
        except ValueError:
            continue
        inodes.append({
            "filesystem": filesystem,
            "total": total,
            "used": used,
            "free": free,
            "total_display": format_inode_mb(total),
            "used_display": format_inode_mb(used),
            "free_display": format_inode_mb(free),
            "percent": usage,
            "mount": mount,
        })
    return inodes

def format_bytes(value):
    if value is None:
        return "Unavailable"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024

def format_df_blocks(value):
    try:
        return format_bytes_mb(int(value) * 1024)
    except (TypeError, ValueError):
        return "Unavailable"

def format_inode_mb(value):
    try:
        return format_storage_mb((int(value) * INODE_BYTES) / (1024 * 1024))
    except (TypeError, ValueError):
        return "Unavailable"

def format_bytes_mb(value):
    try:
        return format_storage_mb(float(value) / (1024 * 1024))
    except (TypeError, ValueError):
        return "Unavailable"

def format_storage_mb(value):
    amount = float(value)
    if amount > 1024:
        return f"{amount / 1024:.1f} GB"
    return f"{amount:.1f} MB"

def format_lsblk_output(output):
    lines = output.splitlines()
    if not lines:
        return output
    header = lines[0].replace("SIZE", "SIZE_MB")
    formatted = [header]
    for line in lines[1:]:
        parts = line.split(None, 1)
        if len(parts) == 2:
            size_match = re.match(r"(\d+)(\s+)(.*)", parts[1])
            if size_match:
                parts[1] = f"{format_bytes_mb(size_match.group(1))}{size_match.group(2)}{size_match.group(3)}"
                line = " ".join(parts)
        formatted.append(line)
    return "\n".join(formatted)

def format_inode_command_output(output):
    lines = output.splitlines()
    if not lines:
        return output
    formatted = ["Filesystem Total_MB Used_MB Free_MB Usage Mount"]
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 6:
            formatted.append(line)
            continue
        filesystem, total, used, free, percent = parts[:5]
        mount = " ".join(parts[5:])
        formatted.append(
            f"{filesystem} {format_inode_mb(total)} {format_inode_mb(used)} "
            f"{format_inode_mb(free)} {percent} {mount}"
        )
    return "\n".join(formatted)

def format_df_command_output(output):
    lines = output.splitlines()
    if not lines:
        return output
    header_parts = lines[0].split()
    if len(header_parts) < 6:
        return output
    formatted = ["Filesystem Type Size_MB Used_MB Available_MB Usage Mount"]
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 7:
            formatted.append(line)
            continue
        filesystem, fstype, size, used, available, percent = parts[:6]
        mount = " ".join(parts[6:])
        formatted.append(f"{filesystem} {fstype} {format_df_blocks(size)} {format_df_blocks(used)} {format_df_blocks(available)} {percent} {mount}")
    return "\n".join(formatted)

def get_storage_summary(filesystems):
    if not filesystems:
        return {"used": "Unavailable", "available": "Unavailable", "total": "Unavailable", "percent": None, "mount": "No filesystem data"}
    filesystem = next((item for item in filesystems if item["mount"] == "/"), filesystems[0])
    return {
        "used": format_df_blocks(filesystem["used"]),
        "available": format_df_blocks(filesystem["available"]),
        "total": format_df_blocks(filesystem["size"]),
        "percent": filesystem["percent"],
        "mount": filesystem["mount"],
    }

def get_memory_status():
    result = run_command(["free", "-b"])
    if not result["ok"]:
        return {"used": "Unavailable", "available": "Unavailable", "total": "Unavailable", "percent": None, "source": result["output"]}
    for line in result["output"].splitlines():
        if line.startswith("Mem:"):
            parts = line.split()
            if len(parts) >= 7:
                try:
                    total, used, available = (int(parts[1]), int(parts[2]), int(parts[6]))
                    return {
                        "used": format_bytes(used),
                        "available": format_bytes(available),
                        "total": format_bytes(total),
                        "percent": round((used / total) * 100) if total else 0,
                        "source": "free -b",
                    }
                except ValueError:
                    break
    return {"used": "Unavailable", "available": "Unavailable", "total": "Unavailable", "percent": None, "source": "free -b returned an unrecognized format"}

def read_cpu_snapshot():
    try:
        line = next(line for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines() if line.startswith("cpu "))
        values = [int(value) for value in line.split()[1:]]
        return {"total": sum(values), "idle": values[3] + (values[4] if len(values) > 4 else 0)}
    except (OSError, StopIteration, ValueError, IndexError):
        return None

def get_system_health():
    first = read_cpu_snapshot()
    time.sleep(0.1)
    second = read_cpu_snapshot()
    cpu_percent = None
    if first and second:
        total_delta = second["total"] - first["total"]
        idle_delta = second["idle"] - first["idle"]
        if total_delta > 0:
            cpu_percent = round(max(0, min(100, (1 - idle_delta / total_delta) * 100)), 1)

    try:
        uptime_seconds = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
        uptime = format_uptime(uptime_seconds)
    except (OSError, ValueError, IndexError):
        uptime_seconds, uptime = None, "Unavailable"

    try:
        load_parts = Path("/proc/loadavg").read_text(encoding="utf-8").split()
        load_average = [float(value) for value in load_parts[:3]]
    except (OSError, ValueError):
        load_average = []

    read_bytes, write_bytes = read_disk_io_totals()
    return {
        "cpu_percent": cpu_percent,
        "uptime_seconds": uptime_seconds,
        "uptime": uptime,
        "load_average": load_average,
        "disk_io": {
            "read_bytes": read_bytes,
            "write_bytes": write_bytes,
            "read_display": format_bytes(read_bytes) if read_bytes is not None else "Unavailable",
            "write_display": format_bytes(write_bytes) if write_bytes is not None else "Unavailable",
        },
        "source": "Linux /proc",
    }

def format_uptime(seconds):
    total_minutes = max(0, int(seconds // 60))
    days, remainder = divmod(total_minutes, 1440)
    hours, minutes = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"

def read_disk_io_totals():
    read_bytes = write_bytes = 0
    found = False
    try:
        for line in Path("/proc/diskstats").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) < 14:
                continue
            name = parts[2]
            if name.startswith(("loop", "ram", "dm-", "sr")) or name[-1:].isdigit():
                continue
            read_bytes += int(parts[5]) * 512
            write_bytes += int(parts[9]) * 512
            found = True
    except (OSError, ValueError, IndexError):
        return None, None
    return (read_bytes, write_bytes) if found else (None, None)

def parse_lsblk_devices():
    result = run_command(["lsblk", "-dn", "-b", "-P", "-o", "NAME,ROTA,TYPE,MODEL,SIZE"])
    devices = []
    if result["ok"]:
        for line in result["output"].splitlines():
            fields = dict(re.findall(r'([A-Z]+)="([^"]*)"', line))
            if fields.get("TYPE") != "disk":
                continue
            devices.append({
                "name": fields.get("NAME", ""),
                "type": "HDD" if fields.get("ROTA") == "1" else "SSD",
                "model": fields.get("MODEL") or "Model unavailable",
                "size": format_bytes_mb(fields.get("SIZE")) if fields.get("SIZE") else "Size unavailable",
            })
    if devices:
        return devices
    for device_path in Path("/sys/block").glob("*"):
        name = device_path.name
        if name.startswith(("loop", "ram", "dm", "sr")):
            continue
        model = "Model unavailable"
        model_path = device_path / "device" / "model"
        try:
            if model_path.exists():
                model = model_path.read_text(encoding="utf-8").strip() or model
        except OSError:
            pass
        rotational = "0"
        try:
            rotational = (device_path / "queue" / "rotational").read_text(encoding="utf-8").strip()
        except OSError:
            pass
        size = "Size unavailable"
        try:
            size = format_df_blocks((device_path / "size").read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pass
        devices.append({"name": name, "type": "HDD" if rotational == "1" else "SSD", "model": model, "size": size})
    return devices

def get_disk_life(device_name):
    if not device_name:
        return {"health": "Unavailable", "life": "Not reported", "temperature": "Unavailable", "source": "No device name"}
    result = run_command(["smartctl", "-a", f"/dev/{device_name}"], timeout=12)
    if not result["ok"]:
        return {"health": "Unavailable", "life": "Not reported", "temperature": "Unavailable", "source": result["output"]}
    output = result["output"]
    health = "PASSED" if re.search(r"\bPASSED\b", output, re.IGNORECASE) else "Available"
    life = None
    nvme_used = re.search(r"Percentage Used:\s*(\d+)%", output, re.IGNORECASE)
    remaining = re.search(r"Percent(?:age)?[_ ]Lifetime[_ ]Remain(?:ing)?:?\s*(\d+)", output, re.IGNORECASE)
    if nvme_used:
        life = f"{max(0, 100 - int(nvme_used.group(1)))}% estimated"
    elif remaining:
        life = f"{remaining.group(1)}% estimated"
    temperature_match = None
    for line in output.splitlines():
        if not re.search(r"(?:Temperature|Airflow_Temperature_Cel|Temperature_Celsius)", line, re.IGNORECASE):
            continue
        values = re.findall(r"(?<![A-Za-z0-9])(\d+(?:\.\d+)?)\s*(?:°C|C)\b", line, re.IGNORECASE)
        if values:
            temperature_match = values[-1]
            break
    temperature = f"{temperature_match} °C" if temperature_match else "Not reported"
    temperature = f"{temperature_match.group(1)} °C" if temperature_match else "Not reported"
    return {"health": health, "life": life or "Not reported", "temperature": temperature, "source": "smartctl"}

def get_hardware_details():
    devices = parse_lsblk_devices()
    for device in devices:
        device["health"] = get_disk_life(device["name"])

    def read_first(paths, default):
        for path in paths:
            try:
                value = Path(path).read_text(encoding="utf-8").strip()
                if value and value not in {"None", "Unknown", "To Be Filled By O.E.M."}:
                    return value
            except (OSError, UnicodeDecodeError):
                continue
        return default

    system_model = read_first([
        "/sys/class/dmi/id/product_name",
        "/sys/devices/virtual/dmi/id/product_name",
        "/sys/class/dmi/id/board_name",
        "/proc/device-tree/model",
    ], "Model unavailable")
    system_vendor = read_first([
        "/sys/class/dmi/id/sys_vendor",
        "/sys/devices/virtual/dmi/id/sys_vendor",
    ], "")
    if system_vendor and system_vendor.lower() not in system_model.lower():
        system_model = f"{system_vendor} {system_model}"

    memory_model = "Model unavailable"
    memory_result = run_command(["dmidecode", "--type", "memory"], timeout=8)
    if memory_result["ok"]:
        manufacturers = re.findall(r"^\s*Manufacturer:\s*(.+)$", memory_result["output"], re.MULTILINE)
        part_numbers = re.findall(r"^\s*Part Number:\s*(.+)$", memory_result["output"], re.MULTILINE)
        values = [value.strip() for value in manufacturers + part_numbers if value.strip() not in {"Not Specified", "Unknown"}]
        if values:
            memory_model = " · ".join(dict.fromkeys(values))
    if memory_model == "Model unavailable":
        memory_result = run_command(["lshw", "-quiet", "-class", "memory"], timeout=8)
        if memory_result["ok"]:
            product = re.search(r"^\s*product:\s*(.+)$", memory_result["output"], re.MULTILINE)
            vendor = re.search(r"^\s*vendor:\s*(.+)$", memory_result["output"], re.MULTILINE)
            values = [match.group(1).strip() for match in (vendor, product) if match]
            if values:
                memory_model = " · ".join(dict.fromkeys(values))
    os_release = read_first(["/proc/sys/kernel/osrelease"], "")
    if "microsoft" in os_release.lower() or "wsl" in os_release.lower():
        if system_model == "Model unavailable":
            system_model = "WSL2 virtual machine"
        if memory_model == "Model unavailable":
            memory_model = "Virtualized RAM (WSL2; physical DIMM model hidden)"

    primary = devices[0] if devices else {"type": "Unavailable", "model": "Model unavailable", "size": "Unavailable", "health": {"health": "Unavailable", "life": "Not reported", "temperature": "Unavailable"}}
    return {
        "system_model": system_model,
        "memory_model": memory_model,
        "devices": devices,
        "primary_disk": primary,
    }
def get_severity(percent, cfg):
    if percent >= cfg["critical"]:
        return "CRITICAL"
    if percent >= cfg["warning"]:
        return "WARNING"
    return "OK"

@app.get("/")
def index():
    return render_template("index.html")

@app.get("/api/status")
def status():
    cfg = get_config()
    filesystems = parse_disk_data()
    inodes = parse_inode_data()
    storage = get_storage_summary(filesystems)
    memory = get_memory_status()
    system_health = get_system_health()
    hardware = get_hardware_details()
    alerts = []
    for fs in filesystems:
        severity = get_severity(fs["percent"], cfg)
        if severity != "OK":
            alerts.append({"severity": severity, "kind": "Disk space", "mount": fs["mount"], "percent": fs["percent"], "filesystem": fs["filesystem"]})
    for item in inodes:
        severity = get_severity(item["percent"], cfg)
        if severity != "OK":
            alerts.append({"severity": severity, "kind": "Inodes", "mount": item["mount"], "percent": item["percent"], "filesystem": item["filesystem"]})
    return jsonify({
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "hostname": __import__("socket").gethostname(),
        "filesystems": filesystems,
        "inodes": inodes,
        "storage": storage,
        "memory": memory,
        "system_health": system_health,
        "hardware": hardware,
        "alerts": alerts,
        "config": cfg
    })

def prometheus_number(value):
    if value is None:
        return None
    return str(value).lower() if isinstance(value, float) else str(value)

def prometheus_line(name, value, help_text, labels=None):
    if value is None:
        return ""
    label_text = ""
    if labels:
        label_text = "{" + ",".join(f'{key}="{str(item).replace(chr(92), chr(92)+chr(92)).replace(chr(34), chr(92)+chr(34))}"' for key, item in labels.items()) + "}"
    return f"# HELP {name} {help_text}\n# TYPE {name} gauge\n{name}{label_text} {prometheus_number(value)}\n"

@app.get("/metrics")
def metrics():
    filesystems = parse_disk_data()
    inodes = parse_inode_data()
    memory = get_memory_status()
    health = get_system_health()
    hardware = get_hardware_details()
    lines = [
        "# Linux Storage Monitor metrics",
        prometheus_line("linux_storage_cpu_percent", health["cpu_percent"], "Current CPU utilization percentage").rstrip(),
        prometheus_line("linux_storage_load_average", health["load_average"][0] if health["load_average"] else None, "1 minute load average"),
        prometheus_line("linux_storage_uptime_seconds", health["uptime_seconds"], "System uptime in seconds"),
        prometheus_line("linux_storage_memory_percent", memory["percent"], "Memory utilization percentage"),
    ]
    for fs in filesystems:
        labels = {"filesystem": fs["filesystem"], "mount": fs["mount"], "type": fs["type"]}
        lines.append(prometheus_line("linux_storage_filesystem_usage_percent", fs["percent"], "Filesystem usage percentage", labels).rstrip())
        lines.append(prometheus_line("linux_storage_filesystem_size_bytes", int(fs["size"]) * 1024, "Filesystem size in bytes", labels).rstrip())
        lines.append(prometheus_line("linux_storage_filesystem_available_bytes", int(fs["available"]) * 1024, "Filesystem available space in bytes", labels).rstrip())
    for item in inodes:
        labels = {"filesystem": item["filesystem"], "mount": item["mount"]}
        lines.append(prometheus_line("linux_storage_inode_usage_percent", item["percent"], "Inode usage percentage", labels).rstrip())
    for device in hardware["devices"]:
        health_data = device.get("health", {})
        temperature = health_data.get("temperature", "")
        match = re.search(r"(\d+(?:\.\d+)?)", temperature)
        if match:
            lines.append(prometheus_line("linux_storage_disk_temperature_celsius", float(match.group(1)), "Disk temperature in Celsius", {"device": device["name"]}).rstrip())
    disk_io = health["disk_io"]
    lines.append(prometheus_line("linux_storage_disk_read_bytes_total", disk_io["read_bytes"], "Cumulative disk bytes read"))
    lines.append(prometheus_line("linux_storage_disk_write_bytes_total", disk_io["write_bytes"], "Cumulative disk bytes written"))
    return "\n".join(line for line in lines if line) + "\n"

@app.get("/api/command/<name>")
def command(name):
    if name not in ALLOWED_COMMANDS:
        return jsonify({"ok": False, "output": "Command not allowed. Choose one of the provided storage commands."}), 400
    args, label = ALLOWED_COMMANDS[name]
    result = run_command(args)
    if result["ok"] and name in {"disk", "root"}:
        result["output"] = format_df_command_output(result["output"])
    elif result["ok"] and name == "inode":
        result["output"] = format_inode_command_output(result["output"])
    elif result["ok"] and name == "devices":
        result["output"] = format_lsblk_output(result["output"])
    append_log(f"COMMAND {label} | exit={result['returncode']}")
    result["label"] = label
    return jsonify(result)

@app.post("/api/cache/clear")
def clear_cache():
    if platform.system() != "Linux":
        return jsonify({"ok": False, "message": "System cache clearing is available only on Linux."}), 400
    sync_result = run_command(["sync"])
    if not sync_result["ok"]:
        append_log(f"CACHE clear failed during sync | exit={sync_result['returncode']}")
        return jsonify({"ok": False, "message": f"Could not synchronize pending writes: {sync_result['output']}"}), 500
    try:
        result = subprocess.run(
            ["sudo", "-n", "tee", "/proc/sys/vm/drop_caches"],
            input="3\n",
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except FileNotFoundError:
        message = "sudo is not installed. Cache clearing was not performed."
        append_log("CACHE clear failed | sudo not found")
        return jsonify({"ok": False, "message": message}), 500
    except subprocess.TimeoutExpired:
        message = "Cache clearing timed out. Cache clearing was not completed."
        append_log("CACHE clear failed | timed out")
        return jsonify({"ok": False, "message": message}), 504
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        message = "Permission denied. Configure passwordless sudo for this operation or run the app with appropriate permissions."
        if detail:
            message = f"{message} ({detail})"
        append_log(f"CACHE clear failed | exit={result.returncode}")
        return jsonify({"ok": False, "message": message}), 403
    append_log("CACHE cleared | pagecache, dentries and inodes")
    return jsonify({"ok": True, "message": "System cache cleared successfully."})

@app.post("/api/config")
def update_config():
    data = request.get_json(silent=True) or {}
    try:
        warning = int(data.get("warning"))
        critical = int(data.get("critical"))
        if not (1 <= warning < critical <= 100):
            raise ValueError()
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Use whole numbers where 1 <= warning < critical <= 100."}), 400
    CONFIG_PATH.write_text(json.dumps({"warning": warning, "critical": critical}, indent=2))
    append_log(f"CONFIG updated | warning={warning}% critical={critical}%")
    return jsonify({"ok": True, "config": {"warning": warning, "critical": critical}})

@app.post("/api/simulate")
def simulate():
    data = request.get_json(silent=True) or {}
    try:
        percent = int(data.get("percent"))
        if not 0 <= percent <= 100:
            raise ValueError()
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Usage must be between 0 and 100."}), 400
    cfg = get_config()
    severity = get_severity(percent, cfg)
    message = f"SIMULATION {severity} | test filesystem | usage={percent}% | thresholds warning={cfg['warning']}%, critical={cfg['critical']}%"
    append_log(message)
    return jsonify({"ok": True, "severity": severity, "percent": percent, "message": message, "simulated": True})

@app.get("/api/logs")
def logs():
    if not LOG_PATH.exists():
        return jsonify({"content": "No log entries yet."})
    return jsonify({"content": LOG_PATH.read_text(encoding="utf-8")[-12000:]})

@app.get("/api/report")
def report():
    cfg = get_config()
    filesystems = parse_disk_data()
    inodes = parse_inode_data()
    system_health = get_system_health()
    hardware = get_hardware_details()
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
    path = REPORT_DIR / f"storage_report_{stamp}.txt"
    with path.open("w", encoding="utf-8") as f:
        generated = datetime.now().astimezone().isoformat(timespec="seconds")
        f.write("LINUX STORAGE MONITOR\n")
        f.write("====================\n\n")
        f.write("REPORT DETAILS\n")
        f.write("--------------\n")
        f.write(f"Generated          : {generated}\n")
        f.write(f"Warning threshold  : {cfg['warning']}%\n")
        f.write(f"Critical threshold : {cfg['critical']}%\n")
        f.write(f"Filesystems found  : {len(filesystems)}\n")
        f.write(f"Inode entries      : {len(inodes)}\n\n")

        f.write("SYSTEM HEALTH\n")
        f.write("-------------\n\n")
        cpu = system_health["cpu_percent"]
        f.write(f"CPU utilization    : {cpu}%\n" if cpu is not None else "CPU utilization    : Unavailable\n")
        f.write(f"Uptime             : {system_health['uptime']}\n")
        loads = system_health["load_average"]
        f.write(f"Load average       : {' / '.join(f'{value:.2f}' for value in loads) if loads else 'Unavailable'}\n")
        f.write(f"Disk read total    : {system_health['disk_io']['read_display']}\n")
        f.write(f"Disk write total   : {system_health['disk_io']['write_display']}\n")
        primary_health = hardware["primary_disk"].get("health", {})
        f.write(f"Primary disk temp  : {primary_health.get('temperature', 'Unavailable')}\n\n")

        f.write("DISK SPACE\n")
        f.write("----------\n\n")
        for fs in filesystems:
            f.write(f"Filesystem : {fs['filesystem']}\n")
            f.write(f"Mount      : {fs['mount']}\n")
            f.write(f"Type       : {fs['type']}\n")
            f.write(f"Size       : {fs['size_display']}\n")
            f.write(f"Used       : {fs['used_display']}\n")
            f.write(f"Available  : {fs['available_display']}\n")
            f.write(f"Usage      : {fs['percent']}%\n\n")

        if not filesystems:
            f.write("No filesystem data was returned.\n\n")

        f.write("INODE USAGE\n")
        f.write("-----------\n\n")
        for item in inodes:
            f.write(f"Filesystem : {item['filesystem']}\n")
            f.write(f"Mount      : {item['mount']}\n")
            f.write(f"Total      : {item['total_display']} (raw count: {item['total']})\n")
            f.write(f"Used       : {item['used_display']} (raw count: {item['used']})\n")
            f.write(f"Free       : {item['free_display']} (raw count: {item['free']})\n")
            f.write(f"Usage      : {item['percent']}%\n\n")

        if not inodes:
            f.write("No inode data was returned.\n\n")

        f.write("END OF REPORT\n")
        f.write("=============\n")
    append_log(f"REPORT generated | {path.name}")
    return send_file(path, as_attachment=True, download_name=path.name, mimetype="text/plain")

if __name__ == "__main__":
    print("Linux Storage Monitor running at http://127.0.0.1:5000")
    print("Use Ctrl+C to stop the server.")
    app.run(host="127.0.0.1", port=5000, debug=False)
