// Bug: crossed uses > instead of >= (equal prices should be crossed).
module TopModule (
  input clk, input reset,
  input bid_valid, input [15:0] bid_price,
  input ask_valid, input [15:0] ask_price,
  output have_both, output crossed, output [15:0] spread
);
  reg [15:0] bid, ask;
  reg have_bid, have_ask;
  always @(posedge clk) begin
    if (reset) begin bid <= 0; ask <= 0; have_bid <= 0; have_ask <= 0; end
    else begin
      if (bid_valid) begin bid <= bid_price; have_bid <= 1; end
      if (ask_valid) begin ask <= ask_price; have_ask <= 1; end
    end
  end
  assign have_both = have_bid & have_ask;
  assign crossed = have_both && (bid > ask);
  assign spread = (have_both && !crossed) ? (ask - bid) : 16'd0;
endmodule
