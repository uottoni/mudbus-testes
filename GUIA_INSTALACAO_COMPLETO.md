# GUIA COMPLETO DE INSTALAÇÃO - Zabbix Agent 2 no Orange Pi
# Compilação e Configuração

## 📋 VISÃO GERAL

Este guia irá:
1. ✅ Compilar o Zabbix Agent 2 do código fonte
2. ✅ Configurar o serviço systemd
3. ✅ Instalar a integração com Battery Monitor
4. ✅ Testar a instalação completa

---

## 🚀 INSTALAÇÃO EM 3 PASSOS

### **PASSO 1: Compilar Zabbix Agent 2**

```bash
# Execute como root
sudo bash install_zabbix_agent2_compile.sh
```

**O que este script faz:**
- Instala dependências de compilação
- Baixa código fonte do Zabbix 6.4.10
- Compila o Zabbix Agent 2
- Instala binários em /usr/local/sbin/

**Tempo estimado:** 10-15 minutos (dependendo do hardware)

---

### **PASSO 2: Configurar Zabbix Agent 2**

```bash
# Execute como root
sudo bash install_zabbix_agent2_configure.sh
```

**Durante a execução, você será solicitado a fornecer:**
- **IP do Zabbix Server:** Ex: 192.168.1.100
- **Hostname do Orange Pi:** Ex: orangepi-battery-01

**O que este script faz:**
- Cria diretórios necessários
- Configura arquivo zabbix_agent2.conf
- Cria serviço systemd
- Configura permissões corretas

---

### **PASSO 3: Instalar Integração com Baterias**

```bash
# Execute como root
sudo bash install_battery_integration.sh
```

**O que este script faz:**
- Copia scripts Python para /usr/local/bin/
- Instala UserParameters em /etc/zabbix/zabbix_agent2.d/
- Testa discovery de baterias
- Reinicia serviço

---

## ⚡ INSTALAÇÃO RÁPIDA (ALL-IN-ONE)

Se preferir executar tudo de uma vez:

```bash
# Como root
sudo bash install_zabbix_agent2_compile.sh && \
sudo bash install_zabbix_agent2_configure.sh && \
sudo bash install_battery_integration.sh
```

---

## 🧪 TESTES DE VALIDAÇÃO

### 1. Verificar se o serviço está rodando

```bash
sudo systemctl status zabbix-agent2
```

**Saída esperada:**
```
● zabbix-agent2.service - Zabbix Agent 2
   Loaded: loaded (/etc/systemd/system/zabbix-agent2.service; enabled)
   Active: active (running) since ...
```

### 2. Verificar versão instalada

```bash
/usr/local/sbin/zabbix_agent2 --version
```

### 3. Testar discovery de baterias

```bash
zabbix_agent2 -t battery.discover
```

**Saída esperada:**
```
battery.discover                              [t|{"data": [{"#BATTERY_ID": "1", ...}]}]
```

### 4. Testar coleta de métricas

```bash
zabbix_agent2 -t battery.metric[1,voltage]
zabbix_agent2 -t battery.metric[1,soc]
zabbix_agent2 -t battery.metric[1,temp_max]
```

### 5. Verificar logs

```bash
sudo tail -f /var/log/zabbix/zabbix_agent2.log
```

### 6. Verificar porta (se Server ativo)

```bash
sudo netstat -tlnp | grep 10050
```

---

## 📁 ESTRUTURA DE ARQUIVOS

Após instalação completa:

```
/usr/local/sbin/
  └─ zabbix_agent2              # Binário principal

/etc/zabbix/
  ├─ zabbix_agent2.conf         # Configuração principal
  └─ zabbix_agent2.d/
      └─ battery_monitor.conf   # UserParameters baterias

/usr/local/bin/
  ├─ battery_monitor.py         # Biblioteca principal
  └─ battery_zabbix.py          # Script integração

/var/log/zabbix/
  └─ zabbix_agent2.log          # Logs

/var/run/zabbix/
  └─ zabbix_agent2.pid          # PID do processo

/etc/systemd/system/
  └─ zabbix-agent2.service      # Serviço systemd
```

---

## ⚙️ COMANDOS ÚTEIS

### Gerenciamento do serviço

```bash
# Iniciar
sudo systemctl start zabbix-agent2

# Parar
sudo systemctl stop zabbix-agent2

# Reiniciar
sudo systemctl restart zabbix-agent2

# Status
sudo systemctl status zabbix-agent2

# Habilitar no boot
sudo systemctl enable zabbix-agent2

# Desabilitar no boot
sudo systemctl disable zabbix-agent2

# Ver logs em tempo real
sudo journalctl -u zabbix-agent2 -f
```

### Editar configurações

```bash
# Arquivo principal
sudo nano /etc/zabbix/zabbix_agent2.conf

# UserParameters das baterias
sudo nano /etc/zabbix/zabbix_agent2.d/battery_monitor.conf

# Após editar, reiniciar
sudo systemctl restart zabbix-agent2
```

### Testar UserParameters

```bash
# Teste de items
zabbix_agent2 -t <key>

# Exemplos:
zabbix_agent2 -t system.hostname
zabbix_agent2 -t agent.ping
zabbix_agent2 -t battery.discover
zabbix_agent2 -t battery.metric[1,voltage]
```

---

## 🔧 CONFIGURAÇÃO AVANÇADA

### Ajustar timeout para baterias

Edite `/etc/zabbix/zabbix_agent2.conf`:

```ini
# Aumentar timeout se necessário
Timeout=30
```

### Configurar porta customizada

```ini
# Porta padrão é 10050
# Para alterar:
# ListenPort=10051
```

