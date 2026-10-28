# Monitor de baterias UPLFP48100

Monitoramento de baterias de lítio UPLFP48100 (até 16 módulos em um barramento RS-485, via Modbus RTU) e de temperatura/umidade ambiente (sensor DHT11), rodando em uma Orange Pi PC com Armbian.

Os dados ficam disponíveis por:

- **API HTTP** (JSON), com uma página web para configurar a rede;
- **SNMP v2c** (`snmpd` com agente `pass_persist`);
- **Zabbix Agent 2** (UserParameters, opcional).

## Hardware

- Orange Pi PC (Allwinner H3) com Armbian (testado no 26.11, kernel 6.18).
- Conversor USB/RS-485 ligado ao barramento das baterias (padrão `/dev/ttyUSB0`, 9600 8N1).
- Módulo DHT11 de 3 pinos (opcional).

### Ligação do DHT11

| Sensor | Orange Pi PC |
|---|---|
| `+` | pino 1 (3,3 V) |
| `out` | pino 7 (PA6) |
| `-` | pino 6 (GND) |

Alimente o sensor com **3,3 V, nunca 5 V**: o sinal de dados volta na tensão de alimentação e os GPIOs do H3 não toleram 5 V. Outros pinos podem ser usados com `--dht-pin`, desde que sejam das portas PA ou PG (as únicas com interrupção no H3).

## Instalação

Na placa, com os arquivos do repositório:

```bash
sudo bash install_battery_api_service.sh --snmp-community <community>
```

O script:

- instala as dependências (APT: `snmpd`, `lldpd`, `ndisc6`, `netplan.io`, `python3-pip`, `python3-libgpiod`; pip: `pymodbus>=3.0,<3.10`, `pyserial`);
- copia os scripts para `/opt/battery-api/` e grava a configuração em `/etc/battery-api.env`;
- cria e inicia o serviço systemd `battery-api`;
- configura o `snmpd`: escuta em IPv4/IPv6, community somente leitura restrita à árvore das baterias e o agente `pass_persist`;
- configura o `lldpd` e o NDP/IPv6;
- pede a troca da senha do root, a menos que se use `--skip-root-password-change`.

Principais opções (lista completa em `--help`):

| Opção | Padrão | Descrição |
|---|---|---|
| `--snmp-community <texto>` | — | Community SNMP v2c (obrigatória) |
| `--port <porta>` | `8080` | Porta da API HTTP |
| `--modbus-port <porta>` | `/dev/ttyUSB0` | Porta serial do barramento |
| `--baudrate <baud>` | `9600` | Baudrate Modbus |
| `--dht-pin <pino\|none>` | `PA6` | Pino de dados do DHT11; `none` desativa o sensor |
| `--dht-interval <s>` | `10` | Intervalo entre leituras do DHT11 |
| `--snmp-oid <oid>` | `.1.3.6.1.4.1.99999.1` | OID base exportado |
| `--skip-root-password-change` | — | Não pede a troca da senha do root |

Depois da instalação:

```bash
sudo systemctl status battery-api
sudo journalctl -u battery-api -f
curl http://<ip-da-placa>:8080/health
```

Para mudar a configuração depois, edite `/etc/battery-api.env` e reinicie o serviço com `sudo systemctl restart battery-api`.

### Desinstalação

```bash
sudo bash uninstall_battery_api_service.sh [--purge] [--keep-deps]
```

Remove o serviço e a configuração e desfaz os ajustes de LLDP/NDP. As dependências instaladas pelo script também são removidas, a menos que se use `--keep-deps`. Com `--purge`, apaga também `/opt/battery-api/`.

## API HTTP

| Método | Caminho | Descrição |
|---|---|---|
| GET | `/health` | Verificação de vida: `{"status": "ok"}` |
| GET/POST | `/batteries` | Leituras das baterias. Filtros: `ids` (ex: `1,2,5`) ou `start_id`/`end_id` |
| GET/POST | `/discover` | IDs de baterias que estão respondendo. Filtros: `start_id`/`end_id` |
| GET | `/environment` | Temperatura e umidade ambiente (DHT11) |
| GET/POST | `/config/network` | Lê/grava a configuração de rede (`host`, `port`, `netmask`, `gateway`, `dns`, `apply_system`) |
| GET | `/` | Página web de configuração de rede |

Os parâmetros vão na query string (GET) ou em um corpo JSON (POST).

A API **não lê o barramento a cada requisição**. Uma thread varre os IDs 1–16 a cada 10 s e mantém um cache, e as requisições são respondidas a partir dele. Uma bateria que deixa de responder continua no cache por até 3 ciclos antes de ser removida. As respostas trazem `cache_updated_at` e `cache_error`.

