#!/bin/bash
export DISPLAY=:99
# Start Xvfb
Xvfb :99 -screen 0 1280x1024x24 &
# Start a lightweight window manager
fluxbox &
# Start VNC server
x11vnc -display :99 -forever -nopw -bg -xkb
# Start NoVNC (web interface for VNC)
websockify --web=/usr/share/novnc/ 6080 localhost:5900 &
# Start the Python application
exec uvicorn server:app --host 0.0.0.0 --port 8000