### Debug mode

```ini
# Para troubleshooting
DebugLevel=4
```

### Habilitar comandos remotos (cuidado!)

```ini
# Permite execução remota de comandos
AllowKey=system.run[*]
```

---

## 📊 PRÓXIMOS PASSOS NO ZABBIX SERVER

### 1. Importar template

- Acesse Zabbix Web Interface
- **Configuration** → **Templates**
- Clique em **Import**
- Selecione: `zabbix_template_battery_uplfp48100.yaml`
- **Import**

### 2. Adicionar host

- **Configuration** → **Hosts**
- Clique em **Create host**
- **Host name:** orangepi-battery-01 (mesmo do Hostname configurado)
- **Groups:** Linux servers, Power
- **Interfaces:**
  - Type: Agent
  - IP: [IP do Orange Pi]
  - Port: 10050
- **Templates:** Battery UPLFP48100 Modbus
- **Save**

### 3. Aguardar discovery

- Aguarde ~5 minutos para conectividade
- Aguarde ~1 hora para discovery automático de baterias
- Ou force discovery manualmente

### 4. Verificar dados chegando

- **Monitoring** → **Latest data**
- Filtrar por host: orangepi-battery-01
- Verificar items coletando dados

---

## 🔍 TROUBLESHOOTING

### Problema: Serviço não inicia

**Verificar:**
```bash
# Verificar erros no log
sudo tail -100 /var/log/zabbix/zabbix_agent2.log

# Verificar sintaxe do config
/usr/local/sbin/zabbix_agent2 -t agent.ping -c /etc/zabbix/zabbix_agent2.conf

# Verificar permissões
ls -l /var/run/zabbix/
ls -l /var/log/zabbix/

# Recriar usuário se necessário
sudo userdel zabbix
sudo useradd -r -s /sbin/nologin -d /var/lib/zabbix -g dialout zabbix
```

### Problema: Não consegue acessar porta serial

**Verificar:**
```bash
# Verificar se zabbix está no grupo dialout
groups zabbix

# Adicionar ao grupo
sudo usermod -a -G dialout zabbix

# Verificar permissões da porta
ls -l /dev/ttyUSB0

# Reiniciar serviço
sudo systemctl restart zabbix-agent2
```

### Problema: Discovery não retorna baterias

**Verificar:**
```bash
# Testar como usuário zabbix
sudo -u zabbix /usr/local/bin/battery_zabbix.py --discover

# Testar descoberta manual
python3 /usr/local/bin/battery_monitor.py --scan

# Verificar se pymodbus está instalado
python3 -c "import pymodbus; print('OK')"

# Instalar se necessário
pip3 install pymodbus
```

### Problema: Zabbix Server não conecta

**Verificar firewall:**
```bash
# Ubuntu/Debian
sudo ufw status
sudo ufw allow 10050/tcp

# Verificar se porta está escutando
sudo netstat -tlnp | grep 10050
```

**Verificar configuração:**
```bash
# IP do Server está correto?
grep "^Server=" /etc/zabbix/zabbix_agent2.conf

# Testar conectividade
ping [IP_DO_SERVER]

# Verificar logs
sudo tail -f /var/log/zabbix/zabbix_agent2.log
```

### Problema: Erro de compilação

**Falta de dependências:**
```bash
# Reinstalar dependências
sudo apt install -y \
    build-essential \
    libpcre3-dev \
    zlib1g-dev \
    libssl-dev \
    pkg-config \
    libevent-dev

# Limpar e recompilar
cd /tmp/zabbix-install/zabbix-6.4.10
make clean
./configure --enable-agent2 --prefix=/usr/local --sysconfdir=/etc/zabbix --with-openssl
make -j$(nproc)
sudo make install
```

---

## 📈 OTIMIZAÇÕES

### Para múltiplas baterias (até 2)

O intervalo de 1 minuto já está configurado e é adequado para 2 baterias.

### Reduzir uso de recursos

Edite `/etc/zabbix/zabbix_agent2.d/battery_monitor.conf`:

```bash
# Aumentar intervalo de discovery se baterias não mudam
# No template, alterar delay de 1h para 12h
```

### Monitoramento de logs

```bash
# Adicionar rotação de logs
sudo nano /etc/logrotate.d/zabbix-agent2
```

```
/var/log/zabbix/zabbix_agent2.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 zabbix zabbix
    postrotate
        systemctl reload zabbix-agent2 > /dev/null 2>&1 || true
    endscript
}
```

---

## 🎯 CHECKLIST DE VALIDAÇÃO FINAL

- [ ] Zabbix Agent 2 compilado com sucesso
- [ ] Serviço zabbix-agent2 rodando
- [ ] Usuário zabbix no grupo dialout
- [ ] Scripts Python em /usr/local/bin/
- [ ] UserParameters instalados
- [ ] Discovery funcionando
- [ ] Métricas retornando valores
- [ ] Template importado no Zabbix
- [ ] Host adicionado no Zabbix
- [ ] Dados chegando no Zabbix Server
- [ ] Triggers configurados
- [ ] Alertas testados

---

## 📞 SUPORTE

Se encontrar problemas:

1. Verifique logs: `/var/log/zabbix/zabbix_agent2.log`
2. Teste manualmente: `battery_zabbix.py --discover`
3. Verifique permissões: `groups zabbix`
4. Revise configurações: `/etc/zabbix/zabbix_agent2.conf`
5. Consulte documentação oficial: https://www.zabbix.com/documentation/6.4/manual

---

✅ **Instalação completa!** Agora você tem um sistema de monitoramento profissional para suas baterias UPLFP48100!
