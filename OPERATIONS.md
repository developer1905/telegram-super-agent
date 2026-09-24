# JARVIS / TELEGRAM SUPER-AGENT — OPERATIONS & SRE GUIDE (OPERATIONS.md)

Ushbu qo'llanma Super-Agent 2.0 tizimini Linux/AWS muhitida 24/7 rejimida uzluksiz boshqarish, monitoring qilish va nosozliklarni bartaraf etish (troubleshooting) yo'riqnomasidir.

---

## 1. Systemd Xizmati Boshqaruvi

Bot tizim servisi orqali boshqariladi: `/etc/systemd/system/superagent.service`.

### Asosiy buyruqlar:
```bash
# Holatni tekshirish
sudo systemctl status superagent --no-pager

# Xizmatni qayta ishga tushirish (yangilanishdan so'ng)
sudo systemctl restart superagent

# Xizmatni to'xtatish
sudo systemctl stop superagent

# Jonli loglarni kuzatish
sudo journalctl -u superagent -f

# So'nggi 50 qator xatolik loglarini ko'rish
sudo journalctl -u superagent -n 50 --no-pager
```

---

## 2. Tarmoq va WebApp Proksi Boshqaruvi

### Variant A: Caddy Server (Tashqi 80/443 portlar ochiq bo'lsa)
Caddy bepul Let's Encrypt SSL sertifikatini avtomatik boshqaradi:
```bash
# Caddy konfiguratsiyasi
sudo nano /etc/caddy/Caddyfile

# Caddy qayta yuklash
sudo systemctl restart caddy

# Caddy loglari
sudo journalctl -u caddy -n 30 --no-pager
```

### Variant B: Cloudflare Tunnel (Port ochish imkoni bo'lmaganda)
AWS xavfsizlik guruhlarida portlarni ochmasdan, xavfsiz bepul HTTPS tunnel ishlatish:
```bash
# Tunnelni fonda doimiy ishga tushirish
nohup cloudflared tunnel --url http://127.0.0.1:8080 > ~/cloudflare.log 2>&1 &

# Faol HTTPS manzilni ko'rish
grep -o 'https://.*trycloudflare.com' ~/cloudflare.log | head -n 1
```

---

## 3. Nosozliklarni Bartaraf Etish (Troubleshooting Runbook)

### 1-Muammo: 8080-port band bo'lib qolishi (`Address already in use`)
Eski yoki to'xtab qolgan jarayon 8080-portni ushlab turgan bo'lsa:
```bash
sudo fuser -k 8080/tcp || true
sudo systemctl restart superagent
```

### 2-Muammo: WebApp 500 Internal Server Error
1. Local server javobini tekshiring:
   ```bash
   curl -i http://127.0.0.1:8080/health
   curl -i http://127.0.0.1:8080/webapp
   ```
2. Agar `500` qaytsa, `journalctl` orqali Python traceback'ni ko'ring:
   ```bash
   sudo journalctl -u superagent -n 30 --no-pager
   ```

### 3-Muammo: Telegram WebApp ochilmay oq ekran bo'lib qolishi
- `.env` faylidagi `WEBAPP_URL` manzilining to'g'riligini va uning `https://` bilan boshlanishini tekshiring (Telegram `http://` havolalarni ochmaydi).
- Cloudflare Tunnel ishlayotganiga ishonch hosil qiling (`ps aux | grep cloudflared`).

---

## 4. Ma'lumotlar Bazasi Zaxirasi (Backup)
SQLite ma'lumotlar bazasi WAL (Write-Ahead Logging) rejimida ishlaydi. Xavfsiz nusxa olish:
```bash
# Zaxira nusxa yaratish
sqlite3 superagent.db ".backup 'superagent_backup_$(date +%Y%m%d).db'"
```
