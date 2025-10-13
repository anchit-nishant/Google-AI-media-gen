import base64
import json
import os
import shutil
import time
import re
import datetime
from typing import Dict, List, Optional, Union, Any
import requests
import google.auth
import google.auth.transport.requests
import streamlit as st
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request
from google.cloud import storage
from moviepy.editor import VideoFileClip, concatenate_videoclips, vfx

TEMP_DOWNLOAD_SUBDIR = "temp_gcs_downloads"

class Veo2API:
    """Client for Google's Veo 2.0 API for text-to-video and image-to-video generation."""

    def get_auth_headers() -> dict:
        """
        Authenticates with Google Cloud and returns authorization headers.
        Uses default credentials (e.g., GOOGLE_APPLICATION_CREDENTIALS, gcloud login, or VM service account).
        """
        credentials, project_id = google_auth_default()
        credentials.refresh(Request()) # Ensure credentials are fresh
        return {"Authorization": f"Bearer {credentials.token}", "Content-Type": "application/json"}

    def __init__(self, project_id: str, location: str = "us-central1"):
        """
        Initialize the Veo2 API client.

        Args:
            project_id: Your Google Cloud project ID
            location: API location (default: us-central1)
        """
        self.project_id = project_id
        self.location = location
        self.model_id = None #Will be selected during generation
        self.base_url = f"https://{location}-aiplatform.googleapis.com/v1"
        
    # def _get_access_token(self) -> str:
    #     """
    #     Get Google Cloud access token using gcloud CLI.
        
    #     Returns:
    #         str: Access token
    #     """
    #     import subprocess
        
    #     result = subprocess.run(
    #         ["gcloud", "auth", "print-access-token"], 
    #         stdout=subprocess.PIPE, 
    #         text=True
    #     )
    #     return result.stdout.strip()

    # Replaced the above access_token fetching function to run it from Cloud Run:
    def _get_access_token(self) -> str:
        """
        Get Google Cloud access token using the google-auth library.
        
        This method uses Application Default Credentials to automatically
        find credentials and is the recommended approach.
        
        Returns:
            str: Access token
        """
        # This is the core of the ADC strategy. It finds credentials automatically.
        credentials, project_id = google.auth.default(
            scopes=['https://www.googleapis.com/auth/cloud-platform']
        )
        
        # Create a transport request object to refresh the credentials.
        auth_req = google.auth.transport.requests.Request()
        
        # Refresh the credentials to ensure the token is valid.
        credentials.refresh(auth_req)
        
        # Return the access token.
        return credentials.token
    
    def generate_video(
        self,
        prompt: str,
        input_image: Optional[Dict] = None,
        aspect_ratio: str = "16:9",
        negative_prompt: Optional[str] = None,
        model: str = "veo-2.0-generate-001", #Add model parameter with default as veo2
        person_generation: Optional[str] = None,
        sample_count: int = 1,
        seed: Optional[int] = None,
        storage_uri: Optional[str] = None,
        duration_seconds: int = 8,
        enhance_prompt: bool = True
    ) -> Dict:
        """
        Generate a video using text and/or image prompts.
        
        Args:
            prompt: Text prompt to guide video generation
            input_image: Optional dictionary with image information, format:
                {'bytesBase64Encoded': str} or {'gcsUri': str}
                Must also include 'mimeType': str (e.g., 'image/jpeg')
            aspect_ratio: Aspect ratio of generated video ("16:9" or "9:16")
            negative_prompt: Text describing what to avoid in generation
            model: The veo model to use for generation, veo2 or veo3
            person_generation: Safety setting for people ("allow_adult" or "disallow")
            sample_count: Number of videos to generate (1-4)
            seed: Optional seed for deterministic generation (0-4294967295)
            storage_uri: GCS URI to store output videos (e.g., "gs://bucket/folder/")
            duration_seconds: Length of video in seconds (5-8)
            enhance_prompt: Whether to use Gemini to enhance the prompt
            
        Returns:
            Dict: Response containing operation name to poll for results
        """
        # Construct the request body
        instance = {
            "prompt": prompt,
        }
        
        # Add image if provided
        if input_image:
            instance["image"] = input_image
            
        # Construct parameters
        parameters = {
            "aspectRatio": aspect_ratio,
            "sampleCount": sample_count,
            "durationSeconds": duration_seconds,
            "enhancePrompt": enhance_prompt
        }
        
        # Add optional parameters if provided
        if negative_prompt:
            parameters["negativePrompt"] = negative_prompt
        if person_generation:
            parameters["personGeneration"] = person_generation
        if seed is not None:
            parameters["seed"] = seed
        if storage_uri:
            parameters["storageUri"] = storage_uri
            
        # Construct the full request
        request_body = {
            "instances": [instance],
            "parameters": parameters
        }
        
        # Make the API request
        self.model_id = model #set model id based on user selection

        url = f"{self.base_url}/projects/{self.project_id}/locations/{self.location}/publishers/google/models/{self.model_id}:predictLongRunning" #use instance variable
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json; charset=utf-8"
        }
        
        response = requests.post(url, headers=headers, json=request_body)
        return response.json()
    

    def poll_operation(self, operation_id: str) -> Dict:
        """
        Poll the status of a video generation operation.
        
        Args:
            operation_id: The operation ID from the generate_video response
            
        Returns:
            Dict: Operation status and results if complete
        """
        url = f"{self.base_url}/projects/{self.project_id}/locations/{self.location}/publishers/google/models/{self.model_id}:fetchPredictOperation"
        
        operation_name = f"projects/{self.project_id}/locations/{self.location}/publishers/google/models/{self.model_id}/operations/{operation_id}"
        request_body = {
            "operationName": operation_name
        }
        
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json; charset=utf-8"
        }
        
        response = requests.post(url, headers=headers, json=request_body)
        return response.json()
    
    def wait_for_operation(self, operation_id: str, poll_interval: int = 10, max_attempts: int = 30) -> Dict:
        """
        Wait for a video generation operation to complete.
        
        Args:
            operation_id: The operation ID from the generate_video response
            poll_interval: Seconds to wait between polling attempts
            max_attempts: Maximum number of polling attempts
            
        Returns:
            Dict: Operation results once complete
            
        Raises:
            TimeoutError: If operation doesn't complete within the allowed attempts
        """
        for attempt in range(max_attempts):
            response = self.poll_operation(operation_id)
            
            if response.get("done", False):
                return response
            
            print(f"Operation still in progress. Waiting {poll_interval} seconds...")
            time.sleep(poll_interval)
        
        raise TimeoutError(f"Operation did not complete after {max_attempts} polling attempts")
    
    def encode_image_file(self, image_path: str) -> Dict:
        """
        Encode an image file to base64 for use in the API.
        
        Args:
            image_path: Path to the image file
            
        Returns:
            Dict: Image information dictionary ready for the API
            
        Raises:
            ValueError: If image format is not supported or can't be determined
        """
        # Determine the MIME type based on file extension
        lower_path = image_path.lower()
        
        if lower_path.endswith((".jpg", ".jpeg")):
            mime_type = "image/jpeg"
        elif lower_path.endswith(".png"):
            mime_type = "image/png"
        elif lower_path.endswith(".webp"):
            # WebP is supported, but we'll check if we need to convert
            try:
                from PIL import Image
                # Open with PIL to verify it's a valid image
                with Image.open(image_path) as img:
                    # Use the actual format from PIL
                    if img.format == "WEBP":
                        mime_type = "image/webp"
                    else:
                        # If PIL detected a different format, use that
                        mime_type = f"image/{img.format.lower()}"
            except ImportError:
                # If PIL is not available, assume it's WebP based on extension
                mime_type = "image/webp"
            except Exception as e:
                raise ValueError(f"Failed to process WebP image: {str(e)}")
        else:
            # For other formats, try to detect using PIL if available
            try:
                from PIL import Image
                with Image.open(image_path) as img:
                    if img.format:
                        mime_type = f"image/{img.format.lower()}"
                    else:
                        raise ValueError(f"Unrecognized image format for file: {image_path}")
            except ImportError:
                raise ValueError(f"Unrecognized image extension for file: {image_path}. "
                               "Install Pillow package for better format detection.")
            except Exception as e:
                raise ValueError(f"Failed to determine image format: {str(e)}")
        
        # Read and encode the file
        try:
            with open(image_path, "rb") as image_file:
                encoded_image = base64.b64encode(image_file.read()).decode("utf-8")
                
            return {
                "bytesBase64Encoded": encoded_image,
                "mimeType": mime_type
            }
        except Exception as e:
            raise ValueError(f"Failed to encode image file: {str(e)}")
    
    def generate_public_url(self, gcs_uri: str) -> str:
        """
        Generate a public URL for accessing a video in a GCS bucket.
        This doesn't require pyopenssl but only works if the object is public.
        
        Args:
            gcs_uri: GCS URI (gs://bucket-name/path/to/file.mp4)
            
        Returns:
            str: Public URL that can be used to stream the video
        """
        # Parse the URI to extract bucket and object path
        if not gcs_uri.startswith("gs://"):
            raise ValueError("URI must start with gs://")
        
        # Remove gs:// prefix and split into bucket and object path
        path = gcs_uri[5:]
        bucket_name = path.split("/")[0]
        blob_name = "/".join(path.split("/")[1:])
        
        # Generate a direct public URL
        return f"https://storage.googleapis.com/{bucket_name}/{blob_name}"
    
    def generate_video_veo3(
        self,
        prompt: str,
        input_image: Optional[Dict] = None,
        aspect_ratio: str = "16:9",
        resolution: Optional[str] = "720p",
        generateAudio: str = "true",
        negative_prompt: Optional[str] = None,
        model: str = "veo-3.0-generate-preview", #Add model parameter with default as veo2
        person_generation: Optional[str] = None,
        sample_count: int = 1,
        seed: Optional[int] = None,
        storage_uri: Optional[str] = None,
        duration_seconds: int = 8,
        enhance_prompt: bool = True
    ) -> Dict:
        """
        Generate a video using text and/or image prompts.
        
        Args:
            prompt: Text prompt to guide video generation
            input_image: Optional dictionary with image information, format:
                {'bytesBase64Encoded': str} or {'gcsUri': str}
                Must also include 'mimeType': str (e.g., 'image/jpeg')
            aspect_ratio: Aspect ratio of generated video ("16:9" or "9:16")
            negative_prompt: Text describing what to avoid in generation
            model: The veo model to use for generation, veo2 or veo3
            person_generation: Safety setting for people ("allow_adult" or "disallow")
            sample_count: Number of videos to generate (1-4)
            seed: Optional seed for deterministic generation (0-4294967295)
            storage_uri: GCS URI to store output videos (e.g., "gs://bucket/folder/")
            duration_seconds: Length of video in seconds (5-8)
            enhance_prompt: Whether to use Gemini to enhance the prompt
            
        Returns:
            Dict: Response containing operation name to poll for results
        """
        # Construct the request body
        instance = {
            "prompt": prompt,
        }
        
        # Add image if provided
        if input_image:
            instance["image"] = input_image
            
        # Construct parameters
        parameters = {
            "aspectRatio": aspect_ratio,
            "sampleCount": sample_count,
            "durationSeconds": duration_seconds,
            "enhancePrompt": enhance_prompt,
            "resolution": resolution,
            "generateAudio": generateAudio,
        }
        
        # Add optional parameters if provided
        if negative_prompt:
            parameters["negativePrompt"] = negative_prompt
        if person_generation:
            parameters["personGeneration"] = person_generation
        if seed is not None:
            parameters["seed"] = seed
        if storage_uri:
            parameters["storageUri"] = storage_uri
            
        # Construct the full request
        request_body = {
            "instances": [instance],
            "parameters": parameters
        }
        
        # Make the API request
        self.model_id = model #set model id based on user selection

        url = f"{self.base_url}/projects/{self.project_id}/locations/{self.location}/publishers/google/models/{self.model_id}:predictLongRunning" #use instance variable
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json; charset=utf-8"
        }
        
        response = requests.post(url, headers=headers, json=request_body)
        return response.json()
    

    def poll_operation(self, operation_id: str) -> Dict:
        """
        Poll the status of a video generation operation.
        
        Args:
            operation_id: The operation ID from the generate_video response
            
        Returns:
            Dict: Operation status and results if complete
        """
        url = f"{self.base_url}/projects/{self.project_id}/locations/{self.location}/publishers/google/models/{self.model_id}:fetchPredictOperation"
        
        operation_name = f"projects/{self.project_id}/locations/{self.location}/publishers/google/models/{self.model_id}/operations/{operation_id}"
        request_body = {
            "operationName": operation_name
        }
        
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json; charset=utf-8"
        }
        
        response = requests.post(url, headers=headers, json=request_body)
        return response.json()
    
    def wait_for_operation(self, operation_id: str, poll_interval: int = 10, max_attempts: int = 30) -> Dict:
        """
        Wait for a video generation operation to complete.
        
        Args:
            operation_id: The operation ID from the generate_video response
            poll_interval: Seconds to wait between polling attempts
            max_attempts: Maximum number of polling attempts
            
        Returns:
            Dict: Operation results once complete
            
        Raises:
            TimeoutError: If operation doesn't complete within the allowed attempts
        """
        for attempt in range(max_attempts):
            response = self.poll_operation(operation_id)
            
            if response.get("done", False):
                return response
            
            print(f"Operation still in progress. Waiting {poll_interval} seconds...")
            time.sleep(poll_interval)
        
        raise TimeoutError(f"Operation did not complete after {max_attempts} polling attempts")
    
    def encode_image_file(self, image_path: str) -> Dict:
        """
        Encode an image file to base64 for use in the API.
        
        Args:
            image_path: Path to the image file
            
        Returns:
            Dict: Image information dictionary ready for the API
            
        Raises:
            ValueError: If image format is not supported or can't be determined
        """
        # Determine the MIME type based on file extension
        lower_path = image_path.lower()
        
        if lower_path.endswith((".jpg", ".jpeg")):
            mime_type = "image/jpeg"
        elif lower_path.endswith(".png"):
            mime_type = "image/png"
        elif lower_path.endswith(".webp"):
            # WebP is supported, but we'll check if we need to convert
            try:
                from PIL import Image
                # Open with PIL to verify it's a valid image
                with Image.open(image_path) as img:
                    # Use the actual format from PIL
                    if img.format == "WEBP":
                        mime_type = "image/webp"
                    else:
                        # If PIL detected a different format, use that
                        mime_type = f"image/{img.format.lower()}"
            except ImportError:
                # If PIL is not available, assume it's WebP based on extension
                mime_type = "image/webp"
            except Exception as e:
                raise ValueError(f"Failed to process WebP image: {str(e)}")
        else:
            # For other formats, try to detect using PIL if available
            try:
                from PIL import Image
                with Image.open(image_path) as img:
                    if img.format:
                        mime_type = f"image/{img.format.lower()}"
                    else:
                        raise ValueError(f"Unrecognized image format for file: {image_path}")
            except ImportError:
                raise ValueError(f"Unrecognized image extension for file: {image_path}. "
                               "Install Pillow package for better format detection.")
            except Exception as e:
                raise ValueError(f"Failed to determine image format: {str(e)}")
        
        # Read and encode the file
        try:
            with open(image_path, "rb") as image_file:
                encoded_image = base64.b64encode(image_file.read()).decode("utf-8")
                
            return {
                "bytesBase64Encoded": encoded_image,
                "mimeType": mime_type
            }
        except Exception as e:
            raise ValueError(f"Failed to encode image file: {str(e)}")
    
    def generate_public_url(self, gcs_uri: str) -> str:
        """
        Generate a public URL for accessing a video in a GCS bucket.
        This doesn't require pyopenssl but only works if the object is public.
        
        Args:
            gcs_uri: GCS URI (gs://bucket-name/path/to/file.mp4)
            
        Returns:
            str: Public URL that can be used to stream the video
        """
        # Parse the URI to extract bucket and object path
        if not gcs_uri.startswith("gs://"):
            raise ValueError("URI must start with gs://")
        
        # Remove gs:// prefix and split into bucket and object path
        path = gcs_uri[5:]
        bucket_name = path.split("/")[0]
        blob_name = "/".join(path.split("/")[1:])
        
        # Generate a direct public URL
        return f"https://storage.googleapis.com/{bucket_name}/{blob_name}"
    
    def generate_signed_url(self, gcs_uri: str, expiration_minutes: int = 60) -> str:
        """
        Generate a URL for accessing a video in a GCS bucket.
        Uses direct HTTP access through the authenticated gcloud credentials.
        
        Args:
            gcs_uri: GCS URI (gs://bucket-name/path/to/file.mp4)
            expiration_minutes: Number of minutes the URL should be valid for (ignored)
            
        Returns:
            str: URL that can be used to stream the video
        """
        # Parse the URI to extract bucket and object path
        if not gcs_uri.startswith("gs://"):
            raise ValueError("URI must start with gs://")
        
        # Remove gs:// prefix and split into bucket and object path
        path = gcs_uri[5:]
        bucket_name = path.split("/")[0]
        blob_name = "/".join(path.split("/")[1:])
        
        # Generate a direct URL using the authenticated gcloud session
        try:
            # Get access token from gcloud CLI
            access_token = self._get_access_token()
            
            # Create a directly accessible URL that includes the access token for authorization
            # This URL works with the current user's permissions without service accounts
            url = f"https://storage.googleapis.com/{bucket_name}/{blob_name}?access_token={access_token}"
            
            print(f"✅ Generated authenticated URL (valid as long as token is valid)")
            return url
        except Exception as e:
            print(f"the value of e is {e}")
            print(f"⚠️ Error generating authenticated URL: {str(e)}")
            
            # Alternative approach for media content
            try:
                # Try using medialink URL form
                url = f"https://storage.googleapis.com/download/storage/v1/b/{bucket_name}/o/{blob_name.replace('/', '%2F')}?alt=media&access_token={access_token}"
                print(f"✅ Generated alternative authenticated URL")
                return url
            except Exception as e:
                print(f"⚠️ Error generating alternative URL: {str(e)}")
            
            # Fallback to direct URL as last resort
            fallback_url = self.generate_public_url(gcs_uri)
            print(f"Using fallback direct URL (may require public access): {fallback_url}")
            return fallback_url
    
    def extract_video_uris(self, result: Dict) -> List[str]:
        """
        Extract video URIs from an API result in various possible formats.
        
        Args:
            result: API response from a completed operation
            
        Returns:
            List[str]: List of video URIs found in the response
        """
        video_uris = []
        
        # Try to extract from response
        if "response" in result:
            response_data = result["response"]
            
            # Format 1: generatedSamples.video.uri
            if "generatedSamples" in response_data:
                for sample in response_data["generatedSamples"]:
                    if "video" in sample and "uri" in sample["video"]:
                        video_uris.append(sample["video"]["uri"])
            
            # Format 2: videos.gcsUri
            elif "videos" in response_data:
                for video in response_data["videos"]:
                    if "gcsUri" in video:
                        video_uris.append(video["gcsUri"])
            
            # Format 3: videosBase64Encoded
            elif "videosBase64Encoded" in response_data:
                video_uris.append("[Base64 encoded video data available]")
            
            # Format 4: Try to find any URI-like strings in the response
            else:
                response_str = str(response_data)
                
                # Look for GCS URIs
                gcs_uris = re.findall(r'gs://[a-zA-Z0-9\-\_\.\/]+', response_str)
                if gcs_uris:
                    video_uris.extend(gcs_uris)
                
                # Look for HTTP/HTTPS URLs
                http_urls = re.findall(r'https?://[a-zA-Z0-9\-\_\.\/\%\&\=\?\:]+', response_str)
                if http_urls:
                    video_uris.extend(http_urls)
        
        return video_uris
    
    def interpolate_video_veo2(
        self,
        start_image_path: str,
        end_image_path: str,
        prompt_text: str,
        output_local_video_path: str,
        aspect_ratio: str,
        storage_uri: str = None,
        
    ) -> str | None:
        """
        Calls the Veo2 API to generate a video using interpolation from two frames.
        This function handles the long-running operation and returns the final API response.
        """
        print(f"Performing Veo 2 Interpolation: from '{os.path.basename(start_image_path)}' "
            f"to '{os.path.basename(end_image_path)}'")
        
        
        # --- 1. Authenticate and Get Access Token ---
        try:
            # Get application default credentials
            credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
            auth_req = google.auth.transport.requests.Request()
            credentials.refresh(auth_req)
            access_token = credentials.token
        except Exception as e:
            st.error(f"Could not get authentication credentials. Please ensure you are authenticated. Error: {e}")
            return

        # --- 2. Set Up API Endpoint and Headers ---
        # The model name is hardcoded to lyria-002 as per the response template.
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
            
        generated_videos_uri = None

        try:
            with open(start_image_path, "rb") as f:
                start_frame_bytes = f.read()
            start_frame_base64 = base64.b64encode(start_frame_bytes).decode('utf-8')

            with open(end_image_path, "rb") as f:
                end_frame_bytes = f.read()
            end_frame_base64 = base64.b64encode(end_frame_bytes).decode('utf-8')
        
        
        except Exception as e:
            print(f"  ERROR: Failed to read and encode local image files to base64: {e}")
            return None
        

        bucket_name, folder_path = storage_uri[5:].split("/", 1)
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        
        target_output_video_gcs_uri = f"gs://{bucket_name}/{output_local_video_path}"

        api_url = f"https://us-central1-aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/us-central1/publishers/google/models/veo-2.0-generate-exp:predictLongRunning" 

        headers['Content-Type'] = 'application/json'
        headers['charset'] = 'utf-8'

        new_url = f"https://us-central1-aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/us-central1/publishers/google/models/veo-2.0-generate-exp:fetchPredictOperation"
        api_call_attempted = True

        # Determine MIME type for start_image
        start_image_ext = os.path.splitext(start_image_path)[1].lower()
        if start_image_ext == ".png":
            start_mime_type = "image/png"
        elif start_image_ext in [".jpg", ".jpeg"]:
            start_mime_type = "image/jpeg"
        else:
            print(f"  ERROR: Unsupported file extension for start image: {start_image_ext}")
            return None
        
        # Determine MIME type for end_image
        end_image_ext = os.path.splitext(end_image_path)[1].lower()
        if end_image_ext == ".png":
            end_mime_type = "image/png"
        elif end_image_ext in [".jpg", ".jpeg"]:
            end_mime_type = "image/jpeg"
        else:
            print(f"  ERROR: Unsupported file extension for end image: {end_image_ext}")
            return None

        
        
        request_body = {
            "instances": [{
                "prompt": prompt_text,
                "image": {"bytesBase64Encoded": start_frame_base64, "mimeType": start_mime_type}, # Using 'content' for base64
                "lastFrame": {"bytesBase64Encoded": end_frame_base64, "mimeType": end_mime_type} # Using 'content'
            }],
            "parameters": {
                "aspectRatio": aspect_ratio,
                "durationSeconds": 8,
                "sampleCount" : 1,
                "storageUri": target_output_video_gcs_uri,
            }
        }
        
        os.makedirs(os.path.dirname(output_local_video_path), exist_ok=True)


        try:
            response = requests.post(api_url, headers=headers, data=json.dumps(request_body))
            response.raise_for_status() 
            
            operation_details = response.json()
            op_name = operation_details.get('name', 'N/A')

            print(f"API Response: {operation_details}")
            print(f"  SUCCESS (LRO Initiated): Veo 2 API call successful. Operation: {op_name}")

            max_iterations = 600
            interval_sec = 10

            new_request_body = {
                "operationName": op_name,
            }


            for i in range(max_iterations):
                try:
                    polling_response = requests.post(new_url, headers=headers, data=json.dumps(new_request_body))
                    polling_response.raise_for_status()

                    print(f" Reponse from polling: {polling_response.text}")

                    if '"done": true' in polling_response.text:
                        print(f" Reponse from polling: {polling_response.text}")
                        generated_videos = (
                            polling_response.json()["response"]["videos"]
                        )

                        print(f"The generated video samples are: {generated_videos}")

                        generated_videos_uri = (
                            polling_response.json()["response"]["videos"][0].get("gcsUri")
                        )
                        
                        return generated_videos_uri
                except requests.exceptions.RequestException as e:
                    print(f"Polling failed for operation {op_name}: {e}")
                    break  # Exit polling loop on error.
                except KeyError as e:
                    print(f"KeyError during polling for {op_name}: {e}. polling_response: {polling_response.text}")
                    break
                except Exception as e:
                    print(f"An unexpected error occurred during polling: {e}")
                    break

            print(f"Polling operation {op_name}, iteration {i+1}. Retrying in {interval_sec} seconds...")
            time.sleep(interval_sec)

        except requests.exceptions.HTTPError as e:
            print(f"  ERROR: HTTP Error during Veo 2 API call (with bytes): {e.response.status_code} - {e.response.text}")
            print(f"           This may indicate the API does not support byte content for images, expecting gcsUri.")
        except requests.exceptions.RequestException as e:
            print(f"  ERROR: Network or other Request Error during Veo 2 API call (with bytes): {e}")
        except Exception as e:
            print(f"  ERROR: An unexpected error occurred during Veo 2 API call (with bytes): {e}")
        
        return generated_videos_uri

    def generate_image_imagen(
        self,
        prompt: str,
        model: str = "imagen-3.0-generate-002",
        negative_prompt: Optional[str] = None,
        resolution: Optional[str] = "1K",
        sample_count: int = 1,
        aspect_ratio: str = "1:1",
        seed: Optional[int] = None,
        person_generation: Optional[str] = None,
        safety_filter_level: str = "block_few",
        storage_uri: Optional[str] = None,
        enhance_prompt: bool = True,
    ) -> Dict:
        """
        Generate an image using an Imagen model on Vertex AI.

        Args:
            prompt: Text prompt for image generation.
            input_image: Optional dictionary with image information.
            reference_images: Optional list of dictionaries for reference images.
            model: The Imagen model ID to use.
            negative_prompt: Text describing what to avoid.
            sample_count: Number of images to generate.
            aspect_ratio: Aspect ratio of the generated images.
            seed: Optional seed for deterministic generation.
            disable_person_face: Whether to disable generation of faces.
            safety_filter_threshold: Safety threshold to apply.

        Returns:
            Dict: API response containing generated images.
        """
        url = f"https://{self.location}-aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/{self.location}/publishers/google/models/{model}:predict"

        instance = {
            "prompt": prompt,
        }

        parameters = {
            "sampleCount": sample_count,
            "aspectRatio": aspect_ratio,
            "enhancePrompt": enhance_prompt,
            "storageUri": storage_uri,

        }

        if negative_prompt:
            parameters["negativePrompt"] = negative_prompt
        if seed is not None:
            parameters["seed"] = seed
        if resolution:
            parameters["sampleImageSize"] = resolution
        
        # Correctly handle the person_generation parameter.
        # The API expects 'disablePersonFace' as a boolean.
        # if person_generation == "Don't Allow":
        #     parameters["disablePersonFace"] = True
        # else: # "Allow" or "Allow (Adults only)"
        #     parameters["disablePersonFace"] = False


        harm_categories = [
            "HARM_CATEGORY_HATE_SPEECH",
            "HARM_CATEGORY_DANGEROUS_CONTENT",
            "HARM_CATEGORY_SEXUALLY_EXPLICIT",
            "HARM_CATEGORY_HARASSMENT"
        ]
        
        safety_settings = [{"category": cat, "threshold": safety_filter_level} for cat in harm_categories]
        parameters["safetySettings"] = safety_settings

        request_body = {
            "instances": [instance],
            "parameters": parameters,
        }

        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json; charset=utf-8"
        }

        response = requests.post(url, headers=headers, json=request_body)
        response.raise_for_status() # Raise an exception for bad status codes
        return response.json()
        
        # The response from streamGenerateContent is a list of JSON objects (chunks).
        # We need to aggregate them to extract the image data.
        # full_response_text = response.text
        
        # # The response is a stream of JSON objects, not a single one.
        # # We need to parse it line by line or as a list of objects.
        # try:
        #     # It's often returned as a JSON array of objects
        #     full_response_json = json.loads(full_response_text)
        # except json.JSONDecodeError:
        #     # Or sometimes as newline-delimited JSON
        #     try:
        #         full_response_json = [json.loads(line) for line in full_response_text.strip().split('\n')]
        #     except json.JSONDecodeError:
        #         raise ValueError(f"Could not parse streaming response from Gemini API: {full_response_text}")

        # # For image generation, the content is usually in one of the first chunks.
        # # Let's find the image data and format it like the other Imagen responses.
        # predictions = []
        # for chunk in full_response_json:
        #     if "candidates" in chunk:
        #         for candidate in chunk["candidates"]:
        #             if "content" in candidate and "parts" in candidate["content"]:
        #                 for part in candidate["content"]["parts"]:
        #                     if "inlineData" in part and "data" in part["inlineData"]:
        #                         predictions.append({
        #                             "bytesBase64Encoded": part["inlineData"]["data"]
        #                         })
        
        # return {"predictions": predictions}

    def extract_image_data(self, result: Dict) -> List[bytes]:
        """Extracts base64 encoded image data from an Imagen API result."""
        image_data_list = []
        if "predictions" in result:
            for prediction in result["predictions"]:
                if "bytesBase64Encoded" in prediction:
                    image_data_list.append(base64.b64decode(prediction["bytesBase64Encoded"]))
        return image_data_list

    def extract_image_uris(self, result: Dict) -> List[str]:
        """
        Extract image GCS URIs from an Imagen API result.

        Args:
            result: API response from a completed operation

        Returns:
            List[str]: List of image GCS URIs found in the response
        """
        image_uris = []
        if "predictions" in result:
            for prediction in result["predictions"]:
                if "gcsUri" in prediction:
                    image_uris.append(prediction["gcsUri"])
        return image_uris

