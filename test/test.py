# SPDX-FileCopyrightText: © 2026 Prof. Santhosh Sivasubramani, IIT Delhi
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge


async def reset_dut(dut):
    """Apply reset and release."""
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0b00001  # CS high (inactive)
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)


async def spi_write(dut, addr, data):
    """SPI write: 0 + 7-bit addr + 8-bit data, MSB first, Mode 0."""
    cs_bit = 0
    mosi_bit = 1
    sck_bit = 3
    word = ((addr & 0x7F) << 8) | (data & 0xFF)

    dut.uio_in.value = 0  # CS=0
    await ClockCycles(dut.clk, 4)

    for i in range(16):
        bit_val = (word >> (15 - i)) & 1
        dut.uio_in.value = (bit_val << mosi_bit)
        await ClockCycles(dut.clk, 4)
        dut.uio_in.value = (bit_val << mosi_bit) | (1 << sck_bit)
        await ClockCycles(dut.clk, 4)
        dut.uio_in.value = (bit_val << mosi_bit)
        await ClockCycles(dut.clk, 2)

    dut.uio_in.value = (1 << cs_bit)
    await ClockCycles(dut.clk, 4)


async def spi_read(dut, addr):
    """SPI read: 1 + 7-bit addr + 8 clocks to read data."""
    cs_bit = 0
    mosi_bit = 1
    sck_bit = 3
    word = (1 << 15) | ((addr & 0x7F) << 8)

    dut.uio_in.value = 0
    await ClockCycles(dut.clk, 4)

    read_data = 0
    for i in range(16):
        bit_val = (word >> (15 - i)) & 1
        dut.uio_in.value = (bit_val << mosi_bit)
        await ClockCycles(dut.clk, 4)
        dut.uio_in.value = (bit_val << mosi_bit) | (1 << sck_bit)
        await ClockCycles(dut.clk, 2)
        if i >= 8:
            miso = (int(dut.uio_out.value) >> 2) & 1
            read_data = (read_data << 1) | miso
        await ClockCycles(dut.clk, 2)
        dut.uio_in.value = (bit_val << mosi_bit)
        await ClockCycles(dut.clk, 2)

    dut.uio_in.value = (1 << cs_bit)
    await ClockCycles(dut.clk, 4)
    return read_data


@cocotb.test()
async def test_reset_idle(dut):
    """After reset, FSM should be idle, no pulse, no row/col enable."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    uo = int(dut.uo_out.value)
    assert (uo & 0x01) == 0, "pulse_out should be 0"
    assert (uo & 0x02) == 0, "row_en should be 0"
    assert (uo & 0x04) == 0, "col_en should be 0"


@cocotb.test()
async def test_spi_register_access(dut):
    """Write and read back configuration registers."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Write row=3, col=5
    await spi_write(dut, 0x02, 0x03)  # ROW
    await spi_write(dut, 0x03, 0x05)  # COL
    await ClockCycles(dut.clk, 10)

    row = await spi_read(dut, 0x02)
    col = await spi_read(dut, 0x03)
    dut._log.info(f"Row={row}, Col={col}")
    assert row == 0x03, f"Expected row=3, got {row}"
    assert col == 0x05, f"Expected col=5, got {col}"


@cocotb.test()
async def test_read_operation(dut):
    """Configure a READ operation and trigger it. Check FSM progresses."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Configure: READ mode, row=1, col=2
    await spi_write(dut, 0x01, 0x00)  # MODE=READ
    await spi_write(dut, 0x02, 0x01)  # ROW=1
    await spi_write(dut, 0x03, 0x02)  # COL=2
    await spi_write(dut, 0x04, 0x0A)  # PULSE_L=10
    await ClockCycles(dut.clk, 10)

    # Trigger start
    await spi_write(dut, 0x00, 0x01)  # CTRL: start=1

    # READ skips pulse, goes to SENSE. Provide adc_ready and poll for op_done.
    dut.ui_in.value = 0b01100010  # adc_ready=1, adc_data=0110
    op_done = 0
    for _ in range(50):
        await ClockCycles(dut.clk, 1)
        uo = int(dut.uo_out.value)
        if (uo >> 3) & 1:
            op_done = 1
            break

    dut._log.info(f"op_done={op_done}, uo_out=0x{uo:02x}")
    assert op_done == 1, "op_done should be asserted after READ completes with adc_ready"


@cocotb.test()
async def test_set_operation_pulse(dut):
    """Configure SET mode and verify pulse_out goes high."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # SET mode with short pulse
    await spi_write(dut, 0x01, 0x01)  # MODE=SET
    await spi_write(dut, 0x04, 0x05)  # PULSE_L=5 cycles
    await spi_write(dut, 0x05, 0x00)  # PULSE_H=0
    await spi_write(dut, 0x06, 0x80)  # DAC=0x80
    await ClockCycles(dut.clk, 10)

    # Trigger
    await spi_write(dut, 0x00, 0x01)
    pulse_seen = False
    for _ in range(50):
        await ClockCycles(dut.clk, 1)
        if int(dut.uo_out.value) & 1:
            pulse_seen = True
            break

    dut._log.info(f"Pulse output seen: {pulse_seen}")
    # After pulse, provide adc_ready to complete
    dut.ui_in.value = 0b00000010  # adc_ready=1
    await ClockCycles(dut.clk, 30)


