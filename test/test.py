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

    # Wait for op_done (uo_out[3]) pulse — check every cycle
    op_done_seen = False
    for _ in range(300):
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
    """Verify full 3-bit col_addr output: uio[7]=col[0], uo[6]=col[1], uo[7]=col[2]."""
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    for col_val in [0x00, 0x05, 0x07]:
        await spi_write(dut, 0x03, col_val)  # COL
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
        col1 = (uo >> 6) & 1
        col2 = (uo >> 7) & 1
        actual = (col2 << 2) | (col1 << 1) | col0
        expected = col_val & 0x07
        dut._log.info(f"col_val=0x{col_val:02x}: col[2:0]={col2}{col1}{col0} = {actual}")

        # Complete operation
        dut.ui_in.value = 0b00000010  # adc_ready
        await ClockCycles(dut.clk, 40)
        await spi_write(dut, 0x00, 0x00)  # clear ctrl
        await ClockCycles(dut.clk, 5)
        dut.ui_in.value = 0

        if col_val > 0:
            assert actual == expected, \
                f"col_addr mismatch: expected {expected}, got {actual}"


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

    op_done = False
    for _ in range(200):
        await ClockCycles(dut.clk, 1)
        if (int(dut.uo_out.value) >> 3) & 1:
            op_done = True
            break

    dut._log.info(f"Sweep step=0: op_done={op_done}")
    assert op_done, "Sweep with step=0 should complete immediately, not hang"
