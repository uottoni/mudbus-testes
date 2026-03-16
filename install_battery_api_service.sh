#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="battery-api"
INSTALL_DIR="/opt/battery-api"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
ENV_FILE="/etc/${SERVICE_NAME}.env"
STATE_FILE="/etc/${SERVICE_NAME}-install.state"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"
MODBUS_PORT="${MODBUS_PORT:-/dev/ttyUSB0}"
BAUDRATE="${BAUDRATE:-9600}"
MODBUS_TIMEOUT="${MODBUS_TIMEOUT:-3}"
DISCOVER_TIMEOUT="${DISCOVER_TIMEOUT:-0.5}"
INSTALL_NETPLAN_DEP=1
LLDP_DEFAULT_FILE="/etc/default/lldpd"
LLDP_HOSTNAME_FILE="/etc/lldpd.d/10-hostname.conf"
SNMP_CONF_FILE="/etc/snmp/snmpd.conf"
SNMP_BASE_OID="${SNMP_BASE_OID:-.1.3.6.1.4.1.99999.1}"
SNMP_COMMUNITY="${SNMP_COMMUNITY:-}"
NDP_SYSCTL_FILE="/etc/sysctl.d/99-ndp-enable.conf"
HOSTNAME_OVERRIDE=""
SKIP_ROOT_PASSWORD_CHANGE=0

usage() {
  cat <<EOF
Uso:
  sudo bash install_battery_api_service.sh [opcoes]

Opcoes:
  --host <host>                 Host da API (padrao: ${HOST})
  --port <porta>                Porta da API (padrao: ${PORT})
  --modbus-port <porta_serial>  Porta Modbus (padrao: ${MODBUS_PORT})
  --baudrate <baudrate>         Baudrate Modbus (padrao: ${BAUDRATE})
  --modbus-timeout <segundos>   Timeout Modbus (padrao: ${MODBUS_TIMEOUT})
  --discover-timeout <segundos> Timeout padrao discovery (padrao: ${DISCOVER_TIMEOUT})
  --python-bin <caminho>        Executavel Python (padrao: ${PYTHON_BIN})
  --skip-netplan-dep            Nao instala pacote netplan.io
  --hostname <nome>             Hostname anunciado por LLDP (padrao: hostname atual)
  --skip-root-password-change   Nao solicita troca de senha do root
  -h, --help                    Mostra esta ajuda
  --snmp-oid <oid>              OID base para pass_persist (padrao: ${SNMP_BASE_OID})
  --snmp-community <texto>      Community SNMP v2c (obrigatoria)

Exemplo:
  sudo bash install_battery_api_service.sh \
    --host 0.0.0.0 --port 8080 --modbus-port /dev/ttyUSB0
EOF
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Erro: execute como root (use sudo)." >&2
    exit 1
  fi
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --host)
        HOST="${2:-}"
        shift 2
        ;;
      --port)
        PORT="${2:-}"
        shift 2
        ;;
      --modbus-port)
        MODBUS_PORT="${2:-}"
        shift 2
        ;;
      --baudrate)
        BAUDRATE="${2:-}"
        shift 2
        ;;
      --modbus-timeout)
        MODBUS_TIMEOUT="${2:-}"
        shift 2
        ;;
      --discover-timeout)
        DISCOVER_TIMEOUT="${2:-}"
        shift 2
        ;;
      --python-bin)
        PYTHON_BIN="${2:-}"
        shift 2
        ;;
      --skip-netplan-dep)
        INSTALL_NETPLAN_DEP=0
        shift
        ;;
      --hostname)
        HOSTNAME_OVERRIDE="${2:-}"
        shift 2
        ;;
      --skip-root-password-change)
        SKIP_ROOT_PASSWORD_CHANGE=1
        shift
        ;;
      --snmp-oid)
        SNMP_BASE_OID="${2:-}"
        shift 2
        ;;
      --snmp-community)
        SNMP_COMMUNITY="${2:-}"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        echo "Erro: opcao desconhecida: $1" >&2
        usage
        exit 1
        ;;
    esac
  done
}

ensure_snmp_community() {
  if [[ -z "${SNMP_COMMUNITY}" ]]; then
    if [[ -t 0 ]]; then
      read -r -p "Informe a community SNMP v2c: " SNMP_COMMUNITY
    fi
  fi

  if [[ -z "${SNMP_COMMUNITY}" ]]; then
    echo "Erro: informe a community SNMP com --snmp-community <texto>." >&2
    exit 1
  fi

  if [[ "${SNMP_COMMUNITY}" =~ [[:space:]] ]]; then
    echo "Erro: community SNMP nao pode conter espacos." >&2
    exit 1
  fi
}

