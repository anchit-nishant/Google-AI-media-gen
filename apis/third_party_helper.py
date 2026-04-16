import os
import json
import requests
import sys
import time
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
    on Vertex AI, handling streaming responses and calculating latency.

    Args:
        model_id: The ID of the third-party model (e.g., "claude-sonnet-4-6").
        prompt: The user's text prompt.
        system_instructions: Optional system-level instructions for the model.
        temperature: The temperature for the generation.
        max_tokens: The maximum number of tokens in the response.
        project_id: Your Google Cloud Project ID.
        location_id: The Vertex AI location for the model.

    Returns:
        A dictionary containing the response text, usage metadata, and latency.
    """
    start_time = time.time()
    try:
        print(f"Starting chat generation with 3P model: {model_id}")

        access_token = _veo2_client_for_auth._get_access_token()

        messages = []
        if system_instructions:
            messages.append({"role": "user", "content": [{"type": "text", "text": system_instructions}]})
            messages.append({"role": "assistant", "content": [{"type": "text", "text": "Okay, I understand."}]})
        
        messages.append({"role": "user", "content": [{"type": "text", "text": prompt}]})

        request_body = {
            "anthropic_version": "vertex-2023-10-16",
            "stream": True,
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

        response_text = ""
        input_tokens = 0
        output_tokens = 0
        raw_response_content = ""

        with requests.post(url, headers=headers, json=request_body, stream=True) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    raw_response_content += decoded_line + "\n"
                    if decoded_line.startswith("data: "):
                        try:
                            event_data = json.loads(decoded_line[len("data: "):])
                            if event_data.get('type') == 'content_block_delta' and event_data['delta'].get('type') == 'text_delta':
                                response_text += event_data['delta']['text']
                            elif event_data.get('type') == 'message_start' and 'usage' in event_data['message']:
                                input_tokens = event_data['message']['usage'].get('input_tokens', 0)
                            elif event_data.get('type') == 'message_delta' and 'usage' in event_data:
                                output_tokens += event_data['usage'].get('output_tokens', 0)
                        except (json.JSONDecodeError, KeyError) as e:
                            print(f"Error parsing stream event: {e} in line: {decoded_line}", file=sys.stderr)

        print("--- 3P Model Raw Response ---")
        print(raw_response_content)
        print("-----------------------------")

        usage_metadata = {
            'promptTokenCount': input_tokens,
            'candidatesTokenCount': output_tokens,
            'totalTokenCount': input_tokens + output_tokens
        }
        
        latency = round(time.time() - start_time, 2)
        print(f"✅ 3P model generation took {latency} seconds.")

        return {
            "text": response_text.strip(),
            "citations": [],
            "usage_metadata": usage_metadata,
            "latency_seconds": latency
        }

    except requests.exceptions.HTTPError as http_err:
        error_msg = f"HTTP error occurred: {http_err} - {http_err.response.text}"
        print(f"❌ {error_msg}", file=sys.stderr)
        raise Exception(error_msg)
    except Exception as e:
        error_msg = f"Failed to generate 3P chat response: {str(e)}"
        print(f"❌ {error_msg}", file=sys.stderr)
        raise Exception(error_msg)