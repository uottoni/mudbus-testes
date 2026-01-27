#!/usr/bin/env python3
"""
Script de integração Zabbix para monitoramento de baterias UPLFP48100 via Modbus RTU
Suporta descoberta automática (LLD) e coleta de métricas individuais
"""

import sys
import json
import argparse
from battery_monitor import BatteryMonitor


def discover_batteries(port='/dev/ttyUSB0', start_id=1, end_id=16):
    """
    Descobre baterias conectadas e retorna JSON para LLD do Zabbix
    Formato: {"data": [{"{#BATTERY_ID}": "1", "{#BATTERY_NAME}": "Battery 1"}, ...]}
    """
    monitor = BatteryMonitor(port=port)
    
    try:
        if not monitor.connect():
            print(json.dumps({"data": []}))
            return 1
        
        batteries = monitor.scan_batteries(start_id, end_id)
        
        # Formata para LLD do Zabbix
        lld_data = {
            "data": [
                {
                    "{#BATTERY_ID}": str(bat_id),
                    "{#BATTERY_NAME}": f"Battery {bat_id}"
                }
                for bat_id in sorted(batteries.keys())
            ]
        }
        
        print(json.dumps(lld_data, indent=2))
        return 0
        
    except Exception as e:
        print(json.dumps({"data": [], "error": str(e)}), file=sys.stderr)
        return 1
    finally:
        monitor.disconnect()


def get_metric(bat_id, metric, port='/dev/ttyUSB0'):
    """
    Retorna valor de uma métrica específica de uma bateria
    """
    monitor = BatteryMonitor(port=port, slave_id=int(bat_id))
    
    try:
        if not monitor.connect():
            return None
        
        data = monitor.read_data()
        
        # Métricas disponíveis
        metrics = {
            'voltage': data.get('voltage', 0),
            'current': data.get('current', 0),
            'power': data.get('power', 0),
            'soc': data.get('soc', 0),
            'soh': data.get('soh', 0),
            'temp_max': data.get('temp_max', 0),
            'cell_min': data.get('cell_min', 0),
            'cell_max': data.get('cell_max', 0),
            'cell_avg': data.get('cell_avg', 0),
            'cell_diff': data.get('cell_diff', 0),
            'cell_count': len(data.get('cells', [])),
            'status': 0 if data.get('status') == 'Stand by' else 1 if data.get('status') == 'Charging' else 2
        }
        
        if metric in metrics:
            print(metrics[metric])
            return 0
        else:
            print(f"Unknown metric: {metric}", file=sys.stderr)
            return 1
            
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        monitor.disconnect()


def get_all_metrics(bat_id, port='/dev/ttyUSB0'):
    """
    Retorna todos os dados de uma bateria em JSON
    """
    monitor = BatteryMonitor(port=port, slave_id=int(bat_id))
    
    try:
        if not monitor.connect():
            print(json.dumps({"error": "Connection failed"}))
            return 1
        
        data = monitor.read_data()
        
        # Formata dados para JSON
        output = {
            'battery_id': bat_id,
            'voltage': data.get('voltage', 0),
            'current': data.get('current', 0),
            'power': data.get('power', 0),
            'soc': data.get('soc', 0),
            'soh': data.get('soh', 0),
            'temp_max': data.get('temp_max', 0),
            'cell_min': data.get('cell_min', 0),
            'cell_max': data.get('cell_max', 0),
            'cell_avg': data.get('cell_avg', 0),
            'cell_diff': data.get('cell_diff', 0),
            'cell_count': len(data.get('cells', [])),
            'status': data.get('status', 'Unknown'),
            'status_code': 0 if data.get('status') == 'Stand by' else 1 if data.get('status') == 'Charging' else 2
        }
        
        print(json.dumps(output, indent=2))
        return 0
        
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 1
    finally:
        monitor.disconnect()


def main():
    parser = argparse.ArgumentParser(
        description='Zabbix integration script for UPLFP48100 battery monitoring'
    )
    
    parser.add_argument('--discover', action='store_true',
                        help='Discover batteries (LLD)')
    parser.add_argument('--id', type=int,
                        help='Battery ID (1-16)')
    parser.add_argument('--metric', type=str,
                        help='Metric name to retrieve')
    parser.add_argument('--json', action='store_true',
                        help='Return all metrics in JSON format')
    parser.add_argument('--port', type=str, default='/dev/ttyUSB0',
                        help='Serial port (default: /dev/ttyUSB0)')
    parser.add_argument('--start-id', type=int, default=1,
                        help='Start ID for discovery (default: 1)')
    parser.add_argument('--end-id', type=int, default=16,
                        help='End ID for discovery (default: 16)')
    
    args = parser.parse_args()
    
    # Discovery mode
    if args.discover:
        return discover_batteries(args.port, args.start_id, args.end_id)
    
    # Get all metrics in JSON
    elif args.json and args.id:
        return get_all_metrics(args.id, args.port)
    
    # Get specific metric
    elif args.id and args.metric:
        return get_metric(args.id, args.metric, args.port)
    
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