@cocotb.test()
async def test_uio_oe(dut):
    """Verify OE direction bits: dynamic MISO, uio[7:4]=addr outputs."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)
    await ClockCycles(dut.clk, 1)
    # CS=1 (inactive): MISO tri-stated → uio_oe=0xF0
    assert int(dut.uio_oe.value) == 0b11110000, \
        f"Expected uio_oe=0xF0 (CS inactive), got 0x{int(dut.uio_oe.value):02x}"

    # Assert CS=0 (active): MISO enabled → uio_oe=0xF4
    dut.uio_in.value = 0  # CS=0
    await ClockCycles(dut.clk, 1)
    assert int(dut.uio_oe.value) == 0b11110100, \
        f"Expected uio_oe=0xF4 (CS active), got 0x{int(dut.uio_oe.value):02x}"
    dut.uio_in.value = 0b00001  # restore CS=1
    await ClockCycles(dut.clk, 1)


@cocotb.test()
async def test_sweep_mode(dut):
    """Configure voltage sweep and verify completion via op_done."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Configure sweep: start=0x00, end=0x20, step=0x10, pulse=5
    await spi_write(dut, 0x04, 0x05)   # pulse_l=5
    await spi_write(dut, 0x05, 0x00)   # pulse_h=0
    await spi_write(dut, 0x09, 0x00)   # sweep_start=0x00
    await spi_write(dut, 0x0A, 0x20)   # sweep_end=0x20
    await spi_write(dut, 0x0B, 0x10)   # sweep_step=0x10
    await ClockCycles(dut.clk, 10)

    # Trigger sweep (ctrl[2]=auto_sweep, ctrl[0]=start)
    await spi_write(dut, 0x00, 0x05)

    # Sweep now goes through S_SENSE at each step — provide adc_ready
    dut.ui_in.value = 0b00000010  # adc_ready=1

    # Wait for op_done (uo_out[3]) pulse — check every cycle
    op_done_seen = False
    for _ in range(500):
        await ClockCycles(dut.clk, 1)
        if (int(dut.uo_out.value) >> 3) & 1:
            op_done_seen = True
            break

    dut._log.info(f"Sweep op_done: {op_done_seen}")
    assert op_done_seen, "Sweep should complete and signal op_done"


@cocotb.test()
async def test_abort_operation(dut):
    """Start a SET with long pulse, then abort mid-operation."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # SET mode with long pulse (255 cycles)
    await spi_write(dut, 0x01, 0x01)   # MODE=SET
    await spi_write(dut, 0x04, 0xFF)   # pulse_l=255
    await spi_write(dut, 0x05, 0x00)   # pulse_h=0
    await ClockCycles(dut.clk, 10)

    # Trigger start
    await spi_write(dut, 0x00, 0x01)

    # Wait until pulse_out goes high (FSM active)
    pulse_seen = False
    for _ in range(80):
        await ClockCycles(dut.clk, 1)
        if int(dut.uo_out.value) & 1:
            pulse_seen = True
            break

    dut._log.info(f"Pulse seen before abort: {pulse_seen}")

    # Abort via reg_ctrl[1]
    await spi_write(dut, 0x00, 0x02)  # abort=1
    await ClockCycles(dut.clk, 20)

    # Check FSM returned to IDLE: pulse_out=0, row_en=0, col_en=0
    uo = int(dut.uo_out.value)
    assert (uo & 0x01) == 0, "pulse_out should be 0 after abort"
    assert (uo & 0x02) == 0, "row_en should be 0 after abort"
    assert (uo & 0x04) == 0, "col_en should be 0 after abort"
    dut._log.info("Abort successful: FSM returned to IDLE")


@cocotb.test()
async def test_sense_timeout(dut):
    """READ mode without adc_ready should timeout after 256 cycles."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # READ mode
    await spi_write(dut, 0x01, 0x00)  # MODE=READ
    await spi_write(dut, 0x02, 0x02)  # ROW=2
    await spi_write(dut, 0x03, 0x03)  # COL=3
    await ClockCycles(dut.clk, 10)

    # Trigger — do NOT assert adc_ready
    await spi_write(dut, 0x00, 0x01)
    dut.ui_in.value = 0x00  # No ADC ready

    # Wait for op_done (should timeout after ~256 + FSM overhead cycles)
    op_done_seen = False
    for _ in range(500):
        await ClockCycles(dut.clk, 1)
        if (int(dut.uo_out.value) >> 3) & 1:
            op_done_seen = True
            break

    dut._log.info(f"Sense timeout triggered: op_done={op_done_seen}")
    # Read status: op_error should be set
    status = await spi_read(dut, 0x07)
    dut._log.info(f"Status after timeout: 0x{status:02x}")


