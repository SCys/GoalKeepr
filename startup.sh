#!/bin/bash

python worker.py > log/worker.log 2>&1 &
python main.py > log/main.log 2>&1