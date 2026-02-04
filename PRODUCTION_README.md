# Hyde Park Gate System - Production Deployment

## 🚀 Quick Deployment

### 1. Upload Files to Server
```bash
# On your local machine
scp hyde_park_gate_production.tar.gz user@server:/home/gatekeeper/

# On the server
cd /home/gatekeeper
tar -xzf hyde_park_gate_production.tar.gz
mv hyde_park_gate manus-gatekeeper
```

### 2. Configure Environment
```bash
cd /home/gatekeeper/manus-gatekeeper

# Edit environment file
nano .env

# Set your configuration:
# - OPENROUTER_API_KEY=your_key_here
# - GATE_PASSWORD=your_password
# - SECRET_KEY=generate_random_key
```

### 3. Run Deployment Script
```bash
chmod +x deploy.sh
sudo ./deploy.sh
```

Done! The application will be running on port 5000.

---

## 🔧 Manual Deployment

### Prerequisites
```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip nginx -y
```

### Install Application
```bash
cd /home/gatekeeper/manus-gatekeeper

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Configure Environment
```bash
# Copy production environment file
cp .env.production .env

# Edit configuration
nano .env
```

**Important Settings:**
- `APP_PREFIX=/new` - URL prefix for reverse proxy
- `PORT=5000` - Application port
- `DEBUG=False` - Production mode
- `OPENROUTER_API_KEY` - Your OpenRouter API key
- `GATE_PASSWORD` - Password for security/admin access
- `SECRET_KEY` - Random secure key for sessions

### Initialize Database
```bash
source venv/bin/activate
python3 -c "from database import init_db; init_db()"
deactivate
```

### Create Systemd Service
```bash
sudo nano /etc/systemd/system/hyde-park-gate.service
```

Paste:
```ini
[Unit]
Description=Hyde Park Gate System
After=network.target

[Service]
Type=simple
User=gatekeeper
WorkingDirectory=/home/gatekeeper/manus-gatekeeper
Environment="PATH=/home/gatekeeper/manus-gatekeeper/venv/bin"
EnvironmentFile=/home/gatekeeper/manus-gatekeeper/.env
ExecStart=/home/gatekeeper/manus-gatekeeper/venv/bin/python /home/gatekeeper/manus-gatekeeper/app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable hyde-park-gate
sudo systemctl start hyde-park-gate
sudo systemctl status hyde-park-gate
```

---

## 🌐 Nginx Configuration (Optional)

If you're using Nginx as reverse proxy:

```bash
sudo nano /etc/nginx/sites-available/hyde-park-gate
```

Paste the content from `nginx.conf` file.

Then:
```bash
sudo ln -s /etc/nginx/sites-available/hyde-park-gate /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

---

## 🔗 URL Prefix Configuration

The application is configured to work under `/new/` path:

**Correct URLs:**
- `https://middleware.hpd-lc.com/new/`
- `https://middleware.hpd-lc.com/new/security`
- `https://middleware.hpd-lc.com/new/admin`

**Configuration:**
- Flask: `APP_PREFIX=/new` in `.env`
- Nginx: `location /new/` with `X-Script-Name` header
- ProxyFix: Handles `X-Forwarded-*` headers

---

## 📊 Monitoring & Logs

### View Logs
```bash
# Application logs
sudo journalctl -u hyde-park-gate -f

# Last 100 lines
sudo journalctl -u hyde-park-gate -n 100

# Nginx logs
sudo tail -f /var/log/nginx/hyde-park-gate-access.log
sudo tail -f /var/log/nginx/hyde-park-gate-error.log
```

### Service Management
```bash
# Status
sudo systemctl status hyde-park-gate

# Restart
sudo systemctl restart hyde-park-gate

# Stop
sudo systemctl stop hyde-park-gate

# Start
sudo systemctl start hyde-park-gate

# Disable auto-start
sudo systemctl disable hyde-park-gate
```

---

## 🔒 Security Checklist

