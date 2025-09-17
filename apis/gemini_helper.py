#!/usr/bin/env python3
"""
Gemini Helper - Module for generating image-to-video prompts using Google's Gemini AI.
Provides functions to analyze images and generate optimized prompts for video generation.
"""
import base64
import io
import sys
from google import genai
from google.genai import types

import config.config as config

def init_gemini_client():
    """
    Initialize and return a Gemini client.
    
    Returns:
        google.genai.Client: Initialized Gemini client
    
    Raises:
        ImportError: If the google.genai package is not installed
        Exception: If initialization fails
    """
    print("Initializing Gemini client...")
    try:
        # Create the Gemini client
        client = genai.Client(
            vertexai=True,
            project=config.GEMINI_PROJECT_ID,
            location=config.GEMINI_LOCATION,
        )
        
        print(f"✅ Gemini client initialized with project: {config.GEMINI_PROJECT_ID}, location: {config.GEMINI_LOCATION}")
        return client
    except ImportError:
        print("❌ Failed to import Google AI libraries", file=sys.stderr)
        raise ImportError(
            "The 'google.genai' package is not installed. "
            "Please make sure you have the correct version of the Google AI libraries."
        )
    except Exception as e:
        print(f"❌ Failed to initialize Gemini client: {str(e)}", file=sys.stderr)
        raise Exception(f"Failed to initialize Gemini client: {str(e)}")

def encode_image_as_base64(image):
    """
    Encode a PIL Image as a base64 string.
    
    Args:
        image (PIL.Image.Image): The PIL Image to encode
        
    Returns:
        str: Base64-encoded image data
    """
    print(f"Encoding image (format: {image.format}, mode: {image.mode}, size: {image.size})...")
    # Ensure image is in RGB mode
    if image.mode != 'RGB':
        print(f"Converting image from {image.mode} to RGB")
        image = image.convert('RGB')
    
    # Save image to bytes buffer
    buffer = io.BytesIO()
    image.save(buffer, format='JPEG')
    image_bytes = buffer.getvalue()
    
    # Encode as base64
    encoded_image = base64.b64encode(image_bytes).decode('utf-8')
    print(f"✅ Image encoded successfully (length: {len(encoded_image)} chars)")
    
    return encoded_image

def generate_prompt_from_image(image, custom_instructions=None):
    """
    Generate a text-to-video prompt based on the provided image.
    
    Args:
        image (PIL.Image.Image): The input image
        custom_instructions (str, optional): Custom instructions to guide the prompt generation
        
    Returns:
        str: Generated prompt suitable for video generation
    
    Raises:
        Exception: If prompt generation fails
    """
    try:
        print("Starting prompt generation from image...")
        # Initialize Gemini client
        client = init_gemini_client()
        
        # Get the instructions text
        instructions_text = custom_instructions or config.DEFAULT_GEMINI_INSTRUCTIONS
        print(f"Using instructions: {instructions_text[:50]}...")
        
        # The google-generativeai library can handle PIL Images directly.
        # We pass the instructions and the image as a simple list.
        contents = [
            instructions_text,
            image,
        ]

        # Generate content
        print("Sending request to Gemini API...")
        response = client.models.generate_content(
            model=config.GEMINI_MODEL_NAME,
            contents=contents,
        )
        print(response)

        # Extract and return the generated prompt
        if response.text:
            prompt = response.text.strip()
            print(f"✅ Received prompt from Gemini: \"{prompt[:100]}...\"")
            return prompt
        else:
            print("❌ Gemini API returned an empty response.")
            prompt = ""  # Or some other default value
        print(f"✅ Received prompt from Gemini: \"{prompt[:100]}...\"")
        
        # Enhance the prompt with additional details from config if specified
        if config.APPEND_DEFAULT_STYLE_TO_GEMINI_PROMPTS and config.DEFAULT_STYLE_PROMPT:
            print(f"Appending style prompt: {config.DEFAULT_STYLE_PROMPT}")
            prompt = f"{prompt}, {config.DEFAULT_STYLE_PROMPT}"
        
        # Print the final prompt
        print(f"Final prompt: \"{prompt}\"")
        return prompt
    
    except Exception as e:
        error_msg = f"Failed to generate prompt from image: {str(e)}"
        print(f"❌ {error_msg}", file=sys.stderr)
        raise Exception(error_msg) 

def generate_gemini_chat_response(model_name, prompt, uploaded_file=None, system_instructions=None, temperature=1.0, enable_grounding=False):
    """
    Generates a chat response from Gemini, handling multimodal inputs.

    Args:
        model_name (str): The name of the Gemini model to use.
        prompt (str): The user's text prompt.
        uploaded_file (UploadedFile, optional): A file uploaded by the user.
        system_instructions (str, optional): System-level instructions for the model.
        temperature (float): The temperature for the generation.
        enable_grounding (bool): Whether to enable Google Search grounding.

    Returns:
        str: The generated text response from the model.
    """
    try:
        print(f"Starting chat generation with model: {model_name}")
        # Initialize Gemini client using the older method for compatibility
        client = init_gemini_client()

        # The modern library usage prefers a simple list of content parts.
        # The client library handles the conversion to the correct Part types.
        contents = []
        if system_instructions:
            contents.append(system_instructions)
        contents.append(prompt)

        if uploaded_file:
            print(f"Processing uploaded file: {uploaded_file.name}")
            # The library expects a Part object for files. We create one from the
            # uploaded file's bytes and its MIME type.
            contents.append(
                types.Part.from_bytes(data=uploaded_file.getvalue(), mime_type=uploaded_file.type)
            )

        # Configure tools for grounding if enabled
        
        if enable_grounding: 
            tools = [
                types.Tool(google_search=types.GoogleSearch())
            ]
        else: 
            tools =  []
        
        print(f"DEBUG: Tools being passed to Gemini API: {tools}")


        # Configure safety settings
        safety_settings = [
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="OFF"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="OFF"),
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="OFF"),
        ]

        # For this client, generation_config, tools, and safety_settings are passed
        # within a single generation_config dictionary.
        generation_config = {
            "temperature": temperature,
            "top_p": 1,
            "max_output_tokens": 8192, # Using a more reasonable max for chat
            "safety_settings": safety_settings,
            "tools": tools,
        }

        # Generate content
        print("Sending request to Gemini API...")
        # Use the streaming version to get results incrementally
        response = client.models.generate_content(
            model=model_name,
            contents=contents,
            config=generation_config,
        )

        # Print the full API response to the terminal for inspection
        print("--- Full Gemini API Response ---")
        print(response)
        print("--------------------------------")

        # Process the response to extract text and citations
        response_text = response.text
        citations = []
        # The grounding metadata is located within the first candidate of the response.
        if response.candidates and hasattr(response.candidates[0], 'grounding_metadata') and response.candidates[0].grounding_metadata:
            citations = [
                {"title": chunk.web.title, "uri": chunk.web.uri}
                for chunk in response.candidates[0].grounding_metadata.grounding_chunks
                if hasattr(chunk, 'web') and hasattr(chunk.web, 'title') and hasattr(chunk.web, 'uri')
            ]

        print(f"✅ Extracted text: \"{response_text[:100]}...\"")
        print(f"✅ Extracted {len(citations)} citations.")
        return {"text": response_text.strip(), "citations": citations}

    except Exception as e:
        error_msg = f"Failed to generate chat response: {str(e)}"
        print(f"❌ {error_msg}", file=sys.stderr)
        raise Exception(error_msg)