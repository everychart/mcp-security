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
    from anthropic import Anthropic
    import anthropic
    
    # Print version for debugging
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
    
    try:
        client = Anthropic(api_key=api_key)
        # Check what attributes the client has
        print(f"Client attributes: {dir(client)}")
        return AnthropicClient(client, model)
    except Exception as e:
        print(f"Error initializing Anthropic client: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return DummyClient()

class AnthropicClient:
    def __init__(self, client, model):
        self.client = client
        self.model = model
        # Check if we're using the new API
        self.has_messages_api = hasattr(self.client, 'messages')
        print(f"Client has messages API: {self.has_messages_api}")
    
    def generate_completion(self, prompt, system_prompt=None, temperature=0.7):
        """Generate completion using Anthropic Claude"""
        try:
            # Create the messages array with the user prompt
            print(f"Calling Anthropic API with model: {self.model}")
            
            if self.has_messages_api:
                # New API (v0.5.0+)
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
                response = self.client.messages.create(**params)
                
                # Extract the response text
                return response.content[0].text
            else:
                # Old API (pre v0.5.0)
                print("Using legacy Anthropic API")
                prompt_text = f"\n\nHuman: {prompt}\n\nAssistant:"
                
                # Check if completions is available
                if hasattr(self.client, 'completions'):
                    response = self.client.completions.create(
                        model=self.model,
                        prompt=prompt_text,
                        max_tokens_to_sample=4000,
                        temperature=temperature
                    )
                    return response.completion
                else:
                    # Direct API call as fallback
                    print("Using direct completion method")
                    response = self.client.completion(
                        model=self.model,
                        prompt=prompt_text,
                        max_tokens_to_sample=4000,
                        temperature=temperature
                    )
                    return response.completion
            
        except Exception as e:
            print(f"Exception when calling Claude API: {str(e)}")
            # Print more detailed error information
            if hasattr(e, 'status_code'):
                print(f"Status code: {e.status_code}")
            if hasattr(e, 'response') and hasattr(e.response, 'text'):
                print(f"Response text: {e.response.text}")
            
            import traceback
            print(f"Detailed error: {traceback.format_exc()}")
            
            # Return error message
            return f"ERROR: Failed to generate completion with Anthropic API. Error: {str(e)}"

class DummyClient:
    """A dummy client that returns error messages when the real client can't be initialized"""
    def generate_completion(self, prompt, system_prompt=None, temperature=0.7):
        return "ERROR: Could not initialize Anthropic client. Please check your API key and configuration."