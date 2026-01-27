#!/usr/bin/env python3
"""
Monitor completo da Bateria UPLFP48100 via Modbus RTU
Mapeamento correto baseado em análise do CSV real
"""
from pymodbus.client import ModbusSerialClient
from datetime import datetime

class BatteryMonitor:
    def __init__(self, port='/dev/ttyUSB0', baudrate=9600, slave_id=1):
        self.port = port
        self.baudrate = baudrate
        self.slave_id = slave_id
        self.client = None
    
    def connect(self):
        self.client = ModbusSerialClient(
            port=self.port, baudrate=self.baudrate,
            bytesize=8, parity='N', stopbits=1, timeout=3
        )
        return self.client.connect()
    
    def disconnect(self):
        if self.client:
            self.client.close()
    
    def read_data(self):
        """Lê 39 registros e decodifica"""
        result = self.client.read_holding_registers(address=0, count=39, slave=self.slave_id)
        if result.isError():
            raise Exception(f"Erro: {result}")
        return self._parse(result.registers)
    
    def _parse(self, r):
        d = {}
        
        # Registro 0: Status/info (0x1557 = 5463)
        d['status_raw'] = r[0]
        
        # Registro 1: Corrente em 0.01A (signed 16-bit)
        current_raw = r[1]
        if current_raw > 32767:
            current_raw = current_raw - 65536
        d['current'] = current_raw / 100.0
        
        # Células: registros 2-16 (15 células em mV)
        d['cells'] = [r[i]/1000.0 for i in range(2, 17) if 2.0 < r[i]/1000.0 < 4.5]
        
        # Temperaturas: registros 18-21
        d['temps'] = [r[18], r[19], r[20], r[21] if r[21] < 100 else 0]
        
        # SOC/SOH: registros 21-22
        d['soc'] = r[21]
        d['soh'] = r[22]
        
        # Tensão total: soma das células (mais confiável que registro)
        d['voltage'] = sum(d['cells'])
        
        # Estatísticas
        d['cell_min'] = min(d['cells'])
        d['cell_max'] = max(d['cells'])
        d['cell_diff'] = d['cell_max'] - d['cell_min']
        d['cell_avg'] = sum(d['cells']) / len(d['cells'])
        d['power'] = d['voltage'] * abs(d['current'])
        d['temp_max'] = max([t for t in d['temps'] if t > 0])
        
        # Status baseado na corrente
        if abs(d['current']) < 0.5:
            d['status'] = 'Stand by'
        elif d['current'] > 0:
            d['status'] = 'Charging'
        else:
            d['status'] = 'Discharging'
        
        return d
    
    def scan_batteries(self, start_id=1, end_id=16):
        """Varre os IDs de baterias e retorna as encontradas"""
        batteries = {}
        print(f"Varrendo IDs de {start_id} a {end_id}...")
        
        for slave_id in range(start_id, end_id + 1):
            try:
                self.slave_id = slave_id
                result = self.client.read_holding_registers(address=0, count=39, slave=slave_id)
                if not result.isError():
                    data = self._parse(result.registers)
                    batteries[slave_id] = data
                    print(f"  ✓ Bateria ID {slave_id} encontrada")
            except:
                pass
        
        print(f"\n{len(batteries)} bateria(s) encontrada(s)\n")
        return batteries
    
    def display_dashboard(self, batteries):
        """Exibe dashboard com todas as baterias"""
        icon = {"Stand by": "⏸️", "Charging": "⚡", "Discharging": "🔋"}
        
        print("\n" + "="*100)
        print(f"{'DASHBOARD - BATERIAS UPLFP48100':^100}")
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S'):^100}")
        print("="*100)
        
        if not batteries:
            print("\nNenhuma bateria encontrada!")
            print("="*100 + "\n")
            return
        
        # Cabeçalho da tabela
        print(f"\n{'ID':^4} {'Status':^12} {'Tensão':^8} {'Corrente':^9} {'Potência':^9} {'SOC':^5} {'SOH':^5} {'Temp':^6} {'Células':^8} {'Δ Cell':^7}")
        print("-"*100)
        
        # Dados de cada bateria
        for bat_id in sorted(batteries.keys()):
            d = batteries[bat_id]
            status_icon = icon[d['status']]
            temp_alert = "⚠️" if d['temp_max'] > 45 else ""
            cell_alert = "⚠️" if d['cell_diff'] > 0.050 else "✓" if d['cell_diff'] < 0.030 else ""
            
            bar = "█"*int(d['soc']/10) + "░"*(10-int(d['soc']/10))
            
            print(f"{bat_id:^4} {status_icon}{d['status'][:9]:10} "
                  f"{d['voltage']:>7.2f}V "
                  f"{d['current']:>8.2f}A "
                  f"{d['power']:>8.1f}W "
                  f"{d['soc']:>3}% "
                  f"{d['soh']:>3}% "
                  f"{d['temp_max']:>4}°{temp_alert:1} "
                  f"{len(d['cells']):^3}({d['cell_avg']:.2f}V) "
                  f"{d['cell_diff']:.3f}{cell_alert:1}")
        
        print("="*100)
        
        # Estatísticas gerais
        total_voltage = sum(d['voltage'] for d in batteries.values())
        total_power = sum(d['power'] for d in batteries.values())
        avg_soc = sum(d['soc'] for d in batteries.values()) / len(batteries)
        avg_temp = sum(d['temp_max'] for d in batteries.values()) / len(batteries)
        
        print(f"\n📊 RESUMO GERAL")
        print(f"   Baterias:      {len(batteries)}")
        print(f"   Tensão Total:  {total_voltage:.2f} V")
        print(f"   Potência Total:{total_power:>8.1f} W")
        print(f"   SOC Médio:     {avg_soc:>6.1f}%")
        print(f"   Temp Média:    {avg_temp:>6.1f}°C")
        print("\n" + "="*100 + "\n")
    
    def display(self, d, bat_id=None):
        """Exibe dados formatados de uma bateria individual"""
        icon = {"Stand by": "⏸️ ", "Charging": "⚡", "Discharging": "🔋"}
        
        title = f"BATERIA UPLFP48100 - ID {bat_id}" if bat_id else "BATERIA UPLFP48100"
        print("\n" + "="*70)
        print(f"{title:^70}")
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S'):^70}")
        print("="*70)
        
        print(f"\n{icon[d['status']]}  {d['status'].upper()}")
        print("-"*70)
        
        print(f"\n⚡ ELÉTRICO")
        print(f"   Tensão:    {d['voltage']:>7.2f} V")
        print(f"   Corrente:  {d['current']:>7.2f} A")
        print(f"   Potência:  {d['power']:>7.1f} W")
        
        print(f"\n📊 ESTADO")
        bar = "█"*int(d['soc']/5) + "░"*(20-int(d['soc']/5))
        print(f"   SOC:       {d['soc']:>3}%  [{bar}]")
        print(f"   SOH:       {d['soh']:>3}%")
        
        print(f"\n🌡️  TEMPERATURAS")
        for i, t in enumerate(d['temps'], 1):
            if t > 0:
                alert = " ⚠️" if t > 45 else ""
                print(f"   Sensor {i}:  {t:>3}°C{alert}")
        
        print(f"\n🔋 CÉLULAS ({len(d['cells'])})")
        print(f"   Média:     {d['cell_avg']:.3f} V")
        print(f"   Mínima:    {d['cell_min']:.3f} V")
        print(f"   Máxima:    {d['cell_max']:.3f} V")
        print(f"   Diferença: {d['cell_diff']:.3f} V", end="")
        
        if d['cell_diff'] > 0.050:
            print("  ⚠️  Alta!")
        elif d['cell_diff'] < 0.030:
            print("  ✓  Balanceadas")
        else:
            print("  OK")
        
        print("\n   Detalhes:")
        for i, v in enumerate(d['cells'], 1):
            mark = " 🔴" if v == d['cell_max'] else " 🔵" if v == d['cell_min'] else ""
            print(f"      #{i:2d}: {v:.3f} V{mark}")
        
        print("\n" + "="*70 + "\n")


