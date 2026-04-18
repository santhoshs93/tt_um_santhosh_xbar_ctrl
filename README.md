![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg)

# Memristive Crossbar Peripheral Controller

A digital peripheral controller for memristive and spintronic crossbar arrays. Provides 8x8 row/column addressing, four operation modes (READ, SET, RESET, FORMING), configurable pulse generation, 4-bit DAC output, and automated voltage sweep for I-V characterization. All parameters are configurable via SPI.

- [Detailed documentation](docs/info.md)

## Architecture

A 6-state FSM (IDLE, SETUP, PULSE, SENSE, REPORT, SWEEP) sequences crossbar operations. For SET/RESET/FORMING, the controller generates a timed pulse on `pulse_out` with configurable width (1-511 clock cycles), then enters SENSE to capture ADC readings. For READ, the pulse phase is bypassed. Sweep mode iterates over a range of DAC codes for automated I-V characterization.

## Key Features

- 6-state operation FSM with abort capability
- 4 modes: READ, SET, RESET, FORMING
- Configurable pulse width (9-bit, up to 511 cycles)
- Automated DAC voltage sweep (configurable start, end, step)
- 256-cycle SENSE timeout with error flag
- SPI Mode 0 interface for register access
- External ADC data capture (4-bit, with `adc_ready` handshake)

## Pin Summary

| Pin | Direction | Function |
|-----|-----------|----------|
| `ui_in[0]` | Input | Sense input |
| `ui_in[1]` | Input | ADC ready |
| `ui_in[7:4]` | Input | ADC data [3:0] |
| `uo_out[0]` | Output | Pulse output |
| `uo_out[1]` | Output | Row enable |
| `uo_out[2]` | Output | Column enable |
| `uo_out[3]` | Output | Operation done |
| `uo_out[7:4]` | Output | DAC code [3:0] |
| `uio[0]` | Input | SPI CS |
| `uio[1]` | Input | SPI MOSI |
| `uio[2]` | Output | SPI MISO |
| `uio[3]` | Input | SPI SCK |
| `uio[7:4]` | Output | Row/column address |

## Simulation

```bash
cd test
make
```

Requires cocotb and Icarus Verilog.

## Target

Tiny Tapeout [TTSKY26a](https://tinytapeout.com) shuttle, 1x1 tile, SkyWater 130 nm.
