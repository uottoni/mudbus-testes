#!/bin/bash
# Script para instalar configuração de monitoramento de baterias
# Parte 3: Integração com Battery Monitor

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================"
echo "INSTALAÇÃO BATTERY MONITOR INTEGRATION"
echo "========================================"
echo ""

echo -e "${GREEN}[1/4]${NC} Copiando scripts Python..."
cp battery_monitor.py /usr/local/bin/
cp battery_zabbix.py /usr/local/bin/
chmod +x /usr/local/bin/battery_zabbix.py
chmod +x /usr/local/bin/battery_monitor.py

echo -e "${GREEN}[2/4]${NC} Instalando configuração do Zabbix Agent..."
cp battery_monitor.conf /etc/zabbix/zabbix_agent2.d/

echo -e "${GREEN}[3/4]${NC} Testando discovery..."
echo "Executando: /usr/local/bin/battery_zabbix.py --discover"
sudo -u zabbix /usr/local/bin/battery_zabbix.py --discover

echo ""
echo -e "${GREEN}[4/4]${NC} Reiniciando Zabbix Agent 2..."
systemctl restart zabbix-agent2
sleep 2
systemctl status zabbix-agent2 --no-pager

echo ""
echo -e "${GREEN}✓${NC} Integração instalada com sucesso!"
echo ""
echo -e "${YELLOW}Testes disponíveis:${NC}"
echo "  zabbix_agent2 -t battery.discover"
echo "  zabbix_agent2 -t battery.metric[1,voltage]"
echo "  zabbix_agent2 -t battery.metric[1,soc]"
echo ""
echo -e "${YELLOW}Próximo passo:${NC}"
echo "  Importar template zabbix_template_battery_uplfp48100.yaml no Zabbix Server"
echo ""