def generate_image_gemini_image_preview(
    self,
    prompt: str,
    aspectRatio: str,
    input_images: Optional[List[Dict[str, str]]] = None,
    model: str = "gemini-2.5-flash-image-preview",
    temperature: float = 1.0,
    top_p: float = 0.95,
    max_output_tokens: int = 32768,
    safety_threshold: str = "OFF"
) -> Dict[str, Any]:
    """
    Generates or edits an image using Gemini with a text prompt and multiple input images.

    Args:
        prompt: Text prompt to guide image generation or editing.
        input_images: Optional list of dictionaries, where each dict contains
                      'mime_type' and 'data' (base64-encoded string) for an image.
        model: The Gemini model ID to use.
        temperature: Controls randomness in generation (0.0-1.0).
        top_p: Nucleus sampling parameter.
        max_output_tokens: The maximum number of tokens in the response.
        safety_threshold: The safety threshold to apply (e.g., "OFF", "BLOCK_FEW").

    Returns:
        Dict: API response containing the generated text and image content.
    """
    # 1. Construct the 'parts' of the request from multiple images and a prompt
    parts = []
    if input_images:
        for image_info in input_images:
            parts.append({
                "inlineData": {
                    "mimeType": image_info['mime_type'],
                    "data": image_info['data'],
                }
            })
    # The text prompt must be the last part
    parts.append({"text": prompt})

    # 2. Construct the full request body
    contents = [{"role": "user", "parts": parts}]

    generation_config = {
        "temperature": temperature,
        "maxOutputTokens": max_output_tokens,
        "responseModalities": ["TEXT", "IMAGE"],
        "imageConfig": {
            "aspectRatio": aspectRatio 
        },
        "topP": top_p,

    }

    safety_categories = [
        "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_DANGEROUS_CONTENT",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_HARASSMENT"
    ]
    safety_settings = [
        {"category": cat, "threshold": safety_threshold} for cat in safety_categories
    ]

    request_body = {
        "contents": contents,
        "generationConfig": generation_config,
        "safetySettings": safety_settings
    }
    
    # 3. Make the API request
    api_endpoint = f"aiplatform.googleapis.com"
    url = (f"https://{api_endpoint}/v1/projects/{self.project_id}/locations/global"
           f"/publishers/google/models/{model}:streamGenerateContent")
           
    headers = {
        "Authorization": f"Bearer {self._get_access_token()}",
        "Content-Type": "application/json; charset=utf-8"
    }

    response = requests.post(url, headers=headers, json=request_body)
    response.raise_for_status()
    # The response from streamGenerateContent is a list of JSON objects (chunks).
    # We need to aggregate them to extract the image data.
    full_response_text = response.text
    
    # The response is a stream of JSON objects, not a single one.
    # We need to parse it line by line or as a list of objects.
    try:
        # It's often returned as a JSON array of objects
        full_response_json = json.loads(full_response_text)
    except json.JSONDecodeError:
        # Or sometimes as newline-delimited JSON
        try:
            full_response_json = [json.loads(line) for line in full_response_text.strip().split('\n')]
        except json.JSONDecodeError:
            raise ValueError(f"Could not parse streaming response from Gemini API: {full_response_text}")

    # For image generation, the content is usually in one of the first chunks.
    # Let's find the image data and format it like the other Imagen responses.
    predictions = []
    for chunk in full_response_json:
        if "candidates" in chunk:
            for candidate in chunk["candidates"]:
                if "content" in candidate and "parts" in candidate["content"]:
                    for part in candidate["content"]["parts"]:
                        if "inlineData" in part and "data" in part["inlineData"]:
                            predictions.append({
                                "bytesBase64Encoded": part["inlineData"]["data"]
                            })
    
    return {"predictions": predictions}

