#!/bin/sh
set -e
cd /home/claude/lems-analyser
git pull
sudo docker build -t lems-analyser:latest .
sudo docker stop lems-analyser
sudo docker rm lems-analyser
sudo docker run -d --name lems-analyser --restart unless-stopped -p 8501:8501 lems-analyser:latest
sudo docker ps --filter name=lems-analyser
