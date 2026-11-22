IV        ?= iverilog
VVP       ?= vvp
PY        ?= python3
LIBRELANE ?= librelane

W ?= 320
H ?= 240

PDK ?= $(firstword $(wildcard $(HOME)/.ciel/ciel/sky130/versions/*/sky130A))
PNL ?= src/runs/pnr/final/pnl/chromaps.pnl.v
SDF ?= src/runs/pnr/final/sdf/nom_tt_025C_1v80/chromaps__nom_tt_025C_1v80.sdf

SRC := src/chromaps.sv src/mat3.sv src/isqrt16.sv src/recip.sv
TB  := tb/tb_rtl.sv
SIM := build/tb_rtl.vvp

.PHONY: all model rtl compare edge test gls gls-sdf pnr demo clean

all: model rtl compare

model:
	$(PY) model/render.py --width $(W) --height $(H)
	$(PY) model/golden.py

$(SIM): $(SRC) $(TB)
	@mkdir -p build out
	$(IV) -g2012 -Ptb_rtl.W=$(W) -Ptb_rtl.H=$(H) -o $(SIM) $(TB) $(SRC)

rtl: $(SIM)
	$(VVP) $(SIM)

compare:
	$(PY) model/compare.py --ppm

# Zero-delay gate-level run: proves the PnR netlist computes the same thing.
gls: build/tb_gls.vvp
	$(VVP) build/tb_gls.vvp
	$(PY) model/compare.py --a gls_golden --b gls

# SDF-annotated run on a tiny window (the whole design is ~80k instances, and
# iverilog with back-annotated delays is only good for a few hundred cycles).
gls-sdf: build/tb_gls_sdf.vvp
	$(VVP) build/tb_gls_sdf.vvp +sdf=$(SDF)
	$(PY) model/compare.py --a gls_golden --b gls

build/tb_gls.vvp: $(PNL) tb/tb_gls.sv
	@mkdir -p build
	$(IV) -g2012 -DFUNCTIONAL -DUNIT_DELAY='#1' -DUSE_POWER_PINS -o $@ \
	  tb/tb_gls.sv $(PNL) \
	  $(PDK)/libs.ref/sky130_fd_sc_hd/verilog/primitives.v \
	  $(PDK)/libs.ref/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v

build/tb_gls_sdf.vvp: $(PNL) tb/tb_gls.sv
	@mkdir -p build
	$(IV) -g2012 -gspecify -DSDF_ANNOTATE -DFUNCTIONAL -DUNIT_DELAY='#1' -DUSE_POWER_PINS -o $@ \
	  tb/tb_gls.sv $(PNL) \
	  $(PDK)/libs.ref/sky130_fd_sc_hd/verilog/primitives.v \
	  $(PDK)/libs.ref/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v

slice:
	$(PY) model/slice.py
	$(PY) model/golden.py --stem gls_golden --frame stim/slice.hex --meta stim/slice_meta.json --gt stim/slice_gt.npy

edge:
	$(PY) model/edge.py
	$(PY) model/golden.py --stem edge_golden --frame stim/edge.hex --meta stim/edge_meta.json --gt stim/edge_gt.npy
	$(IV) -g2012 -Ptb_rtl.W=8 -Ptb_rtl.H=4 -o build/tb_edge.vvp $(TB) $(SRC)
	$(VVP) build/tb_edge.vvp +stim=stim/edge.hex +prefix=out/edge
	$(PY) model/compare.py --a edge_golden --b edge

test:
	$(PY) tests/run_cases.py

pnr:
	$(LIBRELANE) --pdk sky130A src/config.yaml

demo: compare
	$(PY) model/demo.py

clean:
	rm -rf build obj_dir runs out/*.hex out/*.ppm
