# Clock and IO constraints for chromaps (OpenSTA dialect).
create_clock -name clk -period 25.0 [get_ports clk]

set_output_delay 2.5 -clock clk [all_outputs]

# rst_n is an asynchronous control input, not a timed data path.
set_false_path -from [get_ports rst_n]
set_false_path -to   [get_ports rst_n]

set_max_fanout 8 [current_design]
set_clock_uncertainty 0.25 [get_clocks clk]
set_propagated_clock [all_clocks]