if __name__ == "__main__":
    import sys, time
    
    monitor = BatteryMonitor()
    
    try:
        print("Conectando...")
        if not monitor.connect():
            print("❌ Falha")
            exit(1)
        print("✓ Conectado\n")
        
        continuous = '--continuous' in sys.argv or '-c' in sys.argv
        scan_mode = '--scan' in sys.argv or '-s' in sys.argv
        
        if scan_mode:
            # Modo de varredura e dashboard
            if continuous:
                print("Modo dashboard contínuo (Ctrl+C para parar)\n")
                while True:
                    batteries = monitor.scan_batteries(1, 16)
                    monitor.display_dashboard(batteries)
                    time.sleep(5)
            else:
                batteries = monitor.scan_batteries(1, 16)
                monitor.display_dashboard(batteries)
        else:
            # Modo individual (comportamento original)
            if continuous:
                print("Modo contínuo (Ctrl+C para parar)\n")
                while True:
                    data = monitor.read_data()
                    monitor.display(data, monitor.slave_id)
                    time.sleep(3)
            else:
                data = monitor.read_data()
                monitor.display(data, monitor.slave_id)
    
    except KeyboardInterrupt:
        print("\n⏹️  Parado\n")
    except Exception as e:
        print(f"\n❌ Erro: {e}\n")
    finally:
        monitor.disconnect()