Exemplo de `/environment`:

```json
{"enabled": true, "sensor": "dht11", "pin": "PA6", "temperature": 24.7, "humidity": 54.0,
 "cache_updated_at": "2026-10-28T09:23:35+00:00", "cache_error": ""}
```

A temperatura e a umidade publicadas são a mediana das 3 últimas leituras válidas, o que descarta leituras isoladas erradas. Com o intervalo padrão de 10 s, uma mudança real aparece em cerca de 20 s.

## SNMP

OID base: `.1.3.6.1.4.1.99999.1`. O PEN 99999 é um número privado de exemplo; registre o seu na [IANA](https://www.iana.org/assignments/enterprise-numbers) e use `--snmp-oid`.

| OID (relativo à base) | Tipo | Conteúdo |
|---|---|---|
| `.1.0` | integer | Total de baterias |
| `.2.<id>.1` | integer | ID da bateria |
| `.2.<id>.2` | string | Status: `Stand by` / `Charging` / `Discharging` |
| `.2.<id>.3` | gauge | SOC (%) |
| `.2.<id>.4` | gauge | SOH (%) |
| `.2.<id>.5` | gauge | Tensão total (mV) |
| `.2.<id>.6` | integer | Corrente (mA; negativo = descarga) |
| `.2.<id>.7` | gauge | Potência (W) |
| `.2.<id>.8` | gauge | Temperatura máxima (°C) |
| `.2.<id>.9` | gauge | Tensão mínima de célula (mV) |
| `.2.<id>.10` | gauge | Tensão máxima de célula (mV) |
| `.2.<id>.11` | gauge | Diferença entre células (mV) |
| `.3.1.0` | integer | Temperatura ambiente, em décimos de °C (ex: `247` = 24,7 °C) |
| `.3.2.0` | gauge | Umidade relativa ambiente (%) |
| `.3.3.0` | integer | Sensor ambiente: `1` = leitura válida, `0` = sem leitura |

`.3.1.0` e `.3.2.0` só existem enquanto houver leitura válida. O agente SNMP lê os dados do cache da API, e não do barramento, e atualiza a cada 10 s.

```bash
snmpwalk -v2c -c <community> <ip-da-placa> .1.3.6.1.4.1.99999.1
snmpget  -v2c -c <community> <ip-da-placa> .1.3.6.1.4.1.99999.1.3.1.0 .1.3.6.1.4.1.99999.1.3.2.0
```

## Zabbix (opcional)

`battery_zabbix.py` e `battery_monitor.conf` oferecem descoberta (LLD) e métricas por bateria para o Zabbix Agent 2. O install script não instala esses arquivos. Veja as instruções nos comentários de `battery_monitor.conf`.

Esse script abre a porta serial diretamente a cada chamada e pode disputar o barramento com o serviço `battery-api`. Com o serviço instalado, prefira coletar via SNMP ou HTTP.

## Uso pela linha de comando

```bash
# Baterias (lê o barramento diretamente; pare o serviço antes para não disputar a serial)
python3 battery_monitor.py --pretty                 # descobre IDs 1-16 e lê todas
python3 battery_monitor.py --discover
python3 battery_monitor.py --ids 1,2,5

# DHT11 (requer root)
sudo python3 dht_sensor.py --pin PA6 --count 5
```

## Estrutura

| Arquivo | Função |
|---|---|
| `battery_monitor.py` | Leitura Modbus RTU e decodificação dos registradores das baterias |
| `battery_api.py` | API HTTP, cache das baterias e do sensor ambiente, configuração de rede |
| `battery_snmp_agent.py` | Agente SNMP `pass_persist` |
| `dht_sensor.py` | Leitura do DHT11 em userspace (libgpiod + registradores do H3) |
| `battery_zabbix.py`, `battery_monitor.conf` | Integração com Zabbix Agent 2 |
| `install_battery_api_service.sh`, `uninstall_battery_api_service.sh` | Instalação e remoção do serviço |
| `dados-testes/` | Capturas reais de quadros Modbus e exportações da ferramenta do BMS |

## Notas

- **pymodbus fixado em `<3.10`:** o código usa o argumento `slave=`, que a versão 3.10 renomeou para `device_id=`. O projeto foi escrito no firmware Ubuntu antigo do fabricante, e no Armbian o pip instalaria uma versão nova incompatível.
- **DHT11 sem driver de kernel:** o kernel do Armbian não inclui o driver `dht11`, por isso a leitura é feita em userspace. Para isso o código ajusta o debounce de interrupção da porta do pino e gera o pulso de start pelos registradores do PIO (`/dev/mem`), o que exige root. Os detalhes estão na docstring de `dht_sensor.py`.