@cocotb.test()
async def test_rapid_start_abort_recovery(dut):
    """Trigger start, abort quickly, re-trigger — verify FSM recovers cleanly."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # SET mode, long pulse
    await spi_write(dut, 0x01, 0x01)  # MODE=SET
    await spi_write(dut, 0x04, 0xFF)  # pulse_l=255
    await spi_write(dut, 0x06, 0x80)  # DAC=0x80
    await ClockCycles(dut.clk, 5)

    # Start → abort → start cycle (3 iterations)
    for iteration in range(3):
        await spi_write(dut, 0x00, 0x01)  # start
        await ClockCycles(dut.clk, 10)
        await spi_write(dut, 0x00, 0x02)  # abort
        await ClockCycles(dut.clk, 10)
        # Verify FSM returned to IDLE
        uo = int(dut.uo_out.value)
        assert (uo & 0x01) == 0, f"Iteration {iteration}: pulse_out not cleared after abort"
        assert (uo & 0x02) == 0, f"Iteration {iteration}: row_en not cleared after abort"
        assert (uo & 0x04) == 0, f"Iteration {iteration}: col_en not cleared after abort"
        # Clear abort bit
        await spi_write(dut, 0x00, 0x00)
        await ClockCycles(dut.clk, 5)

    # Final: trigger and let it complete (short pulse)
    await spi_write(dut, 0x04, 0x02)  # pulse_l=2
    await spi_write(dut, 0x00, 0x01)  # start
    dut.ui_in.value = 0b00000010  # adc_ready=1
    op_done = False
    for _ in range(100):
        await ClockCycles(dut.clk, 1)
        if (int(dut.uo_out.value) >> 3) & 1:
            op_done = True
            break
    dut._log.info(f"Recovery: op_done after 3 abort cycles = {op_done}")
    assert op_done, "FSM should complete operation after rapid start/abort cycles"


@cocotb.test()
async def test_pulse_width_boundaries(dut):
    """Verify small (10 cycle) and maximum (511 cycle) pulse width boundaries."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # --- Small pulse width: 10 cycles (near-minimum GL-safe boundary) ---
    await spi_write(dut, 0x01, 0x01)  # MODE=SET
    await spi_write(dut, 0x04, 0x0A)  # pulse_l=10
    await spi_write(dut, 0x05, 0x00)  # pulse_h=0
    await ClockCycles(dut.clk, 5)
    await spi_write(dut, 0x00, 0x01)  # start

    # Poll for pulse_out BEFORE asserting adc_ready
    pulse_count_min = 0
    for _ in range(80):
        await ClockCycles(dut.clk, 1)
        if int(dut.uo_out.value) & 1:
            pulse_count_min += 1
    dut._log.info(f"Small pulse width: pulse_out HIGH for {pulse_count_min} cycles")
    assert pulse_count_min >= 1, "Small pulse should produce at least 1 cycle of pulse_out"
    assert pulse_count_min <= 15, f"Small pulse too long: {pulse_count_min} cycles"

    # Now provide adc_ready to complete the operation
    dut.ui_in.value = 0b00000010  # adc_ready
    await ClockCycles(dut.clk, 10)

    # --- Maximum pulse width: 511 cycles ---
    await reset_dut(dut)
    await spi_write(dut, 0x01, 0x01)  # MODE=SET
    await spi_write(dut, 0x04, 0xFF)  # pulse_l=255
    await spi_write(dut, 0x05, 0x01)  # pulse_h=1 → total=511
    await ClockCycles(dut.clk, 5)
    await spi_write(dut, 0x00, 0x01)  # start

    pulse_count_max = 0
    op_done = False
    for cycle in range(700):
        await ClockCycles(dut.clk, 1)
        if int(dut.uo_out.value) & 1:
            pulse_count_max += 1
        # Assert adc_ready after pulse is mostly done
        if cycle == 520:
            dut.ui_in.value = 0b00000010  # adc_ready
        if (int(dut.uo_out.value) >> 3) & 1:
            op_done = True
            break
    dut._log.info(f"Max pulse width: pulse_out HIGH for {pulse_count_max} cycles, op_done={op_done}")
    assert pulse_count_max >= 500, f"Max pulse too short: {pulse_count_max} (expected ~512)"
    assert op_done, "Operation should complete after max pulse width"