check_files() {
  local base_dir
  base_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

  API_SRC="${base_dir}/battery_api.py"
  MONITOR_SRC="${base_dir}/battery_monitor.py"
  SNMP_AGENT_SRC="${base_dir}/battery_snmp_agent.py"

  if [[ ! -f "${API_SRC}" ]]; then
    echo "Erro: arquivo nao encontrado: ${API_SRC}" >&2
    exit 1
  fi

  if [[ ! -f "${MONITOR_SRC}" ]]; then
    echo "Erro: arquivo nao encontrado: ${MONITOR_SRC}" >&2
    exit 1
  fi

  if [[ ! -f "${SNMP_AGENT_SRC}" ]]; then
    echo "Erro: arquivo nao encontrado: ${SNMP_AGENT_SRC}" >&2
    exit 1
  fi
}

maybe_change_root_password() {
  if [[ "${SKIP_ROOT_PASSWORD_CHANGE}" -eq 1 ]]; then
    echo "Pulando troca de senha do root (--skip-root-password-change)."
    return
  fi

  if ! id orangepi >/dev/null 2>&1; then
    # Mantem comportamento focado no alvo citado (sistemas com usuario default orangepi).
    return
  fi

  if [[ ! -t 0 ]]; then
    echo "Aviso: sem terminal interativo; nao foi possivel solicitar troca de senha root."
    echo "Execute manualmente: sudo passwd root"
    return
  fi

  echo
  echo "Seguranca: este sistema usa perfil padrao 'orangepi'."
  read -r -p "Deseja trocar a senha do root agora? [S/n]: " answer
  answer="${answer:-S}"

  case "${answer}" in
    S|s|Y|y)
      echo "Abrindo troca de senha do root..."
      passwd root
      ;;
    *)
      echo "Troca de senha do root ignorada. Recomendado executar: sudo passwd root"
      ;;
  esac
}