# This is a helper function to encode a local image file to base64
def image_to_base64(filepath: str) -> str:
    with open(filepath, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def concatenate_videos(video_paths_list: list, output_concatenated_video_path: str, run_temp_dir: str):
    """
    Concatenates multiple video files.
    Items in video_paths_list can be local paths or GCS URIs.
    GCS URIs are downloaded first.
    """
    print(f"Concatenating {len(video_paths_list)} videos into '{os.path.basename(output_concatenated_video_path)}'")
    
    if not video_paths_list:
        print("No videos to concatenate.")
        return None
    
    local_clips_for_concatenation = []
    downloaded_temp_files_for_cleanup = []

    temp_download_dir_specific = os.path.join(run_temp_dir, TEMP_DOWNLOAD_SUBDIR, "concat_downloads")
    os.makedirs(temp_download_dir_specific, exist_ok=True)

    try:
        for i, video_path_item in enumerate(video_paths_list):
            local_input_path_for_clip = video_path_item
            is_gcs_item = video_path_item.startswith("gs://")

            if is_gcs_item:
                try:
                    bucket_name_in, blob_name_in = video_path_item[5:].split("/", 1)
                    temp_download_path_item = os.path.join(temp_download_dir_specific, f"segment_{i}_{os.path.basename(blob_name_in)}")
                    print(f"  Segment {i+1} is GCS URI. Downloading {video_path_item} to {temp_download_path_item}...")
                    download_blob(bucket_name_in, blob_name_in, temp_download_path_item)
                    local_input_path_for_clip = temp_download_path_item
                    # downloaded_temp_files_for_cleanup.append(local_input_path_for_clip) # Cleanup handled by run_temp_dir
                except Exception as e:
                    print(f"  WARNING: Failed to download GCS video segment {video_path_item}: {e}. Skipping.")
                    continue
            if not os.path.exists(local_input_path_for_clip):
                print(f"  WARNING: Video segment file not found: {local_input_path_for_clip}. Skipping.")
                continue
            
            try:
                print(f"  Loading segment {i+1}: {os.path.basename(local_input_path_for_clip)}")
                clip = VideoFileClip(local_input_path_for_clip)
                local_clips_for_concatenation.append(clip)
            except Exception as e:
                print(f"  WARNING: Failed to load video segment {local_input_path_for_clip} with moviepy: {e}. Skipping.")

        if not local_clips_for_concatenation:
            print("  No valid video segments to concatenate after downloads/loading.")
            return None
        print(f"  Concatenating {len(local_clips_for_concatenation)} loaded clips with moviepy...")
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_concatenated_video_path), exist_ok=True)
        final_concatenated_clip = concatenate_videoclips(local_clips_for_concatenation, method="compose") # Use "compose" for overlapping audio/video
        final_concatenated_clip.write_videofile(output_concatenated_video_path, codec="libx264", audio_codec="aac", logger=None)
        final_concatenated_clip.close()
        print(f"  Concatenated video saved to {output_concatenated_video_path}")
        return output_concatenated_video_path
    except Exception as e:
        print(f"  ERROR: MoviePy video concatenation failed: {e}")
        return None
    finally:
        for clip_obj in local_clips_for_concatenation:
            clip_obj.close()