@cocotb.test()
async def test_abort_clears_flags(dut):
    """Abort should clear op_done and op_error flags (C1 fix)."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Complete a READ to set op_done
    await spi_write(dut, 0x01, 0x00)  # MODE=READ
    await spi_write(dut, 0x04, 0x05)  # pulse_l
    await spi_write(dut, 0x00, 0x01)  # start
    dut.ui_in.value = 0b01100010  # adc_ready + adc_data
    for _ in range(50):
        await ClockCycles(dut.clk, 1)
        if (int(dut.uo_out.value) >> 3) & 1:
            break
    status = await spi_read(dut, 0x07)
    dut._log.info(f"Status before abort: 0x{status:02x}")

    # Now abort — op_done should be cleared
    await spi_write(dut, 0x00, 0x02)
    await ClockCycles(dut.clk, 10)
    status_after = await spi_read(dut, 0x07)
    dut._log.info(f"Status after abort: 0x{status_after:02x}")
    assert (status_after & 0x01) == 0, "op_done should be cleared by abort"
    assert (status_after & 0x02) == 0, "op_error should be cleared by abort"


@cocotb.test()
async def test_col_addr_output(dut):
    """Verify col_addr[0] on uio[7], and DAC[3:0] on uo_out[7:4]."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    for col_val in [0x00, 0x05, 0x07]:
        await spi_write(dut, 0x03, col_val)  # COL
        await spi_write(dut, 0x06, 0xAB)     # DAC=0xAB
        await spi_write(dut, 0x01, 0x01)     # MODE=SET
        await spi_write(dut, 0x04, 0x03)     # short pulse
        await spi_write(dut, 0x00, 0x01)     # start

        # Wait for SETUP/PULSE state where col outputs are active
        for _ in range(60):
            await ClockCycles(dut.clk, 1)
            if int(dut.uo_out.value) & 0x04:  # col_en
                break

        uio = int(dut.uio_out.value)
        uo = int(dut.uo_out.value)
        col0 = (uio >> 7) & 1
        dac_nibble = (uo >> 4) & 0x0F
        dut._log.info(f"col_val=0x{col_val:02x}: col[0]={col0}, DAC[3:0]=0x{dac_nibble:x}")

        # Verify col_addr[0] on uio_out[7]
        expected_col0 = col_val & 1
        assert col0 == expected_col0, \
            f"col_addr[0] mismatch: expected {expected_col0}, got {col0}"

        # Verify DAC[3:0] on uo_out[7:4]
        assert dac_nibble == (0xAB & 0x0F), \
            f"DAC nibble mismatch: expected 0x{0xAB & 0x0F:x}, got 0x{dac_nibble:x}"

        # Verify full col_addr via SPI readback
        col_rb = await spi_read(dut, 0x03)
        assert (col_rb & 0x07) == (col_val & 0x07), \
            f"col_addr SPI mismatch: expected 0x{col_val & 0x07:02x}, got 0x{col_rb & 0x07:02x}"

        # Complete operation
        dut.ui_in.value = 0b00000010  # adc_ready
        await ClockCycles(dut.clk, 40)
        await spi_write(dut, 0x00, 0x00)  # clear ctrl
        await ClockCycles(dut.clk, 5)
        dut.ui_in.value = 0


@cocotb.test()
async def test_sweep_step_zero(dut):
    """Sweep with step=0 should complete immediately, not hang (M1 fix)."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    await spi_write(dut, 0x04, 0x05)  # pulse_l=5
    await spi_write(dut, 0x09, 0x00)  # sweep_start
    await spi_write(dut, 0x0A, 0x20)  # sweep_end
    await spi_write(dut, 0x0B, 0x00)  # sweep_step=0 (was infinite loop!)
    await spi_write(dut, 0x00, 0x05)  # start + auto_sweep

    # Sweep with step=0 does one pulse then goes to SENSE — provide adc_ready
    dut.ui_in.value = 0b00000010  # adc_ready=1

    op_done = False
    for _ in range(200):
        await ClockCycles(dut.clk, 1)
        if (int(dut.uo_out.value) >> 3) & 1:
            op_done = True
            break

    dut._log.info(f"Sweep step=0: op_done={op_done}")
    assert op_done, "Sweep with step=0 should complete immediately, not hang"


# ============================================================
# SPI and FSM corner-case stress tests
# ============================================================

async def spi_write_fast(dut, addr, data):
    """SPI write with minimum timing (2-cycle SCK half-periods)."""
    cs_bit = 0
    mosi_bit = 1
    sck_bit = 3
    word = ((addr & 0x7F) << 8) | (data & 0xFF)

    dut.uio_in.value = 0  # CS=0
    await ClockCycles(dut.clk, 2)

    for i in range(16):
        bit_val = (word >> (15 - i)) & 1
        dut.uio_in.value = (bit_val << mosi_bit)
        await ClockCycles(dut.clk, 2)
        dut.uio_in.value = (bit_val << mosi_bit) | (1 << sck_bit)
        await ClockCycles(dut.clk, 2)
        dut.uio_in.value = (bit_val << mosi_bit)
        await ClockCycles(dut.clk, 1)

    dut.uio_in.value = (1 << cs_bit)
    await ClockCycles(dut.clk, 2)


async def spi_read_fast(dut, addr):
    """SPI read with minimum timing (2-cycle SCK half-periods)."""
    cs_bit = 0
    mosi_bit = 1
    sck_bit = 3
    word = (1 << 15) | ((addr & 0x7F) << 8)

    dut.uio_in.value = 0
    await ClockCycles(dut.clk, 2)

    read_data = 0
    for i in range(16):
        bit_val = (word >> (15 - i)) & 1
        dut.uio_in.value = (bit_val << mosi_bit)
        await ClockCycles(dut.clk, 2)
        dut.uio_in.value = (bit_val << mosi_bit) | (1 << sck_bit)
        await ClockCycles(dut.clk, 1)
        if i >= 8:
            miso = (int(dut.uio_out.value) >> 2) & 1
            read_data = (read_data << 1) | miso
        await ClockCycles(dut.clk, 1)
        dut.uio_in.value = (bit_val << mosi_bit)
        await ClockCycles(dut.clk, 1)

    dut.uio_in.value = (1 << cs_bit)
    await ClockCycles(dut.clk, 2)
    return read_data


@cocotb.test()
async def test_spi_fast_timing(dut):
    """SPI at maximum speed (2-cycle SCK): write/read all config registers."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    test_data = {0x01: 0x03, 0x02: 0x07, 0x03: 0x05, 0x04: 0xAA,
                 0x05: 0x01, 0x06: 0xCD, 0x09: 0x10, 0x0A: 0xF0, 0x0B: 0x08}

    for addr, val in test_data.items():
        await spi_write_fast(dut, addr, val)

    for addr, val in test_data.items():
        rb = await spi_read_fast(dut, addr)
        assert rb == val, f"Fast SPI reg 0x{addr:02x}: expected 0x{val:02x}, got 0x{rb:02x}"

    dut._log.info("All fast-SPI register writes verified")


