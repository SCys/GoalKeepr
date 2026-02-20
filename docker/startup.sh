#!/bin/bash

mkdir -p log
exec python main.py >> log/main.log 2>&1