def alter_video_speed( # Renamed to avoid confusion if a real one is added
    input_video_path: str,
    output_video_path: str,
    speed_factor: float,
    run_temp_dir: str
):
    """
    Alters the playback speed of a video.
    The input_video_path can be a local path or a GCS URI.
    If GCS URI, it's downloaded first.
    """
    print(f"Altering speed for: '{os.path.basename(input_video_path)}' by factor {speed_factor:.2f}")
    
    local_input_path_for_processing = input_video_path
    is_gcs_input = input_video_path.startswith("gs://")
    temp_download_path = None

    if is_gcs_input:
        try:
            bucket_name_in, blob_name_in = input_video_path[5:].split("/", 1)
            temp_download_dir_specific = os.path.join(run_temp_dir, TEMP_DOWNLOAD_SUBDIR, "speed_alter_downloads")
            os.makedirs(temp_download_dir_specific, exist_ok=True)
            temp_download_path = os.path.join(temp_download_dir_specific, os.path.basename(blob_name_in))
            
            print(f"  Input is GCS URI. Downloading {input_video_path} to {temp_download_path}...")
            download_blob(bucket_name_in, blob_name_in, temp_download_path)
            local_input_path_for_processing = temp_download_path
        except Exception as e:
            print(f"  ERROR: Failed to download GCS video {input_video_path} for speed alteration: {e}")
            return None
    
    if not os.path.exists(local_input_path_for_processing):
        print(f"  ERROR: Input video for speed alteration not found at {local_input_path_for_processing}")
        return None

    if abs(speed_factor - 1.0) < 1e-5: # If speed factor is effectively 1.0
        print(f"  Speed factor is {speed_factor}, copying original video.")
        shutil.copy(local_input_path_for_processing, output_video_path)
        return output_video_path
    
    clip = None
    final_clip_processed = None
    try:
        print(f"  Processing video {local_input_path_for_processing} with moviepy...")
        clip = VideoFileClip(local_input_path_for_processing)
        final_clip_processed = clip.fx(vfx.speedx, speed_factor)
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_video_path), exist_ok=True)
        final_clip_processed.write_videofile(output_video_path, codec="libx264", audio_codec="aac", logger=None) # Added logger=None for less verbose output
        print(f"  Speed altered video saved to {output_video_path}")
        return output_video_path
    except Exception as e:
        print(f"  ERROR: MoviePy speed alteration for {os.path.basename(local_input_path_for_processing)} failed: {e}")
        return None

