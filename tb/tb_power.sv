`timescale 1ns/1ps
// Power-analysis run: streams a few real pixels through the post-PnR netlist
// and dumps a VCD so OpenSTA can annotate switching activity.
//
//   vvp build/tb_power.vvp +stim=stim/real/frame.hex +cfg=stim/real/cfg.hex \
//       +vcd=out/power.vcd
//
// The clock period is 25 ns to match the signoff SDC, otherwise OpenSTA scales
// the VCD activity against the wrong cycle.
module tb_power;
    parameter int W = 8;
    parameter int H = 8;
    localparam int NPIX = W * H;

    logic clk = 0;
    logic rst_n = 0;
    always #12.5 clk = ~clk;

    supply1 VPWR;
    supply0 VGND;

    logic        vin_valid = 0;
    logic [7:0]  vin_r = 0, vin_g = 0, vin_b = 0;

    logic        vout_valid;
    logic [23:0] vout_normal, vout_relight0, vout_relight1;
    logic [7:0]  vout_albedo, vout_conf;

    logic        cfg_we = 0;
    logic [5:0]  cfg_addr = 0;
    logic [31:0] cfg_wdata = 0;
    logic [31:0] cfg_rdata;

    chromaps dut (
        .clk(clk), .rst_n(rst_n),
        .vin_valid(vin_valid), .vin_r(vin_r), .vin_g(vin_g), .vin_b(vin_b),
        .vout_valid(vout_valid), .vout_normal(vout_normal),
        .vout_albedo(vout_albedo), .vout_relight0(vout_relight0),
        .vout_relight1(vout_relight1), .vout_conf(vout_conf),
        .cfg_we(cfg_we), .cfg_addr(cfg_addr), .cfg_wdata(cfg_wdata),
        .cfg_rdata(cfg_rdata),
        .VPWR(VPWR), .VGND(VGND)
    );

    logic [23:0] mem [0:NPIX-1];
    logic [31:0] cfg_mem [0:31];

    integer i;
    integer nout = 0;
    string stim_path, cfg_path, vcd_path;

    task automatic cfg_write(input [5:0] a, input [31:0] d);
        @(posedge clk);
        cfg_we    <= 1'b1;
        cfg_addr  <= a;
        cfg_wdata <= d;
        @(posedge clk);
        cfg_we    <= 1'b0;
    endtask

    initial begin
        if (!$value$plusargs("stim=%s", stim_path)) stim_path = "stim/real/frame.hex";
        if (!$value$plusargs("cfg=%s", cfg_path))   cfg_path  = "stim/real/cfg.hex";
        if (!$value$plusargs("vcd=%s", vcd_path))   vcd_path  = "out/power.vcd";

        $readmemh(stim_path, mem);
        $readmemh(cfg_path, cfg_mem);

        $dumpfile(vcd_path);
        $dumpvars(1, dut);

        repeat (4) @(posedge clk);
        rst_n <= 1'b1;
        repeat (2) @(posedge clk);

        for (i = 0; i < 32; i = i + 1) cfg_write(i[5:0], cfg_mem[i]);

        for (i = 0; i < NPIX; i = i + 1) begin
            @(posedge clk);
            vin_valid <= 1'b1;
            vin_r     <= mem[i][23:16];
            vin_g     <= mem[i][15:8];
            vin_b     <= mem[i][7:0];
        end
        @(posedge clk);
        vin_valid <= 1'b0;

        repeat (70) @(posedge clk);
        $display("DONE outputs=%0d expected=%0d", nout, NPIX);
        $finish;
    end

    always @(posedge clk) if (vout_valid) nout <= nout + 1;
endmodule
