#!/bin/env bash

rsync -avz --exclude='.venv' . timmy@192.168.1.3:/home/timmy/CazzuBot/
ssh timmy@192.168.1.3 "sudo systemctl restart cazzubot.service"