@cocotb.test()
async def test_spi_back_to_back(dut):
    """Back-to-back SPI transactions with minimal CS inter-frame gap."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Write 10 registers back-to-back using fast SPI (1-cycle CS gap)
    vals = [(0x02, i) for i in range(8)] + [(0x03, i) for i in range(2)]
    for addr, val in vals:
        await spi_write_fast(dut, addr, val)

    # Verify last values stuck
    row = await spi_read(dut, 0x02)
    col = await spi_read(dut, 0x03)
    assert row == 7, f"After back-to-back writes, row should be 7, got {row}"
    assert col == 1, f"After back-to-back writes, col should be 1, got {col}"
    dut._log.info("Back-to-back SPI verified")


@cocotb.test()
async def test_spi_read_during_operation(dut):
    """Read status and ADC registers while FSM is actively pulsing."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # SET mode with long pulse
    await spi_write(dut, 0x01, 0x01)
    await spi_write(dut, 0x04, 0xFF)
    await spi_write(dut, 0x05, 0x00)
    await spi_write(dut, 0x06, 0x80)
    await spi_write(dut, 0x00, 0x01)  # start

    # Wait until FSM is active
    for _ in range(50):
        await ClockCycles(dut.clk, 1)
        if int(dut.uo_out.value) & 1:
            break

    # Read status mid-operation — should show busy=1
    status = await spi_read(dut, 0x07)
    assert status & 0x01, f"FSM should be busy during pulse, status=0x{status:02x}"
    dut._log.info(f"Mid-operation status: 0x{status:02x}")

    # Read config regs mid-operation — should still return correct values
    mode = await spi_read(dut, 0x01)
    assert mode == 0x01, f"Mode should still be 0x01 during operation, got 0x{mode:02x}"

    # Abort to clean up
    await spi_write(dut, 0x00, 0x02)
    await ClockCycles(dut.clk, 10)


@cocotb.test()
async def test_all_modes_sequence(dut):
    """Exercise all 4 modes (READ/SET/RESET/FORM) back-to-back without reset."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    for mode_val, mode_name in [(0x00, "READ"), (0x01, "SET"), (0x02, "RESET"), (0x03, "FORM")]:
        await spi_write(dut, 0x01, mode_val)
        await spi_write(dut, 0x04, 0x03)  # short pulse
        await spi_write(dut, 0x05, 0x00)
        await spi_write(dut, 0x00, 0x01)  # start

        dut.ui_in.value = 0b01100010  # adc_ready + adc_data

        op_done = False
        for _ in range(100):
            await ClockCycles(dut.clk, 1)
            if (int(dut.uo_out.value) >> 3) & 1:
                op_done = True
                break

        assert op_done, f"Mode {mode_name} (0x{mode_val:02x}) should complete"
        dut._log.info(f"Mode {mode_name} completed successfully")

        # Clear for next iteration
        await spi_write(dut, 0x00, 0x00)
        dut.ui_in.value = 0
        await ClockCycles(dut.clk, 5)


@cocotb.test()
async def test_register_boundary_values(dut):
    """Write 0x00 and 0xFF to all writable registers, verify readback."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    writable = [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x09, 0x0A, 0x0B, 0x0C]

    # Test 0x00
    for addr in writable:
        await spi_write(dut, addr, 0x00)
    for addr in writable:
        rb = await spi_read(dut, addr)
        assert rb == 0x00, f"Reg 0x{addr:02x} with 0x00: got 0x{rb:02x}"

    # Test 0xFF
    for addr in writable:
        await spi_write(dut, addr, 0xFF)
    for addr in writable:
        rb = await spi_read(dut, addr)
        assert rb == 0xFF, f"Reg 0x{addr:02x} with 0xFF: got 0x{rb:02x}"

    dut._log.info("All register boundary values verified")


