from flask import Flask, request, jsonify, send_file
import datetime
import os
import re
from pymongo import MongoClient
from bson.objectid import ObjectId
import certifi
from analysis.mcp_analysis_agent import MCPAnalysisAgent
from rq import Queue
from redis import Redis
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# MongoDB connection
client = MongoClient(os.environ.get("MONGODB_URI", "mongodb://localhost:27017/"), tlsCAFile=certifi.where())
db = client[os.environ.get("MONGODB_DB_NAME", "mcp_security")]

# Set up Redis queue for background processing
redis_conn = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
q = Queue('mcp_analysis', connection=redis_conn)

@app.route('/api/search', methods=['GET'])
def search_certification():
    """Search for a certification by GitHub URL"""
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
    
    result = {
        "found": True,
        "repo_id": str(repo["_id"]),
        "name": repo.get("name", ""),
        "certification_level": repo.get("certification_level", "None"),
        "evaluation_date": repo.get("evaluation_date").isoformat(),
        "security_score": repo.get("security_score", 0)
    }
    
    if profile:
        result["profile_id"] = str(profile["_id"])
        result["executive_summary"] = profile.get("executive_summary", "")
    
    return jsonify(result)

@app.route('/api/certification/request', methods=['POST'])
def request_certification():
    """Request certification for a GitHub repository"""
    data = request.json
    repo_url = data.get('repo_url')
    contact_email = data.get('contact_email')
    
    # Validate inputs
    if not repo_url or not is_valid_github_url(repo_url):
        return jsonify({"error": "Invalid GitHub repository URL"}), 400
    
    # Check if we already have a recent analysis
    existing_analysis = db.repositories.find_one({
        "repo_url": repo_url,
        "evaluation_date": {"$gt": datetime.datetime.now() - datetime.timedelta(days=30)}
    })
    
    if existing_analysis:
        # Return existing certification status
        return jsonify({
            "status": "existing",
            "repo_id": str(existing_analysis["_id"]),
            "certification_level": existing_analysis.get("certification_level", "None"),
            "evaluation_date": existing_analysis.get("evaluation_date").isoformat()
        })
    
    # Queue new analysis
    job = q.enqueue(
        'tasks.analyze_repository',
        repo_url=repo_url,
        contact_email=contact_email,
        job_timeout='1h'
    )
    
    # Record the request
    db.certification_requests.insert_one({
        "repo_url": repo_url,
        "contact_email": contact_email,
        "request_date": datetime.datetime.now(),
        "job_id": str(job.id),
        "status": "queued"
    })
    
    return jsonify({
        "status": "queued",
        "job_id": str(job.id),
        "estimated_completion": "Your analysis will be completed within 24 hours"
    })

@app.route('/api/certification/status/<job_id>', methods=['GET'])
def check_certification_status(job_id):
    """Check the status of a certification request"""
    job = q.fetch_job(job_id)
    
    if not job:
        return jsonify({"error": "Job not found"}), 404
    
    status = {
        "job_id": job_id,
        "status": job.get_status(),
        "queue_position": get_queue_position(job_id),
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "ended_at": job.ended_at.isoformat() if job.ended_at else None
    }
    
    if job.is_finished:
        result = job.result
        if result and "certification_level" in result:
            status["certification_level"] = result["certification_level"]
            status["repo_id"] = result.get("repo_id")
            status["profile_id"] = result.get("profile_id")
    
    return jsonify(status)

@app.route('/api/profile/<profile_id>', methods=['GET'])
def get_profile(profile_id):
    """Get a security profile by ID"""
    try:
        profile_id = ObjectId(profile_id)
    except:
        return jsonify({"error": "Invalid profile ID"}), 400
    
    profile = db.security_profiles.find_one({"_id": profile_id})
    
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    
    # Convert ObjectId to string for JSON serialization
    profile["_id"] = str(profile["_id"])
    profile["repo_id"] = str(profile["repo_id"])
    
    # Format dates for JSON serialization
    profile["evaluation_date"] = profile["evaluation_date"].isoformat()
    if "certification" in profile and "expiration" in profile["certification"]:
        profile["certification"]["expiration"] = profile["certification"]["expiration"].isoformat()
    
    return jsonify(profile)

@app.route('/api/profile/<profile_id>/export', methods=['GET'])
def export_profile(profile_id):
    """Export a security profile as markdown"""
    from scripts.export_profile import export_security_profile
    
    try:
        # Create a temporary file for the export
        import tempfile
        temp_file = tempfile.NamedTemporaryFile(suffix=".md", delete=False)
        temp_file.close()
        
        # Export the profile to the temporary file
        export_security_profile(profile_id, temp_file.name)
        
        # Get the repository name for the filename
        profile = db.security_profiles.find_one({"_id": ObjectId(profile_id)})
        repo = db.repositories.find_one({"_id": profile["repo_id"]}) if profile else None
        filename = f"{repo['name']}_security_profile.md" if repo else f"profile_{profile_id}.md"
        
        # Send the file
        return send_file(
            temp_file.name,
            as_attachment=True,
            download_name=filename,
            mimetype="text/markdown"
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        # Clean up the temporary file
        if 'temp_file' in locals() and os.path.exists(temp_file.name):
            os.unlink(temp_file.name)

def is_valid_github_url(url):
    """Validate that a URL is a GitHub repository URL"""
    pattern = r'^https://github\.com/[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+/?$'
    return bool(re.match(pattern, url))

def get_queue_position(job_id):
    """Get the position of a job in the queue"""
    registry = q.started_job_registry
    if registry.contains(job_id):
        return 0
    
    # Check if job is in the queue
    for i, job in enumerate(q.get_jobs()):
        if job.id == job_id:
            return i + 1
    
    return None

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)