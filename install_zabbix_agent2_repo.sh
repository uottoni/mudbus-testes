#!/bin/bash
# Instalação do Zabbix Agent 2 via repositório (alternativa)
# Mais rápido e confiável para ARM

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "========================================"
echo "INSTALAÇÃO ZABBIX AGENT 2 - Via Repositório"
echo "========================================"
echo ""

echo -e "${GREEN}[1/5]${NC} Removendo instalações antigas..."
systemctl stop zabbix-agent2 2>/dev/null || true
apt remove -y zabbix-agent2 2>/dev/null || true

echo -e "${GREEN}[2/5]${NC} Adicionando repositório Zabbix..."
wget -q https://repo.zabbix.com/zabbix/6.4/ubuntu/pool/main/z/zabbix-release/zabbix-release_6.4-1+ubuntu20.04_all.deb
dpkg -i zabbix-release_6.4-1+ubuntu20.04_all.deb
apt update

echo -e "${GREEN}[3/5]${NC} Instalando Zabbix Agent 2..."
apt install -y zabbix-agent2 zabbix-agent2-plugin-*

echo -e "${GREEN}[4/5]${NC} Criando/ajustando usuário..."
usermod -a -G dialout zabbix 2>/dev/null || true

echo -e "${GREEN}[5/5]${NC} Parando serviço (para configurar depois)..."
systemctl stop zabbix-agent2
systemctl disable zabbix-agent2

echo ""
echo -e "${GREEN}✓${NC} Instalação concluída!"
echo ""
echo -e "${YELLOW}Arquivos instalados:${NC}"
echo "  Binário:      /usr/sbin/zabbix_agent2"
echo "  Config:       /etc/zabbix/zabbix_agent2.conf"
echo "  UserParams:   /etc/zabbix/zabbix_agent2.d/"
echo "  Service:      /lib/systemd/system/zabbix-agent2.service"
echo ""
echo -e "${YELLOW}Próximo passo:${NC}"
echo "  bash install_zabbix_agent2_configure_repo.sh"
echo ""
