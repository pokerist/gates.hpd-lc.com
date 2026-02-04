#!/bin/bash

# Hyde Park Gate System - Deployment Script
# This script deploys the application to production

set -e  # Exit on error

echo "🏛️  Hyde Park Gate System - Deployment"
echo "======================================"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuration
APP_DIR="/home/gatekeeper/manus-gatekeeper"
BACKUP_DIR="/home/gatekeeper/backups"
SERVICE_NAME="hyde-park-gate"

# Check if running as root or with sudo
if [ "$EUID" -eq 0 ]; then 
    echo -e "${YELLOW}⚠️  Warning: Running as root${NC}"
fi

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Function to backup existing installation
backup_existing() {
    if [ -d "$APP_DIR" ]; then
        BACKUP_FILE="$BACKUP_DIR/backup_$(date +%Y%m%d_%H%M%S).tar.gz"
        echo -e "${YELLOW}📦 Creating backup...${NC}"
        tar -czf "$BACKUP_FILE" -C "$(dirname $APP_DIR)" "$(basename $APP_DIR)" 2>/dev/null || true
        echo -e "${GREEN}✅ Backup created: $BACKUP_FILE${NC}"
    fi
}

# Function to install dependencies
install_dependencies() {
    echo -e "${YELLOW}📥 Installing dependencies...${NC}"
    
    # Check if virtual environment exists
    if [ ! -d "$APP_DIR/venv" ]; then
        echo "Creating virtual environment..."
        python3 -m venv "$APP_DIR/venv"
    fi
    
    # Activate virtual environment and install packages
    source "$APP_DIR/venv/bin/activate"
    pip install --upgrade pip
    pip install -r "$APP_DIR/requirements.txt"
    deactivate
    
    echo -e "${GREEN}✅ Dependencies installed${NC}"
}

# Function to setup environment
setup_environment() {
    echo -e "${YELLOW}⚙️  Setting up environment...${NC}"
    
    # Copy production env if not exists
    if [ ! -f "$APP_DIR/.env" ]; then
        if [ -f "$APP_DIR/.env.production" ]; then
            cp "$APP_DIR/.env.production" "$APP_DIR/.env"
            echo -e "${GREEN}✅ Environment file created${NC}"
            echo -e "${YELLOW}⚠️  Please edit $APP_DIR/.env with your configuration${NC}"
        fi
    else
        echo -e "${GREEN}✅ Environment file already exists${NC}"
    fi
}

# Function to initialize database
init_database() {
    echo -e "${YELLOW}🗄️  Initializing database...${NC}"
    cd "$APP_DIR"
    source venv/bin/activate
    python3 -c "from database import init_db; init_db()"
    deactivate
    echo -e "${GREEN}✅ Database initialized${NC}"
}

# Function to create systemd service
create_service() {
    echo -e "${YELLOW}🔧 Creating systemd service...${NC}"
    
    SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
    
    sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Hyde Park Gate System
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin"
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE_NAME"
    
    echo -e "${GREEN}✅ Systemd service created${NC}"
}

# Function to start service
start_service() {
    echo -e "${YELLOW}🚀 Starting service...${NC}"
    sudo systemctl restart "$SERVICE_NAME"
    sleep 2
    
    if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
        echo -e "${GREEN}✅ Service started successfully${NC}"
    else
        echo -e "${RED}❌ Service failed to start${NC}"
        echo "Check logs with: sudo journalctl -u $SERVICE_NAME -f"
        exit 1
    fi
}

# Function to show status
show_status() {
    echo ""
    echo "======================================"
    echo -e "${GREEN}🎉 Deployment Complete!${NC}"
    echo "======================================"
    echo ""
    echo "Service Status:"
    sudo systemctl status "$SERVICE_NAME" --no-pager | head -n 10
    echo ""
    echo "Useful Commands:"
    echo "  - View logs: sudo journalctl -u $SERVICE_NAME -f"
    echo "  - Restart: sudo systemctl restart $SERVICE_NAME"
    echo "  - Stop: sudo systemctl stop $SERVICE_NAME"
    echo "  - Status: sudo systemctl status $SERVICE_NAME"
    echo ""
    echo "Access the application at:"
    echo "  http://localhost:5000"
    echo "  https://middleware.hpd-lc.com/new/"
    echo ""
}

# Main deployment flow
main() {
    echo "Starting deployment..."
    echo ""
    
    # Backup existing installation
    backup_existing
    
    # Install dependencies
    install_dependencies
    
    # Setup environment
    setup_environment
    
    # Initialize database
    init_database
    
    # Create systemd service
    create_service
    
    # Start service
    start_service
    
    # Show status
    show_status
}

# Run main function
main