def generate_video_simple(
    project_id: str,
    prompt: str,
    image_path: Optional[str] = None,
    storage_uri: Optional[str] = None,
    sample_count: int = 1,
    duration_seconds: int = 8,
    aspect_ratio: str = "16:9",
    wait_for_completion: bool = True
) -> Dict:
    """
    Simple function to generate video with Veo 2.0 API.
    
    Args:
        project_id: Your Google Cloud project ID
        prompt: Text prompt to guide video generation
        image_path: Optional path to an image file for image-to-video
        storage_uri: GCS URI to store output videos (e.g., "gs://bucket/folder/")
        sample_count: Number of videos to generate (1-4)
        duration_seconds: Length of video in seconds (5-8)
        aspect_ratio: Aspect ratio of generated video ("16:9" or "9:16")
        wait_for_completion: Whether to wait for the operation to complete
        
    Returns:
        Dict: Response containing operation details or final results
    """
    client = Veo2API(project_id)
    
    # Prepare image if provided
    input_image = None
    if image_path:
        input_image = client.encode_image_file(image_path)
    
    # Generate video
    response = client.generate_video(
        prompt=prompt,
        input_image=input_image,
        storage_uri=storage_uri,
        sample_count=sample_count,
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio
    )
    
    # Extract operation ID from the full operation name
    operation_name = response.get("name", "")
    if not operation_name:
        return response
    
    operation_id = operation_name.split("/")[-1]
    
    # If not waiting for completion, return the operation response
    if not wait_for_completion:
        return response
    
    # Wait for operation to complete and return the result
    return client.wait_for_operation(operation_id)

