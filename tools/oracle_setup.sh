#!/bin/bash
set -e

echo "=== System Update and Basic Tools ==="
sudo dnf update -y
sudo dnf install -y unzip zip curl wget git tzdata gcc python3-devel gcc-c++ make

echo "=== Timezone Configuration ==="
sudo timedatectl set-timezone Asia/Kolkata
date

echo "=== Swap Configuration (2GB) ==="
if [ ! -f /swapfile ]; then
    sudo dd if=/dev/zero of=/swapfile count=2048 bs=1MiB
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile   none    swap    sw    0   0' | sudo tee -a /etc/fstab
    echo "Swap space created and enabled."
else
    echo "Swapfile already exists."
fi

echo "=== Installing Node.js and PM2 ==="
if ! command -v npm &> /dev/null; then
    sudo dnf module enable -y nodejs:20
    sudo dnf install -y nodejs
fi
sudo npm install pm2 -g

echo "=== Extracting Project ==="
unzip -o /home/opc/deploy.zip -d /home/opc/quant_bot

echo "=== Setting up Python Virtual Environment ==="
cd /home/opc/quant_bot
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install wheel
pip install -r requirements.txt

echo "=== PM2 Startup ==="
pm2 start ecosystem.config.js
pm2 save
pm2 startup | tail -n 1 > /tmp/pm2_startup.sh
sudo bash /tmp/pm2_startup.sh

echo "=== SETUP COMPLETE ==="
pm2 status
free -m
