from flask import Flask, request, jsonify, Response
import os
import sys
import re
import subprocess
import threading
from pymongo import MongoClient
from bson.objectid import ObjectId
import certifi
from flask_cors import CORS  # Make sure this import is present
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Add the parent directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    MONGODB_URI, 
    MONGODB_DB_NAME,
    LLM_PROVIDER,
    FALLBACK_PROVIDERS,
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    GEMINI_API_KEY,
    GEMINI_MODEL
)
from scripts.export_profile import export_security_profile

app = Flask(__name__)
# Configure CORS to allow requests from your GitHub Pages domain
CORS(app, origins=["https://everychart.github.io"])  # Add your GitHub Pages domain here

# Alternatively, to allow requests from any domain (less secure but easier for testing):
# CORS(app)

# MongoDB connection
client = MongoClient(MONGODB_URI, tlsCAFile=certifi.where())
db = client[MONGODB_DB_NAME]

# Dictionary to track running analyses
running_analyses = {}

@app.route('/api/search', methods=['GET'])
def search_repository():
    """Search for a repository by GitHub URL"""
    repo_url = request.args.get('repo_url')
    
    if not repo_url or not is_valid_github_url(repo_url):
        return jsonify({"error": "Invalid GitHub repository URL"}), 400
    
    # Find the repository in the database
    repo = db.repositories.find_one({"repo_url": repo_url})
    
    if not repo:
        return jsonify({"found": False})
    
    # Find the latest security profile for this repository
    profile = db.security_profiles.find_one(
        {"repo_id": repo["_id"]},
        sort=[("evaluation_date", -1)]
    )
    
    if not profile:
        return jsonify({"found": True, "has_profile": False, "repo_id": str(repo["_id"])})
    
    return jsonify({
        "found": True,
        "has_profile": True,
        "repo_id": str(repo["_id"]),
        "profile_id": str(profile["_id"])
    })

@app.route('/api/report', methods=['GET'])
def get_report():
    """Get a markdown report for a repository"""
    repo_url = request.args.get('repo_url')
    
    if not repo_url or not is_valid_github_url(repo_url):
        return jsonify({"error": "Invalid GitHub repository URL"}), 400
    
    # Find the repository in the database
    repo = db.repositories.find_one({"repo_url": repo_url})
    
    if not repo:
        # Repository not found, trigger analysis
        return jsonify({"status": "not_found", "message": "Repository not found. Use /api/analyze to trigger analysis."}), 404
    
    # Find the latest security profile for this repository
    profile = db.security_profiles.find_one(
        {"repo_id": repo["_id"]},
        sort=[("evaluation_date", -1)]
    )
    
    if not profile:
        return jsonify({"status": "no_profile", "message": "No security profile found for this repository."}), 404
    
    # Return the markdown report
    return Response(
        profile.get("markdown_report", "No report available"),
        mimetype="text/markdown"
    )

@app.route('/api/analyze', methods=['POST'])
def analyze_repository():
    """Trigger analysis for a GitHub repository"""
    data = request.json
    repo_url = data.get('repo_url')
    
    if not repo_url or not is_valid_github_url(repo_url):
        return jsonify({"error": "Invalid GitHub repository URL"}), 400
    
    # Check if analysis is already running for this URL
    if repo_url in running_analyses:
        return jsonify({
            "status": "in_progress",
            "message": "Analysis is already running for this repository."
        })
    
    # Check if we already have a recent analysis
    repo = db.repositories.find_one({"repo_url": repo_url})
    if repo:
        profile = db.security_profiles.find_one(
            {"repo_id": repo["_id"]},
            sort=[("evaluation_date", -1)]
        )
        if profile:
            return jsonify({
                "status": "exists",
                "message": "Repository already analyzed.",
                "profile_id": str(profile["_id"])
            })
    
    # Start analysis in a background thread
    thread = threading.Thread(
        target=run_analysis_in_background,
        args=(repo_url,)
    )
    thread.daemon = True
    thread.start()
    
    # Track the running analysis
    running_analyses[repo_url] = True
    
    return jsonify({
        "status": "started",
        "message": "Analysis started. Check back in a few minutes for results."
    })

