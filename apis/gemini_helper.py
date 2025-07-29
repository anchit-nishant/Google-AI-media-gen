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
        
        # Encode the image
        encoded_image = encode_image_as_base64(image)
        
        # Create image part from encoded image
        print("Creating image part for Gemini request...")
        image_part = types.Part.from_bytes(
            data=base64.b64decode(encoded_image),
            mime_type="image/jpeg",
        )
        
        # Get the instructions text
        instructions_text = custom_instructions or config.DEFAULT_GEMINI_INSTRUCTIONS
        print(f"Using instructions: {instructions_text[:50]}...")
        
        # Create content for the model
        contents = [
            types.Content(
                role="user",
                parts=[
                    image_part,
                    types.Part.from_text(text=instructions_text)
                ]
            )
        ]
        
        # Set generation configuration
        print(f"Configuring Gemini with model: {config.GEMINI_MODEL_NAME}")
        generate_content_config = types.GenerateContentConfig(
            temperature=0.2,
            top_p=0.8,
            seed=0,
            max_output_tokens=2048,
            response_modalities=["TEXT"],
            safety_settings=[
                types.SafetySetting(
                    category="HARM_CATEGORY_HATE_SPEECH",
                    threshold="OFF"
                ),
                types.SafetySetting(
                    category="HARM_CATEGORY_DANGEROUS_CONTENT",
                    threshold="OFF"
                ),
                types.SafetySetting(
                    category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    threshold="OFF"
                ),
                types.SafetySetting(
                    category="HARM_CATEGORY_HARASSMENT",
                    threshold="OFF"
                )
            ],
        )
        
        # Generate content
        print("Sending request to Gemini API...")
        response = client.models.generate_content(
            model=config.GEMINI_MODEL_NAME,
            contents=contents,
            config=generate_content_config,
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