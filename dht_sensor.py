#!/usr/bin/env python3
"""
Leitura do sensor DHT11 (temperatura e umidade) na Orange Pi PC (Allwinner H3).

O kernel Armbian nao inclui o driver dht11, entao a leitura e feita em userspace:
- libgpiod v2 com deteccao de bordas: o kernel registra o timestamp de cada borda
  na IRQ, entao a latencia do Python nao afeta a medicao dos pulsos.
- O pulso de start e gerado trocando o mux do pino direto nos registradores do PIO
  (/dev/mem). Reconfigurar a linha pelo libgpiod leva ~1.2 ms (alocacao da IRQ),
  tempo em que o sensor ja comecou a responder e os primeiros bits se perdem.
- O debounce de IRQ do banco sai do reset com clock de 32 kHz (~31 us), que engole
  os bits "0" (~26 us). Ajustamos para HOSC 24 MHz / 32 (~1.3 us).

Requer root (/dev/mem e /dev/gpiochip0).
"""
import argparse
import itertools
import json
import mmap
import os
import re
import struct
import time

import gpiod
from gpiod.line import Bias, Clock, Direction, Edge

# Registradores do PIO do H3 (mapeados a partir da pagina 0x01C20000)
PIO_PAGE = 0x01C20000
PIO_OFFSET = 0x800
PORT_STRIDE = 0x24
DAT_OFFSET = 0x10
EINT_BANKS = {"A": 0x200, "G": 0x220}   # unicas portas com IRQ no H3
INT_DEB_OFFSET = 0x18
DEBOUNCE_VALUE = 0x51                   # bit0=1: HOSC 24 MHz, prescale 2^5
FUNC_OUTPUT = 0x1

START_PULSE = 0.020       # sensor exige >= 18 ms em nivel baixo
READ_WINDOW = 0.030       # frame completo leva ~4.5 ms
MAX_EVENTS = 200          # frame normal tem ~84 bordas
EVENT_BUFFER = 256
MIN_INTERVAL = 2.0        # DHT11 aceita no maximo ~1 leitura/s

# Duracoes nominais (us) medidas no sensor e parametros do decodificador
LOW_US, BIT0_US, BIT1_US = 54.0, 24.0, 71.0
MAX_SEGMENTS = 4          # segmentos (baixo/bit) fundidos em um unico intervalo
MAX_SKIP = 3              # bordas espurias que podem ser ignoradas em sequencia
TOLERANCE_US = 9.0
SKIP_PENALTY = 60.0
MERGE_PENALTY = 15.0


class DhtReadError(Exception):
    pass


def parse_pin(name):
    """Converte 'PA6' em ('A', 6). Apenas PA e PG suportam IRQ no H3."""
    match = re.fullmatch(r"P([A-G])(\d{1,2})", name.strip().upper())
    if not match:
        raise ValueError(f"Pino invalido: {name!r} (use o formato PA6, PG7...)")
    port, pin = match.group(1), int(match.group(2))
    if port not in EINT_BANKS:
        raise ValueError(f"Pino {name} sem suporte a IRQ: use um pino das portas PA ou PG")
    if pin > 31:
        raise ValueError(f"Pino invalido: {name}")
    return port, pin


def _build_patterns(phase):
    """
    Sequencias alternadas de segmentos (baixo/bit) que comecam em phase ('L' ou 'B').
    Retorna tuplas (duracao_us, bits, proxima_fase, n_segmentos).
    """
    patterns = []
    for count in range(1, MAX_SEGMENTS + 1):
        kinds = ["L" if (i % 2 == 0) == (phase == "L") else "B" for i in range(count)]
        for combo in itertools.product((0, 1), repeat=kinds.count("B")):
            values = iter(combo)
            duration = 0.0
            bits = []
            for kind in kinds:
                if kind == "L":
                    duration += LOW_US
                else:
                    bit = next(values)
                    bits.append(bit)
                    duration += BIT1_US if bit else BIT0_US
            next_phase = "B" if kinds[-1] == "L" else "L"
            patterns.append((duration, tuple(bits), next_phase, count))
    return patterns


