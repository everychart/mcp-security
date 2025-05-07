import os
import json
import sys
from pymongo import MongoClient
from bson.objectid import ObjectId
import certifi

# Add the parent directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import MONGODB_URI, MONGODB_DB_NAME
except ImportError:
    # Fallback if config module is not available
    MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017/")
    MONGODB_DB_NAME = os.environ.get("MONGODB_DB_NAME", "mcp_security")

# MongoDB connection
client = MongoClient(MONGODB_URI, tlsCAFile=certifi.where())
db = client[MONGODB_DB_NAME]

def export_security_profile(profile_id, output_file=None):
    """
    Export a security profile document from MongoDB
    
    Args:
        profile_id: The ObjectId or string ID of the profile
        output_file: Optional file path to save the profile (defaults to profile_{id}.md)
    
    Returns:
        The markdown content of the profile
    """
    # Convert string ID to ObjectId if needed
    if isinstance(profile_id, str):
        profile_id = ObjectId(profile_id)
    
    # Find the profile in the database
    profile = db.security_profiles.find_one({"_id": profile_id})
    
    if not profile:
        print(f"Profile with ID {profile_id} not found")
        return None
    
    # Get the markdown report
    markdown_report = profile.get("markdown_report", "")
    
    # If no output file specified, create one based on the profile ID
    if not output_file:
        output_file = f"profile_{str(profile_id)}.md"
    
    # Create directory structure if it doesn't exist
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    # Write the markdown to a file
    with open(output_file, "w") as f:
        f.write(markdown_report)
    
    print(f"Profile exported to {output_file}")
    return markdown_report

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python export_profile.py <profile_id> [output_file]")
        sys.exit(1)
    
    profile_id = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    export_security_profile(profile_id, output_file)