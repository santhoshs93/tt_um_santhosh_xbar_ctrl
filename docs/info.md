<!---

This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.
-->

## How it works

This design implements a peripheral controller for memristive/spintronic crossbar arrays. It provides 8-row × 8-column addressing (3-bit row and column addresses), four operation modes (READ, SET, RESET, FORMING), configurable pulse width (1-511 clock cycles), and an automated voltage sweep mode for I-V characterization. All parameters are configurable via SPI. A 6-state FSM (IDLE, SETUP, PULSE, SENSE, REPORT, SWEEP) sequences the crossbar operations and captures ADC readings from an external sense amplifier.

The 2-bit DAC code is output on uo_out[5:4]; the full 8-bit DAC value is readable/writable via SPI register 0x06. ADC data is captured from ui_in[7:4] (4 bits) and stored internally as nibble-replicated `{adc[3:0], adc[3:0]}` to fill the 8-bit SPI read register (0x08). Column address bits [2:1] are output on uo_out[7:6], and col_addr[0] is on uio_out[7].

## How to test

1. Apply reset and configure via SPI (CS=uio_in[0], MOSI=uio_in[1], SCK=uio_in[3], MISO=uio_out[2]).
2. Write operation mode (reg 0x01), row address (0x02), col address (0x03), pulse width (0x04-0x05), and DAC code (0x06).
3. Set CTRL[0]=1 (reg 0x00) to start the operation.
4. For READ: the FSM skips pulse and goes to SENSE, waiting for adc_ready on ui_in[1].
5. For SET/RESET/FORM: pulse_out (uo_out[0]) goes high for the configured duration, then SENSE phase.
6. Monitor op_done on uo_out[3] and read ADC data from reg 0x08.
7. For sweep mode, set CTRL[2]=1 and configure sweep start/end/step registers (0x09-0x0B).

## External hardware

SPI master, external DAC driven by uo_out[5:4] (2-bit code; full 8-bit value available via SPI), external ADC with data on ui_in[7:4] and ready signal on ui_in[1], crossbar array with row select on uio_out[6:4] and column select on {uo_out[7:6], uio_out[7]}.
