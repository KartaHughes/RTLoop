`timescale 1 ps/1 ps

// Same contract as the VerilogEval testbenches: instantiate RefModule and
// TopModule, compare them, print "Mismatches: N in M samples".
module tb();

  reg clk = 0;
  initial forever #5 clk = ~clk;

  reg reset = 1;
  reg bid_valid = 0, ask_valid = 0;
  reg [15:0] bid_price = 0, ask_price = 0;

  wire have_both_ref, crossed_ref;
  wire [15:0] spread_ref;
  wire have_both_dut, crossed_dut;
  wire [15:0] spread_dut;

  RefModule good1 (
    .clk(clk), .reset(reset),
    .bid_valid(bid_valid), .bid_price(bid_price),
    .ask_valid(ask_valid), .ask_price(ask_price),
    .have_both(have_both_ref), .crossed(crossed_ref), .spread(spread_ref));

  TopModule top_module1 (
    .clk(clk), .reset(reset),
    .bid_valid(bid_valid), .bid_price(bid_price),
    .ask_valid(ask_valid), .ask_price(ask_price),
    .have_both(have_both_dut), .crossed(crossed_dut), .spread(spread_dut));

  wire tb_mismatch = ({have_both_ref, crossed_ref, spread_ref} !== {have_both_dut, crossed_dut, spread_dut});

  // Waveform dump, read by the demo's waveform viewer.
  initial begin
    $dumpfile("wave.vcd");
    $dumpvars(1, clk, reset, bid_valid, bid_price, ask_valid, ask_price, tb_mismatch,
              have_both_ref, have_both_dut, crossed_ref, crossed_dut, spread_ref, spread_dut);
  end

  integer errors = 0;
  integer clocks = 0;

  // Compare once per cycle, 5ps after each rising edge. Inputs change 2ps
  // after a rising edge, so an output that wrongly depends on the current
  // inputs (instead of stored state) shows up as a mismatch.
  always @(negedge clk) begin
    clocks = clocks + 1;
    if ({have_both_ref, crossed_ref, spread_ref} !== {have_both_dut, crossed_dut, spread_dut})
      errors = errors + 1;
  end

  task drive(input r, input bv, input [15:0] bp, input av, input [15:0] ap);
    begin
      @(posedge clk);
      #2;
      reset = r;
      bid_valid = bv;
      bid_price = bp;
      ask_valid = av;
      ask_price = ap;
    end
  endtask

  integer i;
  reg [15:0] base;

  initial begin
    // Reset with quote activity during reset: reset must win.
    drive(1, 1, 16'd100, 1, 16'd90);
    drive(1, 0, 16'd0, 0, 16'd0);
    // Bid only: not both yet.
    drive(0, 1, 16'd100, 0, 16'd0);
    drive(0, 0, 16'd0, 0, 16'd0);
    // Ask above bid: not crossed, spread 5.
    drive(0, 0, 16'd0, 1, 16'd105);
    drive(0, 0, 16'd0, 0, 16'd0);
    // Equal prices: crossed.
    drive(0, 0, 16'd0, 1, 16'd100);
    drive(0, 0, 16'd0, 0, 16'd0);
    // Bid above ask.
    drive(0, 1, 16'd110, 0, 16'd0);
    drive(0, 0, 16'd0, 0, 16'd0);
    // Both quotes update in the same cycle.
    drive(0, 1, 16'd200, 1, 16'd201);
    drive(0, 0, 16'd0, 0, 16'd0);
    // Reset clears the flags and values.
    drive(1, 0, 16'd0, 0, 16'd0);
    drive(0, 0, 16'd0, 0, 16'd0);
    // Ask only after reset, then a bid just below it.
    drive(0, 0, 16'd0, 1, 16'd50);
    drive(0, 0, 16'd0, 0, 16'd0);
    drive(0, 1, 16'd49, 0, 16'd0);
    drive(0, 0, 16'd0, 0, 16'd0);
    // Extremes of the 16-bit range.
    drive(0, 1, 16'd0, 1, 16'd65535);
    drive(0, 0, 16'd0, 0, 16'd0);
    drive(0, 1, 16'd65535, 0, 16'd0);
    drive(0, 0, 16'd0, 0, 16'd0);
    // Random walk of prices so bid and ask often sit close together.
    base = 16'd1000;
    for (i = 0; i < 4000; i = i + 1) begin
      base = base + ($urandom % 7) - 3;
      drive(($urandom % 40) == 0,
            ($urandom % 3) == 0, base + ($urandom % 5) - 2,
            ($urandom % 3) == 0, base + ($urandom % 5) - 2);
    end
    drive(0, 0, 16'd0, 0, 16'd0);
    repeat (3) @(posedge clk);
    @(negedge clk);
    #1;
    $display("Mismatches: %0d in %0d samples", errors, clocks);
    $finish;
  end

  // Watchdog, same convention as VerilogEval.
  initial begin
    #1000000
    $display("TIMEOUT");
    $finish();
  end

endmodule
