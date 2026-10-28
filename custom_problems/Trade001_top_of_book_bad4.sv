// Bug: outputs look at the current inputs instead of only the stored quotes.
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
  wire [15:0] cur_bid = bid_valid ? bid_price : bid;
  wire [15:0] cur_ask = ask_valid ? ask_price : ask;
  assign have_both = (have_bid | bid_valid) & (have_ask | ask_valid);
  assign crossed = have_both && (cur_bid >= cur_ask);
  assign spread = (have_both && !crossed) ? (cur_ask - cur_bid) : 16'd0;
endmodule
