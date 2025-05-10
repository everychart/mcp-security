from typing import Dict, Any
import os

def get_llm_client(provider: str, config: Dict[str, Any]):
    """
    Factory function to get the appropriate LLM client
    
    Args:
        provider: The LLM provider (ollama, openai, etc.)
        config: Configuration dictionary
        
    Returns:
        An LLM client instance
    """
    # Ignore the provider parameter and always use Anthropic
    return get_anthropic_client(config)
    
def get_anthropic_client(config):
    """Get Anthropic Claude client"""
    import anthropic
    print(f"Anthropic SDK version: {anthropic.__version__}")
    
    # Get API key from environment or config
    api_key = os.environ.get("ANTHROPIC_API_KEY") or config.get("ANTHROPIC_API_KEY")
    model = config.get("LLM_MODEL", "claude-3-5-sonnet-20240620")
    
    print(f"Initializing Anthropic client with model: {model}")
    print(f"API key exists: {bool(api_key)}")
    print(f"API key length: {len(api_key) if api_key else 0}")
    
    if not api_key:
        print("WARNING: No API key found for Anthropic")
        # Return a dummy client that returns error messages
        return DummyClient()
    
    # Return a direct API client that doesn't rely on SDK structure
    return DirectAnthropicClient(api_key, model)

class DirectAnthropicClient:
    def __init__(self, api_key, model):
        self.api_key = api_key
        self.model = model
    
    def generate_completion(self, prompt, system_prompt=None, temperature=0.7):
        """Generate completion using direct API calls to Anthropic"""
        try:
            import requests
            import json
            
            print(f"Calling Anthropic API with model: {self.model}")
            
            # Prepare the request
            headers = {
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01"
            }
            
            # Prepare the data
            data = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 4000,
                "temperature": temperature
            }
            
            # Add system prompt if provided
            if system_prompt:
                data["system"] = system_prompt
            
            # Make the API call
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                data=json.dumps(data)
            )
            
            # Check for errors
            if response.status_code != 200:
                print(f"API error: {response.status_code} - {response.text}")
                return f"ERROR: API returned status code {response.status_code}: {response.text}"
            
            # Parse the response
            result = response.json()
            return result["content"][0]["text"]
            
        except Exception as e:
            print(f"Exception when calling Claude API: {str(e)}")
            import traceback
            print(f"Detailed error: {traceback.format_exc()}")
            return f"ERROR: Failed to generate completion with Anthropic API. Error: {str(e)}"

class DummyClient:
    """A dummy client that returns error messages when the real client can't be initialized"""
    def generate_completion(self, prompt, system_prompt=None, temperature=0.7):
        return "ERROR: Could not initialize Anthropic client. Please check your API key and configuration."