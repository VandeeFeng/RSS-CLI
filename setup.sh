#!/bin/bash

echo "🚀 Initializing RSS CLI project..."

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3 first."
    exit 1
fi

# Check if Docker and Docker Compose are installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    echo "Visit https://docs.docker.com/get-docker/ for installation instructions."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    echo "Visit https://docs.docker.com/compose/install/ for installation instructions."
    exit 1
fi

# Create virtual environment if not exists
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
echo "🔌 Activating virtual environment..."
source .venv/bin/activate

# Check for UV and suggest installation if not found
if ! command -v uv &> /dev/null; then
    echo "⚡ UV package manager not found"
    echo "💡 UV is recommended for faster package installation"
    read -p "Would you like to install UV now? (y/N) " choice
    if [[ $choice =~ ^[Yy]$ ]]; then
        echo "📥 Installing UV..."
        if [[ "$OSTYPE" == "darwin"* ]] || [[ "$OSTYPE" == "linux"* ]]; then
            curl -LsSf https://astral.sh/uv/install.sh | sh
        elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
            powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
        else
            echo "⚠️  Could not detect OS type for UV installation"
            echo "📥 Falling back to pip installation..."
            pip install uv
        fi
        echo "📥 Installing dependencies using UV..."
        uv pip install -r requirements.txt
    else
        echo "📥 Installing dependencies using pip..."
        pip install -r requirements.txt
    fi
else
    echo "📥 Installing dependencies using UV..."
    uv pip install -r requirements.txt
fi

# Set up environment variables
if [ ! -f ".env" ] && [ -f "env.example" ]; then
    echo "🔧 Setting up environment variables..."
    cp env.example .env
    echo "⚠️ Please update the .env file with your actual configuration"
fi

# Start database using docker-compose
echo "🐳 Starting database services..."
cd database && docker-compose up -d
echo "⏳ Waiting for database to be ready..."
until docker-compose exec -T postgres pg_isready -U postgres > /dev/null 2>&1; do
    echo -n "."
    sleep 1
done
echo "✅ Database is ready!"
cd ..

echo "✅ Initialization complete!"
echo "🎉 You can now start using RSS CLI"
echo "💡 Run 'source .venv/bin/activate' to activate the virtual environment" 