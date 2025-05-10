import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# MongoDB configuration
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "mcp_security")

# LLM configuration - hardcoded to use Anthropic
LLM_PROVIDER = "anthropic"  # Hardcoded to use Anthropic
LLM_MODEL = os.getenv("LLM_MODEL", "claude-3-5-sonnet-20240620")  # Default to a Claude model
LLM_API_KEY = os.getenv("LLM_API_KEY", "")  # API key should still come from env


# Application configuration
DEBUG = os.getenv("DEBUG", "False").lower() == "true"