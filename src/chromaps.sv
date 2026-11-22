// ChromaPS -- single-shot colour-multiplexed photometric stereo core.
//
//   one RGB frame in  ->  surface normal, albedo, two relit frames, confidence
//
// Fixed-point contract (must match model/golden.py exactly):
//   I'_k   = min(1023, (I_k * wb_k) >> 8)                 wb Q2.8
//   g_i    = clamp((sum_k A[i][k].I'_k + 128) >> 8)       A Q2.13, g Q2.13
//   rho    = isqrt(sum_i g_i^2)                           Q2.13
//   inv    = 32768 if rho < 2048 else min(32768, 2^26/rho)
//   n_i    = (g_i * inv) >> 13                            Q1.13
//   normal = clamp(((n_i + 8192) * 255 + 8192) >> 14)
//   albedo = clamp((rho * 255 + 4096) >> 13)
//   relit  = clamp((((sum_i g_i.lv_i + 8192) >> 14) * 255 + 4096) >> 13)
//   conf   = 0 if any I <= low, any I >= sat, or rho < mag else 255
//
// One pixel per cycle, no back-pressure.  Latency is 50 cycles, and every
// valid bit travels with its own data so the two can never drift apart.
module chromaps (
    input  logic        clk,
    input  logic        rst_n,

    input  logic        vin_valid,
    input  logic [7:0]  vin_r,
    input  logic [7:0]  vin_g,
    input  logic [7:0]  vin_b,

    output logic        vout_valid,
    output logic [23:0] vout_normal,
    output logic [7:0]  vout_albedo,
    output logic [23:0] vout_relight0,
    output logic [23:0] vout_relight1,
    output logic [7:0]  vout_conf,

    input  logic        cfg_we,
    input  logic [5:0]  cfg_addr,
    input  logic [31:0] cfg_wdata,
    output logic [31:0] cfg_rdata
);
    // ------------------------------------------------------------ configuration
    logic [31:0] cfg [0:31];
    assign cfg_rdata = cfg[cfg_addr];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cfg[0]  <= 32'h0000_0001;
            cfg[1]  <=  32'sd10923; cfg[2]  <= -32'sd5461; cfg[3]  <= -32'sd5461;
            cfg[4]  <=  32'sd0;     cfg[5]  <=  32'sd9459; cfg[6]  <= -32'sd9459;
            cfg[7]  <=  32'sd3153;  cfg[8]  <=  32'sd3153; cfg[9]  <=  32'sd3153;
            cfg[10] <=  32'sd256;   cfg[11] <=  32'sd256;  cfg[12] <=  32'sd256;
            cfg[13] <=  32'sd6769;  cfg[14] <= -32'sd8068; cfg[15] <=  32'sd12551;
            cfg[16] <=  32'sd3602;  cfg[17] <=  32'sd9896; cfg[18] <=  32'sd12551;
            cfg[19] <= 32'h0800_FB04;
            for (int k = 20; k < 31; k++) cfg[k] <= '0;
            cfg[31] <= 32'h0001_0000;
        end else if (cfg_we) begin
            cfg[cfg_addr] <= cfg_wdata;
        end
    end

    wire         en     = cfg[0][0];
    wire [7:0]   th_low = cfg[19][7:0];
    wire [7:0]   th_sat = cfg[19][15:8];
    wire [15:0]  th_mag = cfg[19][31:16];

    // ------------------------------------------------------------ s1: white balance
    logic [9:0]  wb_r [0:2];
    logic [17:0] wb_p [0:2];
    logic        v1;

    assign wb_p[0] = vin_r * cfg[10][9:0];
    assign wb_p[1] = vin_g * cfg[11][9:0];
    assign wb_p[2] = vin_b * cfg[12][9:0];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            v1 <= 1'b0;
            for (int k = 0; k < 3; k++) wb_r[k] <= '0;
        end else begin
            v1 <= vin_valid & en;
            for (int k = 0; k < 3; k++)
                wb_r[k] <= (wb_p[k][17:8] > 10'd1023) ? 10'd1023 : wb_p[k][17:8];
        end
    end

    // ------------------------------------------------------------ s2: A x image
    logic signed [31:0] mat3_y [0:2];
    logic signed [31:0] acc [0:2];
    logic               v2;

    mat3 u_mat3 (
        .a00($signed(cfg[1][15:0])), .a01($signed(cfg[2][15:0])), .a02($signed(cfg[3][15:0])),
        .a10($signed(cfg[4][15:0])), .a11($signed(cfg[5][15:0])), .a12($signed(cfg[6][15:0])),
        .a20($signed(cfg[7][15:0])), .a21($signed(cfg[8][15:0])), .a22($signed(cfg[9][15:0])),
        .x0(wb_r[0]), .x1(wb_r[1]), .x2(wb_r[2]),
        .y0(mat3_y[0]), .y1(mat3_y[1]), .y2(mat3_y[2])
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            v2 <= 1'b0;
            for (int k = 0; k < 3; k++) acc[k] <= '0;
        end else begin
            v2 <= v1;
            for (int k = 0; k < 3; k++) acc[k] <= mat3_y[k];
        end
    end

    // ------------------------------------------------------------ s3: g = rho * n
    logic signed [17:0] g_r [0:2];
    logic               v3;

    function automatic logic signed [17:0] clamp_g(input logic signed [31:0] a);
        logic signed [31:0] s;
        begin
            s = (a + 32'sd128) >>> 8;
            if (s > 32'sd32767)       clamp_g = 18'sd32767;
            else if (s < -32'sd32768) clamp_g = -18'sd32768;
            else                      clamp_g = s[17:0];
        end
    endfunction

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            v3 <= 1'b0;
            for (int k = 0; k < 3; k++) g_r[k] <= '0;
        end else begin
            v3 <= v2;
            for (int k = 0; k < 3; k++) g_r[k] <= clamp_g(acc[k]);
        end
    end

    // ------------------------------------------------------------ s4: squares, relight, flags
    logic [35:0] sq [0:2];
    logic [31:0] sum_r;
    logic signed [34:0] rel_raw [0:1];
    logic        v4;

    assign sq[0] = g_r[0] * g_r[0];
    assign sq[1] = g_r[1] * g_r[1];
    assign sq[2] = g_r[2] * g_r[2];

    assign rel_raw[0] = $signed(g_r[0]) * $signed(cfg[13][15:0])
                      + $signed(g_r[1]) * $signed(cfg[14][15:0])
                      + $signed(g_r[2]) * $signed(cfg[15][15:0]);
    assign rel_raw[1] = $signed(g_r[0]) * $signed(cfg[16][15:0])
                      + $signed(g_r[1]) * $signed(cfg[17][15:0])
                      + $signed(g_r[2]) * $signed(cfg[18][15:0]);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            v4   <= 1'b0;
            sum_r <= '0;
        end else begin
            v4    <= v3;
            sum_r <= sq[0][31:0] + sq[1][31:0] + sq[2][31:0];
        end
    end

    // input pixels delayed to the s4 time slot, for the shadow / saturation flags
    logic [7:0] i_d1 [0:2];
    logic [7:0] i_d2 [0:2];
    logic [7:0] i_d3 [0:2];
    logic [7:0] i_d4 [0:2];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (int k = 0; k < 3; k++) begin
                i_d1[k] <= '0; i_d2[k] <= '0; i_d3[k] <= '0; i_d4[k] <= '0;
            end
        end else begin
            i_d1[0] <= vin_r; i_d1[1] <= vin_g; i_d1[2] <= vin_b;
            i_d2[0] <= i_d1[0]; i_d2[1] <= i_d1[1]; i_d2[2] <= i_d1[2];
            i_d3[0] <= i_d2[0]; i_d3[1] <= i_d2[1]; i_d3[2] <= i_d2[2];
            i_d4[0] <= i_d3[0]; i_d4[1] <= i_d3[1]; i_d4[2] <= i_d3[2];
        end
    end

    function automatic logic [7:0] min3(input logic [7:0] a, b, c);
        logic [7:0] m;
        begin
            m = (a < b) ? a : b;
            min3 = (m < c) ? m : c;
        end
    endfunction

    function automatic logic [7:0] max3(input logic [7:0] a, b, c);
        logic [7:0] m;
        begin
            m = (a > b) ? a : b;
            max3 = (m > c) ? m : c;
        end
    endfunction

    wire [1:0] bad_w = {max3(i_d4[0], i_d4[1], i_d4[2]) >= th_sat,
                        min3(i_d4[0], i_d4[1], i_d4[2]) <= th_low};

    // ------------------------------------------------------------ s5: relight encode
    function automatic logic [7:0] enc_rel(input logic signed [34:0] raw);
        logic signed [34:0] q13;
        logic signed [43:0] scaled;
        begin
            q13    = (raw + 35'sd8192) >>> 14;
            scaled = (((q13 <<< 8) - q13) + 44'sd4096) >>> 13;
            if (scaled < 0)             enc_rel = 8'd0;
            else if (scaled > 44'sd255) enc_rel = 8'd255;
            else                        enc_rel = scaled[7:0];
        end
    endfunction

    logic signed [34:0] rel_raw_r [0:1];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rel_raw_r[0] <= '0;
            rel_raw_r[1] <= '0;
        end else begin
            rel_raw_r[0] <= rel_raw[0];
            rel_raw_r[1] <= rel_raw[1];
        end
    end

    // ------------------------------------------------------------ rho and 1/rho
    logic        v_sqrt, v_inv;
    logic [15:0] rho, inv_raw, inv;

    isqrt16 u_sqrt (
        .clk(clk), .rst_n(rst_n),
        .vin(v4), .x(sum_r),
        .vout(v_sqrt), .y(rho)
    );

    // clamping d also clamps the quotient: 2^26/2048 == 32768, which is exactly
    // the value the small-rho case needs, so no extra bypass mux is required.
    wire [15:0] d_in = (rho < 16'd2048) ? 16'd2048 : rho;

    recip u_recip (
        .clk(clk), .rst_n(rst_n),
        .vin(v_sqrt), .d(d_in),
        .vout(v_inv), .q(inv_raw)
    );

    assign inv = inv_raw;

    // ------------------------------------------------------------ outputs derived from rho
    logic [23:0] alb_t;
    assign alb_t = ({8'b0, rho} << 8) - {8'b0, rho} + 24'd4096;
    wire [7:0] albedo8 = (alb_t[23:13] > 11'd255) ? 8'd255 : alb_t[20:13];
    wire       mag_bad = (rho < th_mag);

    // ------------------------------------------------------------ delay lines
    // g  : needed when n is computed (together with inv, 44 cycles after s3)
    // rel: encoded at s5, needed at the output (44 cycles after s5)
    // alb/conf: available with rho, needed at the output (28 cycles later)
    // bad: detected at s4, combined with rho (16 cycles later)
    logic signed [17:0] g_dly   [0:44][0:2];
    logic        [7:0]  rel_dly [0:44][0:1];
    logic        [7:0]  alb_dly [0:27];
    logic        [7:0]  conf_dly[0:27];
    logic        [1:0]  bad_dly [0:16];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (int d = 0; d <= 44; d++) begin
                g_dly[d][0] <= '0; g_dly[d][1] <= '0; g_dly[d][2] <= '0;
            end
            for (int d = 0; d <= 44; d++) begin
                rel_dly[d][0] <= '0; rel_dly[d][1] <= '0;
            end
            for (int d = 0; d <= 27; d++) begin
                alb_dly[d] <= '0;
                conf_dly[d] <= '0;
            end
            for (int d = 0; d <= 16; d++) bad_dly[d] <= '0;
        end else begin
            g_dly[0][0] <= g_r[0]; g_dly[0][1] <= g_r[1]; g_dly[0][2] <= g_r[2];
            for (int d = 44; d > 0; d--) begin
                g_dly[d][0] <= g_dly[d-1][0];
                g_dly[d][1] <= g_dly[d-1][1];
                g_dly[d][2] <= g_dly[d-1][2];
            end

            rel_dly[0][0] <= enc_rel(rel_raw_r[0]);
            rel_dly[0][1] <= enc_rel(rel_raw_r[1]);
            for (int d = 44; d > 0; d--) begin
                rel_dly[d][0] <= rel_dly[d-1][0];
                rel_dly[d][1] <= rel_dly[d-1][1];
            end

            alb_dly[0]  <= albedo8;
            conf_dly[0] <= (mag_bad | bad_dly[16][0] | bad_dly[16][1]) ? 8'd0 : 8'd255;
            for (int d = 27; d > 0; d--) begin
                alb_dly[d]  <= alb_dly[d-1];
                conf_dly[d] <= conf_dly[d-1];
            end

            bad_dly[0] <= bad_w;
            for (int d = 16; d > 0; d--) bad_dly[d] <= bad_dly[d-1];
        end
    end

    // ------------------------------------------------------------ s47: n = g * inv
    logic signed [34:0] prod_n [0:2];
    logic signed [20:0] n_r [0:2];
    logic               v47;

    for (genvar k = 0; k < 3; k++) begin : g_n
        assign prod_n[k] = $signed(g_dly[44][k]) * $signed({1'b0, inv});
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            v47 <= 1'b0;
            for (int k = 0; k < 3; k++) n_r[k] <= '0;
        end else begin
            v47 <= v_inv;
            for (int k = 0; k < 3; k++) n_r[k] <= prod_n[k] >>> 13;
        end
    end

    // ------------------------------------------------------------ s48: encode
    function automatic logic [7:0] enc_normal(input logic signed [20:0] n);
        logic signed [31:0] t;
        begin
            t = ((((n + 21'sd8192) <<< 8) - (n + 21'sd8192)) + 32'sd8192) >>> 14;
            if (t < 0)             enc_normal = 8'd0;
            else if (t > 32'sd255) enc_normal = 8'd255;
            else                   enc_normal = t[7:0];
        end
    endfunction

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            vout_valid    <= 1'b0;
            vout_normal   <= '0;
            vout_albedo   <= '0;
            vout_relight0 <= '0;
            vout_relight1 <= '0;
            vout_conf     <= '0;
        end else begin
            vout_valid    <= v47;
            vout_normal   <= {enc_normal(n_r[0]), enc_normal(n_r[1]), enc_normal(n_r[2])};
            vout_albedo   <= alb_dly[27];
            vout_relight0 <= {rel_dly[44][0], rel_dly[44][0], rel_dly[44][0]};
            vout_relight1 <= {rel_dly[44][1], rel_dly[44][1], rel_dly[44][1]};
            vout_conf     <= conf_dly[27];
        end
    end

endmodule
