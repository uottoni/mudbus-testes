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
INSTALL_NETPLAN_DEP=1
LLDP_DEFAULT_FILE="/etc/default/lldpd"
LLDP_HOSTNAME_FILE="/etc/lldpd.d/10-hostname.conf"
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
  --python-bin <caminho>        Executavel Python (padrao: ${PYTHON_BIN})
  --skip-netplan-dep            Nao instala pacote netplan.io
  --hostname <nome>             Hostname anunciado por LLDP (padrao: hostname atual)
  --skip-root-password-change   Nao solicita troca de senha do root
  -h, --help                    Mostra esta ajuda

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

check_files() {
  local base_dir
  base_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

  API_SRC="${base_dir}/battery_api.py"
  MONITOR_SRC="${base_dir}/battery_monitor.py"

  if [[ ! -f "${API_SRC}" ]]; then
    echo "Erro: arquivo nao encontrado: ${API_SRC}" >&2
    exit 1
  fi

  if [[ ! -f "${MONITOR_SRC}" ]]; then
    echo "Erro: arquivo nao encontrado: ${MONITOR_SRC}" >&2
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
    echo "Dependencia 'pymodbus' nao encontrada. Tentando instalar com pip..."
    "${PYTHON_BIN}" -m pip install pymodbus
    INSTALLED_PIP_PACKAGES+=(pymodbus)
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
  chmod 755 "${INSTALL_DIR}/battery_api.py" "${INSTALL_DIR}/battery_monitor.py"
}

write_env_file() {
  cat > "${ENV_FILE}" <<EOF
HOST=${HOST}
PORT=${PORT}
MODBUS_PORT=${MODBUS_PORT}
BAUDRATE=${BAUDRATE}
MODBUS_TIMEOUT=${MODBUS_TIMEOUT}
PYTHON_BIN=${PYTHON_BIN}
EOF
  chmod 600 "${ENV_FILE}"
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
ExecStart=${PYTHON_BIN} ${INSTALL_DIR}/battery_api.py --host \${HOST} --port \${PORT} --env-file ${ENV_FILE} --service-name ${SERVICE_NAME} --modbus-port \${MODBUS_PORT} --baudrate \${BAUDRATE} --modbus-timeout \${MODBUS_TIMEOUT}
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
}

main() {
  parse_args "$@"
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
  show_status
}

main "$@"
