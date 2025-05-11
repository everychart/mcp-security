from typing import Dict, Any
import os
import time
import random

def get_llm_client(provider: str, config: Dict[str, Any]):
    """
    Factory function to get the appropriate LLM client
    
    Args:
        provider: The LLM provider (anthropic, gemini, etc.)
        config: Configuration dictionary
        
    Returns:
        An LLM client instance
    """
    # Try the specified provider first
    if provider == "anthropic":
        client = get_anthropic_client(config)
    elif provider == "gemini":
        client = get_gemini_client(config)
    else:
        # Default to Anthropic if provider not recognized
        client = get_anthropic_client(config)
    
    # If we got a dummy client (API key missing), try fallback providers
    if isinstance(client, DummyClient) and "FALLBACK_PROVIDERS" in config:
        for fallback_provider in config["FALLBACK_PROVIDERS"]:
            print(f"Trying fallback provider: {fallback_provider}")
            if fallback_provider == "anthropic":
                fallback_client = get_anthropic_client(config)
            elif fallback_provider == "gemini":
                fallback_client = get_gemini_client(config)
            
            # If we got a real client, use it
            if not isinstance(fallback_client, DummyClient):
                return fallback_client
    
    return client
    
def get_anthropic_client(config):
    """Get Anthropic Claude client"""
    import anthropic
    print(f"Anthropic SDK version: {anthropic.__version__}")
    
    # Get API key from environment or config
    api_key = os.environ.get("ANTHROPIC_API_KEY") or config.get("ANTHROPIC_API_KEY")
    model = config.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20240620")
    
    print(f"Initializing Anthropic client with model: {model}")
    print(f"API key exists: {bool(api_key)}")
    print(f"API key length: {len(api_key) if api_key else 0}")
    
    if not api_key:
        print("WARNING: No API key found for Anthropic")
        # Return a dummy client that returns error messages
        return DummyClient("No API key found for Anthropic")
    
    # Return a direct API client that doesn't rely on SDK structure
    return DirectAnthropicClient(api_key, model)