def generate_audio(self, prompt: str, negative_prompt: str = None, sample_count: int = 1, seed: Optional[int] = None, storage_uri: Optional[str] = None):
    """
    Calls a generative audio API, processes the response, and displays the audio on the Streamlit UI.

    Args:
        project_id: Your Google Cloud project ID.
        location: The Google Cloud region for the API endpoint (e.g., "us-central1").
        prompt: The text prompt describing the desired audio.
        negative_prompt: Optional text describing elements to avoid.
        sample_count: The number of audio samples to generate.        
        storage_uri: GCS URI where the files should be stored
    """


    # --- 1. Authenticate and Get Access Token ---
    try:
        # Get application default credentials
        credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        access_token = credentials.token
    except Exception as e:
        st.error(f"Could not get authentication credentials. Please ensure you are authenticated. Error: {e}")
        return

    # --- 2. Set Up API Endpoint and Headers ---
    # The model name is hardcoded to lyria-002 as per the response template.
    api_endpoint = f"https://{self.location}-aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/{self.location}/publishers/google/models/lyria-002:predict"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    # --- 3. Construct the Request Body ---
    instance = {"prompt": prompt}
    if negative_prompt:
        instance["negative_prompt"] = negative_prompt
    if seed:
        instance = {"seed": seed}

    parameters = {"sample_count": sample_count}


    print(parameters)

    payload = {
        "instances": [instance],
        "parameters": parameters
    }

    # --- 4. Make the API Call ---
    try:
        response = requests.post(api_endpoint, headers=headers, data=json.dumps(payload))
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
        response_data = response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"API Error: Failed to get a valid response. Status Code: {e.response.status_code if e.response else 'N/A'}")
        # Display the detailed error from the API if available
        st.json(e.response.json() if e.response else "No response from server.")
        return

    # --- 5. Process Response and Display Audio on UI ---
    predictions = response_data.get("predictions", [])
    if not predictions:
        st.warning("Audio generation succeeded, but the API response contained no audio data.")
        st.json(response_data)  # Show the full response for debugging
        return []

    audio_uris = []
    st.success(f"Successfully generated {len(predictions)} audio sample(s)!")

    # Loop through each prediction and display an audio player
    for i, prediction in enumerate(predictions):
        audio_content_b64 = prediction.get("bytesBase64Encoded")

        if audio_content_b64:
            try:
                # Decode the Base64 string into raw audio bytes
                audio_bytes = base64.b64decode(audio_content_b64)

                st.markdown("---")
                st.markdown(f"### Audio Sample {i + 1}")
                
                if storage_uri:
                    try:
                        from google.cloud import storage
                        
                        if not storage_uri.startswith("gs://") or not storage_uri.endswith("/"):
                            st.error("Invalid storage URI. It should start with 'gs://' and end with a '/' (e.g., 'gs://your-bucket/generated_audio/')")
                            return []

                        bucket_name, folder_path = storage_uri[5:].split("/", 1)
                        client = storage.Client()
                        bucket = client.bucket(bucket_name)
                        
                        # Generate a unique filename for the audio
                        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                        audio_filename = f"audio_{timestamp}_{i+1}.wav"
                        gcs_filepath = f"{folder_path}{audio_filename}"
                        
                        # Upload the audio data to GCS
                        blob = bucket.blob(gcs_filepath)
                        blob.upload_from_string(audio_bytes, content_type="audio/wav")
                        
                        st.success(f"Audio sample {i+1} successfully uploaded to GCS: gs://{bucket_name}/{gcs_filepath}")
                        audio_uris.append(f"gs://{bucket_name}/{gcs_filepath}")
                    except ImportError:
                        st.error("Google Cloud Storage SDK not found. Install it using: pip install google-cloud-storage")
                        return []
                    except Exception as e:
                        st.error(f"Error uploading audio sample {i+1} to GCS: {e}")
                
                # Play audio directly in Streamlit
                st.audio(audio_bytes, format="audio/wav")
                # Display the raw prediction object (optional, for debugging)
                # st.json(prediction)

            except Exception as e:
                st.error(f"Failed to decode or display audio sample {i + 1}. Please check the response format. Error: {e}")
        else:
            st.warning(f"Prediction {i+1} did not contain the audio bytes. This is often due to safety filters.")
            # Check for safety ratings, which is a common reason for missing content.
            safety_ratings = prediction.get("safetyRatings")
            if safety_ratings:
                st.error(f"Audio generation for sample {i+1} was likely blocked due to safety policies.")
                with st.expander("View Safety Ratings"):
                    st.json(safety_ratings)
            else:
                # If no specific reason is found, show the whole prediction object for general debugging.
                st.info(f"Here is the full content of prediction {i+1} for debugging:")
                st.json(prediction)
    return audio_uris

    # Optionally display the model information from the response
    # with st.expander("View Model Information"):
    #     st.write(f"**Model Used:** `{response_data.get('model')}`")
    #     st.write(f"**Deployed Model ID:** `{response_data.get('deployedModelId')}`")