ensure_dependencies() {
  local apt_to_install=()
  local pip_to_install=()
  INSTALLED_APT_PACKAGES=()
  INSTALLED_PIP_PACKAGES=()

  if ! command -v apt-get >/dev/null 2>&1; then
    echo "Erro: apt-get nao encontrado (esperado em Ubuntu/Debian)." >&2
    exit 1
  fi

  if ! command -v ip >/dev/null 2>&1; then
    apt_to_install+=(iproute2)
  fi

  if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    apt_to_install+=(python3)
    PYTHON_BIN="/usr/bin/python3"
  fi

  if ! "${PYTHON_BIN}" -m pip --version >/dev/null 2>&1; then
    apt_to_install+=(python3-pip)
  fi

  if [[ "${INSTALL_NETPLAN_DEP}" -eq 1 ]] && ! command -v netplan >/dev/null 2>&1 && [[ ! -x /usr/sbin/netplan ]]; then
    apt_to_install+=(netplan.io)
  fi

  if ! command -v lldpcli >/dev/null 2>&1; then
    apt_to_install+=(lldpd)
  fi

  if ! command -v ndisc6 >/dev/null 2>&1; then
    apt_to_install+=(ndisc6)
  fi

  if ! command -v snmpd >/dev/null 2>&1; then
    apt_to_install+=(snmpd)
  fi

  if [[ ${#apt_to_install[@]} -gt 0 ]]; then
    local unique_apt=()
    local pkg
    for pkg in "${apt_to_install[@]}"; do
      if ! dpkg -s "${pkg}" >/dev/null 2>&1; then
        unique_apt+=("${pkg}")
      fi
    done

    if [[ ${#unique_apt[@]} -gt 0 ]]; then
      echo "Instalando dependencias APT: ${unique_apt[*]}"
      apt-get update
      apt-get install -y "${unique_apt[@]}"
      INSTALLED_APT_PACKAGES=("${unique_apt[@]}")
    fi
  fi

  if ! "${PYTHON_BIN}" -c "import pymodbus" >/dev/null 2>&1; then
    pip_to_install+=(pymodbus)
  fi

  if ! "${PYTHON_BIN}" -c "import serial" >/dev/null 2>&1; then
    pip_to_install+=(pyserial)
  fi

  if [[ ${#pip_to_install[@]} -gt 0 ]]; then
    echo "Instalando dependencias Python: ${pip_to_install[*]}"
    if ! "${PYTHON_BIN}" -m pip install "${pip_to_install[@]}"; then
      echo "Tentando novamente com --break-system-packages (Python gerenciado pelo sistema)..."
      "${PYTHON_BIN}" -m pip install --break-system-packages "${pip_to_install[@]}"
    fi
    INSTALLED_PIP_PACKAGES=("${pip_to_install[@]}")
  fi
}

configure_ndp_sysctl() {
  cat > "${NDP_SYSCTL_FILE}" <<EOF
# Keep IPv6/NDP enabled for host discovery on LAN
net.ipv6.conf.all.disable_ipv6 = 0
net.ipv6.conf.default.disable_ipv6 = 0
net.ipv6.conf.all.accept_ra = 1
net.ipv6.conf.default.accept_ra = 1
net.ipv6.conf.all.autoconf = 1
net.ipv6.conf.default.autoconf = 1
EOF

  sysctl --system >/dev/null || true
}

configure_lldpd() {
  local host_name
  host_name="${HOSTNAME_OVERRIDE}"
  if [[ -z "${host_name}" ]]; then
    host_name="$(hostname)"
  fi

  LLDP_HOSTNAME="${host_name}"

  mkdir -p /etc/lldpd.d

  # Define protocolos de descoberta mais amplos mantendo LLDP como base.
  cat > "${LLDP_DEFAULT_FILE}" <<EOF
DAEMON_ARGS="-c -e -f -s"
EOF

  cat > "${LLDP_HOSTNAME_FILE}" <<EOF
configure system hostname ${LLDP_HOSTNAME}
EOF

  systemctl enable lldpd
  systemctl restart lldpd
}

write_state_file() {
  cat > "${STATE_FILE}" <<EOF
INSTALLED_APT_PACKAGES=${INSTALLED_APT_PACKAGES[*]}
INSTALLED_PIP_PACKAGES=${INSTALLED_PIP_PACKAGES[*]}
PYTHON_BIN=${PYTHON_BIN}
DISCOVER_TIMEOUT=${DISCOVER_TIMEOUT}
LLDP_DEFAULT_FILE=${LLDP_DEFAULT_FILE}
LLDP_HOSTNAME_FILE=${LLDP_HOSTNAME_FILE}
NDP_SYSCTL_FILE=${NDP_SYSCTL_FILE}
LLDP_HOSTNAME=${LLDP_HOSTNAME}
EOF
  chmod 600 "${STATE_FILE}"
}

install_files() {
  mkdir -p "${INSTALL_DIR}"
  cp "${API_SRC}" "${INSTALL_DIR}/battery_api.py"
  cp "${MONITOR_SRC}" "${INSTALL_DIR}/battery_monitor.py"
  cp "${SNMP_AGENT_SRC}" "${INSTALL_DIR}/battery_snmp_agent.py"
  chmod 755 "${INSTALL_DIR}/battery_api.py" "${INSTALL_DIR}/battery_monitor.py" "${INSTALL_DIR}/battery_snmp_agent.py"
}

configure_snmpd() {
  local pass_line="pass_persist ${SNMP_BASE_OID} ${PYTHON_BIN} ${INSTALL_DIR}/battery_snmp_agent.py"
  local listen_line="agentaddress 0.0.0.0,[::]"
  local battery_view="batteryview"
  local ro_line="rocommunity ${SNMP_COMMUNITY} default -V ${battery_view}"
  local ro6_line="rocommunity6 ${SNMP_COMMUNITY} default -V ${battery_view}"

  # Garante acesso do usuario do daemon snmpd a porta serial (dialout)
  if id Debian-snmp >/dev/null 2>&1; then
    usermod -aG dialout Debian-snmp || true
  fi

  # Compatibilidade com outras distros que usam usuario 'snmp'.
  if id snmp >/dev/null 2>&1; then
    usermod -aG dialout snmp || true
  fi

  if [[ -f "${SNMP_CONF_FILE}" ]]; then
    # Expor SNMP em todos os enderecos IPv4/IPv6.
    sed -i '/^[[:space:]]*#\{0,1\}[[:space:]]*[Aa][Gg][Ee][Nn][Tt][Aa][Dd][Dd][Rr][Ee][Ss][Ss][[:space:]]\+/d' "${SNMP_CONF_FILE}"
    printf '%s\n' "${listen_line}" >> "${SNMP_CONF_FILE}"

    # Garante acesso de leitura ao subtree enterprise da bateria.
    if grep -qE '^rocommunity\s+\S+\s+default\s+-V\s+batteryview\s*$' "${SNMP_CONF_FILE}"; then
      sed -i "s|^rocommunity\s\+\S\+\s\+default\s\+-V\s\+batteryview\s*$|${ro_line}|" "${SNMP_CONF_FILE}"
    else
      printf '%s\n' "${ro_line}" >> "${SNMP_CONF_FILE}"
    fi

    if grep -qE '^rocommunity6\s+\S+\s+default\s+-V\s+batteryview\s*$' "${SNMP_CONF_FILE}"; then
      sed -i "s|^rocommunity6\s\+\S\+\s\+default\s\+-V\s\+batteryview\s*$|${ro6_line}|" "${SNMP_CONF_FILE}"
    else
      printf '%s\n' "${ro6_line}" >> "${SNMP_CONF_FILE}"
    fi

    if ! grep -qE "^view\\s+${battery_view}\\s+included\\s+${SNMP_BASE_OID}(\\s|$)" "${SNMP_CONF_FILE}"; then
      printf '\n# Battery API view\nview %s included %s\n' "${battery_view}" "${SNMP_BASE_OID}" >> "${SNMP_CONF_FILE}"
    fi

    # Evita duplicacao em reinstalacoes
    if ! grep -qF "battery_snmp_agent.py" "${SNMP_CONF_FILE}"; then
      printf '\n# Battery API SNMP pass_persist\n%s\n' "${pass_line}" >> "${SNMP_CONF_FILE}"
    else
      # Atualiza linha existente (pode ter mudado o OID ou python bin)
      sed -i "s|.*battery_snmp_agent\.py.*|${pass_line}|" "${SNMP_CONF_FILE}"
    fi
  else
    mkdir -p "$(dirname "${SNMP_CONF_FILE}")"
    cat > "${SNMP_CONF_FILE}" <<EOF
# Battery API - configuracao minima snmpd
${listen_line}
view ${battery_view} included ${SNMP_BASE_OID}
${ro_line}
${ro6_line}

# Battery API SNMP pass_persist
${pass_line}
EOF
  fi

  systemctl enable snmpd
  systemctl restart snmpd
}

write_env_file() {
  cat > "${ENV_FILE}" <<EOF
HOST=${HOST}
PORT=${PORT}
MODBUS_PORT=${MODBUS_PORT}
BAUDRATE=${BAUDRATE}
MODBUS_TIMEOUT=${MODBUS_TIMEOUT}
DISCOVER_TIMEOUT=${DISCOVER_TIMEOUT}
PYTHON_BIN=${PYTHON_BIN}
EOF

  # snmpd (Debian-snmp/snmp) precisa ler este arquivo para o pass_persist.
  if id Debian-snmp >/dev/null 2>&1; then
    chgrp Debian-snmp "${ENV_FILE}" || true
  elif id snmp >/dev/null 2>&1; then
    chgrp snmp "${ENV_FILE}" || true
  fi
  chmod 640 "${ENV_FILE}"
}

write_service_file() {
  cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=Battery API Service
After=network.target

[Service]
Type=simple
EnvironmentFile=${ENV_FILE}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${PYTHON_BIN} ${INSTALL_DIR}/battery_api.py --host \${HOST} --port \${PORT} --env-file ${ENV_FILE} --service-name ${SERVICE_NAME} --modbus-port \${MODBUS_PORT} --baudrate \${BAUDRATE} --modbus-timeout \${MODBUS_TIMEOUT} --discover-timeout \${DISCOVER_TIMEOUT}
Restart=always
RestartSec=3
User=root
Group=root

[Install]
WantedBy=multi-user.target
EOF
}

start_service() {
  systemctl daemon-reload
  systemctl enable "${SERVICE_NAME}"
  systemctl restart "${SERVICE_NAME}"
}

show_status() {
  echo
  echo "Instalacao concluida."
  echo "Servico: ${SERVICE_NAME}"
  echo "Status resumido:"
  systemctl --no-pager --full status "${SERVICE_NAME}" | head -n 20 || true
  echo
  echo "Comandos uteis:"
  echo "  sudo systemctl status ${SERVICE_NAME}"
  echo "  sudo systemctl restart ${SERVICE_NAME}"
  echo "  sudo journalctl -u ${SERVICE_NAME} -f"
  echo
  echo "Teste rapido:"
  echo "  curl http://127.0.0.1:${PORT}/health"
  echo "  UI: http://127.0.0.1:${PORT}/ui/network"
  echo
  echo "Teste SNMP (requer snmp-mibs-downloader ou snmptranslate):"
  echo "  snmpwalk -v2c -c <community> localhost ${SNMP_BASE_OID}"
  echo "  snmpget  -v2c -c <community> localhost ${SNMP_BASE_OID}.1.0"
}

main() {
  parse_args "$@"
  ensure_snmp_community
  require_root
  maybe_change_root_password
  check_files
  ensure_dependencies
  configure_ndp_sysctl
  configure_lldpd
  install_files
  write_env_file
  write_state_file
  write_service_file
  start_service
    configure_snmpd
  show_status
}

main "$@"
