#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="battery-api"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
ENV_FILE="/etc/${SERVICE_NAME}.env"
INSTALL_DIR="/opt/battery-api"
STATE_FILE="/etc/${SERVICE_NAME}-install.state"
LLDP_DEFAULT_FILE="/etc/default/lldpd"
LLDP_HOSTNAME_FILE="/etc/lldpd.d/10-hostname.conf"
NDP_SYSCTL_FILE="/etc/sysctl.d/99-ndp-enable.conf"

usage() {
  cat <<EOF
Uso:
  sudo bash uninstall_battery_api_service.sh [--purge] [--keep-files] [--keep-deps]

Opcoes:
  --purge       Remove tambem o diretorio ${INSTALL_DIR}
  --keep-files  Mantem ${INSTALL_DIR} mesmo com --purge ausente
  --keep-deps   Nao remove dependencias instaladas pelo script
  -h, --help    Mostra esta ajuda

Comportamento padrao:
  - Para e desabilita o servico ${SERVICE_NAME}
  - Remove ${SERVICE_FILE}, ${ENV_FILE} e ${STATE_FILE}
  - Reverte ajustes de LLDP/NDP aplicados pelo instalador
  - Remove dependencias registradas no estado (APT/pip)
  - Mantem ${INSTALL_DIR}
EOF
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Erro: execute como root (use sudo)." >&2
    exit 1
  fi
}

parse_args() {
  PURGE=0
  KEEP_FILES=0
  KEEP_DEPS=0

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --purge)
        PURGE=1
        shift
        ;;
      --keep-files)
        KEEP_FILES=1
        shift
        ;;
      --keep-deps)
        KEEP_DEPS=1
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

load_state() {
  INSTALLED_APT_PACKAGES=""
  INSTALLED_PIP_PACKAGES=""
  PYTHON_BIN="/usr/bin/python3"

  if [[ -f "${STATE_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${STATE_FILE}"
  fi
}

stop_disable_service() {
  if systemctl list-unit-files | grep -q "^${SERVICE_NAME}\.service"; then
    echo "Parando servico ${SERVICE_NAME}..."
    systemctl stop "${SERVICE_NAME}" || true

    echo "Desabilitando servico ${SERVICE_NAME}..."
    systemctl disable "${SERVICE_NAME}" || true
  else
    echo "Servico ${SERVICE_NAME} nao encontrado no systemd."
  fi
}

remove_service_files() {
  if [[ -f "${SERVICE_FILE}" ]]; then
    echo "Removendo ${SERVICE_FILE}..."
    rm -f "${SERVICE_FILE}"
  fi

  if [[ -f "${ENV_FILE}" ]]; then
    echo "Removendo ${ENV_FILE}..."
    rm -f "${ENV_FILE}"
  fi

  if [[ -f "${STATE_FILE}" ]]; then
    echo "Removendo ${STATE_FILE}..."
    rm -f "${STATE_FILE}"
  fi

  systemctl daemon-reload
  systemctl reset-failed || true
}

revert_lldp_ndp() {
  if [[ -f "${LLDP_HOSTNAME_FILE}" ]]; then
    echo "Removendo override de hostname LLDP..."
    rm -f "${LLDP_HOSTNAME_FILE}"
  fi

  if [[ -f "${LLDP_DEFAULT_FILE}" ]]; then
    echo "Restaurando configuracao padrao do lldpd..."
    cat > "${LLDP_DEFAULT_FILE}" <<EOF
# Uncomment to start SNMP subagent and enable CDP, SONMP and EDP protocol
#DAEMON_ARGS="-x -c -s -e"
EOF
  fi

  if systemctl list-unit-files | grep -q "^lldpd\.service"; then
    systemctl restart lldpd || true
  fi

  if [[ -f "${NDP_SYSCTL_FILE}" ]]; then
    echo "Removendo ajuste persistente NDP/IPv6..."
    rm -f "${NDP_SYSCTL_FILE}"
    sysctl --system >/dev/null || true
  fi
}

remove_tracked_dependencies() {
  if [[ "${KEEP_DEPS}" -eq 1 ]]; then
    echo "Mantendo dependencias instaladas (opcao --keep-deps)."
    return
  fi

  if [[ -n "${INSTALLED_PIP_PACKAGES:-}" ]]; then
    if command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
      echo "Removendo dependencias pip registradas: ${INSTALLED_PIP_PACKAGES}"
      "${PYTHON_BIN}" -m pip uninstall -y ${INSTALLED_PIP_PACKAGES} || true
    fi
  fi

  if [[ -n "${INSTALLED_APT_PACKAGES:-}" ]]; then
    echo "Removendo dependencias APT registradas: ${INSTALLED_APT_PACKAGES}"
    apt-get remove -y ${INSTALLED_APT_PACKAGES} || true
    apt-get autoremove -y || true
  fi
}

remove_install_dir_if_requested() {
  if [[ "${PURGE}" -eq 1 && "${KEEP_FILES}" -eq 0 ]]; then
    if [[ -d "${INSTALL_DIR}" ]]; then
      echo "Removendo ${INSTALL_DIR}..."
      rm -rf "${INSTALL_DIR}"
    fi
  fi
}

show_result() {
  echo
  echo "Desinstalacao concluida."
  if [[ "${PURGE}" -eq 1 && "${KEEP_FILES}" -eq 0 ]]; then
    echo "Arquivos da aplicacao removidos: ${INSTALL_DIR}"
  else
    echo "Arquivos da aplicacao mantidos em: ${INSTALL_DIR}"
  fi
}

main() {
  parse_args "$@"
  require_root
  load_state
  stop_disable_service
  revert_lldp_ndp
  remove_tracked_dependencies
  remove_service_files
  remove_install_dir_if_requested
  show_result
}

main "$@"
