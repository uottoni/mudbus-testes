#!/bin/bash
# Instalação via repositório oficial Zabbix

set -e
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================"
echo "INSTALAÇÃO ZABBIX AGENT 2 - Repositório"
echo "========================================"
echo ""

echo -e "${GREEN}[1/6]${NC} Instalando dependências..."
apt update
apt install -y wget gnupg2

echo -e "${GREEN}[2/6]${NC} Adicionando repositório Zabbix 6.4..."
wget https://repo.zabbix.com/zabbix/6.4/ubuntu/pool/main/z/zabbix-release/zabbix-release_6.4-1+ubuntu20.04_all.deb
dpkg -i zabbix-release_6.4-1+ubuntu20.04_all.deb
apt update

echo -e "${GREEN}[3/6]${NC} Instalando Zabbix Agent 2..."
apt install -y zabbix-agent2 zabbix-agent2-plugin-*

echo -e "${GREEN}[4/6]${NC} Adicionando zabbix ao grupo dialout..."
usermod -a -G dialout zabbix

echo -e "${GREEN}[5/6]${NC} Parando serviço..."
systemctl stop zabbix-agent2 || true
systemctl disable zabbix-agent2 || true

echo -e "${GREEN}[6/6]${NC} Criando diretórios..."
mkdir -p /etc/zabbix/zabbix_agent2.d
mkdir -p /var/log/zabbix
chown -R zabbix:zabbix /var/log/zabbix

echo ""
echo -e "${GREEN}✓${NC} Instalado com sucesso!"
zabbix_agent2 --version
echo ""
echo "Próximo: sudo bash install_zabbix_agent2_configure.sh"
