# GUIA DE INSTALAÇÃO - Integração Zabbix com Baterias UPLFP48100

## 📋 PRÉ-REQUISITOS

1. **Zabbix Agent 2** instalado no Orange Pi
2. **Python 3** com pymodbus instalado
3. **Permissões** de acesso à porta serial (/dev/ttyUSB0)

---

## 🚀 INSTALAÇÃO PASSO A PASSO

### 1. Instalar dependências Python

```bash
sudo apt update
sudo apt install python3-pip
pip3 install pymodbus
```

### 2. Copiar scripts para diretório do sistema

```bash
# Copiar biblioteca principal
sudo cp battery_monitor.py /usr/local/bin/

# Copiar script de integração Zabbix
sudo cp battery_zabbix.py /usr/local/bin/

# Dar permissão de execução
sudo chmod +x /usr/local/bin/battery_zabbix.py
sudo chmod +x /usr/local/bin/battery_monitor.py
```

### 3. Configurar permissões de porta serial

```bash
# Adicionar usuário zabbix ao grupo dialout
sudo usermod -a -G dialout zabbix

# Verificar
groups zabbix
```

### 4. Instalar configuração do Zabbix Agent 2

```bash
# Copiar arquivo de configuração
sudo cp battery_monitor.conf /etc/zabbix/zabbix_agent2.d/

# Verificar sintaxe
sudo zabbix_agent2 -t battery.discover
```

### 5. Reiniciar Zabbix Agent 2

```bash
sudo systemctl restart zabbix-agent2
sudo systemctl status zabbix-agent2
```

---

## 🧪 TESTES

### Testar discovery

```bash
/usr/local/bin/battery_zabbix.py --discover
```

**Saída esperada:**
```json
{
  "data": [
    {
      "{#BATTERY_ID}": "1",
      "{#BATTERY_NAME}": "Battery 1"
    }
  ]
}
```

### Testar coleta de métricas

```bash
# Tensão da bateria ID 1
/usr/local/bin/battery_zabbix.py --id 1 --metric voltage

# SOC da bateria ID 1
/usr/local/bin/battery_zabbix.py --id 1 --metric soc

# Todos os dados em JSON
/usr/local/bin/battery_zabbix.py --id 1 --json
```

### Testar via Zabbix Agent

```bash
# Discovery
zabbix_agent2 -t battery.discover

# Métrica específica
zabbix_agent2 -t battery.metric[1,voltage]
zabbix_agent2 -t battery.metric[1,soc]
```

---

## 📊 IMPORTAR TEMPLATE NO ZABBIX

### 1. Acessar interface web do Zabbix

- Vá para: **Configuration** → **Templates**

### 2. Importar template

- Clique em **Import**
- Selecione o arquivo: `zabbix_template_battery_uplfp48100.yaml`
- Marque opções:
  - ✅ Create new
  - ✅ Update existing
- Clique em **Import**

### 3. Aplicar template ao host

- Vá para: **Configuration** → **Hosts**
- Selecione o host (Orange Pi)
- Aba **Templates**
- Clique em **Select** e escolha: **Battery UPLFP48100 Modbus**
- Clique em **Add**
- Clique em **Update**

### 4. Verificar discovery

- Vá para: **Configuration** → **Hosts** → Seu host
- Aba **Discovery**
- Verifique se **Battery Discovery** está ativa
- Aguarde 1 hora ou force execução manual

---

## ⚙️ CONFIGURAÇÃO DE MACROS

As macros podem ser personalizadas por host:

**Configuration** → **Hosts** → Seu host → **Macros** → **Inherited and host macros**

| Macro | Valor Padrão | Descrição |
|-------|--------------|-----------|
| `{$BATTERY.SOC.WARN}` | 20 | SOC de alerta (%) |
| `{$BATTERY.SOC.CRIT}` | 10 | SOC crítico (%) |
| `{$BATTERY.TEMP.WARN}` | 45 | Temperatura de alerta (°C) |
| `{$BATTERY.TEMP.CRIT}` | 50 | Temperatura crítica (°C) |
| `{$BATTERY.CELL_DIFF.WARN}` | 0.050 | Desbalanceamento alerta (V) |
| `{$BATTERY.CELL_DIFF.CRIT}` | 0.100 | Desbalanceamento crítico (V) |
| `{$BATTERY.SOH.WARN}` | 80 | SOH de alerta (%) |

---

## 📈 ITEMS CRIADOS AUTOMATICAMENTE

Para cada bateria descoberta, serão criados os seguintes items:

### Elétricos
- ⚡ Voltage (V)
- ⚡ Current (A)
- ⚡ Power (W)

### Estado
- 📊 SOC (%)
- 📊 SOH (%)
- 📊 Status (Stand by/Charging/Discharging)

### Temperatura
- 🌡️ Temperature Max (°C)

### Células
- 🔋 Cell Voltage Min (V)
- 🔋 Cell Voltage Max (V)
- 🔋 Cell Voltage Average (V)
- 🔋 Cell Voltage Difference (V)
- 🔋 Cell Count

---

## 🚨 TRIGGERS CONFIGURADOS

### Por bateria:

| Severidade | Trigger | Condição |
|-----------|---------|----------|
| HIGH | Critical low SOC | SOC < 10% |
| WARNING | Low SOC | SOC < 20% |
| HIGH | Critical high temperature | Temp > 50°C |
| WARNING | High temperature | Temp > 45°C |
| HIGH | Critical cell imbalance | Diff > 0.100V |
| WARNING | Cell imbalance | Diff > 0.050V |
| AVERAGE | Low SOH | SOH < 80% |
| WARNING | No data received | Sem dados por 5 min |

---

## 🔍 TROUBLESHOOTING

### Problema: Discovery não encontra baterias

**Verificar:**
```bash
# Permissões da porta
ls -l /dev/ttyUSB0

# Executar manualmente
sudo -u zabbix /usr/local/bin/battery_zabbix.py --discover

# Verificar logs
tail -f /var/log/zabbix/zabbix_agent2.log
```

### Problema: Métricas retornam erro

**Verificar:**
```bash
# Testar conexão Modbus
python3 /usr/local/bin/battery_monitor.py

# Verificar timeout
# Editar /etc/zabbix/zabbix_agent2.conf
# Timeout=30
```

### Problema: Items não são criados automaticamente

**Verificar:**
- Discovery rule está habilitada?
- Intervalo de discovery passou (padrão 1h)?
- Host tem template aplicado corretamente?
- Forçar execução manual do discovery

---

## 📝 LOGS

### Zabbix Agent 2
```bash
tail -f /var/log/zabbix/zabbix_agent2.log
```

### Testar manualmente com debug
```bash
/usr/local/bin/battery_zabbix.py --discover 2>&1
/usr/local/bin/battery_zabbix.py --id 1 --metric voltage 2>&1
```

---

## 🎯 PRÓXIMOS PASSOS

1. ✅ Importar template no Zabbix
2. ✅ Aplicar template ao host
3. ✅ Aguardar discovery (1h ou forçar)
4. ✅ Configurar gráficos personalizados
5. ✅ Configurar notificações de alertas
6. ✅ Criar dashboards customizados

---

## 📞 SUPORTE

Para problemas ou dúvidas, verifique:
- Logs do Zabbix Agent 2
- Permissões de usuário
- Conexão Modbus funcionando
- Porta serial correta
