#!/usr/bin/env python3
"""API HTTP simples para expor leituras de baterias via Modbus."""

import argparse
import copy
import datetime
import html
import ipaddress
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from battery_monitor import BatteryMonitor


def parse_ids(value):
    """Aceita lista de inteiros ou string CSV e retorna lista de int."""
    if value is None:
        return None

    if isinstance(value, list):
        return [int(v) for v in value]

    if isinstance(value, str):
        items = []
        for chunk in value.split(','):
            chunk = chunk.strip()
            if chunk:
                items.append(int(chunk))
        return items

    raise ValueError("Campo 'ids' deve ser lista ou string CSV")


def parse_dns(value):
    """Aceita lista de DNS em lista JSON ou CSV e retorna lista limpa."""
    if value is None:
        return []

    if isinstance(value, list):
        items = [str(v).strip() for v in value if str(v).strip()]
        return items

    if isinstance(value, str):
        items = []
        for chunk in value.split(','):
            chunk = chunk.strip()
            if chunk:
                items.append(chunk)
        return items

    raise ValueError("Campo 'dns' deve ser lista ou string CSV")


class BatteryApiHandler(BaseHTTPRequestHandler):
    env_file = "/etc/battery-api.env"
    service_name = "battery-api"
    bind_host = "0.0.0.0"
    bind_port = 8080
    netplan_file = "/etc/netplan/99-battery-api.yaml"
    monitor_port = "/dev/ttyUSB0"
    monitor_baudrate = 9600
    monitor_timeout = 3
    discover_timeout = 0.5
    cache_interval = 10
    cache_max_failures = int(os.environ.get("BATTERY_CACHE_MAX_FAILURES", "3"))

    _cache_lock = threading.Lock()
    _cache_started = False
    _cache_data = {
        "ids": [],
        "baterias": [],
        "updated_at": None,
        "last_error": "Cache ainda nao inicializado",
        "failure_counts": {},
    }

    def _restart_service(self):
        """Reinicia o servico da API de forma sincrona para garantir aplicacao de config."""
        subprocess.check_call(["systemctl", "restart", self.service_name])

    def do_GET(self):
        self._handle_request("GET")

    def do_POST(self):
        self._handle_request("POST")

    def log_message(self, fmt, *args):
        # Mantem o log HTTP padrao em stdout.
        super().log_message(fmt, *args)

    def _handle_request(self, method):
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            if method == "GET":
                params = self._query_to_dict(parsed.query)
            else:
                params = self._read_json_body()

            if path == "/health":
                self._send_json(200, {"status": "ok"})
                return

            if path == "/ui/network":
                self._send_html(200, self._render_network_ui())
                return

            if path == "/config/network":
                payload = self._handle_network_config(params, method)
                self._send_json(200, payload)
                return

            if path == "/discover":
                payload = self._handle_discover(params)
                self._send_json(200, payload)
                return

            if path == "/batteries":
                payload = self._handle_batteries(params)
                self._send_json(200, payload)
                return

            self._send_json(404, {"erro": "Endpoint nao encontrado"})
        except ValueError as exc:
            self._send_json(400, {"erro": str(exc)})
        except PermissionError as exc:
            self._send_json(403, {"erro": str(exc)})
        except Exception as exc:
            self._send_json(500, {"erro": str(exc)})

    def _query_to_dict(self, query):
        parsed = parse_qs(query, keep_blank_values=False)
        data = {}
        for key, values in parsed.items():
            if not values:
                continue
            data[key] = values[0] if len(values) == 1 else values
        return data

    def _read_json_body(self):
        content_len = int(self.headers.get("Content-Length", "0"))
        if content_len == 0:
            return {}

        raw = self.rfile.read(content_len)
        if not raw:
            return {}

        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON invalido: {exc}")

        if not isinstance(data, dict):
            raise ValueError("Corpo JSON deve ser um objeto")

        return data

    def _send_json(self, status_code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status_code, html_payload):
        body = html_payload.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _build_monitor(self):
        monitor = BatteryMonitor(
            port=self.monitor_port,
            baudrate=self.monitor_baudrate,
            timeout=self.monitor_timeout,
        )
        if not monitor.connect():
            raise RuntimeError("Falha ao conectar no barramento Modbus")
        return monitor

    @classmethod
    def _merge_cache_reading(cls, ids, baterias):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        fresh_by_id = {}
        for bateria in baterias:
            battery_id = int(bateria.get("id", 0))
            if battery_id > 0:
                fresh_by_id[battery_id] = bateria

        with cls._cache_lock:
            previous_batteries = {}
            for bateria in cls._cache_data.get("baterias", []):
                battery_id = int(bateria.get("id", 0))
                if battery_id > 0:
                    previous_batteries[battery_id] = bateria

            failure_counts = {
                int(battery_id): int(count)
                for battery_id, count in cls._cache_data.get("failure_counts", {}).items()
            }

            merged = {}
            candidate_ids = set(previous_batteries) | set(fresh_by_id)

            for battery_id in sorted(candidate_ids):
                if battery_id in fresh_by_id:
                    merged[battery_id] = fresh_by_id[battery_id]
                    failure_counts[battery_id] = 0
                    continue

                previous = previous_batteries.get(battery_id)
                if previous is None:
                    continue

                failure_counts[battery_id] = failure_counts.get(battery_id, 0) + 1
                if failure_counts[battery_id] <= cls.cache_max_failures:
                    merged[battery_id] = previous
                else:
                    failure_counts.pop(battery_id, None)

            cls._cache_data = {
                "ids": sorted(merged.keys()),
                "baterias": [merged[battery_id] for battery_id in sorted(merged.keys())],
                "updated_at": now,
                "last_error": "",
                "failure_counts": failure_counts,
            }

    @classmethod
    def _refresh_cache_once(cls):
        monitor = BatteryMonitor(
            port=cls.monitor_port,
            baudrate=cls.monitor_baudrate,
            timeout=cls.monitor_timeout,
        )

        if not monitor.connect():
            with cls._cache_lock:
                cls._cache_data["last_error"] = "Falha ao conectar no barramento Modbus"
            return

        try:
            ids = monitor.discover_ids(1, 16, timeout_seconds=cls.discover_timeout)
            baterias = monitor.read_batteries(ids)
            cls._merge_cache_reading(ids, baterias)
        except Exception as exc:
            with cls._cache_lock:
                cls._cache_data["last_error"] = str(exc)
        finally:
            monitor.disconnect()

    @classmethod
    def _cache_loop(cls):
        while True:
            cls._refresh_cache_once()
            time.sleep(max(1, int(cls.cache_interval)))

    @classmethod
    def start_cache_worker(cls):
        if cls._cache_started:
            return
        cls._cache_started = True
        worker = threading.Thread(target=cls._cache_loop, daemon=True)
        worker.start()

    @classmethod
    def _get_cache_snapshot(cls):
        with cls._cache_lock:
            snapshot = copy.deepcopy(cls._cache_data)
        return snapshot

    def _handle_discover(self, params):
        start_id = int(params.get("start_id", 1))
        end_id = int(params.get("end_id", 16))
        snapshot = self._get_cache_snapshot()
        ids = [battery_id for battery_id in snapshot.get("ids", []) if start_id <= battery_id <= end_id]
        return {
            "ids": ids,
            "total": len(ids),
            "cache_updated_at": snapshot.get("updated_at"),
            "cache_error": snapshot.get("last_error", ""),
        }

    def _handle_batteries(self, params):
        start_id = int(params.get("start_id", 1))
        end_id = int(params.get("end_id", 16))
        ids = parse_ids(params.get("ids"))

        snapshot = self._get_cache_snapshot()
        baterias_cache = snapshot.get("baterias", [])

        if ids is None:
            baterias = [b for b in baterias_cache if start_id <= int(b.get("id", 0)) <= end_id]
        else:
            requested_ids = set(ids)
            baterias = [b for b in baterias_cache if int(b.get("id", 0)) in requested_ids]

        return {
            "baterias": baterias,
            "total": len(baterias),
            "cache_updated_at": snapshot.get("updated_at"),
            "cache_error": snapshot.get("last_error", ""),
        }

    def _read_env_values(self):
        values = {}
        if not os.path.exists(self.env_file):
            return values

        with open(self.env_file, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                values[key.strip()] = val.strip()
        return values

    def _write_env_values(self, updates):
        existing = self._read_env_values()
        existing.update(updates)
        lines = [f"{k}={v}" for k, v in existing.items()]

        with open(self.env_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def _validate_network(self, host, port):
        if not host or any(ch.isspace() for ch in host):
            raise ValueError("Host invalido")

        port_int = int(port)
        if port_int < 1 or port_int > 65535:
            raise ValueError("Porta invalida (1..65535)")
        return host, port_int

    def _validate_ipv4(self, value, field_name):
        try:
            ipaddress.IPv4Address(value)
        except Exception:
            raise ValueError(f"{field_name} invalido")
        return value

    def _validate_ip_any(self, value, field_name):
        try:
            ipaddress.ip_address(value)
        except Exception:
            raise ValueError(f"{field_name} invalido")
        return value

    def _validate_netmask(self, netmask):
        try:
            ipaddress.IPv4Network(f"0.0.0.0/{netmask}")
        except Exception:
            raise ValueError("Mascara invalida")
        return netmask

    def _prefix_from_netmask(self, netmask):
        return ipaddress.IPv4Network(f"0.0.0.0/{netmask}").prefixlen

    def _build_netplan_yaml(self, iface, ip_addr, prefix, gateway, dns_list):
        lines = [
            "network:",
            "  version: 2",
            "  renderer: networkd",
            "  ethernets:",
            f"    {iface}:",
            "      dhcp4: false",
            f"      addresses: [{ip_addr}/{prefix}]",
        ]

        if gateway:
            lines.extend([
                "      routes:",
                f"        - to: default",
                f"          via: {gateway}",
            ])

        if dns_list:
            # IPv6 contem ':' e deve ser quotado para evitar ambiguidades no YAML.
            dns_text = ", ".join([f'"{item}"' for item in dns_list])
            lines.extend([
                "      nameservers:",
                f"        addresses: [{dns_text}]",
            ])

        return "\n".join(lines) + "\n"

    def _apply_system_network(self, ip_addr, netmask, gateway, dns_list, iface):
        if os.geteuid() != 0:
            raise PermissionError("Aplicacao de rede requer root")

        netplan_bin = shutil.which("netplan")
        if not netplan_bin:
            for candidate in ("/usr/sbin/netplan", "/sbin/netplan", "/usr/bin/netplan"):
                if os.path.exists(candidate) and os.access(candidate, os.X_OK):
                    netplan_bin = candidate
                    break

        if not netplan_bin:
            raise RuntimeError(
                "Comando netplan nao encontrado. Instale com: sudo apt-get update && sudo apt-get install -y netplan.io, "
                "ou desmarque 'Aplicar no sistema (netplan)' para salvar sem aplicar."
            )

        if not iface or iface in ("unknown", "loopback"):
            raise RuntimeError("Interface de rede invalida para aplicacao")

        # Host configurado precisa ser um IPv4 para rede estatica.
        self._validate_ipv4(ip_addr, "Host/IP")
        prefix = self._prefix_from_netmask(netmask)

        netplan_yaml = self._build_netplan_yaml(
            iface=iface,
            ip_addr=ip_addr,
            prefix=prefix,
            gateway=gateway,
            dns_list=dns_list,
        )

        backup_path = ""
        if os.path.exists(self.netplan_file):
            ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            backup_path = f"{self.netplan_file}.bak.{ts}"
            shutil.copy2(self.netplan_file, backup_path)

        try:
            with open(self.netplan_file, "w", encoding="utf-8") as f:
                f.write(netplan_yaml)

            subprocess.check_call([netplan_bin, "generate"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.check_call([netplan_bin, "apply"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            # Rollback da configuracao gerenciada por este servico.
            if backup_path and os.path.exists(backup_path):
                shutil.copy2(backup_path, self.netplan_file)
                try:
                    subprocess.check_call([netplan_bin, "generate"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    subprocess.check_call([netplan_bin, "apply"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
            raise RuntimeError(f"Falha ao aplicar netplan: {exc}")

        return {
            "netplan_file": self.netplan_file,
            "backup_file": backup_path,
            "applied": True,
            "interface": iface,
            "prefix": prefix,
        }

    def _get_runtime_network(self):
        """Retorna IP e mascara IPv4 da interface de saida principal."""
        try:
            route = subprocess.check_output(
                ["ip", "-o", "-4", "route", "get", "8.8.8.8"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            iface = ""
            parts = route.split()
            if "dev" in parts:
                iface = parts[parts.index("dev") + 1]

            if iface:
                addr_info = subprocess.check_output(
                    ["ip", "-o", "-4", "addr", "show", "dev", iface],
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
                for token in addr_info.split():
                    if "/" in token and token[0].isdigit():
                        ip_str, prefix = token.split("/", 1)
                        prefix_int = int(prefix)
                        netmask = str(ipaddress.IPv4Network(f"0.0.0.0/{prefix_int}").netmask)
                        return {
                            "ip": ip_str,
                            "prefix": prefix_int,
                            "netmask": netmask,
                            "interface": iface,
                        }
        except Exception:
            pass

        try:
            ip_str = socket.gethostbyname(socket.gethostname())
            return {
                "ip": ip_str,
                "prefix": None,
                "netmask": "255.255.255.255",
                "interface": "unknown",
            }
        except Exception:
            return {
                "ip": "127.0.0.1",
                "prefix": None,
                "netmask": "255.0.0.0",
                "interface": "loopback",
            }

    def _get_default_gateway(self):
        """Retorna gateway IPv4 padrao do sistema."""
        try:
            route = subprocess.check_output(
                ["ip", "route", "show", "default"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            if not route:
                return ""

            parts = route.split()
            if "via" in parts:
                return parts[parts.index("via") + 1]
        except Exception:
            pass
        return ""

    def _get_dns_servers(self):
        """Retorna lista de DNS configurados em /etc/resolv.conf."""
        servers = []
        try:
            with open("/etc/resolv.conf", "r", encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("nameserver "):
                        parts = line.split()
                        if len(parts) >= 2:
                            servers.append(parts[1])
        except Exception:
            return []

        # Remove duplicados mantendo ordem.
        seen = set()
        unique_servers = []
        for item in servers:
            if item in seen:
                continue
            seen.add(item)
            unique_servers.append(item)
        return unique_servers

    def _handle_network_config(self, params, method):
        env_data = self._read_env_values()
        runtime_net = self._get_runtime_network()
        runtime_ip = runtime_net["ip"]
        runtime_gateway = self._get_default_gateway()
        runtime_dns = self._get_dns_servers()
        runtime_interface = runtime_net["interface"]
        configured_netmask = env_data.get("NETMASK", runtime_net["netmask"])
        configured_gateway = env_data.get("GATEWAY", runtime_gateway)
        configured_dns = parse_dns(env_data.get("DNS", ",".join(runtime_dns)))

        if method == "GET":
            current_host = env_data.get("HOST", self.bind_host)
            current_port = int(env_data.get("PORT", self.bind_port))
            return {
                "host": current_host,
                "port": current_port,
                "netmask": configured_netmask,
                "gateway": configured_gateway,
                "dns": configured_dns,
                "runtime_ip": runtime_ip,
                "runtime_netmask": runtime_net["netmask"],
                "runtime_prefix": runtime_net["prefix"],
                "runtime_interface": runtime_interface,
                "runtime_gateway": runtime_gateway,
                "runtime_dns": runtime_dns,
                "system_apply_supported": os.geteuid() == 0,
                "netplan_file": self.netplan_file,
                "access_url": f"http://{runtime_ip}:{current_port}",
                "env_file": self.env_file,
                "restart_required": False,
            }

        host = str(params.get("host", env_data.get("HOST", self.bind_host))).strip()
        port = params.get("port", env_data.get("PORT", self.bind_port))
        netmask = str(params.get("netmask", configured_netmask)).strip()
        gateway = str(params.get("gateway", configured_gateway)).strip()
        dns_list = parse_dns(params.get("dns", configured_dns))
        apply_system = str(params.get("apply_system", "true")).lower() in ("1", "true", "yes")

        host, port_int = self._validate_network(host, port)
        netmask = self._validate_netmask(netmask)
        if gateway:
            gateway = self._validate_ipv4(gateway, "Gateway")

        validated_dns = []
        for dns in dns_list:
            validated_dns.append(self._validate_ip_any(dns, "DNS"))

        apply_result = {
            "applied": False,
            "skipped": not apply_system,
            "reason": "",
        }

        restart_triggered = False
        restart_error = ""
        config_touched = False
        operation_error = None

        try:
            if apply_system:
                config_touched = True
                apply_result = self._apply_system_network(
                    ip_addr=host,
                    netmask=netmask,
                    gateway=gateway,
                    dns_list=validated_dns,
                    iface=runtime_interface,
                )

            self._write_env_values({
                "HOST": host,
                "PORT": str(port_int),
                "NETMASK": netmask,
                "GATEWAY": gateway,
                "DNS": ",".join(validated_dns),
            })
            config_touched = True
        except Exception as exc:
            operation_error = exc
        finally:
            if config_touched:
                try:
                    self._restart_service()
                    restart_triggered = True
                except Exception as exc:
                    restart_error = str(exc)

        if operation_error is not None:
            if restart_error:
                raise RuntimeError(f"{operation_error}; falha ao reiniciar servico: {restart_error}")
            raise RuntimeError(str(operation_error))

        payload = {
            "host": host,
            "port": port_int,
            "netmask": netmask,
            "gateway": gateway,
            "dns": validated_dns,
            "runtime_ip": runtime_ip,
            "runtime_netmask": runtime_net["netmask"],
            "runtime_prefix": runtime_net["prefix"],
            "runtime_interface": runtime_interface,
            "runtime_gateway": runtime_gateway,
            "runtime_dns": runtime_dns,
            "apply_system": apply_system,
            "apply_result": apply_result,
            "access_url": f"http://{runtime_ip}:{port_int}",
            "env_file": self.env_file,
            "restart_required": False,
            "restart_triggered": restart_triggered,
        }
        if restart_error:
            payload["restart_error"] = restart_error
        return payload

    def _render_network_ui(self):
        env_data = self._read_env_values()
        runtime_net = self._get_runtime_network()
        runtime_ip = html.escape(runtime_net["ip"])
        runtime_netmask = html.escape(runtime_net["netmask"])
        runtime_prefix = runtime_net["prefix"]
        prefix_text = f"/{runtime_prefix}" if runtime_prefix is not None else ""
        runtime_interface = html.escape(str(runtime_net["interface"]))
        runtime_gateway = html.escape(self._get_default_gateway() or "nao detectado")
        runtime_dns_list = self._get_dns_servers()
        runtime_dns = html.escape(", ".join(runtime_dns_list) if runtime_dns_list else "nao detectado")
        current_host = html.escape(env_data.get("HOST", self.bind_host))
        current_port = html.escape(str(env_data.get("PORT", self.bind_port)))
        current_netmask = html.escape(env_data.get("NETMASK", runtime_net["netmask"]))
        current_gateway = html.escape(env_data.get("GATEWAY", self._get_default_gateway()))
        current_dns = html.escape(env_data.get("DNS", ",".join(runtime_dns_list)))
        return f"""<!doctype html>
<html lang=\"pt-BR\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Battery API - Configuracao de Rede</title>
    <style>
        body {{ font-family: 'DejaVu Sans', sans-serif; background: #f4f7fb; margin: 0; padding: 24px; }}
        .card {{ max-width: 640px; margin: 0 auto; background: #fff; border: 1px solid #dbe3ef; border-radius: 12px; padding: 20px; }}
        h1 {{ margin: 0 0 16px; font-size: 22px; color: #173a5e; }}
        label {{ display: block; margin-top: 12px; font-weight: 600; color: #274a6e; }}
        input {{ width: 100%; box-sizing: border-box; padding: 10px; margin-top: 6px; border: 1px solid #c5d3e6; border-radius: 8px; }}
        button {{ margin-top: 16px; padding: 10px 14px; border: 0; border-radius: 8px; background: #0069b4; color: #fff; font-weight: 700; cursor: pointer; }}
        .row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
        .msg {{ margin-top: 16px; font-size: 14px; color: #0b4f2f; }}
        .warn {{ color: #8c3a00; }}
    </style>
</head>
<body>
    <div class=\"card\">
        <h1>Configuracao de Rede da API</h1>
        <p>Visualize e altere host/IP e porta da API. Alteracoes exigem restart do servico.</p>
        <p><strong>IP atual do servidor:</strong> {runtime_ip}</p>
        <p><strong>Mascara:</strong> {runtime_netmask}{prefix_text} ({runtime_interface})</p>
        <p><strong>Gateway:</strong> {runtime_gateway}</p>
        <p><strong>DNS:</strong> {runtime_dns}</p>
        <p><strong>URL atual:</strong> http://{runtime_ip}:{current_port}</p>
        <div class=\"row\">
            <div>
                <label>Host/IP</label>
                <input id=\"host\" value=\"{current_host}\" />
            </div>
            <div>
                <label>Porta</label>
                <input id=\"port\" type=\"number\" min=\"1\" max=\"65535\" value=\"{current_port}\" />
            </div>
        </div>
        <div class=\"row\">
            <div>
                <label>Mascara</label>
                <input id=\"netmask\" value=\"{current_netmask}\" placeholder=\"255.255.255.0\" />
            </div>
            <div>
                <label>Gateway</label>
                <input id=\"gateway\" value=\"{current_gateway}\" placeholder=\"192.168.0.1\" />
            </div>
        </div>
        <label>DNS (separado por virgula)</label>
        <input id=\"dns\" value=\"{current_dns}\" placeholder=\"1.1.1.1,8.8.8.8\" />
        <label><input id=\"applySystem\" type=\"checkbox\" checked /> Aplicar no sistema (netplan)</label>
        <button onclick=\"saveCfg()\">Salvar</button>
        <div id=\"msg\" class=\"msg\"></div>
    </div>

    <script>
        async function saveCfg() {{
            const host = document.getElementById('host').value.trim();
            const port = Number(document.getElementById('port').value);
            const netmask = document.getElementById('netmask').value.trim();
            const gateway = document.getElementById('gateway').value.trim();
            const dns = document.getElementById('dns').value.trim();
            const apply_system = document.getElementById('applySystem').checked;
            const msg = document.getElementById('msg');
            msg.textContent = 'Salvando...';
            msg.className = 'msg';

            try {{
                const resp = await fetch('/config/network', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                    }},
                    body: JSON.stringify({{ host, port, netmask, gateway, dns, apply_system }}),
                }});
                const data = await resp.json();
                if (!resp.ok) {{
                    throw new Error(data.erro || 'Falha ao salvar');
                }}

                if (data.apply_system && data.apply_result && data.apply_result.applied) {{
                    msg.textContent = 'Salvo, aplicado no sistema e servico reiniciado com sucesso.';
                }} else if (data.restart_triggered) {{
                    msg.textContent = 'Salvo e servico reiniciado com sucesso.';
                }} else {{
                    msg.textContent = 'Salvo, mas falhou ao reiniciar automaticamente: ' + (data.restart_error || 'erro desconhecido');
                    msg.className = 'msg warn';
                }}
            }} catch (err) {{
                msg.textContent = 'Erro: ' + err.message;
                msg.className = 'msg warn';
            }}
        }}
    </script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(
        description="API HTTP para leitura de baterias UPLFP48100"
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host de bind (padrao: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Porta HTTP (padrao: 8080)")
    parser.add_argument("--env-file", default="/etc/battery-api.env", help="Arquivo .env para configuracoes persistentes")
    parser.add_argument("--service-name", default="battery-api", help="Nome do servico systemd")
    parser.add_argument("--modbus-port", default="/dev/ttyUSB0", help="Porta serial Modbus")
    parser.add_argument("--baudrate", type=int, default=9600, help="Baudrate Modbus")
    parser.add_argument("--modbus-timeout", type=float, default=3, help="Timeout padrao Modbus")
    parser.add_argument("--discover-timeout", type=float, default=0.5, help="Timeout padrao do discovery Modbus")
    parser.add_argument("--cache-interval", type=int, default=10, help="Intervalo de atualizacao do cache em segundos")
    args = parser.parse_args()

    BatteryApiHandler.env_file = args.env_file
    BatteryApiHandler.service_name = args.service_name
    BatteryApiHandler.bind_host = args.host
    BatteryApiHandler.bind_port = args.port
    BatteryApiHandler.monitor_port = args.modbus_port
    BatteryApiHandler.monitor_baudrate = args.baudrate
    BatteryApiHandler.monitor_timeout = args.modbus_timeout
    BatteryApiHandler.discover_timeout = args.discover_timeout
    BatteryApiHandler.cache_interval = args.cache_interval
    BatteryApiHandler.start_cache_worker()

    server = ThreadingHTTPServer((args.host, args.port), BatteryApiHandler)
    print(f"API iniciada em http://{args.host}:{args.port}")
    print("Endpoints: GET/POST /discover, GET/POST /batteries, GET /health")
    print("Config: GET/POST /config/network, UI: GET /ui/network")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
