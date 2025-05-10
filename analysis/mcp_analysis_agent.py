import sys
import os
import certifi
import re
import tempfile
import shutil
import git
from pymongo import MongoClient
import datetime
from typing import Dict, List, Any, Optional, Tuple
from bson.objectid import ObjectId

# Add the parent directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import MONGODB_URI, MONGODB_DB_NAME, LLM_PROVIDER, LLM_MODEL
from llm.llm_factory import get_llm_client

# MongoDB connection
client = MongoClient(MONGODB_URI,tlsCAFile=certifi.where())
db = client[MONGODB_DB_NAME]

class MCPAnalysisAgent:
    """Agent for analyzing MCP server repositories using LLM"""
    
    def __init__(self):
        # Get LLM client from factory
        config = {
            "LLM_MODEL": LLM_MODEL,
            "LLM_API_KEY": os.environ.get("LLM_API_KEY", "")
        }
        self.llm_client = get_llm_client(LLM_PROVIDER, config)
        
        # Load evaluation criteria from file
        with open("framework/evaluation-criterea.md", "r") as f:
            self.evaluation_criteria = f.read()
            
        # Load evaluation template from file
        with open("framework/evaluation-template.md", "r") as f:
            self.evaluation_template = f.read()
    
    def analyze_repository(self, repo_url: str) -> dict[str, any]:
        """
        Analyze an MCP server repository and generate a security profile
        
        Args:
            repo_url: URL of the GitHub repository
            
        Returns:
            Dictionary containing the security profile
        """
        # Clone repository to temporary directory
        repo_path = self._clone_repository(repo_url)
        try:
            # Extract repository metadata
            repo_metadata = self._extract_repo_metadata(repo_path, repo_url)
            
            # Extract security-relevant files
            security_files = self._extract_security_files(repo_path)
            
            # Store files in database
            repo_id = self._store_repository_info(repo_metadata)
            self._store_security_files(repo_id, security_files)
            
            # Generate LLM analysis prompt
            prompt = self._generate_analysis_prompt(repo_metadata, security_files)
            
            # Get LLM analysis
            analysis_result = self._get_llm_analysis(prompt)
            
            # Parse and store the analysis
            security_profile = self._parse_llm_analysis(analysis_result)
            security_profile["repo_id"] = repo_id
            
            # Store the security profile
            profile_id = self._store_security_profile(security_profile)
            
            # Update repository certification
            self._update_repository_certification(
                repo_id, 
                security_profile["certification"]["level"],
                security_profile["scores"]["overall"]
            )
            
            return {
                "repo_id": str(repo_id),
                "profile_id": str(profile_id),
                "certification_level": security_profile["certification"]["level"],
                "security_score": security_profile["scores"]["overall"]
            }
            
        finally:
            # Clean up temporary directory
            if repo_path and os.path.exists(repo_path):
                shutil.rmtree(repo_path)
    
    def _clone_repository(self, repo_url: str) -> str:
        """Clone a repository to a temporary directory"""
        temp_dir = tempfile.mkdtemp()
        try:
            git.Repo.clone_from(repo_url, temp_dir)
            return temp_dir
        except Exception as e:
            shutil.rmtree(temp_dir)
            raise Exception(f"Failed to clone repository: {str(e)}")
    
    def _extract_repo_metadata(self, repo_path: str, repo_url: str) -> dict[str, any]:
        """Extract metadata from the repository"""
        repo = git.Repo(repo_path)
        
        # Get the latest commit
        latest_commit = repo.head.commit
        
        # Try to extract name from repo_url
        repo_name = repo_url.split("/")[-1]
        
        # Try to determine primary function from README or other files
        primary_function = self._determine_primary_function(repo_path)
        
        return {
            "name": repo_name,
            "repo_url": repo_url,
            "primary_function": primary_function,
            "evaluation_date": datetime.datetime.now(),
            "evaluator": "MCP Security Analysis Agent",
            "version_evaluated": latest_commit.hexsha,
            "last_updated": datetime.datetime.fromtimestamp(latest_commit.committed_date)
        }
    
    def _determine_primary_function(self, repo_path: str) -> str:
        """Try to determine the primary function of the MCP server"""
        # Check README for clues
        readme_path = os.path.join(repo_path, "README.md")
        if os.path.exists(readme_path):
            with open(readme_path, "r") as f:
                content = f.read().lower()
                if "memory" in content and "store" in content:
                    return "Memory"
                elif "retrieval" in content and ("search" in content or "query" in content):
                    return "Retrieval"
                elif "tool" in content or "function" in content:
                    return "Tool"
        
        # Default if we can't determine
        return "Unknown"
    
    def _extract_security_files(self, repo_path: str) -> dict[str, dict[str, any]]:
        """Extract security-relevant files from the repository"""
        security_files = {}
        
        # File patterns to look for by category
        file_patterns = {
            "config": [
                "config.py", "settings.py", ".env.example", "config.json", 
                "docker-compose.yml", "Dockerfile"
            ],
            "auth": [
                "auth.py", "authentication.py", "security.py", "login.py",
                "oauth.py", "jwt.py", "token.py"
            ],
            "api": [
                "api.py", "routes.py", "endpoints.py", "views.py", 
                "controllers.py", "handlers.py"
            ],
            "main": [
                "app.py", "main.py", "server.py", "index.py", 
                "__main__.py", "run.py"
            ],
            "docs": [
                "README.md", "SECURITY.md", "API.md", "CONTRIBUTING.md"
            ],
            "dependencies": [
                "requirements.txt", "package.json", "pyproject.toml",
                "setup.py", "Pipfile", "poetry.lock"
            ]
        }
        
        # Walk through repository and find matching files
        for root, _, files in os.walk(repo_path):
            for file in files:
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, repo_path)
                
                # Skip .git directory
                if ".git" in relative_path.split(os.path.sep):
                    continue
                
                # Determine file type
                file_type = None
                for category, patterns in file_patterns.items():
                    if any(file.endswith(pattern) or file == pattern for pattern in patterns):
                        file_type = category
                        break
                
                # If no match in patterns, try to determine by content for Python files
                if not file_type and file.endswith(".py"):
                    file_type = self._determine_file_type_by_content(file_path)
                
                # If we identified a file type, read the content
                if file_type:
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                            
                            security_files[relative_path] = {
                                "file_path": relative_path,
                                "file_type": file_type,
                                "content": content,
                                "last_updated": datetime.datetime.fromtimestamp(
                                    os.path.getmtime(file_path)
                                )
                            }
                    except UnicodeDecodeError:
                        # Skip binary files
                        pass
        
        return security_files
    
    def _determine_file_type_by_content(self, file_path: str) -> Optional[str]:
        """Determine file type by examining content"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().lower()
                
                if "auth" in content or "login" in content or "token" in content:
                    return "auth"
                elif "app.route" in content or "fastapi" in content or "endpoint" in content:
                    return "api"
                elif "config" in content or "settings" in content or "environment" in content:
                    return "config"
                elif "if __name__ == '__main__'" in content:
                    return "main"
                
                return None
        except UnicodeDecodeError:
            return None
    
    def _store_repository_info(self, repo_metadata: dict[str, any]) -> ObjectId:
        """Store repository information in database"""
        # Check if repository already exists
        existing_repo = db.repositories.find_one({"repo_url": repo_metadata["repo_url"]})
        
        if existing_repo:
            # Update existing repository
            db.repositories.update_one(
                {"_id": existing_repo["_id"]},
                {"$set": {
                    "evaluation_date": repo_metadata["evaluation_date"],
                    "version_evaluated": repo_metadata["version_evaluated"],
                    "last_updated": repo_metadata["last_updated"]
                }}
            )
            return existing_repo["_id"]
        else:
            # Insert new repository
            result = db.repositories.insert_one(repo_metadata)
            return result.inserted_id
    
    def _store_security_files(self, repo_id: ObjectId, security_files: dict[str, dict[str, any]]) -> None:
        """Store security-relevant files in database"""
        # Delete existing files for this repository
        db.security_files.delete_many({"repo_id": repo_id})
        
        # Insert new files
        for file_path, file_data in security_files.items():
            file_data["repo_id"] = repo_id
            db.security_files.insert_one(file_data)
    
    def _generate_analysis_prompt(self, repo_metadata: dict[str, any], security_files: dict[str, dict[str, any]]) -> str:
        """Generate a prompt for LLM analysis"""
        prompt = f"""
