import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# MongoDB configuration
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "mcp_security")

# LLM configuration with multiple providers
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")  # Primary provider
FALLBACK_PROVIDERS = os.getenv("FALLBACK_PROVIDERS", "gemini").split(",")  # Fallback providers

# Anthropic configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20240620")

# Gemini configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

# Application configuration
DEBUG = os.getenv("DEBUG", "False").lower() == "true"