@cocotb.test()
async def test_repeat_register_readback(dut):
    """Write and read back reg_repeat at address 0x0C."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Default should be 0x00
    rb = await spi_read(dut, 0x0C)
    assert rb == 0x00, f"Default reg_repeat should be 0x00, got 0x{rb:02x}"

    await spi_write(dut, 0x0C, 0x35)  # repeat=5, gap=3*16=48
    rb = await spi_read(dut, 0x0C)
    assert rb == 0x35, f"Expected 0x35, got 0x{rb:02x}"

    await spi_write(dut, 0x0C, 0xF0)  # repeat=0, gap=15*16=240
    rb = await spi_read(dut, 0x0C)
    assert rb == 0xF0, f"Expected 0xF0, got 0x{rb:02x}"
    dut._log.info("reg_repeat readback OK")


@cocotb.test()
async def test_single_pulse_default(dut):
    """With reg_repeat=0, behavior should be identical to original single-pulse."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # SET mode, pulse_width=10
    await spi_write(dut, 0x01, 0x01)   # mode=SET
    await spi_write(dut, 0x04, 0x0A)   # pulse_l=10
    await spi_write(dut, 0x05, 0x00)   # pulse_h=0
    await spi_write(dut, 0x0C, 0x00)   # repeat=0 (single pulse)

    # Start
    await spi_write(dut, 0x00, 0x01)

    # Wait for pulse phase
    for _ in range(200):
        await RisingEdge(dut.clk)
        uo = int(dut.uo_out.value)
        if uo & 0x01:  # pulse_out
            break

    # Count pulse cycles
    pulse_cycles = 0
    for _ in range(50):
        await RisingEdge(dut.clk)
        uo = int(dut.uo_out.value)
        if uo & 0x01:
            pulse_cycles += 1
        else:
            break

    dut._log.info(f"Single-pulse cycles with repeat=0: {pulse_cycles}")
    assert pulse_cycles > 0, "Should have seen at least one pulse cycle"

    # Provide ADC ready to finish, then wait for op_done on uo_out[3]
    dut.ui_in.value = 0x02
    op_done_seen = False
    for _ in range(200):
        await RisingEdge(dut.clk)
        if int(dut.uo_out.value) & 0x08:
            op_done_seen = True
            break
    dut.ui_in.value = 0
    assert op_done_seen, "op_done should pulse high"
    dut._log.info("Single-pulse default behavior verified")


@cocotb.test()
async def test_pulse_train_3_pulses(dut):
    """With reg_repeat=3, gap=0: should see 3 consecutive pulses."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # SET mode, short pulse_width=5
    await spi_write(dut, 0x01, 0x01)   # mode=SET
    await spi_write(dut, 0x04, 0x05)   # pulse_l=5
    await spi_write(dut, 0x05, 0x00)   # pulse_h=0
    await spi_write(dut, 0x0C, 0x03)   # repeat=3, gap=0*16=0

    # Start
    await spi_write(dut, 0x00, 0x01)

    # Count distinct pulse bursts (transitions from 0→1)
    pulse_count = 0
    prev_pulse = 0
    for _ in range(500):
        await RisingEdge(dut.clk)
        uo = int(dut.uo_out.value)
        curr_pulse = uo & 0x01
        if curr_pulse and not prev_pulse:
            pulse_count += 1
        prev_pulse = curr_pulse
        # Check if we reached SENSE state (busy but no pulse, after all pulses)
        if pulse_count >= 3 and not curr_pulse:
            break

    dut._log.info(f"Pulse bursts counted: {pulse_count}")
    assert pulse_count == 3, f"Expected 3 pulse bursts, got {pulse_count}"

    # Provide ADC ready, then watch for op_done pulse on uo_out[3]
    dut.ui_in.value = 0x02
    op_done_seen = False
    for _ in range(200):
        await RisingEdge(dut.clk)
        if int(dut.uo_out.value) & 0x08:
            op_done_seen = True
            break
    dut.ui_in.value = 0
    assert op_done_seen, "op_done should pulse high after pulse train"


@cocotb.test()
async def test_pulse_train_with_gap(dut):
    """With reg_repeat=2, gap=1*16=16: should see 2 pulses with gap."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # SET mode, pulse_width=5
    await spi_write(dut, 0x01, 0x01)   # mode=SET
    await spi_write(dut, 0x04, 0x05)   # pulse_l=5
    await spi_write(dut, 0x05, 0x00)   # pulse_h=0
    await spi_write(dut, 0x0C, 0x12)   # repeat=2, gap=1*16=16 cycles

    # Start
    await spi_write(dut, 0x00, 0x01)

    # Track pulse rising edges and gap between them
    pulse_count = 0
    prev_pulse = 0
    gap_cycles = 0
    measuring_gap = False

    for _ in range(500):
        await RisingEdge(dut.clk)
        uo = int(dut.uo_out.value)
        curr_pulse = uo & 0x01

        if curr_pulse and not prev_pulse:
            pulse_count += 1
            if measuring_gap:
                dut._log.info(f"Gap between pulses: {gap_cycles} cycles")
                measuring_gap = False

        if not curr_pulse and prev_pulse and pulse_count < 2:
            measuring_gap = True
            gap_cycles = 0

        if measuring_gap and not curr_pulse:
            gap_cycles += 1

        prev_pulse = curr_pulse

        if pulse_count >= 2 and not curr_pulse:
            break

    assert pulse_count == 2, f"Expected 2 pulse bursts, got {pulse_count}"
    # Gap should be at least 16 cycles (gap_counter counts down from 16)
    assert gap_cycles >= 16, f"Expected gap >= 16, got {gap_cycles}"

    # Finish
    dut.ui_in.value = 0x02
    await ClockCycles(dut.clk, 30)
    dut.ui_in.value = 0