# MCP Security Analysis Request

Please analyze the following Model Context Protocol (MCP) server implementation for security vulnerabilities and best practices.

## Repository Information
- Name: {repo_metadata['name']}
- Repository URL: {repo_metadata['repo_url']}
- Primary Function: {repo_metadata['primary_function']}
- Version: {repo_metadata['version_evaluated']}

## Important Context About MCP Implementations

MCP is a new protocol that standardizes how applications provide context to Large Language Models (LLMs). When analyzing MCP server implementations, consider:

1. **Integration Context**: Many MCP servers are designed to be integrated into larger systems where authentication, rate limiting, and other security features are provided by the integrating application. Do not flag missing security features if the README or documentation clearly indicates they should be added by the developer during integration.

2. **Implementation Intent**: Use the README.md and documentation to understand the intended use case and deployment model. Some implementations are meant to be used behind API gateways or within secure environments where certain security features would be redundant.

3. **Component Architecture**: Determine if the repository is a standalone server or a component meant to be used within a larger system. Components may rely on their parent system for security features.

4. **API Keys and Authentication**: If the documentation mentions the need for API keys or authentication to be added during deployment (e.g., "add your GitHub personal access token"), do not flag the absence of these in the code as vulnerabilities.

5. **Development Status**: Consider whether the repository is in active development, a proof of concept, or a production-ready implementation. Adjust your expectations accordingly.

