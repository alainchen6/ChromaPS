// Pipelined integer square root: y = floor(sqrt(x)), 16 bits of result.
//
// One result per cycle, latency 16.  Non-restoring style: two input bits per
// stage, so a 32-bit input (max 3.22e9 from 3 x 18-bit squares) lands in 16
// result bits.
module isqrt16 (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        vin,
    input  logic [31:0] x,
    output logic        vout,
    output logic [15:0] y
);
    logic [23:0] rem  [0:16];
    logic [15:0] root [0:16];
    logic [31:0] xs   [0:16];
    logic [16:0] vld;

    logic [23:0] sh    [0:15];
    logic [17:0] trial [0:15];
    logic        ge    [0:15];

    genvar i;
    generate
        for (i = 0; i < 16; i++) begin : g_stage
            assign sh[i]    = {rem[i][21:0], xs[i][31:30]};
            assign trial[i] = {root[i], 2'b01};
            assign ge[i]    = (sh[i] >= {6'b0, trial[i]});
        end
    endgenerate

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            vld <= '0;
            for (int k = 0; k <= 16; k++) begin
                rem[k]  <= '0;
                root[k] <= '0;
                xs[k]   <= '0;
            end
        end else begin
            vld[0]  <= vin;
            rem[0]  <= '0;
            root[0] <= '0;
            xs[0]   <= x;
            for (int k = 0; k < 16; k++) begin
                vld[k+1] <= vld[k];
                xs[k+1]  <= xs[k] << 2;
                if (ge[k]) begin
                    rem[k+1]  <= sh[k] - {6'b0, trial[k]};
                    root[k+1] <= {root[k][14:0], 1'b1};
                end else begin
                    rem[k+1]  <= sh[k];
                    root[k+1] <= {root[k][14:0], 1'b0};
                end
            end
        end
    end

    assign y    = root[16];
    assign vout = vld[16];
endmodule
