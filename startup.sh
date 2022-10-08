#!/bin/bash

python worker.py > log/worker.log 2>&1 &

exec python main.py > log/main.log