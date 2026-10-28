# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Monitoring stack for UPLFP48100 LiFePO4 batteries (up to 16 packs on one RS-485 bus) read over Modbus RTU. Targets a small Ubuntu/Debian box that exposes the data via HTTP, SNMP and Zabbix. Code, comments, log messages and JSON keys (`baterias`, `erro`) are in Portuguese — keep that convention.

No build, lint or test tooling exists. Dependencies are `pymodbus` pinned `>=3.0,<3.10` (code uses the `slave=` kwarg, renamed `device_id=` in 3.10; written on the vendor's old Ubuntu firmware, now running on Armbian), `pyserial` and, for the DHT11, `python3-libgpiod` >= 2.0 (apt). Everything uses only the stdlib otherwise.

Testing happens remotely on the target board (Orange Pi PC, `ssh ulisses@<board-ip>`; IP may change after reboot). Without the RS-485 bus, run `battery_api.py` from a temp dir next to a stub `pymodbus/client.py` whose `ModbusSerialClient.connect()` returns False, and drive `battery_snmp_agent.py` directly over stdin (`printf "get\n<OID>\n" | BATTERY_API_URL=... python3 battery_snmp_agent.py`) — no snmpd needed.

## Running

```bash
# Direct Modbus read, JSON output (needs serial access, e.g. dialout group)
python3 battery_monitor.py --port /dev/ttyUSB0 --pretty            # discover 1-16 + read all
python3 battery_monitor.py --discover --start-id 1 --end-id 16
python3 battery_monitor.py --ids 1,2,5

# HTTP API (endpoints: /health, /discover, /batteries, /environment, /config/network; network UI at /)
sudo python3 battery_api.py --host 0.0.0.0 --port 8080 --modbus-port /dev/ttyUSB0 --env-file ./test.env --dht-pin PA6

# Zabbix helper
python3 battery_zabbix.py --discover
python3 battery_zabbix.py --id 1 --metric voltage
python3 battery_zabbix.py --id 1 --json

# Install/uninstall as systemd service (root; --snmp-community is mandatory)
sudo ./install_battery_api_service.sh --snmp-community <text> [--modbus-port /dev/ttyUSB0 ...]
sudo ./uninstall_battery_api_service.sh
```

Without hardware, `dados-testes/` holds captured raw Modbus frames (`work_Communication.txt`, RTF-wrapped hex dumps of `03` reads of 39 registers) and BMS tool exports — use these to reason about/verify register decoding.

## Architecture

- **`battery_monitor.py`** — `BatteryMonitor` is the single Modbus layer. Reads 39 holding registers from address 0 per slave and decodes in `_parse()`: r1 signed current ×0.01 A, r2–16 cell mV (cells outside 2.0–4.5 V are dropped, so `voltage` is the sum of valid cells, not a register), r18–20 temps, r21 SOC, r22 SOH. Status (`Stand by`/`Charging`/`Discharging`) is derived from current (±0.5 A). Any register-map change belongs here and propagates to every consumer.
- **`battery_api.py`** — `ThreadingHTTPServer` with config held as class attributes on `BatteryApiHandler` (set from argparse in `main()`). A background thread is the **only** owner of the serial port during normal operation: every `cache_interval` s it discovers + reads IDs 1–16 and merges into `_cache_data`. Request handlers only serve cache snapshots — they never touch Modbus. `_merge_cache_reading` keeps a battery's last reading for up to `BATTERY_CACHE_MAX_FAILURES` (default 3) consecutive misses before dropping it. `/config/network` writes `/etc/battery-api.env` and optionally a netplan file (`/etc/netplan/99-battery-api.yaml`, with backup/rollback) and can restart the systemd service; runs as root.
- **`battery_snmp_agent.py`** — net-snmp `pass_persist` agent (stdin/stdout protocol) under base OID `.1.3.6.1.4.1.99999.1` (OID tree documented in its docstring; values scaled to integer mV/mA). It polls the API's `/batteries` cache over HTTP to avoid contending for the serial port, and falls back to direct Modbus (config from `/etc/battery-api.env`) only if the API is down.
- **`dht_sensor.py`** — DHT11 ambient temperature/humidity reader for the Orange Pi PC (Allwinner H3, Armbian, kernel has no `dht11` driver). Userspace via libgpiod v2 edge events (kernel IRQ timestamps) plus direct PIO register access through `/dev/mem` (root only). Hardware-specific choices, all verified on the board:
  - Start pulse is done by flipping the pin mux (output-low ↔ EINT) via registers while the gpiod edge request stays open; reconfiguring through libgpiod takes ~1.2 ms and loses the first bits.
  - Bank IRQ debounce (`PA_INT_DEB`/`PG_INT_DEB`) is forced to `0x51` (~1.3 µs). Reset default (32 kHz) swallows the ~24 µs "0" bits; `0x1` (no filter) caused an IRQ storm that hung the board.
  - Edge polarity from the kernel is unreliable on H3 and edges get merged/split, so `decode_frame` is a DP parser over edge timestamps (~98% per-attempt success, ~130 ms decode on H3). Only PA/PG pins are IRQ-capable.
  - Default wiring: `+` → pin 1 (3.3 V, never 5 V), `out` → pin 7 (PA6), `-` → pin 6 (GND). Test: `sudo python3 dht_sensor.py --pin PA6 --count 5`.
  The API reads it in its own thread (`--dht-pin`, disabled when empty; lazy import so a missing libgpiod never affects batteries) and serves the median of the last 3 good reads at `GET /environment`; SNMP exposes it under `BASE.3`.
- **`battery_zabbix.py` + `battery_monitor.conf`** — Zabbix Agent 2 UserParameters calling the script per metric. Note this path opens the serial port directly on every call (it does not use the API cache), so it can collide with a running `battery-api` service.

The serial bus is single-access: when adding a new consumer, read from the API cache rather than opening the port.

## Deployment layout (from install script)

Installs `battery_api.py`, `battery_monitor.py`, `battery_snmp_agent.py`, `dht_sensor.py` to `/opt/battery-api/` (DHT pin via `--dht-pin PA6|none`); env in `/etc/battery-api.env` (group-readable by the snmpd user); unit `battery-api.service` runs as root. Also configures snmpd (view, rocommunity/rocommunity6, pass_persist line), lldpd, NDP sysctl, and optionally changes the root password. Installed packages are recorded in `/etc/battery-api-install.state` for the uninstaller. `battery_zabbix.py` is not installed by the script (expected at `/usr/local/bin/`).
