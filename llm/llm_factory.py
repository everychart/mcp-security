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
    try:
        from anthropic import Anthropic
        import anthropic
        
        # Print version for debugging
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
        
        client = Anthropic(api_key=api_key)
        return AnthropicClient(client, model)
    except Exception as e:
        print(f"Error initializing Anthropic client: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return DummyClient(f"Failed to initialize Anthropic client: {str(e)}")

def get_gemini_client(config):
    """Get Google Gemini client"""
    try:
        import google.generativeai as genai
        
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
        
        # Configure the Gemini API
        genai.configure(api_key=api_key)
        
        return GeminiClient(model)
    except Exception as e:
        print(f"Error initializing Gemini client: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return DummyClient(f"Failed to initialize Gemini client: {str(e)}")

class AnthropicClient:
    def __init__(self, client, model):
        self.client = client
        self.model = model
        self.provider = "anthropic"
        self.max_retries = 3
        self.retry_delay = 5  # seconds
    
    def generate_completion(self, prompt, system_prompt=None, temperature=0.7):
        """Generate completion using Anthropic Claude with retry logic"""
        for attempt in range(self.max_retries):
            try:
                # Create the messages array with the user prompt
                messages = [{"role": "user", "content": prompt}]
                
                # Prepare the API call parameters
                params = {
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": 4000,
                    "temperature": temperature
                }
                
                # Add system prompt if provided
                if system_prompt:
                    params["system"] = system_prompt
                
                # Call the API
                print(f"Calling Anthropic API with model: {self.model} (attempt {attempt+1}/{self.max_retries})")
                response = self.client.messages.create(**params)
                
                # Extract the response text
                return response.content[0].text
                
            except Exception as e:
                print(f"Exception when calling Claude API: {str(e)}")
                
                # Check if it's an overloaded error
                if "overloaded" in str(e).lower() or "529" in str(e):
                    if attempt < self.max_retries - 1:
                        # Add jitter to retry delay to prevent thundering herd
                        jitter = random.uniform(0.5, 1.5)
                        wait_time = self.retry_delay * (2 ** attempt) * jitter
                        print(f"Anthropic API overloaded. Retrying in {wait_time:.1f} seconds...")
                        time.sleep(wait_time)
                    else:
                        print("Max retries exceeded for Anthropic API")
                        return f"ERROR: Anthropic API overloaded after {self.max_retries} attempts. Please try again later."
                else:
                    # For other errors, don't retry
                    return f"ERROR: Failed to generate completion with Anthropic API. Error: {str(e)}"

class GeminiClient:
    def __init__(self, model):
        import google.generativeai as genai
        self.model_name = model
        self.model = genai.GenerativeModel(model_name=model)
        self.provider = "gemini"
        self.max_retries = 3
        self.retry_delay = 3  # seconds
    
    def generate_completion(self, prompt, system_prompt=None, temperature=0.7):
        """Generate completion using Google Gemini with retry logic"""
        for attempt in range(self.max_retries):
            try:
                # Configure generation parameters
                generation_config = {
                    "temperature": temperature,
                    "max_output_tokens": 4000,
                    "top_p": 0.95,
                }
                
                # Prepare the prompt with system prompt if provided
                if system_prompt:
                    full_prompt = f"{system_prompt}\n\n{prompt}"
                else:
                    full_prompt = prompt
                
                # Generate the response
                print(f"Calling Gemini API with model: {self.model_name} (attempt {attempt+1}/{self.max_retries})")
                response = self.model.generate_content(
                    full_prompt,
                    generation_config=generation_config
                )
                
                # Extract and return the text
                return response.text
                
            except Exception as e:
                print(f"Exception when calling Gemini API: {str(e)}")
                
                if attempt < self.max_retries - 1:
                    # Add jitter to retry delay
                    jitter = random.uniform(0.5, 1.5)
                    wait_time = self.retry_delay * (2 ** attempt) * jitter
                    print(f"Gemini API error. Retrying in {wait_time:.1f} seconds...")
                    time.sleep(wait_time)
                else:
                    print("Max retries exceeded for Gemini API")
                    return f"ERROR: Failed to generate completion with Gemini API after {self.max_retries} attempts. Error: {str(e)}"

class DummyClient:
    """A dummy client that returns error messages when the real client can't be initialized"""
    def __init__(self, error_message="Could not initialize LLM client. Please check your API key and configuration."):
        self.error_message = error_message
        self.provider = "dummy"
    
    def generate_completion(self, prompt, system_prompt=None, temperature=0.7):
        return f"ERROR: {self.error_message}"