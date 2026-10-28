# Linux Storage Monitor

Linux Storage Monitor is a local Flask dashboard for observing Linux storage
and system health. It reads live values from standard Linux commands and
kernel interfaces, formats the results for the browser, and provides reports,
logs, alerts, and Prometheus metrics.

The project is designed for Linux and WSL2. It may start on Windows Python,
but Linux monitoring commands such as `df`, `free`, `lsblk`, and `findmnt` are
not normally available there. For full functionality, run the application
inside Linux or WSL2.

## Features

- Filesystem storage usage from `df -P -T`
- Adaptive storage units:
  - Values up to and including 1024 MB are shown in MB
  - Values above 1024 MB are shown in GB
- Inode monitoring from `df -Pi`
- Inode MB/GB equivalents using a 256-byte-per-inode estimate
- Raw inode counts preserved for accurate percentages and reports
- RAM usage from `free -b`
- CPU utilization, uptime, load average, and disk I/O totals from `/proc`
- Disk type, model, and size from `lsblk` and `/sys/block`
- SMART disk health, estimated life, and temperature when available
- Hardware and RAM model detection through DMI, `dmidecode`, and `lshw`
- Configurable warning and critical thresholds
- Filesystem and inode alerts
- Safe allowlisted Linux command console
- Downloadable, spaced text reports
- Persistent activity logs
- Alert simulation without changing disk contents
- Linux cache-clearing action with animated UI feedback
- Prometheus-compatible `/metrics` endpoint
- Light dashboard theme with Sora, Inter, and IBM Plex Mono fonts
- Inline SVG icons with no external icon package

## Project structure

```text
linux_storage_monitor/
├── app.py                         # Flask backend and Linux data collection
├── templates/
│   └── index.html                 # Dashboard HTML, CSS, SVG icons, and JS
├── requirements.txt               # Python dependencies
├── config.json                    # Warning/critical thresholds
├── logs/
│   ├── .gitkeep
│   └── storage_monitor.log        # Runtime activity log
├── reports/
│   ├── .gitkeep
│   └── storage_report_*.txt       # Generated reports
├── .venv/                         # Optional Windows virtual environment
└── .venv-linux/                   # Optional WSL/Linux virtual environment
```

Generated virtual environments, logs, reports, Python caches, and local
configuration should normally be excluded from a public repository. Existing
generated files may be present in this educational repository because they
were created during local demonstrations.

## Important note about shell scripts

There are currently **no `.sh` shell scripts** in this project. The run and
setup commands are executed directly in a Linux terminal. The backend invokes
Linux commands through Python's `subprocess.run()` instead of storing them in
shell files.

The commands used by the backend are:

| Purpose | Command |
|---|---|
| Filesystem space | `df -P -T` |
| Inode usage | `df -Pi` |
| Block devices | `lsblk -dn -b -P -o NAME,ROTA,TYPE,MODEL,SIZE` |
| Command-console devices | `lsblk -b -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS` |
| Mount summary | `findmnt -D` |
| RAM usage | `free -b` |
| SMART information | `smartctl -a /dev/<device>` |
| RAM module details | `dmidecode --type memory` |
| Hardware fallback | `lshw -quiet -class memory` |
| Synchronize writes | `sync` |
| Cache clearing | `sudo -n tee /proc/sys/vm/drop_caches` |

The application does not accept arbitrary commands from the browser. The
command console maps fixed button names to the allowlisted commands above.

## How the application is connected

```text
Browser
  │
  ├── GET /
  │     └── Flask renders templates/index.html
  │
  ├── JavaScript fetches GET /api/status every 15 seconds
  │     └── app.py collects Linux metrics
  │           ├── df / df -i
  │           ├── free
  │           ├── lsblk
  │           ├── smartctl, dmidecode, lshw
  │           └── /proc and /sys files
  │
  ├── Toolbar and dashboard actions call:
  │     ├── GET  /api/report
  │     ├── GET  /api/logs
  │     ├── GET  /api/command/<name>
  │     ├── POST /api/config
  │     ├── POST /api/simulate
  │     └── POST /api/cache/clear
  │
  └── Monitoring systems scrape GET /metrics
```

### Backend flow

1. Flask receives a browser or monitoring request.
2. `app.py` executes a fixed Linux command or reads a fixed kernel file.
3. Output is parsed into Python dictionaries.
4. Storage values are converted to adaptive MB/GB display strings.
5. Raw values remain available where percentage calculations need them.
6. Flask returns JSON, a text report, or Prometheus text.
7. The browser updates cards, tables, alerts, and console output.

## Requirements

### Required

- Linux, Ubuntu, Kali, or WSL2
- Python 3.10 or newer
- Flask 3.x
- `df`
- `free`
- `lsblk`
- `findmnt`

The required Linux utilities are normally installed by default.

### Optional

- `smartctl` for SMART health, life, and temperature
- `dmidecode` for physical RAM module information
- `lshw` for hardware fallback information
- Passwordless permission for the fixed cache-clearing command

Optional utilities are detected at runtime. Missing utilities produce
`Unavailable` or `Not reported` values instead of crashing the dashboard.

