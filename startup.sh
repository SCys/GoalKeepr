#!/bin/bash

mkdir log

python worker.py > log/worker.log &
python main.py > log/main.log