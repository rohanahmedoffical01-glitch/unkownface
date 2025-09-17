#!/bin/bash
/opt/venv/bin/python3 j.py > tmp.txt &
php -S 0.0.0.0:80
