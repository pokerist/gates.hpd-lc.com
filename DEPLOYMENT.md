# Deployment Guide

## Quick Start

### 1. Set API Key
```bash
export OPENROUTER_API_KEY="your_api_key_here"
```

### 2. Run the Application
```bash
./run.sh
```

Or manually:
```bash
python3 app.py
```

### 3. Access the System
Open your browser or tablet to:
```
http://localhost:5000
```

Or from another device on the same network:
```
http://[your-ip]:5000
```

## Production Deployment

### Using Gunicorn (Recommended)

1. Install Gunicorn:
```bash
pip3 install gunicorn
```

2. Run with Gunicorn:
```bash
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

### Using systemd (Linux Service)

1. Create service file `/etc/systemd/system/hyde-park-gate.service`:
```ini
[Unit]
Description=Hyde Park Gate System
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/hyde_park_gate
Environment="OPENROUTER_API_KEY=your_key_here"
ExecStart=/usr/bin/python3 /home/ubuntu/hyde_park_gate/app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

2. Enable and start:
```bash
sudo systemctl enable hyde-park-gate
sudo systemctl start hyde-park-gate
```

### Using Docker

1. Create `Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV OPENROUTER_API_KEY=""
EXPOSE 5000

CMD ["python", "app.py"]
```

2. Build and run:
```bash
docker build -t hyde-park-gate .
docker run -p 5000:5000 -e OPENROUTER_API_KEY="your_key" hyde-park-gate
```

## Nginx Reverse Proxy (Optional)

For HTTPS and better performance:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Increase timeout for Vision API calls
    proxy_read_timeout 60s;
    proxy_connect_timeout 60s;
}
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENROUTER_API_KEY` | OpenRouter API key for Vision LLM | Yes |
| `PORT` | Application port (default: 5000) | No |

## Security Recommendations

1. **HTTPS**: Always use HTTPS in production
2. **API Key**: Store API key securely (use secrets manager)
3. **Authentication**: Add authentication for admin panel
4. **Rate Limiting**: Implement rate limiting for API endpoints
5. **CORS**: Configure CORS if accessing from different domains
6. **Firewall**: Restrict access to port 5000 if using reverse proxy

## Backup

### Database Backup
```bash
cp gate_system.db gate_system.db.backup
```

### Automated Backup (cron)
```bash
0 0 * * * cp /home/ubuntu/hyde_park_gate/gate_system.db /backups/gate_system_$(date +\%Y\%m\%d).db
```

## Monitoring

### Check Application Status
```bash
curl http://localhost:5000/
```

### View Logs (if using systemd)
```bash
sudo journalctl -u hyde-park-gate -f
```

## Troubleshooting

### Camera Not Working
- Check browser permissions for camera access
- Ensure HTTPS is used (required for camera on non-localhost)
- Try different browsers (Chrome/Safari recommended)

### Vision API Errors
- Verify OPENROUTER_API_KEY is set correctly
- Check API quota and rate limits
- Review captured images in `static/captures/`

### Database Issues
- Delete `gate_system.db` and restart to recreate
- Check file permissions on database file

## Performance Tuning

### For High Traffic
- Use Gunicorn with multiple workers
- Enable database connection pooling
- Add Redis for session management
- Use CDN for static assets

### For Low-End Devices
- Reduce camera resolution in `camera.js`
- Optimize image compression before sending
- Add image caching

## Mobile Optimization

### iOS Safari
- Add to home screen for app-like experience
- Ensure proper viewport meta tags (already included)

### Android Chrome
- Enable "Add to Home Screen" for PWA-like experience
- Test camera orientation handling

## Updates

### Pulling Updates
```bash
git pull origin main
pip3 install -r requirements.txt --upgrade
sudo systemctl restart hyde-park-gate
```

## Support

For issues or questions:
1. Check logs for error messages
2. Verify all dependencies are installed
3. Test camera access in browser console
4. Review OpenRouter API status
