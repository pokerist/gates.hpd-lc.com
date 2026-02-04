#!/bin/bash

# Hyde Park Gate System - Run Script

echo "🏛️  Hyde Park Compound Gate System"
echo "=================================="
echo ""

# Check if OPENROUTER_API_KEY is set
if [ -z "$OPENROUTER_API_KEY" ]; then
    echo "⚠️  WARNING: OPENROUTER_API_KEY environment variable is not set!"
    echo "   Vision LLM extraction will not work without it."
    echo ""
    echo "   Set it with: export OPENROUTER_API_KEY='your_key_here'"
    echo ""
fi

# Initialize database
echo "📦 Initializing database..."
python3 -c "from database import init_db; init_db()"

echo ""
echo "🚀 Starting Flask application on http://0.0.0.0:5000"
echo "   Press Ctrl+C to stop"
echo ""

# Run the application
python3 app.py