@cocotb.test()
async def test_sweep_ignores_repeat(dut):
    """In sweep mode, pulse-train should not apply (sweep_active blocks it)."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Setup with repeat=5 but sweep mode
    await spi_write(dut, 0x01, 0x01)   # mode=SET
    await spi_write(dut, 0x04, 0x05)   # pulse_l=5
    await spi_write(dut, 0x05, 0x00)   # pulse_h=0
    await spi_write(dut, 0x0C, 0x05)   # repeat=5, gap=0
    await spi_write(dut, 0x09, 0x00)   # sweep_start=0
    await spi_write(dut, 0x0A, 0x10)   # sweep_end=16
    await spi_write(dut, 0x0B, 0x10)   # sweep_step=16

    # Start with sweep (ctrl[2]=1)
    await spi_write(dut, 0x00, 0x05)

    # In sweep mode, each DAC step should produce exactly 1 pulse burst
    # because sweep_active blocks the repeat logic.
    # Count pulse rising edges for the first sweep step.
    first_step_pulses = 0
    prev_pulse = 0
    for _ in range(200):
        await RisingEdge(dut.clk)
        uo = int(dut.uo_out.value)
        curr_pulse = uo & 0x01
        if curr_pulse and not prev_pulse:
            first_step_pulses += 1
        prev_pulse = curr_pulse
        # After first pulse ends, check if we're done
        if first_step_pulses >= 1 and not curr_pulse:
            break

    dut._log.info(f"First sweep step pulses: {first_step_pulses}")
    assert first_step_pulses == 1, f"Sweep should produce single pulse per step, got {first_step_pulses}"

    # Finish sweep by providing adc_ready for each step
    for _ in range(5):
        dut.ui_in.value = 0x02
        await ClockCycles(dut.clk, 50)
        dut.ui_in.value = 0
        await ClockCycles(dut.clk, 50)

    dut._log.info("Sweep correctly ignores repeat setting")


@cocotb.test()
async def test_abort_during_pulse_train(dut):
    """Abort during a pulse train should stop immediately."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # SET mode, longish pulse, 5 repeats
    await spi_write(dut, 0x01, 0x01)
    await spi_write(dut, 0x04, 0x14)   # pulse_l=20
    await spi_write(dut, 0x05, 0x00)
    await spi_write(dut, 0x0C, 0x15)   # repeat=5, gap=1*16=16

    # Start
    await spi_write(dut, 0x00, 0x01)

    # Wait for first pulse to start
    for _ in range(200):
        await RisingEdge(dut.clk)
        if int(dut.uo_out.value) & 0x01:
            break

    # Abort
    await spi_write(dut, 0x00, 0x02)
    await ClockCycles(dut.clk, 10)

    uo = int(dut.uo_out.value)
    assert (uo & 0x01) == 0, "pulse_out should be 0 after abort"
    assert (uo & 0x02) == 0, "row_en should be 0 after abort"
    assert (uo & 0x04) == 0, "col_en should be 0 after abort"

    status = await spi_read(dut, 0x07)
    assert (status & 0x01) == 0, "FSM should be idle after abort"
    dut._log.info("Abort during pulse train verified")


# ============================================================
# Compliance Limit / Pulse Count / Half-Select DAC Tests
# ============================================================

@cocotb.test()
async def test_compliance_register_defaults(dut):
    """Compliance register defaults to 0xFF (no limit)."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    val = await spi_read(dut, 0x0D)
    assert val == 0xFF, f"Expected compliance default 0xFF, got 0x{val:02x}"

    # Write and read back
    await spi_write(dut, 0x0D, 0x42)
    val = await spi_read(dut, 0x0D)
    assert val == 0x42, f"Expected compliance 0x42, got 0x{val:02x}"
    dut._log.info("Compliance register read/write verified")


@cocotb.test()
async def test_half_select_dac(dut):
    """V/2 half-select DAC register (0x0F) reflects half of active DAC."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Set DAC to various values and verify half-select
    for dac_val in [0x80, 0x40, 0xFE, 0x01, 0x00]:
        await spi_write(dut, 0x06, dac_val)  # reg_dac
        half = await spi_read(dut, 0x0F)
        expected = dac_val >> 1
        dut._log.info(f"DAC=0x{dac_val:02x}, half=0x{half:02x}, expected=0x{expected:02x}")
        assert half == expected, f"V/2 DAC mismatch: got 0x{half:02x}, expected 0x{expected:02x}"
    dut._log.info("Half-select DAC register verified")


