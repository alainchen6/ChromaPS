// 3x3 signed/unsigned multiply-accumulate.
//
//   y_i = sum_k a[i][k] * x_k
//
// x_k is unsigned (pixel data), a[i][k] is signed Q2.13.
module mat3 (
    input  logic signed [15:0] a00, a01, a02,
    input  logic signed [15:0] a10, a11, a12,
    input  logic signed [15:0] a20, a21, a22,
    input  logic        [9:0]  x0, x1, x2,
    output logic signed [31:0] y0, y1, y2
);
    logic signed [25:0] p00, p01, p02;
    logic signed [25:0] p10, p11, p12;
    logic signed [25:0] p20, p21, p22;

    assign p00 = a00 * $signed({1'b0, x0});
    assign p01 = a01 * $signed({1'b0, x1});
    assign p02 = a02 * $signed({1'b0, x2});
    assign p10 = a10 * $signed({1'b0, x0});
    assign p11 = a11 * $signed({1'b0, x1});
    assign p12 = a12 * $signed({1'b0, x2});
    assign p20 = a20 * $signed({1'b0, x0});
    assign p21 = a21 * $signed({1'b0, x1});
    assign p22 = a22 * $signed({1'b0, x2});

    assign y0 = p00 + p01 + p02;
    assign y1 = p10 + p11 + p12;
    assign y2 = p20 + p21 + p22;
endmodule