_PATTERNS = {"L": _build_patterns("L"), "B": _build_patterns("B")}


def _best_parse(times, start):
    """
    Programacao dinamica sobre as bordas observadas: encontra a sequencia de bordas
    reais (podendo pular espurias) cujos intervalos melhor se explicam como
    baixo/bit alternados, ate completar 40 bits. Retorna (custo, bits) ou None.
    """
    best = {(start, "L", 0): (0.0, None)}
    finished = []
    for i in range(start, len(times)):
        for phase in "LB":
            for count in range(41):
                state = (i, phase, count)
                if state not in best:
                    continue
                cost = best[state][0]
                if count == 40:
                    finished.append((cost, state))
                    continue
                for j in range(i + 1, min(len(times), i + 2 + MAX_SKIP)):
                    elapsed = times[j] - times[i]
                    for duration, bits, next_phase, segments in _PATTERNS[phase]:
                        error = abs(elapsed - duration)
                        if error > TOLERANCE_US + 2 * (segments - 1) or count + len(bits) > 40:
                            continue
                        new_cost = (cost + error * error + SKIP_PENALTY * (j - i - 1)
                                    + MERGE_PENALTY * (segments - 1))
                        new_state = (j, next_phase, count + len(bits))
                        if new_state not in best or new_cost < best[new_state][0]:
                            best[new_state] = (new_cost, (state, bits))

    if not finished:
        return None
    cost, state = min(finished)
    bits = []
    while best[state][1]:
        state, step_bits = best[state][1]
        bits[:0] = step_bits
    return cost, bits


def decode_frame(intervals):
    """
    Decodifica os intervalos (us) entre bordas consecutivas em (umidade, temperatura).

    O tipo de borda reportado pelo kernel nao e confiavel (o H3 nao informa a
    polaridade; o kernel le o nivel do pino depois, quando ja pode ter mudado),
    entao a decodificacao usa so as duracoes: baixo ~54 us, bit 0 ~24 us, bit 1 ~71 us.
    Bordas se perdem quando a IRQ atrasa mais que um pulso curto (intervalos aparecem
    somados) e ruido pode gerar bordas extras; o parser tolera ambos e o checksum
    decide entre interpretacoes.
    """
    times = [0.0]
    for value in intervals:
        times.append(times[-1] + value)

    # Dados comecam apos a resposta do sensor em nivel alto (~80-90 us)
    starts = [i + 1 for i, value in enumerate(intervals[:4]) if 83 <= value <= 100] or [0, 1, 2]

    candidates = []
    last_error = "Frame incompleto"
    for start in starts:
        parsed = _best_parse(times, start)
        if parsed is None:
            continue
        cost, bits = parsed
        data = [int("".join(str(b) for b in bits[i:i + 8]), 2) for i in range(0, 40, 8)]
        if (sum(data[:4]) & 0xFF) != data[4]:
            last_error = f"Checksum invalido: {data}"
            continue
        candidates.append((cost, data))

    if not candidates:
        raise DhtReadError(f"{last_error} ({len(intervals) + 1} bordas)")
    data = min(candidates)[1]

    humidity = data[0] + data[1] / 10.0
    temperature = data[2] + (data[3] & 0x7F) / 10.0
    if data[3] & 0x80:
        temperature = -temperature

    if not (0 <= humidity <= 100 and -20 <= temperature <= 60):
        raise DhtReadError(f"Leitura fora da faixa: {temperature} C, {humidity} %")

    return humidity, temperature


