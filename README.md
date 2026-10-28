# Linux Storage Monitor

A small educational mini-project that monitors actual Linux filesystem usage through a local Flask web dashboard.

## Features
- Live disk-space and inode monitoring
- Live storage, RAM, disk health, and hardware model cards
- CPU, uptime, load average, disk I/O, and disk temperature cards
- Prometheus-compatible metrics at `/metrics`
- Controlled system cache clearing on Linux with visible progress feedback
- Configurable warning and critical thresholds
- Storage command console with an allowlist of read-only commands
- Persistent logs for approved command runs, configuration changes, simulations and report generation
- Downloadable text report
- Alert simulation without filling a real disk

## Requirements
- Linux/Ubuntu/Kali Linux
- Python 3
- `df`, `free`, `lsblk`, and `findmnt` (normally available on Linux)
- `smartctl`, `dmidecode`, and `lshw` for optional disk-life, temperature, and hardware details
- Flask

## Run on Ubuntu / Kali Linux
Open a terminal in this folder and run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000` in the Linux machine's browser.

If `venv` creation fails on Ubuntu/Debian, install the package and retry:

```bash
sudo apt update
sudo apt install python3-venv
```

Do not run the web app with `sudo`. It is designed to work as your normal user.

## Safety
The web console intentionally does not accept arbitrary shell commands. It only runs a fixed set of read-only storage commands. Do not expose this development server to the public internet. The demo server is intended for local educational use.

## Suggested demo
1. Refresh live data and show the filesystem table.
2. Click `df -hT`, `df -i`, and `lsblk` in the command console.
3. Set warning to 60 and critical to 80 temporarily, save, and refresh to demonstrate threshold handling against real usage.
4. Simulate 95% usage to demonstrate a critical alert.
5. Open logs and download the report.
6. Restore warning to 80 and critical to 90.

The four system cards read from Linux at each refresh. Storage values use
adaptive units across the cards, filesystem table, inode table, hardware
disk-size details, command console output, and reports: values above 1024 MB
are displayed in GB, while values at or below 1024 MB remain in MB. They use
`df`, while RAM uses
`free`, disk type/model uses `lsblk`, disk health/life uses `smartctl` when
available, and RAM/system model details use `dmidecode` and Linux DMI files.
Disk model detection also falls back to `/sys/block`. When an optional utility
is missing or requires elevated permissions, the
affected value is shown as `Unavailable` without breaking the dashboard.

The inode table and inode command output show an adaptive MB/GB equivalent
using the standard 256-byte-per-inode estimate. Raw inode counts are retained
in the API and included in reports because inode usage is fundamentally a
count rather than byte capacity.

The **Clear system cache** button first runs `sync`, then requests Linux to clear
page cache, dentries, and inodes through non-interactive `sudo`. It never waits
for a password in the web process. If the user is not allowed to run the fixed
operation with passwordless sudo, the dashboard reports the permission error and
does not claim that the cache was cleared.

System health metrics are read from Linux `/proc`, including CPU utilization,
uptime, load average, and cumulative disk I/O totals. SMART temperatures are
shown when `smartctl` exposes a readable temperature. Missing permissions or
utilities result in an explicit `Unavailable`/`Not reported` value.

The `/metrics` endpoint exposes filesystem, inode, memory, CPU, uptime, disk
I/O, and available SMART temperature values in Prometheus text format. It is
intended for a local Prometheus scraper and does not require an additional
Python dependency.

## Files
- `app.py`: Flask backend and Linux command execution
- `templates/index.html`: dashboard UI
- `config.json`: created automatically; stores thresholds
- `logs/storage_monitor.log`: created when log entries are generated
- `reports/`: downloaded reports are generated here before being sent to the browser

## UI design
The dashboard uses a light theme, custom inline SVG icons (no emoji icons), and Google Fonts: Sora for modern dashboard headings, Inter for interface text, and IBM Plex Mono for terminal output. Internet access is required to fetch the Google Fonts; system fallbacks are provided.
