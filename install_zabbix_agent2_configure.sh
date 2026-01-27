#!/bin/bash
# Script de configuração pós-instalação do Zabbix Agent 2
# Parte 2: Configuração

set -e

# Cores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================"
echo "CONFIGURAÇÃO ZABBIX AGENT 2"
echo "========================================"
echo ""

# Solicitar IP do Zabbix Server
echo -e "${YELLOW}Configuração necessária:${NC}"
read -p "IP do Zabbix Server: " ZABBIX_SERVER_IP
read -p "Hostname deste Orange Pi: " HOSTNAME

echo ""
echo -e "${GREEN}[1/6]${NC} Criando diretórios..."
mkdir -p /etc/zabbix
mkdir -p /etc/zabbix/zabbix_agent2.d
mkdir -p /var/log/zabbix
mkdir -p /var/run/zabbix
mkdir -p /var/lib/zabbix

echo -e "${GREEN}[2/6]${NC} Ajustando permissões..."
chown -R zabbix:dialout /var/log/zabbix
chown -R zabbix:dialout /var/run/zabbix
chown -R zabbix:dialout /var/lib/zabbix
chmod 755 /var/log/zabbix
chmod 755 /var/run/zabbix

echo -e "${GREEN}[3/6]${NC} Criando configuração principal..."
cat > /etc/zabbix/zabbix_agent2.conf << EOF
# Zabbix Agent 2 Configuration File
# Gerado automaticamente

# Servidor Zabbix
Server=${ZABBIX_SERVER_IP}
ServerActive=${ZABBIX_SERVER_IP}

# Identificação do host
Hostname=${HOSTNAME}

# Diretórios
PidFile=/var/run/zabbix/zabbix_agent2.pid
LogFile=/var/log/zabbix/zabbix_agent2.log
LogFileSize=10

# Includes para UserParameters customizados
Include=/etc/zabbix/zabbix_agent2.d/*.conf

# Timeout para execução de comandos
Timeout=30

# Permitir comandos remotos (cuidado!)
# AllowKey=system.run[*]

# Buffer de dados
BufferSize=100
BufferSend=5
EOF

echo -e "${GREEN}[4/6]${NC} Criando serviço systemd..."
cat > /etc/systemd/system/zabbix-agent2.service << EOF
[Unit]
Description=Zabbix Agent 2
After=syslog.target
After=network.target

[Service]
Type=simple
User=zabbix
Group=dialout
PIDFile=/var/run/zabbix/zabbix_agent2.pid
ExecStart=/usr/local/sbin/zabbix_agent2 -c /etc/zabbix/zabbix_agent2.conf
ExecStop=/bin/kill -SIGTERM \$MAINPID
Restart=on-failure
RestartSec=10s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo -e "${GREEN}[5/6]${NC} Recarregando systemd..."
systemctl daemon-reload

echo -e "${GREEN}[6/6]${NC} Habilitando serviço..."
systemctl enable zabbix-agent2

echo ""
echo -e "${GREEN}✓${NC} Configuração concluída!"
echo ""
echo -e "${YELLOW}Para iniciar o serviço:${NC}"
echo "  sudo systemctl start zabbix-agent2"
echo ""
echo -e "${YELLOW}Para verificar status:${NC}"
echo "  sudo systemctl status zabbix-agent2"
echo ""
echo -e "${YELLOW}Para ver logs:${NC}"
echo "  sudo tail -f /var/log/zabbix/zabbix_agent2.log"
echo ""
echo -e "${YELLOW}Arquivo de configuração:${NC}"
echo "  /etc/zabbix/zabbix_agent2.conf"
echo ""
echo -e "${YELLOW}UserParameters customizados:${NC}"
echo "  /etc/zabbix/zabbix_agent2.d/"
echo ""
