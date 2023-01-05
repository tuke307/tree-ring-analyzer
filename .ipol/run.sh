#!/bin/bash
set -e

# Read input parameters
input=$1
sigma=$2
nr=$3
th_low=$4
th_high=$5
hsize=$6
wsize=$7
BIN=$8
HOME=$9

# Extract center from mask
if [ ! -f input_1.png ]; then
  convert mask_0.png -white-threshold 000001 -alpha off mask_0_black.png
  cp mask_0_black.png input_1.png
  stdout=$(python $BIN/.ipol/process_mask.py --input input_1.png)
  echo $stdout
fi

Cx=1264
Cy=1204

# Execute algorithm
python $BIN/main.py --input $input --cx $Cx --cy $Cy --root $BIN --output_dir $HOME --nr $nr --th_high $th_high --th_low $th_low --hsize $hsize --wsize $wsize --sigma $sigma

