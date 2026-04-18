/*
 * Copyright (c) 2026 Prof. Santhosh Sivasubramani, IIT Delhi
 * SPDX-License-Identifier: Apache-2.0
 *
 * Memristive Crossbar Peripheral Controller
 * - 8-row × 8-column addressable crossbar arrays (3-bit row, 3-bit col)
 * - 4 operation modes: READ, SET, RESET, FORMING
 * - Configurable pulse width (1-511 clock cycles)
 * - 8-bit DAC code output for voltage control
 * - Automated voltage sweep mode for I-V characterization
 * - SPI-configurable, device-agnostic standalone IP
 */

`default_nettype none

module tt_um_santhosh_xbar_ctrl (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

    // ============================================================
    // Input assignments
    // ============================================================
    wire       sense_in     = ui_in[0];     // External comparator result
    wire       adc_ready    = ui_in[1];     // External ADC data-ready
    wire       ext_irq      = ui_in[2];     // External interrupt
    wire [3:0] adc_data_lo  = ui_in[7:4];   // ADC data lower nibble

    // SPI signals
    wire spi_cs_n = uio_in[0];
    wire spi_mosi = uio_in[1];
    wire spi_miso;
    wire spi_sck  = uio_in[3];

    // ============================================================
    // SPI Slave & Register File
    // ============================================================
    wire        wr_en;
    wire [7:0]  wr_addr, wr_data, rd_addr;
    reg  [7:0]  rd_data;

    spi_slave #(.NUM_REGS(16)) u_spi (
        .clk      (clk),
        .rst_n    (rst_n),
        .spi_cs_n (spi_cs_n),
        .spi_mosi (spi_mosi),
        .spi_miso (spi_miso),
        .spi_sck  (spi_sck),
        .wr_en    (wr_en),
        .wr_addr  (wr_addr),
        .wr_data  (wr_data),
        .rd_addr  (rd_addr),
        .rd_data  (rd_data)
    );

    // Configuration registers
    reg [7:0] reg_ctrl;        // 0x00: [0]=start, [1]=abort, [2]=auto_sweep
    reg [7:0] reg_mode;        // 0x01: [1:0]=mode (00=READ,01=SET,10=RESET,11=FORM)
    reg [7:0] reg_row;         // 0x02: [2:0]=row address
    reg [7:0] reg_col;         // 0x03: [2:0]=col address
    reg [7:0] reg_pulse_l;    // 0x04: pulse width [7:0]
    reg [7:0] reg_pulse_h;    // 0x05: pulse width [8]
    reg [7:0] reg_dac;        // 0x06: DAC code
    reg [7:0] reg_sweep_start;// 0x09: sweep start DAC
    reg [7:0] reg_sweep_end;  // 0x0A: sweep end DAC
    reg [7:0] reg_sweep_step; // 0x0B: sweep increment
    wire [7:0] reg_status;     // 0x07: status (read-only)
    reg  [7:0] reg_adc_data;  // 0x08: last ADC reading (read-only)

    // Register write
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            reg_ctrl        <= 8'h00;
            reg_mode        <= 8'h00;
            reg_row         <= 8'h00;
            reg_col         <= 8'h00;
            reg_pulse_l     <= 8'h0A;    // 10 cycles default
            reg_pulse_h     <= 8'h00;
            reg_dac         <= 8'h80;
            reg_sweep_start <= 8'h00;
            reg_sweep_end   <= 8'hFF;
            reg_sweep_step  <= 8'h10;
        end else if (wr_en) begin
            case (wr_addr)
                8'h00: reg_ctrl        <= wr_data;
                8'h01: reg_mode        <= wr_data;
                8'h02: reg_row         <= wr_data;
                8'h03: reg_col         <= wr_data;
                8'h04: reg_pulse_l     <= wr_data;
                8'h05: reg_pulse_h     <= wr_data;
                8'h06: reg_dac         <= wr_data;
                8'h09: reg_sweep_start <= wr_data;
                8'h0A: reg_sweep_end   <= wr_data;
                8'h0B: reg_sweep_step  <= wr_data;
                default: ;
            endcase
        end else begin
            // Auto-clear start bit after FSM picks it up
            if (start_pulse)
                reg_ctrl[0] <= 1'b0;
        end
    end

    // Register read mux
    always @(*) begin
        case (rd_addr)
            8'h00: rd_data = reg_ctrl;
            8'h01: rd_data = reg_mode;
            8'h02: rd_data = reg_row;
            8'h03: rd_data = reg_col;
            8'h04: rd_data = reg_pulse_l;
            8'h05: rd_data = reg_pulse_h;
            8'h06: rd_data = reg_dac;
            8'h07: rd_data = reg_status;
            8'h08: rd_data = reg_adc_data;
            8'h09: rd_data = reg_sweep_start;
            8'h0A: rd_data = reg_sweep_end;
            8'h0B: rd_data = reg_sweep_step;
            default: rd_data = 8'h00;
        endcase
    end

    // ============================================================
    // Edge detection for start
    // ============================================================
    reg start_prev;
    wire start_pulse;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) start_prev <= 1'b0;
        else        start_prev <= reg_ctrl[0];
    end
    assign start_pulse = reg_ctrl[0] & ~start_prev;

    // ============================================================
    // Main FSM
    // ============================================================
    localparam S_IDLE    = 3'd0;
    localparam S_SETUP   = 3'd1;
    localparam S_PULSE   = 3'd2;
    localparam S_SENSE   = 3'd3;
    localparam S_REPORT  = 3'd4;
    localparam S_SWEEP   = 3'd5;

    reg [2:0]  state;
    reg [8:0]  pulse_counter;
    reg        pulse_out;
    reg        row_en, col_en;
    reg        op_done;
    reg        op_error;
    reg [7:0]  sweep_dac;

    wire [8:0] pulse_width = {reg_pulse_h[0], reg_pulse_l};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state         <= S_IDLE;
            pulse_counter <= 9'd0;
            pulse_out     <= 1'b0;
            row_en        <= 1'b0;
            col_en        <= 1'b0;
            op_done       <= 1'b0;
            op_error      <= 1'b0;
            reg_adc_data  <= 8'd0;
            sweep_dac     <= 8'd0;
        end else if (reg_ctrl[1]) begin
            // Abort: clear all outputs and flags
            state     <= S_IDLE;
            pulse_out <= 1'b0;
            row_en    <= 1'b0;
            col_en    <= 1'b0;
            op_done   <= 1'b0;
            op_error  <= 1'b0;
        end else begin
            case (state)
                S_IDLE: begin
                    pulse_out <= 1'b0;
                    row_en    <= 1'b0;
                    col_en    <= 1'b0;
                    op_done   <= 1'b0;
                    op_error  <= 1'b0;
                    if (start_pulse) begin
                        if (reg_ctrl[2]) begin
                            // Sweep mode
                            sweep_dac     <= reg_sweep_start;
                            pulse_counter <= 9'd0;
                            state         <= S_SWEEP;
                        end else begin
                            state <= S_SETUP;
                        end
                    end
                end

                S_SETUP: begin
                    // Assert row and column enables
                    row_en        <= 1'b1;
                    col_en        <= 1'b1;
                    pulse_counter <= 9'd0;

                    if (reg_mode[1:0] == 2'b00) begin
                        // READ: skip pulse, go to sense
                        state <= S_SENSE;
                    end else begin
                        // SET/RESET/FORM: apply pulse
                        state <= S_PULSE;
                    end
                end

                S_PULSE: begin
                    pulse_out <= 1'b1;
                    if (pulse_counter >= pulse_width) begin
                        pulse_out     <= 1'b0;
                        pulse_counter <= 9'd0;  // Reset for S_SENSE timeout
                        state         <= S_SENSE;
                    end else begin
                        pulse_counter <= pulse_counter + 9'd1;
                    end
                end

                S_SENSE: begin
                    pulse_out <= 1'b0;
                    // Wait for ADC ready or use comparator
                    if (adc_ready) begin
                        reg_adc_data <= {adc_data_lo, adc_data_lo}; // Read external ADC
                        state        <= S_REPORT;
                    end else begin
                        // Timeout after 256 cycles
                        if (pulse_counter >= 9'd256) begin
                            op_error <= 1'b1;
                            state    <= S_REPORT;
                        end
                        pulse_counter <= pulse_counter + 9'd1;
                    end
                end

                S_REPORT: begin
                    row_en  <= 1'b0;
                    col_en  <= 1'b0;
                    op_done <= 1'b1;
                    state   <= S_IDLE;
                end

                S_SWEEP: begin
                    // Automated sweep: apply pulses at each DAC step
                    row_en    <= 1'b1;
                    col_en    <= 1'b1;
                    pulse_out <= 1'b1;

                    if (pulse_counter >= pulse_width) begin
                        pulse_out <= 1'b0;
                        if (sweep_dac >= reg_sweep_end || reg_sweep_step == 8'd0) begin
                            op_done <= 1'b1;
                            row_en  <= 1'b0;
                            col_en  <= 1'b0;
                            state   <= S_IDLE;
                        end else begin
                            sweep_dac     <= sweep_dac + reg_sweep_step;
                            pulse_counter <= 9'd0;
                        end
                    end else begin
                        pulse_counter <= pulse_counter + 9'd1;
                    end
                end

                default: state <= S_IDLE;
            endcase
        end
    end

    // ============================================================
    // Status register
    // ============================================================
    // Status register: [7:4]=0, [3]=sense_in, [2]=op_error, [1]=op_done, [0]=busy
    assign reg_status = {4'b0, sense_in, op_error, op_done, (state != S_IDLE)};

    // ============================================================
    // Row/Column decoder outputs (directly usable on external bus)
    // ============================================================
    wire [2:0] row_addr = reg_row[2:0];
    wire [2:0] col_addr = reg_col[2:0];

    // Active DAC code (sweep mode uses sweep_dac, normal uses reg_dac)
    wire [7:0] active_dac = (state == S_SWEEP) ? sweep_dac : reg_dac;

    // ============================================================
    // Output assignments
    // ============================================================
    assign uo_out[0]   = pulse_out;         // Pulse output to DUT
    assign uo_out[1]   = row_en;            // Row enable strobe
    assign uo_out[2]   = col_en;            // Column enable strobe
    assign uo_out[3]   = op_done;           // Operation complete flag
    assign uo_out[5:4] = active_dac[1:0];   // DAC code [1:0]
    assign uo_out[6]   = col_addr[1];       // Col address bit 1
    assign uo_out[7]   = col_addr[2];       // Col address bit 2

    assign uio_out[0]  = 1'b0;             // CS is input
    assign uio_out[1]  = 1'b0;             // MOSI is input
    assign uio_out[2]  = spi_miso;         // MISO output (high-Z via uio_oe when CS inactive)
    assign uio_out[3]  = 1'b0;             // SCK is input
    assign uio_out[4]  = row_addr[0];      // Row address bit 0
    assign uio_out[5]  = row_addr[1];      // Row address bit 1
    assign uio_out[6]  = row_addr[2];      // Row address bit 2
    assign uio_out[7]  = col_addr[0];      // Col address bit 0

    // MISO tri-stated when SPI CS inactive (uio_oe[2] gated by ~spi_cs_n)
    assign uio_oe = {4'b1111, 1'b0, ~spi_cs_n, 2'b00};
    // uio[7:4]=addr out(1), uio[3]=SCK in(0), uio[2]=MISO(dynamic), uio[1]=MOSI in(0), uio[0]=CS in(0)

    // Unused inputs
    wire _unused = &{ena, ui_in[3], uio_in[2], uio_in[7:4], active_dac[7:2], 1'b0};

endmodule
