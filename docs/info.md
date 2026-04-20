<!---

This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.
-->

## How it works

This design is a device-agnostic peripheral controller for 8-row × 8-column memristive / spintronic / phase-change / ferroelectric crossbar arrays. It drives four operation modes — READ, SET, RESET, FORMING — with a configurable 1-to-511-cycle pulse width, repeatable pulse trains with programmable inter-pulse gap, a swept-DAC I-V characterization mode, a compliance-current auto-abort, a hardware pulse counter, and a read-only `V/2` half-select DAC value for sneak-path mitigation. All parameters are programmed through an SPI slave. An FSM (IDLE → SETUP → PULSE → SENSE → GAP → REPORT, with an additional SWEEP outer loop) sequences each operation and captures readings from an external ADC.

Row, column, mode, pulse width, DAC code, sweep range, pulse-train parameters, and the compliance threshold are all SPI-configurable (Mode 0, MSB-first; CS=`uio_in[0]`, MOSI=`uio_in[1]`, MISO=`uio_out[2]`, SCK=`uio_in[3]`). The register map is: `reg_ctrl` (0x00: `[0]=start`, `[1]=abort`, `[2]=auto_sweep`, `[3]=compliance_en`), `reg_mode` (0x01: `[1:0]` ∈ {READ, SET, RESET, FORM}), `reg_row` (0x02, 3-bit), `reg_col` (0x03, 3-bit), `reg_pulse_l/h` (0x04/0x05, 9-bit pulse width, default 10 cycles), `reg_dac` (0x06, 8-bit DAC code, default 0x80), `reg_status` (0x07, read-only — includes `op_done`, `busy`, `compliance_trip`), `reg_adc_data` (0x08, read-only), `reg_sweep_start/end/step` (0x09/0x0A/0x0B, defaults 0x00/0xFF/0x10), `reg_repeat` (0x0C: `[3:0]=pulse count` with 0 meaning single pulse, `[7:4]=gap in ×16 cycles`), `reg_compliance` (0x0D, default 0xFF = max/off), `pulse_count` (0x0E, read-only — actual pulses delivered), and `V/2 half-select` (0x0F, read-only — `{1'b0, active_dac[7:1]}`).

On the pins: `pulse_out` (`uo_out[0]`) is the level that feeds the external DAC/driver, `row_enable`/`col_enable` (`uo_out[1:2]`) are the strobes, `op_done` (`uo_out[3]`) goes high at end-of-operation, and the **low 4 bits of the active DAC code** are exposed on `uo_out[7:4]` as `dac_code[3:0]` for a simple direct R-2R or resistor-string DAC — the full 8-bit code (and its V/2 value) is always readable over SPI. The 3-bit row address is mirrored on `uio_out[4:6]` and `col_addr[0]` on `uio_out[7]`. External inputs: `sense_in` (`ui_in[0]`), `adc_ready` (`ui_in[1]`), `ext_irq` (`ui_in[2]`), and a 4-bit ADC data nibble on `ui_in[7:4]` which is captured as `{adc[3:0], adc[3:0]}` into the 8-bit `reg_adc_data`. During a SET/RESET/FORM pulse, if compliance is enabled (`reg_ctrl[3]=1`) and the captured ADC value exceeds `reg_compliance`, the FSM aborts mid-pulse to protect the device and sets the compliance-trip status bit. For pulse trains (`reg_repeat[3:0]>0`), the FSM delivers that many pulses with the configured gap in between and `pulse_count` (0x0E) reports the actual number delivered, which may be less if compliance aborted. Sweep mode iterates the DAC from `sweep_start` to `sweep_end` in steps of `sweep_step`, recording the ADC at each point.

## How to test

1. Apply reset and configure via SPI. For a single SET pulse on row 2, col 5 with DAC 0xA0: write `reg_mode=0x01`, `reg_row=0x02`, `reg_col=0x05`, `reg_pulse_l=0x32` (50 cycles), `reg_dac=0xA0`, then pulse `reg_ctrl[0]=1`.
2. Observe `pulse_out` (`uo_out[0]`) go high for 50 clock cycles, `row_enable`/`col_enable` stay high throughout the operation, and `op_done` assert on completion. Read `reg_adc_data` (0x08) for the sensed value.
3. **READ:** `reg_mode=0x00`, start — the FSM skips PULSE and goes directly to SENSE, waiting for `adc_ready` (`ui_in[1]`).
4. **Pulse train:** set `reg_repeat=0x34` → 4 pulses with a 3×16=48-cycle gap between them. Read `pulse_count` (0x0E) to verify delivery.
5. **Compliance limit:** set `reg_compliance=0x40` and `reg_ctrl[3]=1`. During the next pulse, if the ADC nibble rises above 0x40, the pulse aborts mid-cycle and `compliance_trip` latches in `reg_status`.
6. **Sweep mode:** configure `reg_sweep_start/end/step`, set `reg_ctrl[2]=1` and `reg_ctrl[0]=1`; the FSM iterates through DAC values, pulses at each, and captures ADC into `reg_adc_data` (readable between iterations via `op_done`).
7. **V/2 half-select:** read 0x0F at any time — it returns the current `active_dac` right-shifted by 1, useful for biasing un-selected lines to mitigate sneak-path current.

A cocotb suite (30 tests in `test/test.py`) covers reset, SPI register roundtrip, all four operation modes, pulse-width programming (1–511 cycles), pulse trains, compliance abort, sweep, V/2 readback, and `uio_oe` direction control. All tests pass in RTL and post-synthesis gate-level simulation.

## External hardware

- **SPI master** (microcontroller or FPGA) on `uio[0:3]`.
- **External DAC**: connect `uo_out[7:4]` (4-bit `dac_code[3:0]`) to a fast 4-bit DAC for basic operation, or read the full 8-bit `reg_dac` over SPI each cycle to drive a higher-resolution converter. The `V/2` value at register 0x0F drives the half-select bias line.
- **External ADC / transimpedance amplifier / sense amplifier**: 4-bit data on `ui_in[7:4]`, ready pulse on `ui_in[1]`.
- **Crossbar array**: row select on `uio_out[6:4]` (3 bits), column-low on `uio_out[7]`; note that this pinout exposes only `col_addr[0]` on a pin, so decode `reg_col` externally via SPI for full 3-bit column addressing in silicon tests.
- Optional: external interrupt on `ui_in[2]`, single-bit sense (comparator) on `ui_in[0]`.
