#!/bin/bash
# Restart the Flask Wine Python process with the correct environment.
# Usage: docker exec mt5 /scripts/restart-flask.sh

pkill -f "Z:/app/app.py" 2>/dev/null
sleep 2

# Ensure log file is writable by abc
touch /tmp/flask.log && chmod 666 /tmp/flask.log

su -s /bin/bash abc -c \
  'export DISPLAY=:0 PYTHONPATH="Z:/app"; cd /app; nohup wine python Z:/app/app.py >> /tmp/flask.log 2>&1 &'

echo -n "Waiting for Flask..."
for i in $(seq 1 15); do
    sleep 1
    result=$(curl -s http://localhost:5001/health 2>/dev/null)
    if echo "$result" | grep -q '"status":"healthy"'; then
        echo " ready."
        echo "$result"
        exit 0
    fi
    echo -n "."
done

echo " timed out. Check /tmp/flask.log"
exit 1