class Dht11Sensor:
    def __init__(self, pin="PA6", chip="/dev/gpiochip0"):
        self.port, self.pin = parse_pin(pin)
        self.pin_name = f"P{self.port}{self.pin}"
        self.chip = chip

        port_index = ord(self.port) - ord("A")
        port_base = PIO_OFFSET + port_index * PORT_STRIDE
        self.line = port_index * 32 + self.pin
        self._cfg_reg = port_base + (self.pin // 8) * 4
        self._cfg_shift = (self.pin % 8) * 4
        self._dat_reg = port_base + DAT_OFFSET
        self._deb_reg = PIO_OFFSET + EINT_BANKS[self.port] + INT_DEB_OFFSET

        self._settings = gpiod.LineSettings(
            direction=Direction.INPUT,
            edge_detection=Edge.BOTH,
            bias=Bias.PULL_UP,
            event_clock=Clock.MONOTONIC,
        )
        self._mem = None
        self._last_read = 0.0

    def _reg_read(self, offset):
        return struct.unpack_from("<I", self._mem, offset)[0]

    def _reg_write(self, offset, value):
        struct.pack_into("<I", self._mem, offset, value)

    def _get_func(self):
        return (self._reg_read(self._cfg_reg) >> self._cfg_shift) & 0xF

    def _set_func(self, func):
        cfg = self._reg_read(self._cfg_reg) & ~(0xF << self._cfg_shift)
        self._reg_write(self._cfg_reg, cfg | (func << self._cfg_shift))

    def _ensure_mapped(self):
        if self._mem is None:
            fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
            try:
                self._mem = mmap.mmap(fd, mmap.PAGESIZE, offset=PIO_PAGE)
            finally:
                os.close(fd)
        # O kernel nao mexe no debounce depois do boot, mas conferir e barato
        if self._reg_read(self._deb_reg) != DEBOUNCE_VALUE:
            self._reg_write(self._deb_reg, DEBOUNCE_VALUE)

    def _capture(self):
        """Envia o start e retorna os intervalos (us) entre as bordas recebidas."""
        wait = self._last_read + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)

        self._ensure_mapped()
        events = []
        try:
            with gpiod.request_lines(
                self.chip,
                consumer="dht11",
                config={self.line: self._settings},
                event_buffer_size=EVENT_BUFFER,
            ) as req:
                # Com a IRQ solicitada o pino fica no mux EINT
                eint_func = self._get_func()

                for _ in range(MAX_EVENTS):
                    if not req.wait_edge_events(0):
                        break
                    req.read_edge_events()

                self._reg_write(self._dat_reg, self._reg_read(self._dat_reg) & ~(1 << self.pin))
                self._set_func(FUNC_OUTPUT)
                try:
                    time.sleep(START_PULSE)
                finally:
                    self._set_func(eint_func)

                deadline = time.monotonic() + READ_WINDOW
                while len(events) < MAX_EVENTS:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not req.wait_edge_events(remaining):
                        break
                    events.extend(req.read_edge_events())
        finally:
            self._last_read = time.monotonic()

        return [
            (events[i].timestamp_ns - events[i - 1].timestamp_ns) / 1000.0
            for i in range(1, len(events))
        ]

    def read(self, retries=3):
        """Retorna {'temperature': C, 'humidity': %} ou levanta DhtReadError."""
        last_error = None
        for _ in range(max(1, retries)):
            try:
                humidity, temperature = decode_frame(self._capture())
                return {"temperature": temperature, "humidity": humidity}
            except DhtReadError as exc:
                last_error = exc
        raise last_error

    def close(self):
        if self._mem is not None:
            self._mem.close()
            self._mem = None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Leitura do sensor DHT11 com saida JSON")
    parser.add_argument('--pin', default='PA6', help='Pino do sinal de dados (padrao: PA6)')
    parser.add_argument('--chip', default='/dev/gpiochip0', help='gpiochip do PIO (padrao: /dev/gpiochip0)')
    parser.add_argument('--retries', type=int, default=3, help='Tentativas por leitura (padrao: 3)')
    parser.add_argument('--count', type=int, default=1, help='Numero de leituras (padrao: 1)')
    args = parser.parse_args()

    sensor = None
    status = 0
    try:
        sensor = Dht11Sensor(pin=args.pin, chip=args.chip)
        for _ in range(max(1, args.count)):
            try:
                print(json.dumps({'pin': sensor.pin_name, **sensor.read(args.retries)}, ensure_ascii=False))
            except DhtReadError as e:
                print(json.dumps({'erro': str(e)}, ensure_ascii=False))
                status = 1
    except KeyboardInterrupt:
        status = 130
    except Exception as e:
        print(json.dumps({'erro': str(e)}, ensure_ascii=False))
        status = 1
    finally:
        if sensor:
            sensor.close()
    exit(status)
