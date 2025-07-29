#!/usr/bin/env python3
"""
History Manager - Module for uploading history artifacts (e.g., source images)
to Google Cloud Storage.
"""
import os
import io
import time
import pandas as pd
from datetime import datetime
from google.cloud import storage
from google.cloud.exceptions import NotFound
import tempfile
from PIL import Image

import config.config as config

# Initialize the Google Cloud Storage client
try:
    storage_client = storage.Client()
except Exception as e:
    print(f"⚠️ Warning: Failed to initialize Google Cloud Storage client. History tracking may not work: {str(e)}")
    storage_client = None

def upload_image_to_history(image, image_name=None):
    """
    Uploads an image to the history folder in GCS.
    
    Args:
        image (PIL.Image): Image to upload
        image_name (str, optional): Name for the image, if not provided a timestamp will be used
        
    Returns:
        str: GCS URI of the uploaded image
    """
    if storage_client is None:
        raise Exception("Google Cloud Storage client not initialized")
    
    # Parse the storage URI to get bucket name and folder path
    bucket_name, history_folder = _parse_storage_uri(config.STORAGE_URI)
    
    # Get the bucket
    bucket = storage_client.bucket(bucket_name)
    
    # Generate a filename with timestamp if not provided
    if not image_name:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        image_name = f"input_{timestamp}.jpg"
    
    # Generate the full path for the image
    image_path = os.path.join(history_folder.rstrip('/'), config.HISTORY_FOLDER, 'images', image_name).lstrip('/')
    
    # Prepare the image for upload
    with tempfile.NamedTemporaryFile(suffix='.jpg') as tmp:
        # Convert RGBA to RGB if needed to ensure JPEG compatibility
        if image.mode == 'RGBA':
            # Create a white background
            background = Image.new('RGB', image.size, (255, 255, 255))
            # Paste the image on the background using alpha channel
            background.paste(image, mask=image.split()[3])  # 3 is the alpha channel
            # Save the RGB image
            background.save(tmp.name, format='JPEG')
        else:
            # For RGB and other modes compatible with JPEG
            image.save(tmp.name, format='JPEG')
        
        # Upload the image
        blob = bucket.blob(image_path)
        blob.upload_from_filename(tmp.name, content_type='image/jpeg')
    
    # Return the GCS URI
    return f"gs://{bucket_name}/{image_path}"

def _parse_storage_uri(uri):
    """
    Parse a Google Cloud Storage URI to extract bucket name and folder path.
    
    Args:
        uri (str): GCS URI in the format gs://bucket/folder
        
    Returns:
        tuple: (bucket_name, folder_path)
    """
    # Remove gs:// prefix
    if uri.startswith('gs://'):
        uri = uri[5:]
    
    # Split into bucket and folder path
    parts = uri.split('/', 1)
    bucket_name = parts[0]
    folder_path = parts[1] if len(parts) > 1 else ''
    
    return bucket_name, folder_path 