## Installation on Ubuntu or Kali

Open a terminal in the project directory:

```bash
cd /path/to/linux_storage_monitor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

If virtual-environment creation fails:

```bash
sudo apt update
sudo apt install python3-venv
```

Optional hardware utilities can be installed with:

```bash
sudo apt update
sudo apt install smartmontools dmidecode lshw
```

Do not run the web application itself with `sudo`. The cache-clearing route
uses a non-interactive `sudo -n` call and reports a clear permission error if
the current user is not authorized.

## Running in WSL2 from Windows

From a WSL terminal:

```bash
cd /mnt/c/Users/koush/OneDrive/Documents/AU/5thsem/Linux/linux_storage_monitor_project/linux_storage_monitor
source .venv-linux/bin/activate
python app.py
```

Then open `http://127.0.0.1:5000` in a Windows browser.

If the Linux environment has not been created yet:

```bash
cd /mnt/c/Users/koush/OneDrive/Documents/AU/5thsem/Linux/linux_storage_monitor_project/linux_storage_monitor
python3 -m venv .venv-linux
source .venv-linux/bin/activate
python -m pip install -r requirements.txt
python app.py
```

Do not use the Windows command below for full Linux monitoring:

```powershell
.\.venv\Scripts\python.exe app.py
```

Windows Python can serve the page, but the Linux commands will usually return
`Command not found`, leaving the dashboard without system data.

## API reference

### `GET /`

Returns the dashboard page.

### `GET /api/status`

Returns current dashboard data:

- `filesystems`
- `inodes`
- `storage`
- `memory`
- `system_health`
- `hardware`
- `alerts`
- `config`
- `hostname`
- `timestamp`

### `GET /api/command/<name>`

Runs one approved read-only command. Valid names are:

```text
disk
inode
devices
mounts
root
```

Any other name returns HTTP 400.

### `GET /api/report`

Generates and downloads a readable text report containing report metadata,
disk space, inode usage, system health, and thresholds.

### `GET /api/logs`

Returns the latest log content as JSON. The response is limited to the most
recent 12,000 characters.

### `POST /api/config`

Updates thresholds:

```json
{
  "warning": 80,
  "critical": 90
}
```

The valid range is `1 <= warning < critical <= 100`.

### `POST /api/simulate`

Tests alert severity without modifying a real filesystem:

```json
{
  "percent": 95
}
```

### `POST /api/cache/clear`

Runs `sync`, then requests:

```bash
sudo -n tee /proc/sys/vm/drop_caches
```

This is Linux-only and may require a carefully configured sudoers rule.

### `GET /metrics`

Returns Prometheus text-format metrics including:

- CPU utilization
- Load average
- Uptime
- Memory utilization
- Filesystem usage, size, and available bytes
- Inode usage
- Cumulative disk read/write bytes
- SMART disk temperature when available

Example Prometheus scrape configuration:

```yaml
scrape_configs:
  - job_name: linux-storage-monitor
    static_configs:
      - targets: ["127.0.0.1:5000"]
```

## Storage and unit handling

`df` reports filesystem blocks. The backend converts those values to bytes
internally and formats them as:

- `MB` when the value is less than or equal to 1024 MB
- `GB` when the value is greater than 1024 MB

Inodes are counts, not byte capacity. The UI provides an estimated MB/GB
equivalent using 256 bytes per inode, while preserving the original count for
alerts, API consumers, and reports.

## Safety

- The command console has a fixed allowlist.
- Browser users cannot provide arbitrary shell arguments.
- The command console performs read-only storage inspection.
- Cache clearing is a separate guarded endpoint.
- Cache clearing never waits for an interactive password.
- Errors are returned explicitly instead of being presented as success.
- The Flask development server is intended for local use only.
- Do not expose this application directly to the public internet.

If the dashboard is deployed beyond localhost, add authentication, CSRF
protection, HTTPS, rate limiting, and a production WSGI server.

## Validation commands

Run a Python syntax check:

```bash
python -m py_compile app.py
```

Check the status API:

```bash
curl http://127.0.0.1:5000/api/status
```

Check Prometheus output:

```bash
curl http://127.0.0.1:5000/metrics
```

Check the report endpoint:

```bash
curl -OJ http://127.0.0.1:5000/api/report
```

Check the underlying Linux commands directly:

```bash
df -P -T
df -Pi
free -b
lsblk -dn -b -P -o NAME,ROTA,TYPE,MODEL,SIZE
findmnt -D
cat /proc/uptime
cat /proc/loadavg
cat /proc/diskstats
```

## GitHub publishing

This repository already contains `README.md` at its root, which GitHub uses
as the repository landing-page documentation. After reviewing the changes,
stage and push the README with:

```bash
git add README.md
git commit -m "Document Linux storage monitor architecture and usage"
git push
```

If the repository has no upstream configured:

```bash
git remote -v
git remote add origin https://github.com/<username>/<repository>.git
git push -u origin main
```

Do not commit passwords, tokens, private keys, virtual environments, or
machine-specific secrets.
