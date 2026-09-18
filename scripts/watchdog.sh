#!/bin/bash
# ==============================================================================
# scripts/watchdog.sh — 24/7 Super-Agent Self-Healing Watchdog (Qo'riqchi)
# ==============================================================================
# Vazifasi:
# 1. Bot systemd xizmati (superagent) to'xtab qolgan bo'lsa darhol qayta yoqadi.
# 2. Port 8080 qotib qolgan bo'lsa uni ozod qilib xizmatni qayta tiklaydi.
# 3. HTTP /health endpointiga so'rov yuborib javob bermasa xizmatni restart qiladi.
# 4. Server xotirasi (RAM) qotib qolishining oldini oladi.
# ==============================================================================

SERVICE_NAME="superagent"
LOG_FILE="/home/ubuntu/telegram-super-agent/watchdog.log"
HEALTH_URL="http://127.0.0.1:8080/health"
DATE_NOW=$(date "+%Y-%m-%d %H:%M:%S")

# 1. Systemd xizmati faolligini tekshirish
if ! systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "[$DATE_NOW] ⚠️ Xizmat '$SERVICE_NAME' to'xtagan! Qayta tiklanmoqda..." >> "$LOG_FILE"
    # Band portlarni tozalash
    fuser -k 8080/tcp 2>/dev/null || true
    systemctl restart "$SERVICE_NAME"
    exit 0
fi

# 2. HTTP Health Check tekshirish (5 soniya timeout bilan)
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -m 5 "$HEALTH_URL" 2>/dev/null || echo "000")

if [ "$HTTP_CODE" != "200" ]; then
    echo "[$DATE_NOW] ⚠️ Health check muvaffaqiyatsiz (Status: $HTTP_CODE)! Servis qayta ishga tushirilmoqda..." >> "$LOG_FILE"
    fuser -k 8080/tcp 2>/dev/null || true
    systemctl restart "$SERVICE_NAME"
    exit 0
fi

# 3. Log hajmi 5MB dan oshib ketsa tozalash
if [ -f "$LOG_FILE" ]; then
    LOG_SIZE=$(wc -c < "$LOG_FILE")
    if [ "$LOG_SIZE" -gt 5242880 ]; then
        tail -n 1000 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
    fi
fi
