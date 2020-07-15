#!/bin/bash
exec python3 -u prog_alpha.py 2>&1 | tee --ignore-interrupts logfile
