#!/bin/bash
# Startup script for Databricks API Explorer

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install/update dependencies
echo "Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

# Create logs directory if it doesn't exist
mkdir -p logs

# Run the application
echo "Starting Flask application..."
echo "Open http://localhost:5000 in your browser"
echo ""
python app.py

