#!/bin/bash
cd /home/claude/anneal-py
export PYTHONPATH=. OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
run(){ python -u research/am_tune.py "$@" >> research/tune.log 2>&1; }
run plain60 none 60 0 & run after60 after 60 0 & wait
run before60 before 60 0 & run beforecont60 before 60 1 & wait
run after120 after 120 0 & run before120 before 120 0 & wait
run plain120 none 120 0 & run aftercont120 after 120 1 & wait
echo DONE >> research/tune.log
