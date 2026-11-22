// Pipelined reciprocal of a constant dividend: q = 2^26 / d, 26 stages.
//
// d is the Q2.13 magnitude of g, so d lives in [2048, 32768] and the quotient
// is at most 32768 (Q2.13 of 4.0).  Callers below that range get the clamped
// 32768 and mark the pixel invalid.
module recip (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        vin,
    input  logic [15:0] d,
    output logic        vout,
    output logic [15:0] q
);
    logic [16:0] rem [0:26];
    logic [25:0] quo [0:26];
    logic [15:0] dv  [0:26];
    logic [26:0] vld;

    logic [16:0] sh [0:25];
    logic        ge [0:25];

    genvar i;
    generate
        for (i = 0; i < 26; i++) begin : g_stage
            assign sh[i] = {rem[i][15:0], 1'b0};
            assign ge[i] = (sh[i] >= {1'b0, dv[i]});
        end
    endgenerate

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            vld <= '0;
            for (int k = 0; k <= 26; k++) begin
                rem[k] <= '0;
                quo[k] <= '0;
                dv[k]  <= '0;
            end
        end else begin
            // 2^26 = 1 followed by 26 zeros: the first bit leaves rem = 1
            vld[0] <= vin;
            rem[0] <= 17'd1;
            quo[0] <= '0;
            dv[0]  <= d;
            for (int k = 0; k < 26; k++) begin
                vld[k+1] <= vld[k];
                dv[k+1]  <= dv[k];
                if (ge[k]) begin
                    rem[k+1] <= sh[k] - {1'b0, dv[k]};
                    quo[k+1] <= {quo[k][24:0], 1'b1};
                end else begin
                    rem[k+1] <= sh[k];
                    quo[k+1] <= {quo[k][24:0], 1'b0};
                end
            end
        end
    end

    assign q    = (quo[26] > 26'd32768) ? 16'd32768 : quo[26][15:0];
    assign vout = vld[26];
endmodule