@app.route('/api/export/<profile_id>', methods=['GET'])
def export_report(profile_id):
    """Export a markdown report for a profile"""
    try:
        # Find the profile
        profile = db.security_profiles.find_one({"_id": ObjectId(profile_id)})
        
        if not profile:
            return jsonify({"error": "Profile not found"}), 404
        
        # Return the markdown report
        return Response(
            profile.get("markdown_report", "No report available"),
            mimetype="text/markdown"
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/search-servers', methods=['GET'])
def search_servers():
    """Search for MCP servers by keyword"""
    keyword = request.args.get('keyword', '').lower()
    
    # If no keyword provided, return all repositories
    query = {}
    if keyword:
        # Search in name, primary_function, and description fields
        query = {
            "$or": [
                {"name": {"$regex": keyword, "$options": "i"}},
                {"primary_function": {"$regex": keyword, "$options": "i"}},
                {"description": {"$regex": keyword, "$options": "i"}}
            ]
        }
    
    # Find matching repositories
    repos = list(db.repositories.find(
        query,
        {
            "_id": 1,
            "name": 1,
            "repo_url": 1,
            "primary_function": 1,
            "certification_level": 1,
            "security_score": 1,
            "description": 1,
            "evaluation_date": 1
        }
    ).sort("security_score", -1))
    
    # Convert ObjectId to string for JSON serialization
    for repo in repos:
        repo["_id"] = str(repo["_id"])
        if "evaluation_date" in repo and repo["evaluation_date"]:
            repo["evaluation_date"] = repo["evaluation_date"].isoformat()
    
    return jsonify({
        "count": len(repos),
        "servers": repos
    })

def run_analysis_in_background(repo_url):
    """Run repository analysis in a background thread"""
    try:
        print(f"Starting analysis for {repo_url}")
        
        # Get the absolute path to the analysis script
        script_path = os.path.abspath(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "analysis", "mcp_analysis_agent.py"
        ))
        
        print(f"Analysis script path: {script_path}")
        
        # Check if the script exists
        if not os.path.exists(script_path):
            print(f"ERROR: Analysis script not found at {script_path}")
            return
        
        # Try to find the best Python executable
        # First try python3 (common on macOS)
        try:
            subprocess.run(["python3", "--version"], capture_output=True, check=True)
            python_executable = "python3"
        except (subprocess.SubprocessError, FileNotFoundError):
            # Fall back to sys.executable
            python_executable = sys.executable
        
        print(f"Using Python executable: {python_executable}")
        
        # Pass LLM configuration as environment variables
        env = os.environ.copy()
        env["LLM_PROVIDER"] = LLM_PROVIDER
        env["FALLBACK_PROVIDERS"] = ",".join(FALLBACK_PROVIDERS)
        env["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY
        env["ANTHROPIC_MODEL"] = ANTHROPIC_MODEL
        env["GEMINI_API_KEY"] = GEMINI_API_KEY
        env["GEMINI_MODEL"] = GEMINI_MODEL
        
        # Run the analysis script as a subprocess with full output capture
        print(f"Executing: {python_executable} {script_path} {repo_url}")
        
        # Use subprocess.run for better control and output capture
        result = subprocess.run(
            [python_executable, script_path, repo_url],
            capture_output=True,
            text=True,
            env=env
        )
        
        # Log the output regardless of success/failure
        print(f"Analysis stdout: {result.stdout}")
        print(f"Analysis stderr: {result.stderr}")
        
        # Check if the process was successful
        if result.returncode != 0:
            print(f"Analysis process failed with return code {result.returncode}")
            return
        
        # Look for the profile ID in the output
        profile_id_match = re.search(r"Profile ID: ([a-f0-9]{24})", result.stdout)
        repo_id_match = re.search(r"Repository ID: ([a-f0-9]{24})", result.stdout)
        
        if profile_id_match:
            profile_id = profile_id_match.group(1)
            print(f"Successfully extracted profile ID: {profile_id}")
        else:
            print("Could not extract profile ID from analysis output")
        
        # Directly query MongoDB to find the profile
        if not profile_id_match:
            print("Attempting to find profile in database...")
            # Find the repository
            repo = db.repositories.find_one({"repo_url": repo_url})
            if repo:
                print(f"Found repository with ID: {repo['_id']}")
                # Find the latest profile for this repository
                profile = db.security_profiles.find_one(
                    {"repo_id": repo["_id"]},
                    sort=[("evaluation_date", -1)]
                )
                if profile:
                    print(f"Found profile with ID: {profile['_id']}")
    
    except Exception as e:
        print(f"Exception during analysis: {str(e)}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Remove from running analyses
        if repo_url in running_analyses:
            del running_analyses[repo_url]
            print(f"Removed {repo_url} from running analyses")

def is_valid_github_url(url):
    """Validate that a URL is a GitHub repository URL"""
    pattern = r'^https://github\.com/[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+/?'
    return bool(re.match(pattern, url))

@app.after_request
def add_cors_headers(response):
    response.headers.add('Access-Control-Allow-Origin', 'https://everychart.github.io')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
    return response

# Handle OPTIONS requests for CORS preflight
@app.route('/api/<path:path>', methods=['OPTIONS'])
@app.route('/api/', defaults={'path': ''}, methods=['OPTIONS'])
def options_handler(path):
    return Response('', status=200)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)