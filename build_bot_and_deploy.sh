#!/bin/sh
sudo docker container rm -f cazzubot-webapp-1
sudo docker build -t cazzubot .
sudo docker compose up -d
sudo docker attach --no-stdin cazzubot-webapp-1