## Evaluation Criteria
Use the following criteria to evaluate the security of this MCP server:

{self.evaluation_criteria}

## Security-Relevant Files

"""
        
        # Add README.md first if it exists, to provide context for the analysis
        readme_content = None
        for file_path, file_data in security_files.items():
            if file_path.lower() == "readme.md":
                readme_content = file_data["content"]
                prompt += f"### README.md (Important for Context)\n\n{readme_content}\n\n"
                break
        
        # Group files by type
        files_by_type = {}
        for file_path, file_data in security_files.items():
            # Skip README.md as we've already included it
            if file_path.lower() == "readme.md":
                continue
                
            file_type = file_data["file_type"]
            if file_type not in files_by_type:
                files_by_type[file_type] = []
            files_by_type[file_type].append((file_path, file_data["content"]))
        
        # Add files to prompt, grouped by type
        for file_type, files in files_by_type.items():
            prompt += f"### {file_type.title()} Files\n\n"
            
            for file_path, content in files:
                # Truncate very large files
                if len(content) > 5000:
                    content = content[:5000] + "...[truncated]"
                
                prompt += f"**File: {file_path}**\n\n{content}\n\n\n"
        
        # Add instructions for output format with emphasis on context-aware analysis
        prompt += f"""
## Output Format
Please provide your analysis in the following format:

{self.evaluation_template}

## Special Analysis Instructions

1. **Context-Aware Analysis**: Before identifying vulnerabilities, carefully consider the intended deployment context from the README and documentation. Only flag issues that would be security problems in the intended deployment scenario.

2. **Integration Assumptions**: If the repository is meant to be integrated with other systems that provide security features, clearly state these assumptions in your analysis.

3. **Distinguish Between Issues**:
   - **Actual Vulnerabilities**: Security issues that exist regardless of deployment context
   - **Integration Requirements**: Security features that need to be added during integration
   - **Recommendations**: Suggestions for improving security beyond the minimum requirements