def download_blob(bucket_name: str, source_blob_name: str, destination_file_name: str):
    """Downloads a blob from a GCS bucket."""
    try:
        
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(source_blob_name)
        print(f"Attempting to download {source_blob_name} to {destination_file_name}...")
        blob.download_to_filename(destination_file_name)
        print(f"Blob downloaded successfully.")
    except Exception as e:
        raise ConnectionError(f"Failed to download blob gs://{bucket_name}/{source_blob_name}: {e}")


def upload_to_gcs(bucket_name, source_path, destination_blob_prefix, is_folder=False):
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    if not bucket.exists():
        print(f"Bucket {bucket_name} does not exist. Please create it or check the name.")
        return False
    # (Rest of the GCS upload logic from previous version)
    if is_folder:
        for dirpath, _, filenames in os.walk(source_path):
            for filename in filenames:
                local_path = os.path.join(dirpath, filename)
                relative_path = os.path.relpath(local_path, source_path)
                blob_name = os.path.join(destination_blob_prefix, relative_path)
                blob = bucket.blob(blob_name)
                try:
                    blob.upload_from_filename(local_path)
                    # print(f"Uploaded {local_path} to gs://{bucket_name}/{blob_name}")
                except Exception as e:
                    print(f"Error uploading {local_path}: {e}")
        return True
    else:
        filename = os.path.basename(source_path)
        blob_name = os.path.join(destination_blob_prefix, filename)
        blob = bucket.blob(blob_name)
        try:
            blob.upload_from_filename(source_path)
            # print(f"Uploaded {source_path} to gs://{bucket_name}/{blob_name}")
            return True
        except Exception as e:
            print(f"Error uploading {source_path}: {e}")
            return False
    return True

# Add the new functions to the Veo2API class
Veo2API.generate_audio = generate_audio
Veo2API.download_blob = download_blob
Veo2API.concatenate_videos = concatenate_videos
Veo2API.alter_video_speed = alter_video_speed
Veo2API.upload_to_gcs = upload_to_gcs
Veo2API.generate_image_gemini_image_preview = generate_image_gemini_image_preview

Veo2API.download_blob = download_blob