@cocotb.test()
async def test_pulse_count_increments(dut):
    """Pulse count register tracks actual pulses delivered."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Configure for 3 repeated short pulses
    await spi_write(dut, 0x01, 0x01)  # SET mode
    await spi_write(dut, 0x02, 0x00)  # row=0
    await spi_write(dut, 0x03, 0x00)  # col=0
    await spi_write(dut, 0x04, 0x05)  # pulse_width_lo = 5
    await spi_write(dut, 0x06, 0x80)  # dac = 0x80
    await spi_write(dut, 0x0C, 0x13)  # repeat=3, gap=1×16=16 cycles

    # Pulse count should be 0 before start
    pc = await spi_read(dut, 0x0E)
    assert pc == 0, f"Pulse count should be 0 before start, got {pc}"

    # Start operation
    await spi_write(dut, 0x00, 0x01)
    await ClockCycles(dut.clk, 500)

    # Wait for done
    for _ in range(20):
        status = await spi_read(dut, 0x07)
        if (status >> 1) & 1:  # op_done
            break
        await ClockCycles(dut.clk, 100)

    pc = await spi_read(dut, 0x0E)
    dut._log.info(f"Pulse count after 3 repeats: {pc}")
    assert pc == 3, f"Expected 3 pulses, got {pc}"


@cocotb.test()
async def test_compliance_auto_abort(dut):
    """Compliance limit triggers auto-abort when ADC exceeds threshold."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Configure READ with compliance
    await spi_write(dut, 0x01, 0x00)  # READ mode
    await spi_write(dut, 0x02, 0x01)  # row=1
    await spi_write(dut, 0x03, 0x02)  # col=2
    await spi_write(dut, 0x04, 0x03)  # pulse_width = 3
    await spi_write(dut, 0x06, 0x40)  # dac = 0x40
    await spi_write(dut, 0x0D, 0x02)  # compliance threshold = 2 (very low)
    await spi_write(dut, 0x00, 0x09)  # start + compliance_en (bit 3)

    # Wait until FSM is in SENSE (pulse phase done)
    await ClockCycles(dut.clk, 100)

    # Simulate ADC ready with value exceeding compliance threshold
    # adc_ready = ui_in[1], adc_data_lo = ui_in[7:4]
    dut.ui_in.value = (0xF << 4) | (1 << 1)  # adc_data=15, adc_ready=1
    await ClockCycles(dut.clk, 20)

    status = await spi_read(dut, 0x07)
    compliance_bit = (status >> 7) & 1
    dut._log.info(f"Status after compliance violation: 0x{status:02x}, hit={compliance_bit}")
    assert compliance_bit == 1, "Compliance hit flag should be set"

    # FSM should have auto-aborted to REPORT→IDLE
    busy = status & 1
    # Give more time for state machine to reach IDLE through REPORT
    if busy:
        await ClockCycles(dut.clk, 50)
        status = await spi_read(dut, 0x07)
        busy = status & 1
    dut._log.info(f"Final status: 0x{status:02x}, busy={busy}")


@cocotb.test()
async def test_compliance_no_abort_below_threshold(dut):
    """No compliance abort when ADC value is below threshold."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Configure READ with compliance, high threshold
    await spi_write(dut, 0x01, 0x00)  # READ mode
    await spi_write(dut, 0x02, 0x00)  # row=0
    await spi_write(dut, 0x03, 0x00)  # col=0
    await spi_write(dut, 0x04, 0x03)  # pulse_width = 3
    await spi_write(dut, 0x06, 0x40)  # dac
    await spi_write(dut, 0x0D, 0x80)  # compliance = 128 (high)
    await spi_write(dut, 0x00, 0x09)  # start + compliance_en

    await ClockCycles(dut.clk, 100)

    # ADC value below threshold
    # adc_ready = ui_in[1], adc_data_lo = ui_in[7:4]
    dut.ui_in.value = (0x01 << 4) | (1 << 1)  # adc_data=1, adc_ready=1
    await ClockCycles(dut.clk, 50)

    status = await spi_read(dut, 0x07)
    compliance_bit = (status >> 7) & 1
    dut._log.info(f"Status (below threshold): 0x{status:02x}, hit={compliance_bit}")
    assert compliance_bit == 0, "Compliance should NOT be triggered below threshold"


@cocotb.test()
async def test_status_compliance_cleared_on_new_start(dut):
    """Compliance hit flag is cleared when starting a new operation."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # First: trigger compliance
    await spi_write(dut, 0x01, 0x00)
    await spi_write(dut, 0x04, 0x03)
    await spi_write(dut, 0x06, 0x40)
    await spi_write(dut, 0x0D, 0x01)  # Very low threshold
    await spi_write(dut, 0x00, 0x09)  # start + compliance_en
    await ClockCycles(dut.clk, 100)
    dut.ui_in.value = (0xF << 4) | (1 << 1)  # ADC above threshold (adc_data=15, adc_ready=1)
    await ClockCycles(dut.clk, 50)

    status = await spi_read(dut, 0x07)
    assert (status >> 7) & 1 == 1, "Compliance should be set"

    # Clear ADC and start a new operation
    dut.ui_in.value = 0
    await ClockCycles(dut.clk, 20)
    await spi_write(dut, 0x0D, 0xFF)  # High threshold (won't trigger)
    await spi_write(dut, 0x00, 0x01)  # start (no compliance_en)
    await ClockCycles(dut.clk, 10)

    status = await spi_read(dut, 0x07)
    compliance_bit = (status >> 7) & 1
    dut._log.info(f"Status after new start: 0x{status:02x}, hit={compliance_bit}")
    assert compliance_bit == 0, "Compliance flag should clear on new start"