4. **Certification Justification**: Provide clear reasoning for the certification level, considering the intended use case and deployment model.

5. **Specific GitHub MCP Server Context**: For GitHub's MCP server implementation, pay special attention to how it's intended to be deployed and integrated. The README likely indicates that users need to provide their own GitHub Personal Access Token, which means authentication is handled through integration rather than being a vulnerability in the implementation itself.

Focus on practical, actionable insights rather than theoretical concerns. Avoid penalizing the implementation for security features that are intentionally left to the integrator.
"""
        
        return prompt
    
    def _get_llm_analysis(self, prompt: str) -> str:
        """Get analysis from LLM API"""
        system_prompt = "You are a security expert analyzing MCP server implementations."
        
        try:
            return self.llm_client.generate_completion(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.2
            )
        except Exception as e:
            raise Exception(f"LLM analysis failed: {str(e)}")
    
    def _extract_section(self, text: str, section_title: str, next_section: Optional[str] = None) -> str:
        """Extract a section from the markdown text"""
        import re
        
        # Pattern to match the section header (more flexible)
        section_patterns = [
            rf"## {re.escape(section_title)}\s*\n",
            rf"#{{{2,3}}} {re.escape(section_title)}\s*\n",
            rf"\*\*{re.escape(section_title)}\*\*\s*\n"
        ]
        
        # Find the start of the section
        start_pos = -1
        for pattern in section_patterns:
            match = re.search(pattern, text)
            if match:
                start_pos = match.end()
                break
        
        if start_pos == -1:
            # Try a more lenient search
            simple_pattern = re.escape(section_title)
            match = re.search(simple_pattern, text)
            if match:
                # Find the end of the line
                line_end = text.find('\n', match.end())
                if line_end != -1:
                    start_pos = line_end + 1
        
        if start_pos == -1:
            return ""
        
        # Find the end of the section (start of the next section or end of text)
        end_pos = len(text)
        
        if next_section:
            next_section_patterns = [
                rf"## {re.escape(next_section)}\s*\n",
                rf"#{{{2,3}}} {re.escape(next_section)}\s*\n",
                rf"\*\*{re.escape(next_section)}\*\*\s*\n"
            ]
            
            for pattern in next_section_patterns:
                next_match = re.search(pattern, text[start_pos:])
                if next_match:
                    end_pos = start_pos + next_match.start()
                    break
        else:
            # Look for any section header
            next_header_matches = re.finditer(r"(?:^|\n)(?:#{2,3}|\*\*)[^#\*\n]+(?:\*\*)?(?:\n|$)", text[start_pos:])
            for next_match in next_header_matches:
                end_pos = start_pos + next_match.start()
                break
        
        # Extract and return the section content
        return text[start_pos:end_pos].strip()
    
    def _parse_llm_analysis(self, analysis_result: str) -> dict[str, any]:
        """Parse the LLM analysis into a structured format"""
        # Store the full markdown report
        security_profile = {
            "markdown_report": analysis_result,
            "evaluation_date": datetime.datetime.now()
        }
        
        # Extract scores with more flexible patterns
        scores = {
            "overall": 0,
            "authentication": 0,
            "data_protection": 0,
            "input_validation": 0,
            "prompt_security": 0,
            "infrastructure": 0
        }
        
        # Try to extract the Security Score section
        score_section = self._extract_section(analysis_result, "Security Score", None)
        if not score_section:
            # Try alternative section titles
            score_section = self._extract_section(analysis_result, "Security Scores", None)
        
        if score_section:
            # Process each line in the score section
            for line in score_section.split("\n"):
                line = line.lower()
                
                # Check for each score type
                if "overall" in line:
                    scores["overall"] = self._extract_score(line)
                elif "authentication" in line:
                    scores["authentication"] = self._extract_score(line)
                elif "data protection" in line:
                    scores["data_protection"] = self._extract_score(line)
                elif "input validation" in line:
                    scores["input_validation"] = self._extract_score(line)
                elif "prompt security" in line:
                    scores["prompt_security"] = self._extract_score(line)
                elif "infrastructure" in line:
                    scores["infrastructure"] = self._extract_score(line)
        
        # If we still don't have scores, try to extract them from the entire document
        if scores["overall"] == 0:
            # Look for patterns like "Overall Score: 7/10" anywhere in the document
            import re
            
            score_patterns = {
                "overall": r"overall\s+score:?\s*(\d+(?:\.\d+)?)",
                "authentication": r"authentication.*?score:?\s*(\d+(?:\.\d+)?)",
                "data_protection": r"data\s+protection.*?score:?\s*(\d+(?:\.\d+)?)",
                "input_validation": r"input\s+validation.*?score:?\s*(\d+(?:\.\d+)?)",
                "prompt_security": r"prompt\s+security.*?score:?\s*(\d+(?:\.\d+)?)",
                "infrastructure": r"infrastructure.*?score:?\s*(\d+(?:\.\d+)?)"
            }
            
            for score_type, pattern in score_patterns.items():
                match = re.search(pattern, analysis_result.lower())
                if match:
                    try:
                        scores[score_type] = float(match.group(1))
                    except (ValueError, IndexError):
                        pass
        
        security_profile["scores"] = scores
        
        # Extract executive summary with more flexible section detection
        executive_summary = self._extract_section(analysis_result, "Executive Summary", None)
        security_profile["executive_summary"] = executive_summary
        
        # Extract integration context
        integration_context = self._extract_section(analysis_result, "Architecture Overview", None)
        if not integration_context:
            integration_context = self._extract_section(analysis_result, "Implementation Context", None)
        security_profile["integration_context"] = integration_context
        
        # Extract vulnerabilities with more flexible parsing
        vulnerabilities_section = self._extract_section(analysis_result, "Vulnerabilities", None)
        vulnerabilities = []
        integration_requirements = []
        
        if vulnerabilities_section:
            # Parse the markdown table - more robust approach
            import re
            
            # Find table rows
            table_rows = re.findall(r"\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|", vulnerabilities_section)
            
            for row in table_rows:
                # Skip header or separator rows
                if not row[0] or row[0].strip() == "ID" or "-" in row[0]:
                    continue
                
                # Determine if this is a vulnerability or integration requirement
                vuln_type = row[2].lower() if len(row) > 2 else ""
                
                if "integration" in vuln_type or "requirement" in vuln_type:
                    integration_requirements.append({
                        "id": row[0].strip(),
                        "severity": row[1].strip() if len(row) > 1 else "Medium",
                        "category": row[2].strip() if len(row) > 2 else "",
                        "description": row[3].strip() if len(row) > 3 else "",
                        "recommendation": row[4].strip() if len(row) > 4 else "",
                        "status": "Open"
                    })
                else:
                    vulnerabilities.append({
                        "id": row[0].strip(),
                        "severity": row[1].strip() if len(row) > 1 else "Medium",
                        "category": row[2].strip() if len(row) > 2 else "",
                        "description": row[3].strip() if len(row) > 3 else "",
                        "recommendation": row[4].strip() if len(row) > 4 else "",
                        "status": "Open"
                    })
        
        security_profile["vulnerabilities"] = vulnerabilities
        security_profile["integration_requirements"] = integration_requirements
        
        # Extract certification details with more flexible section detection
        certification_section = self._extract_section(analysis_result, "Certification Details", None)
        
        # Set current date and expiration date (1 year from now)
        current_date = datetime.datetime.now()
        expiration_date = current_date + datetime.timedelta(days=365)
        
        certification = {
            "level": "None",
            "justification": "",
            "conditions": "",
            "expiration": expiration_date
        }
        
        if certification_section:
            # Look for certification level
            import re
            level_match = re.search(r"(?:certification|level).*?:\s*(Bronze|Silver|Gold|None)", certification_section, re.IGNORECASE)
            if level_match:
                certification["level"] = level_match.group(1).capitalize()
            
            # Look for justification
            justification_match = re.search(r"justification.*?:\s*([^\n]+)", certification_section, re.IGNORECASE)
            if justification_match:
                certification["justification"] = justification_match.group(1).strip()
            
            # Look for conditions
            conditions_match = re.search(r"conditions.*?:\s*([^\n]+)", certification_section, re.IGNORECASE)
            if conditions_match:
                certification["conditions"] = conditions_match.group(1).strip()
        
        security_profile["certification"] = certification
        
        # Extract security features with more flexible section detection
        security_features = {}
        
        feature_sections = [
            ("Authentication & Authorization", "authentication"),
            ("Data Protection", "data_protection"),
            ("Input Validation & Processing", "input_validation"),
            ("Prompt Security", "prompt_security"),
            ("Infrastructure Security", "infrastructure")
        ]
        
        for section_title, feature_key in feature_sections:
            section_content = self._extract_section(analysis_result, section_title, None)
            if section_content:
                security_features[feature_key] = section_content
        
        security_profile["security_features"] = security_features
        
        # Extract deployment recommendations
        deployment_recommendations = self._extract_section(analysis_result, "Deployment Recommendations", None)
        security_profile["deployment_recommendations"] = deployment_recommendations
        
        # Extract code quality assessment
        code_quality = self._extract_section(analysis_result, "Code Quality Assessment", None)
        security_profile["code_quality"] = code_quality
        
        # Update the markdown report with correct dates
        import re
        eval_date_str = current_date.strftime("%Y-%m-%d")
        exp_date_str = expiration_date.strftime("%Y-%m-%d")
        
        # Replace or add evaluation date
        updated_markdown = analysis_result
        
        # Try to replace existing evaluation date patterns
        eval_date_patterns = [
            r"(Evaluation Date:).*",
            r"(Date of Evaluation:).*",
            r"(Evaluated on:).*",
            r"(Evaluation:).*\d{4}"
        ]
        
        for pattern in eval_date_patterns:
            updated_markdown = re.sub(pattern, r"\1 " + eval_date_str, updated_markdown, flags=re.IGNORECASE)
        
        # Try to replace existing expiration date patterns
        exp_date_patterns = [
            r"(Expiration Date:).*",
            r"(Valid Until:).*",
            r"(Expires on:).*",
            r"(Expiration:).*\d{4}"
        ]
        
        for pattern in exp_date_patterns:
            updated_markdown = re.sub(pattern, r"\1 " + exp_date_str, updated_markdown, flags=re.IGNORECASE)
        
        # Check if evaluation date exists in the updated markdown
        if not re.search(r"Evaluation Date:", updated_markdown, re.IGNORECASE):
            # Try to find a good place to insert it - after the title or before the first section
            if "# Security Certification Report" in updated_markdown:
                updated_markdown = updated_markdown.replace(
                    "# Security Certification Report", 
                    "# Security Certification Report\n\nEvaluation Date: " + eval_date_str
                )
            elif "## Executive Summary" in updated_markdown:
                updated_markdown = updated_markdown.replace(
                    "## Executive Summary", 
                    "Evaluation Date: " + eval_date_str + "\n\n## Executive Summary"
                )
            else:
                # Just add it at the beginning
                updated_markdown = "Evaluation Date: " + eval_date_str + "\n\n" + updated_markdown
        
        # Check if expiration date exists in the updated markdown
        if not re.search(r"Expiration Date:", updated_markdown, re.IGNORECASE):
            # Try to find the certification section to add it
            if "## Certification Details" in updated_markdown:
                # Add after the certification section header
                updated_markdown = updated_markdown.replace(
                    "## Certification Details", 
                    "## Certification Details\n\nExpiration Date: " + exp_date_str
                )
            elif "Certification Level:" in updated_markdown:
                # Add after the certification level
                updated_markdown = updated_markdown.replace(
                    "Certification Level:", 
                    "Certification Level:\nExpiration Date: " + exp_date_str
                )
        
        security_profile["markdown_report"] = updated_markdown
        
        return security_profile
    
    def _extract_score(self, line: str) -> float:
        """Extract a numeric score from a line of text with more robust parsing"""
        import re
        
        # Try multiple patterns to extract scores
        patterns = [
            r"(\d+(?:\.\d+)?)\s*/\s*10",  # Format: 8/10 or 8.5/10
            r"score:?\s*(\d+(?:\.\d+)?)",  # Format: Score: 8 or Score: 8.5
            r":\s*(\d+(?:\.\d+)?)",        # Format: : 8 or : 8.5
            r"(\d+(?:\.\d+)?)"             # Just a number
        ]
        
        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                try:
                    score = float(match.group(1))
                    # Ensure it's in the range 1-10
                    if 0 <= score <= 10:
                        return score
                except (ValueError, IndexError):
                    pass
        
        # Default score if we can't extract one
        return 0
    
    def _store_security_profile(self, security_profile: dict[str, any]) -> ObjectId:
        """Store the security profile in the database"""
        # Ensure the evaluation_date is set
        if "evaluation_date" not in security_profile:
            security_profile["evaluation_date"] = datetime.datetime.now()
        
        # Ensure the certification expiration is set to 1 year from evaluation date
        if "certification" in security_profile and "expiration" not in security_profile["certification"]:
            security_profile["certification"]["expiration"] = security_profile["evaluation_date"] + datetime.timedelta(days=365)
        
        # Check if a profile already exists for this repository
        existing_profile = db.security_profiles.find_one({"repo_id": security_profile["repo_id"]})
        
        if existing_profile:
            # Update existing profile
            db.security_profiles.update_one(
                {"_id": existing_profile["_id"]},
                {"$set": security_profile}
            )
            return existing_profile["_id"]
        else:
            # Insert new profile
            result = db.security_profiles.insert_one(security_profile)
            return result.inserted_id
    
    def _update_repository_certification(self, repo_id: ObjectId, certification_level: str, security_score: float) -> None:
        """Update the certification level and security score in the repository record"""
        db.repositories.update_one(
            {"_id": repo_id},
            {"$set": {
                "certification_level": certification_level,
                "security_score": security_score
            }}
        )
        
        # Add entry to certification history
        db.certification_history.insert_one({
            "repo_id": repo_id,
            "date": datetime.datetime.now(),
            "level": certification_level,
            "evaluator": "MCP Security Analysis Agent",
            "notes": f"Automated security analysis with score {security_score}/10"
        })


def analyze_github_repository(repo_url: str, llm_api_key: str, llm_endpoint: str) -> dict[str, any]:
    """
    Analyze a GitHub repository for MCP security
    
    Args:
        repo_url: URL of the GitHub repository
        llm_api_key: API key for the LLM service
        llm_endpoint: Endpoint URL for the LLM service
        
    Returns:
        Dictionary with analysis results
    """
    agent = MCPAnalysisAgent(llm_api_key, llm_endpoint)
    return agent.analyze_repository(repo_url)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Analyze MCP server security")
    parser.add_argument("repo_url", help="URL of the GitHub repository")
    
    args = parser.parse_args()
    
    # Create an instance of the analysis agent
    # This will use the LLM factory with the configured provider (Ollama)
    agent = MCPAnalysisAgent()
    
    # Run analysis
    try:
        result = agent.analyze_repository(args.repo_url)
        print(f"=== Analysis Results ===")
        print(f"Repository ID: {result['repo_id']}")
        print(f"Profile ID: {result['profile_id']}")
        print(f"Certification Level: {result['certification_level']}")
        print(f"Security Score: {result['security_score']}/10")
    except Exception as e:
        print(f"Error analyzing repository: {str(e)}")
        import traceback
        traceback.print_exc()
        exit(1)