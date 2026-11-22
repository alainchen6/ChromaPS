`timescale 1ns/1ps
// Gate-level short run: same pixel stream as the RTL bench, but on the
// post-PnR netlist with SDF back-annotation.  Pass the SDF with +sdf=<path>.
module tb_gls;
    parameter int W = 64;
    parameter int H = 64;
    localparam int NPIX = W * H;

    logic clk = 0;
    logic rst_n = 0;
    always #50 clk = ~clk;      // 10 MHz: far below the 100 MHz signoff target

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

    integer f_n, f_a, f_r0, f_r1, f_c;
    integer i;
    integer nout = 0;
    string  sdf_path;

    task automatic cfg_write(input [5:0] a, input [31:0] d);
        @(posedge clk);
        cfg_we    <= 1'b1;
        cfg_addr  <= a;
        cfg_wdata <= d;
        @(posedge clk);
        cfg_we    <= 1'b0;
    endtask

    initial begin
`ifdef SDF_ANNOTATE
        if (!$value$plusargs("sdf=%s", sdf_path)) begin
            $display("ERROR: pass +sdf=<file>");
            $finish;
        end
        $display("SDF: %s", sdf_path);
        $sdf_annotate(sdf_path, dut);
`endif

        $readmemh("stim/slice.hex", mem);
        f_n  = $fopen("out/gls_normal.hex", "w");
        f_a  = $fopen("out/gls_albedo.hex", "w");
        f_r0 = $fopen("out/gls_relight0.hex", "w");
        f_r1 = $fopen("out/gls_relight1.hex", "w");
        f_c  = $fopen("out/gls_conf.hex", "w");

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

        repeat (120) @(posedge clk);

        $fclose(f_n);
        $fclose(f_a);
        $fclose(f_r0);
        $fclose(f_r1);
        $fclose(f_c);
        $display("DONE outputs=%0d expected=%0d", nout, NPIX);
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
