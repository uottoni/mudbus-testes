#!/usr/bin/env python3
"""
Agente SNMP pass_persist para expor dados das baterias UPLFP48100 via snmpd.

Protocolo pass_persist (net-snmp):
  stdin  "PING"            -> stdout "PONG"
  stdin  "get\n<OID>\n"   -> stdout "<OID>\n<tipo>\n<valor>\n"
  stdin  "getnext\n<OID>" -> stdout "<OID>\n<tipo>\n<valor>\n"
  stdin  "set\n..."        -> stdout "not-writable\n"

Configurar em /etc/snmp/snmpd.conf:
  pass_persist .1.3.6.1.4.1.99999.1  /usr/bin/python3 /opt/battery-api/battery_snmp_agent.py

OID base: .1.3.6.1.4.1.99999.1  (PEN 99999 - privado, registre o seu em https://www.iana.org/assignments/enterprise-numbers)

Arvore de OIDs exportados:
  BASE.1.0           total de baterias (integer)
  BASE.2.<id>.1      id da bateria (integer)
  BASE.2.<id>.2      status: "Stand by" / "Charging" / "Discharging" (string)
  BASE.2.<id>.3      SOC % (gauge)
  BASE.2.<id>.4      SOH % (gauge)
  BASE.2.<id>.5      tensao total em mV (gauge)
  BASE.2.<id>.6      corrente em mA, signed - negativo = descarga (integer)
  BASE.2.<id>.7      potencia em W (gauge)
  BASE.2.<id>.8      temperatura maxima em graus C (gauge)
  BASE.2.<id>.9      tensao minima de celula em mV (gauge)
  BASE.2.<id>.10     tensao maxima de celula em mV (gauge)
  BASE.2.<id>.11     diferenca maxima entre celulas em mV (gauge)
"""

import os
import sys
import threading
import time
import json
from urllib import request, error

# Permite importar battery_monitor.py instalado junto com este script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from battery_monitor import BatteryMonitor  # noqa: E402

# ---------------------------------------------------------------------------
# Configuracao
# ---------------------------------------------------------------------------

BASE_OID = os.environ.get("BATTERY_SNMP_BASE_OID", ".1.3.6.1.4.1.99999.1")
ENV_FILE  = os.environ.get("BATTERY_ENV_FILE", "/etc/battery-api.env")
REFRESH_INTERVAL = int(os.environ.get("BATTERY_SNMP_REFRESH", "10"))  # segundos
DEFAULT_DISCOVER_TIMEOUT = 0.5
BATTERY_API_URL = os.environ.get("BATTERY_API_URL", "http://127.0.0.1:8080/batteries")
BATTERY_API_TIMEOUT = float(os.environ.get("BATTERY_API_TIMEOUT", "3"))

# Indices dos campos por bateria (subOID relativo a BASE.2.<id>)
_F_ID        = 1
_F_STATUS    = 2
_F_SOC       = 3
_F_SOH       = 4
_F_VOLTAGE   = 5
_F_CURRENT   = 6
_F_POWER     = 7
_F_TEMP      = 8
_F_CELL_MIN  = 9
_F_CELL_MAX  = 10
_F_CELL_DIFF = 11


# ---------------------------------------------------------------------------
# Utilitarios de OID
# ---------------------------------------------------------------------------

def _oid_to_tuple(oid: str) -> tuple:
    return tuple(int(x) for x in oid.lstrip(".").split("."))


def _tuple_to_oid(t: tuple) -> str:
    return "." + ".".join(str(x) for x in t)


# ---------------------------------------------------------------------------
# Leitura do env file
# ---------------------------------------------------------------------------

