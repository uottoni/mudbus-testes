#!/bin/bash
# Configuração do Zabbix Agent 2 instalado via repositório

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================"
echo "CONFIGURAÇÃO ZABBIX AGENT 2"
echo "========================================"
echo ""

# Solicitar informações
echo -e "${YELLOW}Configuração necessária:${NC}"
read -p "IP do Zabbix Server: " ZABBIX_SERVER_IP
read -p "Hostname deste Orange Pi: " HOSTNAME

echo ""
echo -e "${GREEN}[1/4]${NC} Fazendo backup da configuração original..."
cp /etc/zabbix/zabbix_agent2.conf /etc/zabbix/zabbix_agent2.conf.bak

echo -e "${GREEN}[2/4]${NC} Configurando zabbix_agent2.conf..."
cat > /etc/zabbix/zabbix_agent2.conf << EOF
# Zabbix Agent 2 Configuration File

# Servidor Zabbix
Server=${ZABBIX_SERVER_IP}
ServerActive=${ZABBIX_SERVER_IP}

# Identificação do host
Hostname=${HOSTNAME}

# Diretórios
PidFile=/run/zabbix/zabbix_agent2.pid
LogFile=/var/log/zabbix/zabbix_agent2.log
LogFileSize=10

# Includes para UserParameters customizados
Include=/etc/zabbix/zabbix_agent2.d/*.conf

# Timeout para execução de comandos
Timeout=30

# Buffer de dados
BufferSize=100
BufferSend=5
EOF

echo -e "${GREEN}[3/4]${NC} Verificando permissões..."
chown -R zabbix:zabbix /var/log/zabbix /run/zabbix 2>/dev/null || true

echo -e "${GREEN}[4/4]${NC} Habilitando e iniciando serviço..."
systemctl daemon-reload
systemctl enable zabbix-agent2
systemctl start zabbix-agent2
sleep 2

echo ""
echo -e "${GREEN}✓${NC} Configuração concluída!"
echo ""

# Verificar status
if systemctl is-active --quiet zabbix-agent2; then
    echo -e "${GREEN}✓ Serviço está rodando!${NC}"
    systemctl status zabbix-agent2 --no-pager -l
else
    echo -e "${RED}✗ Serviço não iniciou. Verificando logs...${NC}"
    tail -20 /var/log/zabbix/zabbix_agent2.log
fi

echo ""
echo -e "${YELLOW}Próximo passo:${NC}"
echo "  bash install_battery_integration.sh"
echo ""