def get_gemini_client(config):
    """Get Google Gemini client"""
    try:
        # Get API key from environment or config
        api_key = os.environ.get("GEMINI_API_KEY") or config.get("GEMINI_API_KEY")
        model = config.get("GEMINI_MODEL", "gemini-1.5-flash")
        
        print(f"Initializing Gemini client with model: {model}")
        print(f"API key exists: {bool(api_key)}")
        print(f"API key length: {len(api_key) if api_key else 0}")
        
        if not api_key:
            print("WARNING: No API key found for Gemini")
            # Return a dummy client that returns error messages
            return DummyClient("No API key found for Gemini")
        
        # Return a direct API client
        return DirectGeminiClient(api_key, model)
    except Exception as e:
        print(f"Error initializing Gemini client: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return DummyClient(f"Failed to initialize Gemini client: {str(e)}")

class DirectAnthropicClient:
    def __init__(self, api_key, model):
        self.api_key = api_key
        self.model = model
        self.provider = "anthropic"
        self.max_retries = 3
        self.retry_delay = 5  # seconds
    
    def generate_completion(self, prompt, system_prompt=None, temperature=0.7):
        """Generate completion using direct API calls to Anthropic with retry logic"""
        for attempt in range(self.max_retries):
            try:
                import requests
                import json
                
                print(f"Calling Anthropic API with model: {self.model} (attempt {attempt+1}/{self.max_retries})")
                
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
                    
                    # Check if it's an overloaded error
                    if response.status_code == 529 or "overloaded" in response.text.lower():
                        if attempt < self.max_retries - 1:
                            # Add jitter to retry delay
                            jitter = random.uniform(0.5, 1.5)
                            wait_time = self.retry_delay * (2 ** attempt) * jitter
                            print(f"Anthropic API overloaded. Retrying in {wait_time:.1f} seconds...")
                            time.sleep(wait_time)
                            continue
                        else:
                            return f"ERROR: Anthropic API overloaded after {self.max_retries} attempts. Please try again later."
                    
                    return f"ERROR: API returned status code {response.status_code}: {response.text}"
                
                # Parse the response
                result = response.json()
                return result["content"][0]["text"]
                
            except Exception as e:
                print(f"Exception when calling Claude API: {str(e)}")
                import traceback
                print(f"Detailed error: {traceback.format_exc()}")
                
                if attempt < self.max_retries - 1:
                    # Add jitter to retry delay
                    jitter = random.uniform(0.5, 1.5)
                    wait_time = self.retry_delay * (2 ** attempt) * jitter
                    print(f"Error calling Anthropic API. Retrying in {wait_time:.1f} seconds...")
                    time.sleep(wait_time)
                else:
                    return f"ERROR: Failed to generate completion with Anthropic API. Error: {str(e)}"

class DirectGeminiClient:
    def __init__(self, api_key, model):
        self.api_key = api_key
        self.model = model
        self.provider = "gemini"
        self.max_retries = 3
        self.retry_delay = 3  # seconds
    
    def generate_completion(self, prompt, system_prompt=None, temperature=0.7):
        """Generate completion using direct API calls to Google Gemini with retry logic"""
        for attempt in range(self.max_retries):
            try:
                import requests
                import json
                
                print(f"Calling Gemini API with model: {self.model} (attempt {attempt+1}/{self.max_retries})")
                
                # Prepare the prompt with system prompt if provided
                if system_prompt:
                    full_prompt = f"{system_prompt}\n\n{prompt}"
                else:
                    full_prompt = prompt
                
                # Prepare the data
                data = {
                    "contents": [
                        {
                            "parts": [
                                {"text": full_prompt}
                            ]
                        }
                    ],
                    "generationConfig": {
                        "temperature": temperature,
                        "maxOutputTokens": 4000,
                        "topP": 0.95
                    }
                }
                
                # Make the API call
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
                response = requests.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(data)
                )
                
                # Check for errors
                if response.status_code != 200:
                    print(f"API error: {response.status_code} - {response.text}")
                    
                    if attempt < self.max_retries - 1:
                        # Add jitter to retry delay
                        jitter = random.uniform(0.5, 1.5)
                        wait_time = self.retry_delay * (2 ** attempt) * jitter
                        print(f"Gemini API error. Retrying in {wait_time:.1f} seconds...")
                        time.sleep(wait_time)
                        continue
                    else:
                        return f"ERROR: API returned status code {response.status_code}: {response.text}"
                
                # Parse the response
                result = response.json()
                
                # Extract the text from the response
                if "candidates" in result and len(result["candidates"]) > 0:
                    if "content" in result["candidates"][0]:
                        content = result["candidates"][0]["content"]
                        if "parts" in content and len(content["parts"]) > 0:
                            return content["parts"][0]["text"]
                
                # If we couldn't extract the text, return an error
                return f"ERROR: Could not extract text from Gemini API response: {result}"
                
            except Exception as e:
                print(f"Exception when calling Gemini API: {str(e)}")
                import traceback
                print(f"Detailed error: {traceback.format_exc()}")
                
                if attempt < self.max_retries - 1:
                    # Add jitter to retry delay
                    jitter = random.uniform(0.5, 1.5)
                    wait_time = self.retry_delay * (2 ** attempt) * jitter
                    print(f"Error calling Gemini API. Retrying in {wait_time:.1f} seconds...")
                    time.sleep(wait_time)
                else:
                    return f"ERROR: Failed to generate completion with Gemini API. Error: {str(e)}"

class DummyClient:
    """A dummy client that returns error messages when the real client can't be initialized"""
    def __init__(self, error_message="Could not initialize LLM client. Please check your API key and configuration."):
        self.error_message = error_message
        self.provider = "dummy"
    
    def generate_completion(self, prompt, system_prompt=None, temperature=0.7):
        return f"ERROR: {self.error_message}"