#!/bin/bash

source /scripts/02-common.sh

log_message "RUNNING" "08-start-tick-streamer.sh"

log_message "INFO" "Starting tick streamer (system Python)..."

# Wait for Flask API to be reachable before starting the streamer
# Wine/QEMU on ARM can take 30-60s to initialize Flask
for i in $(seq 1 30); do
    if curl -s --max-time 3 http://localhost:5001/get_positions > /dev/null 2>&1; then
        log_message "INFO" "Flask API is ready."
        break
    fi
    if [ "$i" -eq 30 ]; then
        log_message "ERROR" "Flask API not ready after 30 attempts, starting tick streamer anyway."
    fi
    sleep 3
done

python3 /app/tick_streamer.py &
TICK_PID=$!

sleep 5

if kill -0 $TICK_PID 2>/dev/null; then
    log_message "INFO" "Tick streamer started successfully with PID $TICK_PID."
else
    log_message "ERROR" "Failed to start tick streamer."
    exit 1
fi
