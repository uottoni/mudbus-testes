#!/bin/bash
# Script de instalação do Zabbix Agent 2 no Orange Pi
# Ubuntu 20.04 ARM (armv7l) - Compilação do GitHub

set -e  # Para em caso de erro

echo "========================================"
echo "INSTALAÇÃO ZABBIX AGENT 2 - Orange Pi"
echo "========================================"
echo ""

# Variáveis
ZABBIX_BRANCH="release/6.4"
INSTALL_DIR="/tmp/zabbix-install"
ZABBIX_USER="zabbix"

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}[1/9]${NC} Atualizando sistema..."
apt update

echo -e "${GREEN}[2/9]${NC} Instalando dependências..."
apt install -y \
    build-essential \
    autoconf \
    automake \
    libpcre3-dev \
    zlib1g-dev \
    libssl-dev \
    pkg-config \
    libevent-dev \
    git

echo -e "${GREEN}[3/9]${NC} Criando usuário e grupo zabbix..."
if ! id -u $ZABBIX_USER > /dev/null 2>&1; then
    groupadd -r dialout 2>/dev/null || true
    useradd -r -s /sbin/nologin -d /var/lib/zabbix -G dialout $ZABBIX_USER
    echo "Usuário $ZABBIX_USER criado"
else
    echo "Usuário $ZABBIX_USER já existe"
    usermod -a -G dialout $ZABBIX_USER
fi

echo -e "${GREEN}[4/9]${NC} Clonando repositório do GitHub (branch ${ZABBIX_BRANCH})..."
mkdir -p $INSTALL_DIR
cd $INSTALL_DIR

if [ -d "zabbix" ]; then
    echo "Removendo clone anterior..."
    rm -rf zabbix
fi

git clone --depth 1 --branch ${ZABBIX_BRANCH} https://github.com/zabbix/zabbix.git
cd zabbix

echo -e "${GREEN}[5/9]${NC} Executando bootstrap..."
./bootstrap.sh

echo -e "${GREEN}[6/9]${NC} Configurando compilação..."
./configure \
    --enable-agent2 \
    --prefix=/usr/local \
    --sysconfdir=/etc/zabbix \
    --with-openssl \
    --silent

echo -e "${GREEN}[7/9]${NC} Compilando Agent 2 (pode demorar 10-15 minutos)..."
make -s -j$(nproc)

echo -e "${GREEN}[8/9]${NC} Instalando binários..."
make -s install

echo -e "${GREEN}[9/9]${NC} Verificando instalação..."
/usr/local/sbin/zabbix_agent2 --version

echo ""
echo -e "${GREEN}✓${NC} Compilação concluída!"
echo ""
echo -e "${YELLOW}Próximos passos:${NC}"
echo "1. Criar diretórios e configurações"
echo "2. Configurar systemd service"
echo "3. Configurar zabbix_agent2.conf"
echo ""
echo "Execute: sudo bash install_zabbix_agent2_configure.sh"
echo ""
