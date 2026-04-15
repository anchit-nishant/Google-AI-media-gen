import os
import json
import requests
import sys
from typing import Dict, Any, List, Optional

# Assuming Veo2API is the source of _get_access_token
from apis.veo2_api import Veo2API
import config.config as config

# Initialize Veo2API client to get access token
# This instance is used solely for authentication purposes.
_veo2_client_for_auth = Veo2API(config.PROJECT_ID)

def generate_third_party_chat_response(
    model_id: str,
    prompt: str,
    system_instructions: Optional[str] = None,
    temperature: float = 1.0,
    max_tokens: int = 1024,
    project_id: str = config.PROJECT_ID,
    location_id: str = "global" # Anthropic models are typically global
) -> Dict[str, Any]:
    """
    Generates a chat response from a third-party model (e.g., Anthropic Claude)
    on Vertex AI, handling streaming responses.

    Args:
        model_id: The ID of the third-party model (e.g., "claude-sonnet-4-6").
        prompt: The user's text prompt.
        system_instructions: Optional system-level instructions for the model.
        temperature: The temperature for the generation.
        max_tokens: The maximum number of tokens in the response.
        project_id: Your Google Cloud Project ID.
        location_id: The Vertex AI location for the model.

    Returns:
        A dictionary containing the response text and usage metadata.
    """
    try:
        print(f"Starting chat generation with 3P model: {model_id}")

        access_token = _veo2_client_for_auth._get_access_token()

        messages = []
        if system_instructions:
            # Anthropic models typically handle system instructions as a top-level parameter
            # or as a first user message. For streamRawPredict, it's usually part of the
            # 'messages' array. Let's put it as a user message followed by an assistant ack.
            messages.append({"role": "user", "content": [{"type": "text", "text": system_instructions}]})
            messages.append({"role": "assistant", "content": [{"type": "text", "text": "Okay, I understand."}]})
        
        messages.append({"role": "user", "content": [{"type": "text", "text": prompt}]})

        request_body = {
            "anthropic_version": "vertex-2023-10-16",
            "stream": True, # Set to True for streaming
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages
        }

        publisher = "anthropic"

        endpoint = "aiplatform.googleapis.com"
        url = (f"https://{endpoint}/v1/projects/{project_id}/locations/{location_id}/"
               f"publishers/{publisher}/models/{model_id}:streamRawPredict")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=utf-8"
        }

        print(f"Sending streaming request to 3P API: {url}")
        print(f"Request body: {json.dumps(request_body, indent=2)}")

        response_text = ""
        input_tokens = 0
        output_tokens = 0

        # Use stream=True for requests.post to handle chunked responses
        with requests.post(url, headers=headers, json=request_body, stream=True) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    if decoded_line.startswith("data: "):
                        try:
                            event_data = json.loads(decoded_line[len("data: "):])

                            if event_data.get('type') == 'content_block_delta':
                                if event_data['delta'].get('type') == 'text_delta':
                                    response_text += event_data['delta']['text']
                            elif event_data.get('type') == 'message_start':
                                if 'usage' in event_data['message']:
                                    input_tokens = event_data['message']['usage'].get('input_tokens', 0)
                            elif event_data.get('type') == 'message_delta':
                                if 'usage' in event_data:
                                    output_tokens += event_data['usage'].get('output_tokens', 0)
                            elif event_data.get('type') == 'message_end':
                                if 'usage' in event_data['message']:
                                    input_tokens = event_data['message']['usage'].get('input_tokens', input_tokens)
                                    output_tokens = event_data['message']['usage'].get('output_tokens', output_tokens)

                        except json.JSONDecodeError:
                            print(f"Could not decode JSON from line: {decoded_line}", file=sys.stderr)
                        except KeyError as ke:
                            print(f"KeyError in parsing event data: {ke} in {event_data}", file=sys.stderr)

        usage_metadata = {
            'promptTokenCount': input_tokens,
            'candidatesTokenCount': output_tokens,
            'totalTokenCount': input_tokens + output_tokens
        }
        
        print(f"✅ Extracted text from 3P model: \"{response_text[:100]}...\"")
        print(f"✅ Extracted usage metadata: {usage_metadata}")

        return {
            "text": response_text.strip(),
            "citations": [],
            "usage_metadata": usage_metadata
        }

    except requests.exceptions.HTTPError as http_err:
        error_msg = f"HTTP error occurred: {http_err} - {http_err.response.text}"
        print(f"❌ {error_msg}", file=sys.stderr)
        raise Exception(error_msg)
    except Exception as e:
        error_msg = f"Failed to generate 3P chat response: {str(e)}"
        print(f"❌ {error_msg}", file=sys.stderr)
        raise Exception(error_msg)