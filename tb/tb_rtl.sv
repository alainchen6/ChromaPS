`timescale 1ns/1ps
// Streams stim/frame.hex through the core and writes one hex line per output
// pixel for each channel, so they can be diffed against model/golden.py.
module tb_rtl;
    parameter int W = 320;
    parameter int H = 240;
    localparam int NPIX = W * H;

    logic clk = 0;
    logic rst_n = 0;
    always #5 clk = ~clk;

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
        .cfg_rdata(cfg_rdata)
    );

    logic [23:0] mem [0:NPIX-1];
    logic [31:0] cfg_mem [0:31];

    integer f_n, f_a, f_r0, f_r1, f_c;
    integer i;
    integer nout = 0;

    task automatic cfg_write(input [5:0] a, input [31:0] d);
        @(posedge clk);
        cfg_we    <= 1'b1;
        cfg_addr  <= a;
        cfg_wdata <= d;
        @(posedge clk);
        cfg_we    <= 1'b0;
    endtask

    string stim_path;
    string cfg_path;
    string prefix;

    initial begin
        if (!$value$plusargs("stim=%s", stim_path)) stim_path = "stim/frame.hex";
        if (!$value$plusargs("cfg=%s", cfg_path))   cfg_path  = "stim/cfg.hex";
        if (!$value$plusargs("prefix=%s", prefix))  prefix    = "out/rtl";
        $display("loading stimulus %s (%0d x %0d)", stim_path, W, H);
        $readmemh(stim_path, mem);
        $readmemh(cfg_path, cfg_mem);

        f_n  = $fopen({prefix, "_normal.hex"}, "w");
        f_a  = $fopen({prefix, "_albedo.hex"}, "w");
        f_r0 = $fopen({prefix, "_relight0.hex"}, "w");
        f_r1 = $fopen({prefix, "_relight1.hex"}, "w");
        f_c  = $fopen({prefix, "_conf.hex"}, "w");

        repeat (4) @(posedge clk);
        rst_n <= 1'b1;
        repeat (2) @(posedge clk);

        // exercise the configuration path (values match model/render.py)
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

        repeat (120) @(posedge clk);

        $fclose(f_n);
        $fclose(f_a);
        $fclose(f_r0);
        $fclose(f_r1);
        $fclose(f_c);

        $display("DONE outputs=%0d expected=%0d", nout, NPIX);
        if (nout != NPIX) $display("ERROR pixel count mismatch");
        $finish;
    end

    always @(posedge clk) begin
        if (vout_valid) begin
            $fwrite(f_n,  "%06x\n", vout_normal);
            $fwrite(f_a,  "%02x\n", vout_albedo);
            $fwrite(f_r0, "%02x\n", vout_relight0[7:0]);
            $fwrite(f_r1, "%02x\n", vout_relight1[7:0]);
            $fwrite(f_c,  "%02x\n", vout_conf);
            nout <= nout + 1;
        end
    end
endmodule