- [ ] Change `SECRET_KEY` to random secure value
- [ ] Change `GATE_PASSWORD` from default
- [ ] Set `DEBUG=False` in production
- [ ] Configure firewall (allow only 5000 from localhost)
- [ ] Use HTTPS with valid SSL certificate
- [ ] Regular database backups
- [ ] Monitor logs for suspicious activity
- [ ] Keep dependencies updated

### Generate Secure Keys
```bash
# Generate SECRET_KEY
python3 -c "import secrets; print(secrets.token_hex(32))"

# Generate strong password
python3 -c "import secrets; import string; chars = string.ascii_letters + string.digits + string.punctuation; print(''.join(secrets.choice(chars) for _ in range(20)))"
```

---

## 🔄 Updates & Maintenance

### Update Application
```bash
cd /home/gatekeeper/manus-gatekeeper

# Backup current version
tar -czf ~/backup_$(date +%Y%m%d_%H%M%S).tar.gz .

# Pull new code or copy new files
# ...

# Restart service
sudo systemctl restart hyde-park-gate
```

### Database Backup
```bash
# Manual backup
cp gate_system.db gate_system.db.backup_$(date +%Y%m%d_%H%M%S)

# Automated backup (add to crontab)
0 0 * * * cp /home/gatekeeper/manus-gatekeeper/gate_system.db /home/gatekeeper/backups/gate_system_$(date +\%Y\%m\%d).db
```

---

## 🐛 Troubleshooting

### Service Won't Start
```bash
# Check logs
sudo journalctl -u hyde-park-gate -n 50

# Check if port is in use
sudo netstat -tulpn | grep 5000

# Test manually
cd /home/gatekeeper/manus-gatekeeper
source venv/bin/activate
python3 app.py
```

### URL Prefix Issues
1. Check `APP_PREFIX` in `.env`
2. Verify Nginx `X-Script-Name` header
3. Check Flask `url_for()` usage in templates
4. Clear browser cache

### Camera Not Working
- Ensure HTTPS is used (camera requires secure context)
- Check browser permissions
- Test on different browsers

### Vision API Errors
- Verify `OPENROUTER_API_KEY` is set
- Check API quota and rate limits
- Review logs for detailed error messages

---

## 📞 Support

For issues or questions:
1. Check logs: `sudo journalctl -u hyde-park-gate -f`
2. Review configuration: `cat .env`
3. Test connectivity: `curl http://localhost:5000/`
4. Check reverse proxy: `curl https://middleware.hpd-lc.com/new/`

---

## 📦 File Structure

```
/home/gatekeeper/manus-gatekeeper/
├── app.py                    # Main Flask application
├── database.py               # Database operations
├── requirements.txt          # Python dependencies
├── .env                      # Environment configuration (create from .env.production)
├── .env.production          # Production environment template
├── deploy.sh                # Deployment script
├── nginx.conf               # Nginx configuration template
├── gate_system.db           # SQLite database (auto-created)
├── venv/                    # Virtual environment
├── templates/               # HTML templates (Arabic)
│   ├── home.html
│   ├── security.html
│   ├── admin.html
│   └── login.html
├── static/
│   ├── js/
│   │   └── camera.js
│   └── captures/            # Captured ID card images
└── backups/                 # Database backups
```

---

## ✅ Production Checklist

Before going live:

- [ ] All environment variables configured
- [ ] Database initialized
- [ ] Service running and enabled
- [ ] Nginx configured (if using)
- [ ] SSL certificate installed
- [ ] Firewall rules set
- [ ] Backup strategy in place
- [ ] Monitoring configured
- [ ] Logs reviewed
- [ ] Test all features:
  - [ ] Home page loads
  - [ ] Security login works
  - [ ] Admin login works
  - [ ] Camera scan works
  - [ ] Block/Unblock works
  - [ ] Logout works

---

## 🎉 You're Ready!

Access your application at:
**https://middleware.hpd-lc.com/new/**

Default password: `Smart@1150` (change immediately!)
