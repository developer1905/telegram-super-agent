#!/bin/bash
set -e

echo "=================================================="
echo "🚀 Super-Agent AWS EC2 Avtomatik Sozlash Skripti"
echo "=================================================="

APP_DIR="/home/ubuntu/telegram-super-agent"
if [ ! -d "$APP_DIR" ]; then
    APP_DIR="$(pwd)"
fi

cd "$APP_DIR"

# 1. SWAP Xotira (2 GB) qo'shish
if [ ! -f /swapfile ]; then
    echo "📦 2 GB Swap xotira yaratilmoqda..."
    sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab > /dev/null
    echo "✅ Swap qo'shildi."
else
    echo "ℹ️ Swap allaqachon mavjud."
fi

# 2. Caddy o'rnatilganligini tekshirish
if ! command -v caddy &> /dev/null; then
    echo "📥 Caddy server o'rnatilmoqda..."
    sudo apt update -qq
    sudo apt install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl
    curl -1sLF 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg --yes 2>/dev/null
    curl -1sLF 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null
    sudo apt update -qq
    sudo apt install -y -qq caddy
fi

# 3. Public IP ni aniqlash
echo "🔍 Server Public IP manzili aniqlanmoqda..."
PUBLIC_IP=$(curl -s --max-time 5 ifconfig.me || curl -s --max-time 5 icanhazip.com || curl -s --max-time 5 api.ipify.org)
if [ -z "$PUBLIC_IP" ]; then
    echo "❌ Public IP ni aniqlab bo'lmadi. Iltimos, internet aloqasini tekshiring."
    exit 1
fi
echo "🌐 Server Public IP: $PUBLIC_IP"

# 4. Caddyfile sozlash (Bepul Let's Encrypt SSL bilan)
echo "🔒 HTTPS va Caddy sozlanmoqda..."
sudo tee /etc/caddy/Caddyfile > /dev/null <<EOF
$PUBLIC_IP.nip.io {
    reverse_proxy localhost:8080
}
EOF

sudo systemctl daemon-reload
sudo systemctl enable caddy
sudo systemctl restart caddy
echo "✅ Caddy muvaffaqiyatli ishga tushdi."

# 5. .env faylini yangilash
if [ -f "$APP_DIR/.env" ]; then
    NEW_URL="https://$PUBLIC_IP.nip.io/webapp"
    if grep -q "WEBAPP_URL=" "$APP_DIR/.env"; then
        sed -i "s|WEBAPP_URL=.*|WEBAPP_URL=$NEW_URL|" "$APP_DIR/.env"
    else
        echo "WEBAPP_URL=$NEW_URL" >> "$APP_DIR/.env"
    fi
    echo "✅ .env faylidagi WEBAPP_URL yangilandi: $NEW_URL"
fi

# 6. Systemd servisini yaratish (Bot 24/7 fonda ishlashi uchun)
echo "⚙️ Systemd tizim servisi yaratilmoqda..."
PYTHON_EXEC="$APP_DIR/venv/bin/python"
if [ ! -f "$PYTHON_EXEC" ]; then
    PYTHON_EXEC="/usr/bin/python3"
fi

sudo tee /etc/systemd/system/superagent.service > /dev/null <<EOF
[Unit]
Description=Telegram Super-Agent AI Bot
After=network.target

[Service]
User=ubuntu
WorkingDirectory=$APP_DIR
ExecStart=$PYTHON_EXEC main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable superagent
sudo systemctl restart superagent
echo "✅ Super-Agent servisi ishga tushirildi."

echo ""
echo "=================================================="
echo "🎉 HAMMASI TAYYOR VA 24/7 ISHGA TUSHDI!"
echo "=================================================="
echo "🌐 Yangi Web App havolangiz: https://$PUBLIC_IP.nip.io/webapp"
echo "🤖 Bot statusini ko'rish: sudo systemctl status superagent"
echo "📋 Jonli loglarni ko'rish: sudo journalctl -u superagent -f"
echo "=================================================="