def _read_env() -> dict:
    cfg = {
        "MODBUS_PORT": "/dev/ttyUSB0",
        "BAUDRATE": "9600",
        "MODBUS_TIMEOUT": "3",
        "DISCOVER_TIMEOUT": str(DEFAULT_DISCOVER_TIMEOUT),
    }
    if not os.path.exists(ENV_FILE):
        return cfg
    with open(ENV_FILE, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg


# ---------------------------------------------------------------------------
# Agente
# ---------------------------------------------------------------------------

class SnmpPassPersistAgent:
    def __init__(self):
        self._lock = threading.Lock()
        self._oid_map: dict = {}        # oid_tuple -> (tipo, valor)
        self._sorted_oids: list = []
        self._base_tuple = _oid_to_tuple(BASE_OID)

        # Inicializa com mapa vazio.
        self._build_map([])

        # Primeiro refresh sincrono: busca do cache HTTP eh rapida e evita
        # janela inicial com total=0 logo apos restart do snmpd.
        self._refresh_once()

        # Atualizacao periodica em background.
        t = threading.Thread(target=self._background_loop, daemon=True)
        t.start()

    # ------------------------------------------------------------------
    # Construcao do mapa de OIDs
    # ------------------------------------------------------------------

    def _build_map(self, batteries: list):
        new_map: dict = {}

        def add(suffix: str, typ: str, val):
            key = self._base_tuple + _oid_to_tuple(suffix)
            new_map[key] = (typ, val)

        add("1.0", "integer", len(batteries))

        for bat in batteries:
            bid = bat.get("id", 0)
            p   = f"2.{bid}"
            cells = bat.get("cells", [])
            cell_min  = int(bat.get("cell_min",  min(cells) if cells else 0.0) * 1000)
            cell_max  = int(bat.get("cell_max",  max(cells) if cells else 0.0) * 1000)
            cell_diff = int(bat.get("cell_diff", (max(cells) - min(cells)) if cells else 0.0) * 1000)

            add(f"{p}.{_F_ID}",        "integer", bid)
            add(f"{p}.{_F_STATUS}",    "string",  bat.get("status", "unknown"))
            add(f"{p}.{_F_SOC}",       "gauge",   int(bat.get("soc",     0)))
            add(f"{p}.{_F_SOH}",       "gauge",   int(bat.get("soh",     0)))
            add(f"{p}.{_F_VOLTAGE}",   "gauge",   int(bat.get("voltage", 0.0) * 1000))
            add(f"{p}.{_F_CURRENT}",   "integer", int(bat.get("current", 0.0) * 1000))
            add(f"{p}.{_F_POWER}",     "gauge",   int(bat.get("power",   0.0)))
            add(f"{p}.{_F_TEMP}",      "gauge",   int(bat.get("temp_max", 0)))
            add(f"{p}.{_F_CELL_MIN}",  "gauge",   cell_min)
            add(f"{p}.{_F_CELL_MAX}",  "gauge",   cell_max)
            add(f"{p}.{_F_CELL_DIFF}", "gauge",   cell_diff)

        with self._lock:
            self._oid_map     = new_map
            self._sorted_oids = sorted(new_map.keys())

    # ------------------------------------------------------------------
    # Coleta periodica de dados
    # ------------------------------------------------------------------

    def _fetch_from_api_cache(self):
        req = request.Request(BATTERY_API_URL, method="GET")
        with request.urlopen(req, timeout=BATTERY_API_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")

        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return []

        baterias = payload.get("baterias", [])
        if isinstance(baterias, list):
            return baterias
        return []

    def _fetch_batteries(self) -> list:
        # Preferencia: usa cache da API para evitar disputa da serial Modbus.
        try:
            return self._fetch_from_api_cache()
        except Exception:
            pass

        # Fallback opcional: leitura direta Modbus, caso API esteja indisponivel.
        cfg     = _read_env()
        discover_timeout = float(cfg.get("DISCOVER_TIMEOUT", DEFAULT_DISCOVER_TIMEOUT))
        monitor = BatteryMonitor(
            port=cfg["MODBUS_PORT"],
            baudrate=int(cfg["BAUDRATE"]),
            timeout=int(cfg["MODBUS_TIMEOUT"]),
        )
        try:
            if not monitor.connect():
                return []
            ids      = monitor.discover_ids(1, 16, timeout_seconds=discover_timeout)
            return monitor.read_batteries(ids)
        except Exception:
            return []
        finally:
            monitor.disconnect()

    def _background_loop(self):
        while True:
            self._refresh_once()
            time.sleep(REFRESH_INTERVAL)

    def _refresh_once(self):
        try:
            batteries = self._fetch_batteries()
            self._build_map(batteries)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Operacoes SNMP
    # ------------------------------------------------------------------

    def get(self, oid_str: str):
        """Retorna (oid, tipo, valor) ou None se OID nao encontrado."""
        key = _oid_to_tuple(oid_str)
        with self._lock:
            if key in self._oid_map:
                typ, val = self._oid_map[key]
                return _tuple_to_oid(key), typ, val
        return None

    def getnext(self, oid_str: str):
        """Retorna proximo OID apos oid_str dentro da subarvore BASE_OID, ou None."""
        key = _oid_to_tuple(oid_str)
        with self._lock:
            for k in self._sorted_oids:
                if k > key:
                    typ, val = self._oid_map[k]
                    return _tuple_to_oid(k), typ, val
        return None

    # ------------------------------------------------------------------
    # Loop principal stdin/stdout (protocolo pass_persist)
    # ------------------------------------------------------------------

    def run(self):
        for line in sys.stdin:
            cmd = line.strip()

            if cmd == "PING":
                sys.stdout.write("PONG\n")
                sys.stdout.flush()

            elif cmd == "get":
                oid_str = sys.stdin.readline().strip()
                result  = self.get(oid_str)
                if result is None:
                    sys.stdout.write("NONE\n")
                else:
                    oid_out, typ, val = result
                    sys.stdout.write(f"{oid_out}\n{typ}\n{val}\n")
                sys.stdout.flush()

            elif cmd == "getnext":
                oid_str = sys.stdin.readline().strip()
                result  = self.getnext(oid_str)
                if result is None:
                    sys.stdout.write("NONE\n")
                else:
                    oid_out, typ, val = result
                    sys.stdout.write(f"{oid_out}\n{typ}\n{val}\n")
                sys.stdout.flush()

            elif cmd == "set":
                sys.stdin.readline()  # OID
                sys.stdin.readline()  # tipo valor
                sys.stdout.write("not-writable\n")
                sys.stdout.flush()


if __name__ == "__main__":
    SnmpPassPersistAgent().run()
