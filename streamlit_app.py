"""
Veo2 Video Generator - A Streamlit app for generating high-quality videos
from text prompts and images using Google's Veo 2.0 API.
"""
import os
import mimetypes
import uuid
import time
import json
import tempfile
import io
import queue
import sys
import hashlib
import pandas as pd
import subprocess
from datetime import datetime
from PIL import Image
import streamlit as st
import requests
from moviepy.editor import VideoFileClip, concatenate_videoclips
import numpy as np
import firebase_admin
from firebase_admin import credentials, firestore
from collections import OrderedDict
from typing import Dict, List, Optional, Union, Any
import shutil
from streamlit_oauth import OAuth2Component
from werkzeug.utils import secure_filename
from streamlit_mic_recorder import mic_recorder


# Import project modules
import config.config as config
import apis.gemini_helper as gemini_helper
import app as dubbing_lib
import apis.history_manager as history_manager
from apis.veo2_api import Veo2API

# Initialize the Veo2 API client globally for shared use
client = Veo2API(config.PROJECT_ID)
db_id = config.DB_ID


# Initialize Firestore
try:
    # This will use the GOOGLE_APPLICATION_CREDENTIALS environment variable.
    # Make sure it's set in your deployment environment.
    if not firebase_admin._apps:
        # Initialize the app if it hasn't been initialized yet
        firebase_admin.initialize_app()
    db = firestore.client(database_id=db_id) #The line below specifies which db will be used when initializing
    FIRESTORE_AVAILABLE = True
    print("Firestore initialized successfully!")
except Exception as e:
    print(f"Failed to initialize Firestore: {e}", file=sys.stderr)
    db = None
    FIRESTORE_AVAILABLE = False


# Helper function to generate signed URLs
def generate_signed_url(uri, expiration=3600):
    """
    Generate a signed URL for a GCS URI.
    
    Args:
        uri (str): GCS URI to generate a signed URL for
        expiration (int): Expiration time in seconds
        
    Returns:
        str: Signed URL for accessing the resource
    """
    # Use the global client to generate a signed URL
    return client.generate_signed_url(uri, expiration_minutes=expiration//60)

# Class for simulating file uploads from different sources
class SimulatedUploadFile:
    def __init__(self, name, content):
        self.name = name
        self.content = content
        self.size = len(content)
        self._position = 0
    
    def getvalue(self):
        return self.content
        
    def read(self, size=-1):
        """Read content from current position, like a file object."""
        if size < 0:
            # Read all content from current position
            data = self.content[self._position:]
            self._position = len(self.content)
        else:
            # Read only 'size' bytes
            data = self.content[self._position:self._position + size]
            self._position += len(data)
        return data
    
    def seek(self, offset, whence=0):
        """Change the current position like a file object."""
        if whence == 0:  # Absolute position
            self._position = offset
        elif whence == 1:  # Relative to current position
            self._position += offset
        elif whence == 2:  # Relative to end
            self._position = len(self.content) + offset
        # Ensure position is within bounds
        self._position = max(0, min(self._position, len(self.content)))
        return self._position
    
    def tell(self):
        """Return the current position in the file."""
        return self._position
    
    # Make compatible with contextlib.closing and context managers
    def close(self):
        """Close the file-like object."""
        pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

# Check if Google Cloud Storage SDK is available
try:
    from google.cloud import storage
    GCS_SDK_AVAILABLE = True
except ImportError:
    GCS_SDK_AVAILABLE = False

# Create a cleaner logger
class Logger:
    """Simple logger with section formatting for cleaner console output."""
    
    def __init__(self, debug=False):
        self.sections = []
        self.debug_mode = debug
    
    def start_section(self, name):
        """Start a new log section."""
        section = name.upper()
        border = "=" * (len(section) + 4)
        print(f"\n{border}")
        print(f"| {section} |")
        print(f"{border}")
        self.sections.append(name)
    
    def end_section(self):
        """End the current log section."""
        if self.sections:
            section = self.sections.pop()
            print(f"--- END {section.upper()} ---\n")
    
    def info(self, message):
        """Log an info message."""
        print(f"INFO: {message}")
    
    def success(self, message):
        """Log a success message."""
        print(f"✅ {message}")
    
    def warning(self, message):
        """Log a warning message."""
        print(f"⚠️ {message}", file=sys.stderr)
    
    def error(self, message):
        """Log an error message."""
        print(f"❌ {message}", file=sys.stderr)
    
    def debug(self, message):
        """Log a debug message (only when debug is enabled)."""
        if self.debug_mode:
            print(f"DEBUG: {message}")

# Initialize logger
logger = Logger(debug=config.DEBUG_MODE)

logger.start_section("Application Startup")
logger.info(f"Starting Veo2 Video Generator App (v0.2.0)")
logger.info(f"Python version: {sys.version}")
logger.info(f"Working directory: {os.getcwd()}")
logger.end_section()

# Custom CSS to improve app appearance
st.markdown("""
<style>
    /* Overall app styling */
    .main .block-container {
        padding-top: 0 !important;
        padding-bottom: 2rem;
        max-width: 100%;
    }
    
    /* Remove empty input bars */
    .stTextInput, .stNumberInput {
        margin-bottom: 0 !important;
    }
    
    /* Ensure consistent widths */
    .stButton, .stButton > button {
        width: 100%;
    }
    
    /* Fix the Generate Video button width */
    [data-testid="column"] .stButton {
        width: 100% !important;
    }
    
    /* Title row styling */
    .title-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin: 0;
        padding: 0.5rem 0;
    }
    
    /* Title heading style */
    .title-row h2 {
        margin: 0 !important;
        padding: 0 !important;
        font-size: 1.5rem !important;
    }
    
    /* Card-like containers */
    .card {
        background-color: white;
        border-radius: 10px;
        padding: 20px;
        margin-bottom: 20px;
        border: 1px solid #e0e0e0;
        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.05);
    }
    
    /* Button styles */
    .success-button {
        background-color: #28a745;
        color: white;
        padding: 0.25rem 0.75rem;
        border-radius: 0.25rem;
        text-decoration: none;
        font-weight: bold;
        display: inline-block;
    }
    .warning-button {
        background-color: #dc3545;
        color: white;
        padding: 0.25rem 0.75rem;
        border-radius: 0.25rem;
        text-decoration: none;
        font-weight: bold;
        display: inline-block;
    }
    
    /* Spinner styling */
    .stSpinner > div > div {
        border-color: #4caf50 #f3f3f3 #f3f3f3 !important;
    }
    
    /* Image container */
    .image-preview {
        border: 1px solid #e0e0e0;
        border-radius: 5px;
        padding: 10px;
        background-color: #f9f9f9;
    }
    
    /* Prompt text area container */
    .prompt-textarea {
        border-radius: 5px;
    }
    
    /* Space between elements */
    .spacer {
        margin-top: 20px;
    }
    
    /* Tabs styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    
    .stTabs [data-baseweb="tab"] {
        height: 40px;
        border-radius: 5px 5px 0 0;
        padding: 0 20px;
        font-weight: 500;
    }
    
    /* Make tabs more compact */
    .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
        font-size: 0.9rem;
        margin-bottom: 0;
    }
    
    /* Decrease padding around tab content */
    .stTabs [data-baseweb="tab-panel"] {
        padding-top: 1rem;
    }
    
    /* Table styling */
    .stDataFrame {
        border-radius: 5px;
    }
    
    .sidebar .sidebar-content {
        background-color: #f8f9fa;
    }
    
    .upload-container {
        border: 2px dashed #aaaaaa;
        border-radius: 8px;
        padding: 20px 10px;
        text-align: center;
        margin-bottom: 15px;
        background-color: #f9f9f9;
    }
    .image-preview-container {
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 20px;
        background-color: #f8f8f8;
    }
    .prompt-container {
        border-radius: 4px;
        padding: 0;
        margin-top: 5px;
        margin-bottom: 10px;
        background-color: transparent;
    }
    
    /* Custom header styling */
    .main-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 2rem;
        padding-bottom: 1rem;
        border-bottom: 1px solid #f0f0f0;
    }
    
    .header-logo {
        display: flex;
        align-items: center;
        gap: 10px;
    }
    
    .header-logo img {
        height: 50px;
    }
    
    .header-status {
        display: flex;
        align-items: center;
        gap: 10px;
        background-color: #f8f9fa;
        padding: 8px 15px;
        border-radius: 50px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }
    
    .status-indicator {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background-color: #4CAF50;
    }
    
    /* Footer styling - fixed at bottom */
    .footer {
        position: fixed;
        left: 0;
        bottom: 0;
        width: 100%;
        background-color: white;
        border-top: 1px solid #f0f0f0;
        padding: 0.5rem 0;
        text-align: center;
        color: #888;
        font-size: 0.8rem;
        z-index: 100;
    }
    
    /* Add padding to ensure content isn't hidden beneath footer */
    .main .block-container {
        padding-bottom: 3rem !important;
    }
    
    /* Remove any specific row or element causing empty spaces */
    div[data-testid="stExpander"] .streamlit-expanderContent {
        overflow: hidden;
    }
    
    /* Reduce all section heading margins */
    h1, h2, h3, h4, h5, h6 {
        margin-top: 0.5rem !important;
        margin-bottom: 0.5rem !important;
        padding-top: 0 !important;
    }
    
    /* Remove margins between UI elements */
    .element-container {
        margin-top: 0.3rem !important;
        margin-bottom: 0.3rem !important;
    }
    
    /* History styling improvements */
    .history-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr) !important; /* Changed from 2 to 3 columns */
        grid-gap: 15px; /* Reduced gap for tighter packing */
        margin-bottom: 20px;
        width: 100%;
    }
    
    .history-card {
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        overflow: hidden;
        background-color: white;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        height: 100%;
        display: flex;
        flex-direction: column;
        width: 100%;
        max-width: 100%;
        padding-top: 0;
        margin-top: 0;
    }
    
    .history-card-content {
        padding: 10px;
        flex-grow: 1;
    }
    
    .history-card-toolbar {
        display: flex;
        justify-content: space-between;
        padding: 8px;
        background-color: #f8f9fa;
        border-top: 1px solid #e0e0e0;
    }
    
    /* Ensure videos and images display consistently */
    .history-card video, .history-card img,
    .history-card [data-testid="stVideo"] video,
    .history-card [data-testid="stImage"] img {
        width: 100% !important;
        max-height: 250px !important;
        object-fit: contain !important;
        background-color: #f0f0f0;
    }
    
    /* Control video width */
    .history-card [data-testid="stVideo"] {
        width: 100% !important;
        max-width: 100% !important;
    }
    
    /* Style markdown content in cards for better readability */
    .history-card [data-testid="stMarkdownContainer"] p {
        margin: 5px 0;
        font-size: 0.9rem;
    }
    
    .history-card [data-testid="stMarkdownContainer"] strong {
        color: #555;
    }
    
    /* Fix width consistency issues */
    .stApp {
        max-width: 100%;
    }
    
    /* Ensure all containers have consistent width */
    .stButton, .stButton > button, .stSpinner {
        width: 100% !important;
        max-width: 100% !important;
    }
    
    /* Ensure notification banners have consistent width */
    [data-testid="stNotificationContent"] {
        width: 100% !important;
        max-width: 100% !important;
    }
    
    /* Center all generated output */
    [data-testid="column"] > div {
        width: 100% !important;
    }
    
    /* Overall app simplification */
    .streamlit-container {
        max-width: 100%;
    }
    
    /* Simplified UI approach */
    .simplified-card {
        background-color: #f9f9f9;
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 15px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
    
    /* Reduce visual clutter */
    .streamlit-expanderHeader {
        font-size: 0.9rem !important;
        font-weight: normal !important;
        color: #555 !important;
    }
    
    /* Simplify form controls */
    .stSlider, .stSelectbox {
        margin-top: 0 !important;
        margin-bottom: 0.5rem !important;
    }
    
    /* More subtle info messages */
    .stAlert {
        padding: 0.5rem !important;
        margin-top: 0.5rem !important;
        margin-bottom: 0.5rem !important;
    }
    
    /* Cleaner text areas */
    .stTextArea > div > div {
        border-radius: 6px !important;
        border-color: #ddd !important;
    }
    
    /* Cleaner expandable sections */
    div[data-testid="stExpander"] {
        border: none !important;
        box-shadow: none !important;
        background-color: #f9f9f9 !important;
        margin-bottom: 0.5rem !important;
    }
    
    /* More explicit control for videos in history cards */
    .history-card iframe,
    .history-card [data-testid="stVideo"] iframe {
        max-width: 100% !important;
        width: 100% !important;
        height: auto !important;
        max-height: 250px !important;
    }
    
    /* Ensure streamlit element containers in history cards don't exceed card width */
    .history-card .element-container,
    .history-card .stVideo,
    .history-card .stImage {
        width: 100% !important;
        max-width: 100% !important;
    }
    
    /* Remove video/image overflow */
    .history-card > div {
        width: 100% !important;
        max-width: 100% !important;
        overflow: hidden !important;
    }
    
    /* App-wide Styling */
    .sidebar-section {
        margin-bottom: 20px;
        padding-bottom: 20px;
        border-bottom: 1px solid #e6e6e6;
    }
    
    .sidebar-title {
        font-weight: bold;
        margin-bottom: 10px;
    }
    
    /* Video Container Styling */
    .video-container {
        position: relative;
        width: 100%;
        max-width: 640px;
        margin: 0 auto 20px auto;
        border-radius: 10px;
        overflow: hidden;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        max-height: calc(100vh - 200px); /* Limit height to viewport minus some space */
    }
    
    /* Special handling for vertical (9:16) videos */
    .video-container.vertical {
        max-width: 360px; /* Narrower width for vertical videos */
        max-height: calc(100vh - 200px); /* Ensure it fits in viewport height */
    }
    
    .video-container video {
        width: 100%;
        display: block;
        max-height: calc(100vh - 200px);
        object-fit: contain;
    }
    
    /* History Tab Styling */
    .history-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 20px;
        margin-bottom: 30px;
    }
    
    .history-card {
        padding: 15px;
        border-radius: 10px;
        background-color: #f9f9f9;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
        height: 100%;
        display: flex;
        flex-direction: column;
    }
    
    .history-card img, .history-card video {
        width: 100%;
        border-radius: 8px;
        margin-bottom: 10px;
        max-height: 300px;
        object-fit: contain;
    }
    
    .history-prompt {
        margin: 10px 0;
        font-size: 0.9rem;
        color: #555;
        max-height: 100px;
        overflow-y: auto;
    }
    
    .history-meta {
        font-size: 0.8rem;
        color: #777;
        margin-top: auto;
    }
    
    .button-row {
        display: flex;
        justify-content: space-between;
        margin-top: 10px;
        gap: 10px;
    }
    
    .button-row > button, .button-row > a {
        flex: 1;
    }
    
    /* Settings Tab Styling */
    .settings-section {
        margin-bottom: 30px;
        padding-bottom: 20px;
        border-bottom: 1px solid #e6e6e6;
    }
    
    .settings-title {
        font-weight: bold;
        margin-bottom: 15px;
    }
    
    /* Make fullscreen images/videos more constrained */
    .fullscreen-content img, .fullscreen-content video {
        max-width: 100%;
        max-height: calc(100vh - 200px);
        margin: 0 auto;
        display: block;
        object-fit: contain;
    }
</style>
""", unsafe_allow_html=True)


# App state initialization
def init_state():
    """Initialize all session state variables."""
    logger.start_section("Initializing App State")
    
    # Initialize session state variables if they don't exist
    if "generated_videos" not in st.session_state:
        logger.info("Initializing 'generated_videos' in session state")
        st.session_state.generated_videos = []
    
    if "history_loaded" not in st.session_state:
        logger.info("Initializing 'history_loaded' in session state")
        st.session_state.history_loaded = False
        
    if "history_initialized" not in st.session_state:
        logger.info("Initializing 'history_initialized' in session state")
        st.session_state.history_initialized = False
    
    if "confirm_clear_history" not in st.session_state:
        logger.debug("Initializing 'confirm_clear_history' in session state")
        st.session_state.confirm_clear_history = False
    
    if "generated_prompt" not in st.session_state:
        logger.debug("Initializing 'generated_prompt' in session state")
        st.session_state.generated_prompt = None
    
    if "active_tab" not in st.session_state:
        logger.debug("Initializing 'active_tab' in session state")
        st.session_state.active_tab = "text_to_video"
    
    # Initialize image-related session variables
    if "current_image" not in st.session_state:
        logger.debug("Initializing 'current_image' in session state")
        st.session_state.current_image = None
        
    if "current_uploaded_file" not in st.session_state:
        logger.debug("Initializing 'current_uploaded_file' in session state")
        st.session_state.current_uploaded_file = None
        
    if "current_image_url" not in st.session_state:
        logger.debug("Initializing 'current_image_url' in session state")
        st.session_state.current_image_url = ""
        
    if "last_entered_prompt" not in st.session_state:
        logger.debug("Initializing 'last_entered_prompt' in session state")
        st.session_state.last_entered_prompt = ""
    
    # Add cache for signed URLs
    if "signed_url_cache" not in st.session_state:
        logger.info("Initializing 'signed_url_cache' in session state")
        st.session_state.signed_url_cache = {}
    
    # Ensure the history file exists in GCS, but only do this once per session
    if not st.session_state.get('history_initialized', False):
        # History is now managed in Firestore. The collection will be created on first write.
        # We just need to mark the state as initialized to avoid re-checks.
        logger.info("History tracking is configured for Firestore.")
        st.session_state.history_initialized = True
        # Force history to be loaded freshly on first run
        st.session_state.history_loaded = False

    # Initialize history selection state
    if "selected_history_items" not in st.session_state:
        logger.debug("Initializing 'selected_history_items' in session state")
        st.session_state.selected_history_items = {} # Will store {uri: type}

    # Initialize state for the main navigation tabs
    if "active_main_tab" not in st.session_state:
        logger.debug("Initializing 'active_main_tab' in session state")
        st.session_state.active_main_tab = "🎬 Video"

    # State for files passed from history to editing tabs
    if 'edit_image_files' not in st.session_state:
        st.session_state.edit_image_files = []
    if 'active_video_sub_tab' not in st.session_state:
        st.session_state.active_video_sub_tab = "Text-to-Video"
    if 'active_image_sub_tab' not in st.session_state:
        st.session_state.active_image_sub_tab = "Text-to-Image"
    if 'active_audio_sub_tab' not in st.session_state:
        st.session_state.active_audio_sub_tab = "Text-to-Audio"
    if 'speed_change_video_file' not in st.session_state:
        st.session_state.speed_change_video_file = None
    if 'concat_video_files' not in st.session_state:
        st.session_state.concat_video_files = []
    
    if 'active_history_sub_tab' not in st.session_state:
        logger.debug("Initializing 'active_history_sub_tab' in session state")
        st.session_state.active_history_sub_tab = "🎬 Recent Videos"

    if 'next_active_main_tab' not in st.session_state:
        st.session_state.next_active_main_tab = None

    # State for the new Gemini Chat tab
    if "gemini_messages" not in st.session_state:
        logger.debug("Initializing 'gemini_messages' for chat history")
        st.session_state.gemini_messages = []

    # State for resetting the Gemini chat file uploader
    if "gemini_uploader_key_counter" not in st.session_state:
        logger.debug("Initializing 'gemini_uploader_key_counter' in session state")
        st.session_state.gemini_uploader_key_counter = 0

    # Flag to ensure pending operations are checked only once per session
    if 'pending_ops_checked' not in st.session_state:
        logger.debug("Initializing 'pending_ops_checked' flag in session state")
        st.session_state.pending_ops_checked = False

    logger.end_section()

def _setup_page():
    """
    Configures the Streamlit page, applies the theme, and handles programmatic tab switching.
    This function should be called at the very beginning of the main app script execution.
    """
    # Initialize dark_mode state if it doesn't exist. This ensures it's set only
    # once per session and persists across all reruns.
    if "dark_mode" not in st.session_state:
        st.session_state.dark_mode = False

    # Configure the Streamlit page. This must be the first Streamlit command.
    # The 'theme' argument is removed for compatibility with older Streamlit versions.
    st.set_page_config(
        page_title="Google Media Gen Tool",
        page_icon="🎬",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # --- Dark Mode CSS Injection ---
    # This CSS is conditionally applied to style components that Streamlit's
    # native dark mode doesn't cover fully, like expanders.
    DARK_MODE_CSS = """
    <style>
        /* Expander (Advanced Options) styling for dark mode */
        div[data-testid="stExpander"] {
            background-color: #1c1c1c !important;
            border: 1px solid #31333F !important;
            color: #fafafa !important;
            border-radius: 8px;
        }
        div[data-testid="stExpander"] > div[data-testid="stExpanderHeader"] > p {
            color: #fafafa !important; /* Header text color */
        }
        div[data-testid="stExpander"] [data-testid="stMarkdownContainer"] p,
        div[data-testid="stExpander"] [data-testid="stMarkdownContainer"] li {
            color: #fafafa !important; /* Content text color */
        }
        
        /* Ensure input/select box text is visible in dark mode */
        .stTextInput > div > div > input, 
        .stNumberInput > div > div > input,
        .stTextArea > div > div > textarea,
        .stSelectbox div[data-baseweb="select"] > div {
            background-color: #262730 !important;
            color: #fafafa !important;
            border-color: #4d4d4d !important;
        }

        /* Sidebar section styling */
        .sidebar-section {
            border-bottom: 1px solid #31333F;
        }
    </style>
    """

    # Apply dark mode CSS if the toggle is active.
    if st.session_state.get("dark_mode", False):
        st.markdown(DARK_MODE_CSS, unsafe_allow_html=True)

    # Handle programmatic tab switching. This must be done after applying CSS.
    # By updating the state and allowing the script to continue without a second
    # rerun, we prevent the "flicker" of the light theme.
    if st.session_state.get("next_active_main_tab"):
        st.session_state.active_main_tab = st.session_state.next_active_main_tab
        st.session_state.next_active_main_tab = None

def get_google_user_info(token_dict: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Fetches user information from Google's userinfo endpoint.

    Args:
        token_dict: The token dictionary received from the OAuth flow.

    Returns:
        A dictionary containing user info (email, name, etc.) or None on failure.
    """
    if not token_dict or 'access_token' not in token_dict:
        return None

    access_token = token_dict['access_token']
    userinfo_endpoint = "https://www.googleapis.com/oauth2/v3/userinfo"
    headers = {'Authorization': f'Bearer {access_token}'}

    response = requests.get(userinfo_endpoint, headers=headers)
    if response.status_code == 200:
        return response.json()
    return None

def add_pending_operation_to_firestore(operation_id, operation_type, params, model_id, direct_response=None):
    """Saves a new pending operation to Firestore."""
    if not FIRESTORE_AVAILABLE:
        logger.warning("Firestore not available. Cannot save pending operation.")
        return

    try:
        doc_ref = db.collection('pending_operations').document()
        operation_data = {
            'user_id': st.session_state.user_id,
            'operation_id': operation_id,
            'operation_type': operation_type,
            'model_id': model_id,
            'params': params,
            'timestamp': firestore.SERVER_TIMESTAMP
        }
        # For synchronous operations like Imagen, store the response directly
        if direct_response:
            operation_data['direct_response'] = direct_response

        doc_ref.set(operation_data)
        logger.info(f"Saved pending {operation_type} operation to Firestore (ID: {doc_ref.id}).")
    except Exception as e:
        logger.error(f"Failed to save pending operation to Firestore: {e}")

def check_and_process_pending_operations(user_id):
    """Checks Firestore for pending operations and processes them."""
    if not FIRESTORE_AVAILABLE:
        return

    try:
        pending_ref = db.collection('pending_operations').where('user_id', '==', user_id).stream()
        pending_ops = list(pending_ref)

        if not pending_ops:
            return

        st.info(f"Found {len(pending_ops)} pending generation(s) from a previous session. Checking status...")

        for op_doc in pending_ops:
            op_data = op_doc.to_dict()
            op_id = op_data.get('operation_id')
            op_type = op_data.get('operation_type')
            model_id = op_data.get('model_id')
            params = op_data.get('params', {})
            prompt = params.get('prompt', 'N/A')
            doc_id = op_doc.id

            with st.spinner(f"Processing pending {op_type} operation..."):
                # Handle synchronous operations (like Imagen) that have a direct response
                if 'direct_response' in op_data:
                    result = op_data['direct_response']
                    is_done = True
                # Handle asynchronous long-running operations
                elif op_id and model_id:
                    client.model_id = model_id # Ensure client is using the correct model for polling
                    result = client.poll_operation(op_id)
                    is_done = result.get("done", False)
                else:
                    logger.warning(f"Skipping invalid pending operation document: {doc_id}")
                    continue

                if is_done:
                    logger.success(f"Pending operation {op_id or doc_id} is complete.")
                    # Extract URI(s) based on operation type
                    if op_type == 'video':
                        uris = client.extract_video_uris(result)
                    elif op_type in ['image', 'image_edit']:
                        uris = client.extract_image_uris(result)
                        if not uris: # Fallback for base64 encoded images
                            image_data_list = client.extract_image_data(result)
                            uris = []
                            for image_data in image_data_list:
                                img = Image.open(io.BytesIO(image_data))
                                uri = history_manager.upload_image_to_history(img, f"recovered_{uuid.uuid4().hex}.png")
                                uris.append(uri)
                    elif op_type == 'audio':
                        # For synchronous audio, the 'direct_response' will be set upon completion.
                        # If we are here, it means the process was interrupted before the direct_response
                        # could be saved. For now, we assume it failed and will remove the pending op.
                        # A more advanced implementation could check GCS for the expected output file.
                        uris = result.get('uris', [])
                    elif op_type == 'audio':
                        uris = result.get('uris', [])
                    elif op_type == 'voice':
                        # For voice, we get file paths and need to re-upload them
                        file_paths = result.get('file_paths', [])
                        uris = gemini_TTS_api.upload_audio_to_gcs(file_paths, f"{config.STORAGE_URI.rstrip('/')}/voiceovers/")
                    else:
                        uris = []

                    # Add to history and delete pending doc
                    if uris:
                        for uri in uris:
                            db.collection('history').add({
                                'user_id': user_id,
                                'timestamp': firestore.SERVER_TIMESTAMP,
                                'type': op_type, # Use the dynamic operation type
                                'uri': uri,
                                'prompt': prompt,
                                'params': params
                            })
                        st.success(f"✅ Recovered {len(uris)} generated asset(s) and added to your history.")
                    db.collection('pending_operations').document(doc_id).delete()
                    logger.info(f"Processed and removed pending operation: {doc_id}")
                elif 'direct_response' not in op_data:
                    # If the operation is not done and has no direct response, it's a genuinely pending LRO
                    # or a synchronous one that was interrupted. We can leave it for the next check.
                    logger.info(f"Pending operation {op_id or doc_id} is still in progress.")
                else:
                    # This case handles a synchronous operation that was logged but never completed.
                    # We can safely remove it.
                    logger.warning(f"Removing stale synchronous pending operation: {doc_id}")
                    db.collection('pending_operations').document(doc_id).delete()

    except Exception as e:
        logger.error(f"Error processing pending operations: {e}")
        st.error("An error occurred while checking for pending generations.")

def main():
    """Main function to run the Streamlit app."""
    logger.start_section("App Initialization")
    
    init_state() # Initialize session state
    # --- Bypass Authentication for Local Development ---
    # Check for a command-line flag to bypass authentication.
    if '--no-auth' in sys.argv:
        if "user_id" not in st.session_state:
            # If the flag is present and no user is logged in, set a default user.
            st.session_state.user_id = "local_dev_user@example.com"
            st.session_state.user_name = "Local Dev User"

    # --- OAuth2 Configuration ---
    oauth2 = OAuth2Component(
        client_id=config.GOOGLE_CLIENT_ID,
        client_secret=config.GOOGLE_CLIENT_SECRET,
        authorize_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
        token_endpoint="https://oauth2.googleapis.com/token",
        refresh_token_endpoint=None, # Google uses the same endpoint for refresh
        revoke_token_endpoint="https://oauth2.googleapis.com/revoke",
    )
    # --- Password Hashing and Verification Helpers ---
    def hash_password(password):
        """Returns the SHA-256 hash of the password."""
        return hashlib.sha256(str.encode(password)).hexdigest()

    def verify_password(stored_hash, provided_password):
        """Verifies a provided password against a stored hash."""
        return stored_hash == hash_password(provided_password)

    # --- Check for and process any pending operations from previous sessions ---
    # This runs only once per session after the user is logged in.
    if 'user_id' in st.session_state and not st.session_state.get('pending_ops_checked', False):
        check_and_process_pending_operations(st.session_state.user_id)
        st.session_state.pending_ops_checked = True # Set flag to prevent re-checking

    # If we have a token, but no user_id, the user is returning to the session
    # We need to fetch their info
    if 'token' in st.session_state and st.session_state.token and 'user_id' not in st.session_state:
        user_info = get_google_user_info(st.session_state['token'])
        if user_info:
            st.session_state['user_id'] = user_info.get("email")
            st.session_state['user_name'] = user_info.get("name")
        else:
            # If token is invalid, clear it
            st.session_state.token = None

    # --- Authentication Gate ---
    if 'user_id' not in st.session_state:
        st.set_page_config(page_title="Login - Media Gen Tool")
        st.title("🎬 Welcome to the Google AI Media Generator")
        st.subheader("Please sign in to continue")

        result = oauth2.authorize_button(
            name="Sign in with Google",
            icon="https://www.google.com.tw/favicon.ico",
            redirect_uri=config.REDIRECT_URI,
            scope="openid email profile",
            key="google_login",
            use_container_width=True,
        )

        if result and "token" in result:
            st.session_state.token = result.get('token')
            st.rerun()

        return  # Stop execution until the user is logged in
    
    # Run the setup function to configure the page, theme, and handle tab switches.
    _setup_page()

    # Sidebar for configuration
    with st.sidebar:
        # App title
        st.markdown("## ⚙️ Settings")
        
        # Google Cloud Settings
        st.markdown('<div class="sidebar-section">', unsafe_allow_html=True)
        st.markdown("### Google Cloud Settings")
        
        # Project ID
        project_id = st.text_input(
            "Project ID", 
            value=config.PROJECT_ID,
            help="Your Google Cloud Project ID"
        )
        
        
        # Update session state for project ID if changed
        if "project_id" not in st.session_state or st.session_state.project_id != project_id:
            st.session_state.project_id = project_id
            logger.info(f"Updated project_id in session state: {project_id}")
        
        # Storage URI
        storage_uri = st.text_input(
            "Storage URI", 
            value=config.STORAGE_URI,
            help="GCS URI for storing generated videos (gs://bucket-name)"
        )
        
        # Update session state for storage URI if changed
        if "storage_uri" not in st.session_state or st.session_state.storage_uri != storage_uri:
            st.session_state.storage_uri = storage_uri
            logger.info(f"Updated storage_uri in session state: {storage_uri}")
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Advanced Settings in a cleaner collapsible section
        st.markdown('<div class="sidebar-section">', unsafe_allow_html=True)
        st.markdown("### Advanced Settings")
        
        with st.expander("API Options", expanded=False):
            # Polling settings
            st.markdown("#### Polling Settings")
            wait_for_completion = st.checkbox(
                "Wait for completion", 
                value=config.DEFAULT_WAIT_FOR_COMPLETION,
                help="Wait for the video to complete generation"
            )
            
            # Update session state
            if "wait_for_completion" not in st.session_state or st.session_state.wait_for_completion != wait_for_completion:
                st.session_state.wait_for_completion = wait_for_completion
            
            if wait_for_completion:
                col1, col2 = st.columns(2)
                with col1:
                    poll_interval = st.number_input(
                        "Poll interval (seconds)", 
                        min_value=1, 
                        max_value=60, 
                        value=config.DEFAULT_POLL_INTERVAL,
                        help="How often to check for completion"
                    )
                    
                    # Update session state
                    if "poll_interval" not in st.session_state or st.session_state.poll_interval != poll_interval:
                        st.session_state.poll_interval = poll_interval
                
                with col2:
                    max_poll_attempts = st.number_input(
                        "Max poll attempts", 
                        min_value=1, 
                        max_value=100, 
                        value=config.DEFAULT_MAX_POLL_ATTEMPTS,
                        help="Max number of times to check for completion"
                    )
                    
                    # Update session state
                    if "max_poll_attempts" not in st.session_state or st.session_state.max_poll_attempts != max_poll_attempts:
                        st.session_state.max_poll_attempts = max_poll_attempts
        
        with st.expander("Display Options", expanded=False):
            # Display settings
            show_full_response = st.checkbox(
                "Show API responses", 
                value=config.DEFAULT_SHOW_FULL_RESPONSE,
                help="Display the full API response JSON"
            )
            
            # Update session state
            if "show_full_response" not in st.session_state or st.session_state.show_full_response != show_full_response:
                st.session_state.show_full_response = show_full_response
            
            enable_streaming = st.checkbox(
                "Enable video streaming", 
                value=config.DEFAULT_ENABLE_STREAMING,
                help="Stream videos directly from Google Cloud Storage"
            )
            
            # Update session state
            if "enable_streaming" not in st.session_state or st.session_state.enable_streaming != enable_streaming:
                st.session_state.enable_streaming = enable_streaming
            
            # Debug mode
            debug_mode = st.checkbox(
                "Debug Mode", 
                value=config.DEBUG_MODE,
                help="Show detailed logging information"
            )
            
            # Update session state and logger config
            if "debug_mode" not in st.session_state or st.session_state.debug_mode != debug_mode:
                st.session_state.debug_mode = debug_mode
                logger.debug_mode = debug_mode
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Display configuration summary if in debug mode
        if debug_mode:
            with st.expander("Current Configuration", expanded=False):
                st.write("Project ID:", project_id)
                st.write("Storage URI:", storage_uri)
                st.write("Wait for completion:", wait_for_completion)
                if wait_for_completion:
                    st.write("Poll interval:", poll_interval)
                    st.write("Max poll attempts:", max_poll_attempts)
                st.write("Show full response:", show_full_response)
                st.write("Enable streaming:", enable_streaming)
                st.write("Session State Keys:", list(st.session_state.keys()))
    
    # Check for critical configuration issues
    if not project_id:
        st.error("⚠️ Project ID is required. Please set it in the sidebar.")
        logger.error("Project ID is missing")
        return
    
    if not storage_uri and st.session_state.active_tab != "text_to_video":
        st.warning("⚠️ Storage URI is required for image-to-video generation and history features.")
        logger.warning("Storage URI is missing")
    
    # Add a file change notification at the top
    # st.caption(f"App last updated: {time.strftime('%Y-%m-%d')}")
    
    # Main content area with tabs - simple approach without extra complexity
    title_col, toggle_col = st.columns([5, 1])
    with title_col:
        st.title("📽️ Google AI Media Generator")
    with toggle_col:
        st.toggle("🌙 Dark Mode", key="dark_mode", help="Toggle between light and dark themes.")
    
    # --- User Info and Logout Button ---
    user_col, _, logout_col = st.columns([4, 1, 1])
    with user_col:
        st.markdown(f"👤 **Logged in as:** {st.session_state.user_id}")
    with logout_col:
        if st.button("🚪 Logout", key="logout_button"):
            st.session_state.clear()
            st.query_params.clear() # Remove user from query params on logout
            st.rerun()

    # Define the main tabs and their corresponding functions
    TABS = OrderedDict([
        ("🎬 Video", video_tab),
        ("🎨 Image", image_tab),
        ("🎵 Audio", audio_tab),
        ("♊ Gemini", gemini_chat_tab),
        ("📋 History", history_tab),
    ])
    # Use a radio button for main navigation that is directly tied to the session state.
    # This is the standard way to create a "controlled" widget in Streamlit.
    st.radio(
        "Main Navigation",
        options=list(TABS.keys()),
        horizontal=True,
        label_visibility="collapsed",
        key="active_main_tab"  # Directly link the widget to the session state key.
    )

    # Call the function for the currently active tab
    TABS[st.session_state.active_main_tab]()

    # Remove the footer which might be causing spacing issues
    # st.markdown('<div class="footer">', unsafe_allow_html=True)
    # st.markdown('Veo2 Video Generator • Built with Streamlit • Powered by Google Cloud')
    # st.markdown('</div>', unsafe_allow_html=True)
    
    logger.end_section()

def video_tab():
    """Main tab for all video-related operations."""
    # Define the video sub-tabs and their corresponding functions
    sub_tabs = OrderedDict([
        ("Text-to-Video", text_to_video_tab),
        ("Image-to-Video", image_to_video_tab),
        ("Video Editing", video_editing_tab),
    ])

    # Use a radio button styled as tabs for sub-navigation.
    # This is a "controlled" component, allowing programmatic switching.
    st.radio(
        "Video Sub-Navigation",
        options=list(sub_tabs.keys()),
        horizontal=True,
        label_visibility="collapsed",
        key="active_video_sub_tab"  # Directly link to session state
    )

    # Call the function for the currently active sub-tab
    active_sub_tab_func = sub_tabs.get(st.session_state.active_video_sub_tab)
    if active_sub_tab_func:
        active_sub_tab_func()
    else:
        # Fallback to the first tab if the state is somehow invalid
        text_to_video_tab()

def image_tab():
    """Main tab for all image-related operations."""
    # Define the image sub-tabs and their corresponding functions
    sub_tabs = OrderedDict([
        ("Text-to-Image", text_to_image_tab),
        ("Image Editing (Nano Banana)", image_editing_tab),
    ])

    # Use a radio button for controlled sub-navigation
    st.radio(
        "Image Sub-Navigation",
        options=list(sub_tabs.keys()),
        horizontal=True,
        label_visibility="collapsed",
        key="active_image_sub_tab" # Directly link to session state
    )

    # Call the function for the active sub-tab
    active_sub_tab_func = sub_tabs.get(st.session_state.active_image_sub_tab)
    if active_sub_tab_func:
        active_sub_tab_func()
    else:
        # Fallback to the first tab
        text_to_image_tab()

def audio_tab():
    """Main tab for all audio-related operations."""
    # Define the audio sub-tabs and their corresponding functions
    sub_tabs = OrderedDict([
        ("Text-to-Audio", text_to_audio_tab),
        ("Text-to-Voiceover", text_to_voiceover_tab),
    ])

    # Use a radio button for controlled sub-navigation
    st.radio(
        "Audio Sub-Navigation",
        options=list(sub_tabs.keys()),
        horizontal=True,
        label_visibility="collapsed",
        key="active_audio_sub_tab" # Directly link to session state
    )

    # Call the function for the active sub-tab
    active_sub_tab_func = sub_tabs.get(st.session_state.active_audio_sub_tab)
    if active_sub_tab_func:
        active_sub_tab_func()
    else:
        # Fallback to the first tab
        text_to_audio_tab()

def gemini_chat_tab():
    """A tab for multimodal chat with Gemini."""
    st.header("Chat with Gemini")

    # Model selection
    model_name = st.selectbox(
        "Select Gemini Model",
        options=["gemini-2.5-pro", "gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.0-flash-001", "gemini-2.0-flash-lite-001", "gemini-1.5-pro-002"],
        key="gemini_chat_model",
        help="Choose the Gemini model to chat with. 'Flash' is faster, 'Pro' is more capable."
    )

    # System instructions input
    system_instructions = st.text_area(
        "System Instructions (Optional)",
        placeholder="e.g., You are a helpful assistant that speaks like a pirate.",
        help="Provide instructions to guide the model's behavior and personality.",
        key="gemini_system_instructions"
    )

    # Advanced settings for temperature and grounding
    with st.expander("Advanced Settings"):
        temperature = st.slider(
            "Temperature",
            min_value=0.0,
            max_value=2.0,
            value=1.0,
            step=0.1,
            help="Controls the randomness of the output. Lower values are more deterministic, higher values are more creative."
        )
        enable_grounding = st.toggle(
            "Enable Google Search Grounding",
            value=False,
            help="Allows the model to use Google Search to ground its responses with real-time information."
        )

    # --- Microphone Input ---
    # Place the mic recorder next to the file uploader.
    st.write("OR")
    # The mic_recorder returns audio data when the user stops recording
    audio_data = mic_recorder(start_prompt="🎤 Start Recording", stop_prompt="⏹️ Stop Recording", key='gemini_mic')


    # File uploader for multimodal input
    uploaded_file = st.file_uploader(
        "Upload an image, audio, or video file (optional)",
        type=["jpg", "jpeg", "png", "webp", "mp3", "wav", "mp4", "mov", "avi", "mkv", "txt", "pdf"],
        key=f"gemini_chat_uploader_{st.session_state.gemini_uploader_key_counter}"
    )

    # --- Handle Inputs ---
    # We prioritize the last provided input: microphone audio takes precedence over file upload.
    input_file_for_gemini = None
    # A flag to indicate if we should trigger the API call automatically for audio.
    trigger_from_audio = False
    prompt_for_api = ""

    if audio_data and audio_data['bytes']:
        st.info("🎤 Voice recording is ready to be sent with your next message.")
        st.audio(audio_data['bytes'])
        # Wrap the recorded audio bytes in our file-like object for the API helper
        input_file_for_gemini = SimulatedUploadFile(name="voice_recording.wav", content=audio_data['bytes'])
        input_file_for_gemini.type = "audio/wav" # Set the mime type

        # Set the flag to trigger the API call and provide a default prompt for the model.
        trigger_from_audio = True
        prompt_for_api = "Analyze the provided audio and respond to the query within it."

    elif uploaded_file:
        file_type = uploaded_file.type.split('/')[0]
        st.info(f"File '{uploaded_file.name}' is ready to be sent with your next message.")
        if file_type == "image":
            st.image(uploaded_file, width=200)
        elif file_type == "audio":
            st.audio(uploaded_file)
        elif file_type == "video":
            st.video(uploaded_file)
        input_file_for_gemini = uploaded_file

    # Display chat messages from history
    for message in st.session_state.gemini_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"]["text"])
            if message["content"].get("citations"):
                with st.expander("View Citations"):
                    for i, citation in enumerate(message["content"]["citations"], 1):
                        st.markdown(f"**[{i}] [{citation['title']}]({citation['uri']})**")

    # --- Clear Chat Button ---
    # Place the button at the bottom, just above the chat input.
    # Use columns to align the button to the right for a cleaner look.
    _, button_col = st.columns([4, 1])
    with button_col:
        if st.button("🗑️ Clear Chat", key="clear_gemini_chat_bottom", help="Clear chat history and remove uploaded files."):
            # Clear the chat message history
            st.session_state.gemini_messages = []
            # Increment the counter to force a re-render of the file_uploader with a new key
            st.session_state.gemini_uploader_key_counter += 1
            # Rerun the app to reflect the changes immediately
            st.rerun()

    # React to user input
    if text_prompt := st.chat_input("What would you like to ask Gemini?"):
        # If the user types a message, it takes precedence.
        trigger_from_audio = False
        prompt_for_api = text_prompt

    # Trigger the API call if either a text prompt was entered or an audio recording was made.
    if prompt_for_api:
        # Add user message to chat history
        st.session_state.gemini_messages.append({
            "role": "user",
            "content": {"text": prompt_for_api, "citations": []}
        })
        # Display user message in chat message container
        # with st.chat_message("user"):
            # st.markdown(prompt_for_api)

        # Display assistant response in chat message container
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            citations_placeholder = st.empty()
            response_content = {"text": "", "citations": []}

            with st.spinner("Gemini is thinking..." if not trigger_from_audio else "Processing audio..."):
                try:
                    # Use the existing gemini_helper for the API call
                    # This function is assumed to return a dict: {'text': str, 'citations': list}
                    response_dict = gemini_helper.generate_gemini_chat_response(
                        model_name=model_name,
                        prompt=prompt_for_api,
                        uploaded_file=input_file_for_gemini, # Pass the selected input
                        system_instructions=system_instructions,
                        temperature=temperature,
                        enable_grounding=enable_grounding
                    )
                    # Handle both dict (with citations) and str (without) responses
                    if isinstance(response_dict, dict):
                        response_content["text"] = response_dict.get("text", "No response text found.")
                        response_content["citations"] = response_dict.get("citations", [])
                    else:
                        # Handle the case where a simple string is returned
                        response_content["text"] = response_dict
                        response_content["citations"] = []

                except Exception as e:
                    response_content["text"] = f"An error occurred: {e}"
                    st.error(response_content["text"])

            # Display the main response text
            message_placeholder.markdown(response_content["text"])

            # Display citations if they exist
            if response_content["citations"]:
                with citations_placeholder.expander("View Citations"):
                    for i, citation in enumerate(response_content["citations"], 1):
                        st.markdown(f"**[{i}] [{citation['title']}]({citation['uri']})**")

        # Add assistant response to chat history
        st.session_state.gemini_messages.append({"role": "assistant", "content": response_content})

def text_to_image_tab():
    """Text-to-Image generation tab."""
    st.header("Text-to-Image Generation with Imagen")

    prompt = st.text_area(
        "Prompt",
        value="A majestic lion with a glowing mane, standing on a cliff overlooking a futuristic city at sunset, cinematic lighting.",
        height=100,
        help="Describe the image you want to generate.",
        key="t2i_prompt"
    )

    col1, col2 = st.columns(2)
    with col1:
        model = st.selectbox(
            "Model",
            # Using placeholder names as requested. User can change if needed.
            options=["imagen-4.0-generate-001", "imagen-4.0-ultra-generate-001", "imagen-4.0-fast-generate-001", "imagen-3.0-generate-002","imagen-3.0-fast-generate-001"],
            index=0,
            help="Choose the Imagen model for generation.",
            key="t2i_model"
        )
    with col2:
        aspect_ratio = st.selectbox(
            "Aspect Ratio",
            options=["1:1", "9:16", "16:9", "3:4", "4:3"],
            index=0,
            help="Choose the aspect ratio of the generated image.",
            key="t2i_aspect_ratio"
        )

    col1, col2 = st.columns(2)
    with col1:
        sample_count = st.slider(
            "Number of Images",
            min_value=1,
            max_value=4,
            value=1,
            help="How many image variations to generate.",
            key="t2i_sample_count"
        )
    with col2:
        resolution = st.selectbox(
            "Output Resolution", 
            options=["1K", "2K"] if model == "imagen-4.0-generate-001" or model == "imagen-4.0-ultra-generate-001" else ["1k"], 
            index=0, 
            disabled=model != "imagen-4.0-generate-001" and model != "imagen-4.0-ultra-generate-001", 
            help="Choose the resolution of the generated image.", 
            key="text_image_resolution"
        )

    enhance_prompt = st.checkbox(
        "Enhance Prompt",
        value=True,
        help="Use Gemini to enhance your prompt.",
        key="t2i_enhance_prompt"
    )


    with st.expander("Advanced Options"):
        negative_prompt = st.text_area(
            "Negative Prompt",
            value="blurry, low quality, ugly, deformed, text, watermark",
            help="Describe what to avoid in the image.",
            key="t2i_negative_prompt"
        )

        col1_adv, col2_adv = st.columns(2)
        with col1_adv:
            person_generation = st.selectbox(
                "Person Generation",
                options=["Allow", "Don't Allow"],
                index=0,
                help="Allow or disallow the generation of people.",
                key="t2i_person_generation"
            )

        with col2_adv:
            safety_filter_threshold = st.selectbox(
                "Safety Filter Strength",
                options=["BLOCK_MOST", "BLOCK_SOME", "BLOCK_FEW", "BLOCK_NONE"],
                index=2,
                help="Set the threshold for safety filters.",
                key="t2i_safety_threshold"
            )

    if st.button("🎨 Generate Image", key="t2i_generate", type="primary"):
        generate_image(
            project_id=st.session_state.get("project_id", config.PROJECT_ID),
            prompt=prompt,
            model=model,
            negative_prompt=negative_prompt,
            sample_count=sample_count,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
            seed=None, # Seed not exposed in this UI for simplicity
            person_generation=person_generation,
            safety_filter_level=safety_filter_threshold,
            enhance_prompt=enhance_prompt,
            storage_uri=st.session_state.get("storage_uri", config.STORAGE_URI),
        )

def image_editing_tab():
    """Image editing tab."""
    st.header("Image Editing with Gemini")
    
    # This callback is triggered when the file_uploader's value changes.
    # It syncs the widget's state to our application's state variable.
    def _sync_edit_image_files():
        st.session_state.edit_image_files = st.session_state.get("edit_image_uploader", [])
    
    st.file_uploader(
        "Upload images to edit (or load from history)",
        type=["jpg", "jpeg", "png", "webp"],
        key="edit_image_uploader",
        accept_multiple_files=True,
        on_change=_sync_edit_image_files,
    )

    # The primary source of truth for images to be edited.
    input_image_files = st.session_state.get('edit_image_files', [])

    # Display uploaded images
    if input_image_files:
        # Convert all file-like objects to PIL Images for display
        # This handles both Streamlit's UploadedFile and our SimulatedUploadFile
        try:
            images_to_display = [Image.open(f) for f in input_image_files]
            # Create a list of captions from the filenames
            captions = [f.name for f in input_image_files]
            st.image(images_to_display, caption=captions, width=128)
            
            def _clear_edit_images_callback():
                st.session_state.edit_image_files = []
            st.button("🗑️ Clear Loaded Images", key="clear_edit_images", on_click=_clear_edit_images_callback)

        except Exception as e:
            st.error(f"Could not display one of the loaded images: {e}")

    prompt = st.text_area(
        "Prompt",
        value="Make the lion's mane glow brighter and change the sky to a deep purple.",
        height=100,
        help="Describe the edits you want to make.",
        key="i2i_prompt"
    )

    col1, col2 = st.columns(2)
    with col1:
        model = st.selectbox(
            "Model",
            options=["gemini-2.5-flash-image"],
            index=0,
            help="Choose the model for editing.",
            key="i2i_model"
        )
    with col2:
        aspect_ratio = st.selectbox(
            "Aspect Ratio",
            options=["1:1", "3:2", "2:3", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"],
            index=0,
            help="Choose the aspect ratio of the edited image.",
            key="i2i_aspect_ratio"
        )



    enhance_prompt = st.checkbox(
        "Enhance Prompt",
        value=True,
        help="Use Gemini to enhance your prompt.",
        key="i2i_enhance_prompt"
    )

    if st.button("🎨 Edit Image", key="i2i_generate", type="primary"):
        
        if not input_image_files:
            st.error("Please upload an input image to edit.")
            return

       
        input_image_paths = []
        try:
            
            for uploaded_file in input_image_files:
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp_in:
                    tmp_in.write(uploaded_file.getvalue())
                    input_image_paths.append(tmp_in.name)

            edit_image(
                project_id=st.session_state.get("project_id", config.PROJECT_ID),
                prompt=prompt,
                model=model,
                aspect_ratio=aspect_ratio,
                seed=None,
                person_generation="Don't Allow",
                safety_filter_level="OFF",
                enhance_prompt=enhance_prompt,
                storage_uri=st.session_state.get("storage_uri", config.STORAGE_URI),
                input_image_paths=input_image_paths,
            )
        finally:
            # Clean up temporary files
            for path in input_image_paths:
                os.unlink(path)

def text_to_video_tab():
    """Text-to-Video generation tab."""
    st.header("Text-to-Video Generation")
    
    # Text prompt
    prompt = st.text_area(
        "Prompt", 
        value=config.DEFAULT_TEXT_PROMPT,
        height=100,
        help="Describe the video you want to generate",
        key="text_prompt"
    )

    model = st.selectbox(
        "Model",
        options=["veo-3.1-generate-preview", "veo-3.1-generate-fast-preview", "veo-3.0-generate-preview", "veo-3.0-fast-generate-preview", "veo-3.0-fast-generate-001", "veo-3.0-generate-001", "veo-2.0-generate-001"],  # Assuming these are the model IDs
        index=0,  # Default to Veo 3
        help="Choose the video generation model (Veo 2 or Veo 3)",
        key="text_model"
    )

    # Audio and resolution options (Veo 3.0 only)
    enable_audio = st.checkbox("Add Audio", value=False if model == "veo-2.0-generate-001" else True, disabled=model == "veo-2.0-generate-001", key="text_enable_audio")
    resolution = st.selectbox("Resolution", options=["720p"] if model == "veo-2.0-generate-001" else ["720p", "1080p"], index=0, disabled=model == "veo-2.0-generate-001", key="text_video_resolution")

    
    # Video settings
    col1, col2, col3 = st.columns(3)
    with col1:
        aspect_ratio = st.selectbox(
            "Aspect Ratio", 
            options=["16:9", "9:16"],
            index=0,
            help="Choose landscape (16:9) or portrait (9:16) orientation. Veo 3.0 is fixed to 16:9.",
            key="text_aspect_ratio"
        )
    with col2:
        duration = st.slider(
            "Duration (seconds)", 
            min_value=5, 
            max_value=8,
            value=config.DEFAULT_DURATION_SECONDS,
            help="Length of the generated video",
            key="text_duration"
        )
    with col3:
        sample_count = st.slider(
            "Number of Videos", 
            min_value=1, 
            max_value=4,
            value=config.DEFAULT_SAMPLE_COUNT,
            help="Generate multiple variations (requires storage_uri)",
            key="text_sample_count"
        )
    
    # Advanced options
    with st.expander("Advanced Options"):
        negative_prompt = st.text_area(
            "Negative Prompt", 
            value=config.DEFAULT_NEGATIVE_PROMPT,
            height=100,
            help="Describe what you want to avoid in the video",
            key="text_negative_prompt"
        )
            
        col1, col2 = st.columns(2)
        with col1:
            person_generation = st.selectbox(
                "Person Generation", 
                options=["allow_adult", "disallow"],
                index=0,
                help="Safety setting for people/faces",
                key="text_person_generation"
            )
        with col2:
            enhance_prompt = st.checkbox(
                "Enhance Prompt",
                value=True,
                help="Use Gemini to enhance your prompt",
                key="text_enhance_prompt"
            )
        
        seed = st.number_input(
            "Seed",
            min_value=0,
            max_value=4294967295,
            value=None,
            help="Optional seed for deterministic generation",
            key="text_seed"
        )
        if seed is not None and seed == 0:
            seed = None  # Treat 0 as None
    
    # Generate button

    if st.button("🚀 Generate Video", key="text_generate"):
        generate_video(
            project_id=st.session_state.get("project_id", config.PROJECT_ID),
            prompt=prompt,
            input_image=None,
            aspect_ratio=aspect_ratio,
            negative_prompt=negative_prompt,
            person_generation=person_generation,
            resolution=resolution,
            enable_audio=enable_audio,
            model=model,  # Pass the selected model
            sample_count=sample_count,
            seed=seed,
            storage_uri=st.session_state.get("storage_uri", config.STORAGE_URI),
            duration_seconds=duration,
            enhance_prompt=enhance_prompt,
            wait_for_completion=st.session_state.get("wait_for_completion", True),
            poll_interval=st.session_state.get("poll_interval", config.DEFAULT_POLL_INTERVAL),
            max_attempts=st.session_state.get("max_poll_attempts", config.DEFAULT_MAX_POLL_ATTEMPTS),
            show_full_response=st.session_state.get("show_full_response", False),
            enable_streaming=st.session_state.get("enable_streaming", True),
        )

def text_to_audio_tab():
    """Text-to-Audio generation tab."""
    st.header("Text-to-Audio Generation")

    # Text prompt for audio
    prompt = st.text_area(
        "Prompt",
        value="A futuristic synthwave track with a driving bassline and atmospheric pads.",
        height=100,
        help="Describe the audio you want to generate",
        key="audio_prompt"
    )

    # Number of results slider
    # sample_count = st.slider(
    #     "Number of Results",
    #     min_value=1,
    #     max_value=4,
    #     value=1,
    #     help="Generate multiple audio variations",
    #     key="audio_sample_count"
    # )

    # Seed input and Sample count interaction
    # seed_disabled = sample_count > 1
    # seed_help_text = "Optional seed for deterministic generation"
    # if seed_disabled:
    #     seed_help_text += " (disabled for more than one sample)"
    seed = st.number_input(
        "Seed",
        min_value=0,
        max_value=4294967295,
        value=None,
        # help=seed_help_text,
        key="audio_seed",
        # disabled=seed_disabled
    )
    if seed is not None and seed == 0:
        seed = None  # Treat 0 as None

    # Disable sample count if seed is provided
    sample_count_disabled = seed is not None

    # Advanced options for audio
    with st.expander("Advanced Options"):
        negative_prompt = st.text_area(
            "Negative Prompt",
            value="low quality, muffled, distorted",
            help="Describe sounds or qualities to avoid",
            key="audio_negative_prompt"
        )

    base_uri = st.session_state.get("storage_uri", config.STORAGE_URI)

    # Generate button 
    if st.button("🎵 Generate Audio", key="audio_generate"):
        generate_audio(
            project_id=st.session_state.get("project_id", config.PROJECT_ID),
            prompt=prompt,
            sample_count=1,
            negative_prompt=negative_prompt,
            seed=seed,
            storage_uri=f"{base_uri.rstrip('/')}/generated_audio/",
            wait_for_completion=st.session_state.get("wait_for_completion", True),
            poll_interval=st.session_state.get("poll_interval", config.DEFAULT_POLL_INTERVAL),
            max_attempts=st.session_state.get("max_poll_attempts", config.DEFAULT_MAX_POLL_ATTEMPTS),
            show_full_response=st.session_state.get("show_full_response", False),
            enable_streaming=st.session_state.get("enable_streaming", True),
    )


def text_to_voiceover_tab():
    """Text-to-Voiceover generation tab based on the provided UI image."""
    st.header("Generate Speech")

    # --- Initialize State ---
    if 'voiceover_dialogs' not in st.session_state:
        st.session_state.voiceover_dialogs = [
            {
                "id": 1,
                "name": "Speaker 1",
                "text": "Hello! We're excited to show you our native speech capabilities",
                "voice": "Zar"
            },
            {
                "id": 2,
                "name": "Speaker 2",
                "text": "Where you can direct a voice, create realistic dialog, and so much more. Edit these placeholders to get started.",
                "voice": "Puck"
            }
        ]
    if 'voiceover_mode' not in st.session_state:
        st.session_state.voiceover_mode = 'Multi-speaker audio'
    if 'next_speaker_id' not in st.session_state:
        st.session_state.next_speaker_id = 3
    if 'voiceover_run_setting' not in st.session_state:
        st.session_state.voiceover_run_setting = "gemini-2.5-flash-preview-tts"

    # Define available voices
    VOICE_OPTIONS = ["Zar", "Puck", "Chirp", "Echo", "Onyx", "Nova", "Alloy", "Fable", "Shimmer"]

    # --- Main Layout ---
    left_col, right_col = st.columns(2)

    with left_col:
        st.subheader("Script builder")

        # Style instructions
        style_instructions = st.text_area(
            "Style instructions",
            "Read aloud in a warm, welcoming tone.",
            height=100,
            key="voiceover_style"
        )

        # Handle single vs. multi-speaker mode for script input
        if st.session_state.voiceover_mode == 'Single-speaker audio':
            # If there's more than one speaker, consolidate their text
            if len(st.session_state.voiceover_dialogs) > 1:
                full_text = "\n".join([d['text'] for d in st.session_state.voiceover_dialogs])
                # Keep the first speaker's settings but update the text
                st.session_state.voiceover_dialogs = [st.session_state.voiceover_dialogs[0]]
                st.session_state.voiceover_dialogs[0]['text'] = full_text
            
            # Display single text area
            st.session_state.voiceover_dialogs[0]['text'] = st.text_area(
                "Script",
                value=st.session_state.voiceover_dialogs[0]['text'],
                height=250,
                key="single_speaker_text"
            )

        else: # Multi-speaker mode
            # Dynamically display dialog entries
            for i, dialog in enumerate(st.session_state.voiceover_dialogs):
                with st.container(border=True):
                    col1, col2 = st.columns([0.9, 0.1])
                    with col1:
                        st.markdown(f"**{dialog['name']}**")
                    with col2:
                        # Add a delete button, but not for the last remaining speaker
                        if len(st.session_state.voiceover_dialogs) > 1:
                            if st.button("✖", key=f"delete_{dialog['id']}", help="Remove this dialog"):
                                st.session_state.voiceover_dialogs.pop(i)
                                st.rerun()
                    
                    # Text input for the dialog
                    new_text = st.text_area(
                        "Dialog",
                        value=dialog['text'],
                        key=f"text_{dialog['id']}",
                        label_visibility="collapsed"
                    )
                    st.session_state.voiceover_dialogs[i]['text'] = new_text

            # "Add dialog" button
            if st.button("➕ Add dialog"):
                new_speaker_id = st.session_state.next_speaker_id
                st.session_state.voiceover_dialogs.append({
                    "id": new_speaker_id,
                    "name": f"Speaker {new_speaker_id}",
                    "text": "",
                    "voice": VOICE_OPTIONS[0]
                })
                st.session_state.next_speaker_id += 1
                st.rerun()

    with right_col:
        st.subheader("Settings")

        # Run setting selection
        st.session_state.voiceover_run_setting = st.selectbox(
            "Run setting",
            options=["gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts"],
            key="voiceover_run_select",
            help="Choose the Text-to-Speech model for generation."
        )

        # Mode selection
        st.session_state.voiceover_mode = st.radio(
            "Mode",
            ['Single-speaker audio', 'Multi-speaker audio'],
            index=1 if st.session_state.voiceover_mode == 'Multi-speaker audio' else 0,
            key="voiceover_mode_radio",
            horizontal=True
        )

        # --- Voice Settings ---
        st.markdown("##### Voice settings")
        if st.session_state.voiceover_mode == 'Single-speaker audio':
            # Ensure there's at least one speaker to configure
            if not st.session_state.voiceover_dialogs:
                 st.session_state.voiceover_dialogs.append({
                    "id": 1, "name": "Speaker 1", "text": "", "voice": VOICE_OPTIONS[0]
                })
            
            # Display settings for the single speaker
            speaker = st.session_state.voiceover_dialogs[0]
            with st.container(border=True):
                col1, col2 = st.columns(2)
                with col1:
                    speaker['name'] = st.text_input("Name", value=speaker['name'], key="name_single")
                with col2:
                    speaker['voice'] = st.selectbox("Voice", VOICE_OPTIONS, index=VOICE_OPTIONS.index(speaker['voice']), key="voice_single")

        else: # Multi-speaker mode
            for i, dialog in enumerate(st.session_state.voiceover_dialogs):
                with st.container(border=True):
                    st.markdown(f"**Speaker {i+1} settings**")
                    col1, col2 = st.columns(2)
                    with col1:
                        # Editable speaker name
                        new_name = st.text_input("Name", value=dialog['name'], key=f"name_{dialog['id']}")
                        st.session_state.voiceover_dialogs[i]['name'] = new_name
                    with col2:
                        # Voice selection
                        current_voice = dialog.get('voice', VOICE_OPTIONS[0])
                        if current_voice not in VOICE_OPTIONS:
                            current_voice = VOICE_OPTIONS[0]
                        voice_index = VOICE_OPTIONS.index(current_voice)
                        new_voice = st.selectbox("Voice", VOICE_OPTIONS, index=voice_index, key=f"voice_{dialog['id']}")
                        st.session_state.voiceover_dialogs[i]['voice'] = new_voice

    st.divider()
    # --- Bottom bar emulation ---
    st.subheader("Script Templates")
    template_cols = st.columns(4)
    with template_cols[0]:
        if st.button("🎙️ Podcast Intro"):
            st.session_state.voiceover_mode = 'Multi-speaker audio'
            st.session_state.voiceover_dialogs = [
                {"id": 1, "name": "Host", "text": "Welcome back to Tech Forward, the podcast that looks at the future of technology. I'm your host, Alex.", "voice": "Alloy"},
                {"id": 2, "name": "Co-host", "text": "And I'm Jordan. Today, we have a fascinating topic: the rise of generative AI in creative fields.", "voice": "Echo"}
            ]
            st.session_state.next_speaker_id = 3
            st.rerun()

    with template_cols[1]:
        if st.button("🎬 Movie Scene"):
            st.session_state.voiceover_mode = 'Multi-speaker audio'
            st.session_state.voiceover_dialogs = [
                {"id": 1, "name": "Detective K", "text": "The files... they're gone. Wiped clean. There's nothing left.", "voice": "Onyx"},
                {"id": 2, "name": "Agent S", "text": "Nothing is ever truly gone. They left a trace. They always do.", "voice": "Fable"}
            ]
            st.session_state.next_speaker_id = 3
            st.rerun()

    with template_cols[2]:
        if st.button("📢 Ad Read"):
            st.session_state.voiceover_mode = 'Single-speaker audio'
            st.session_state.voiceover_dialogs = [
                {"id": 1, "name": "Announcer", "text": "Tired of slow internet? Upgrade to Quantum-Link today and experience speeds you've only dreamed of. Visit quantumlink.com to learn more.", "voice": "Nova"},
            ]
            st.session_state.next_speaker_id = 2
            st.rerun()

    # --- Run Button ---
    if st.button("▶️ Run", type="primary", use_container_width=True):
        try:
            # Collect the style instructions
            full_script = style_instructions + "\n"
            
            # Build the script based on mode
            if st.session_state.voiceover_mode == 'Single-speaker audio':
                speaker = st.session_state.voiceover_dialogs[0]
                full_script += f"{speaker['name']}: {speaker['text']}"
            else: # Multi-speaker
                for dialog in st.session_state.voiceover_dialogs:
                    full_script += f"{dialog['name']}: {dialog['text']}\n"

            # Call the voiceover generation
            with st.spinner("Generating voiceover..."):
                # Call the external function from gemini_TTS_api.py
                # The call is modified to use the new function structure.
                # Assuming generate_voiceover() now takes the script as an argument
                # and returns a list of local file paths.
                voiceover_model = st.session_state.voiceover_run_setting
                import apis.gemini_TTS_api as gemini_TTS_api
                file_paths = gemini_TTS_api.generate_voiceover(full_script, voiceover_model)
                if file_paths:
                    st.success("Voiceover generated successfully!")
                    print(f"File saved to to: {file_paths}")
                    # Play each audio file
                    base_uri = st.session_state.get("storage_uri", config.STORAGE_URI)
                    # Construct a clean path for the voiceovers folder, avoiding the f-string syntax error.
                    storage_uri = f"{base_uri.rstrip('/')}/voiceovers/"
                    uploaded_uris = gemini_TTS_api.upload_audio_to_gcs(file_paths, storage_uri)
                    if uploaded_uris:
                        # Add to history
                        if FIRESTORE_AVAILABLE:
                            logger.info(f"Adding {len(uploaded_uris)} voice entries to Firestore history.")
                            voice_params = {
                                'model': voiceover_model,
                                'mode': st.session_state.voiceover_mode,
                                'style_instructions': style_instructions
                            }
                            for uri in uploaded_uris:
                                try:
                                    doc_ref = db.collection('history').document()
                                    doc_ref.set({
                                        'user_id': st.session_state.user_id,
                                        'timestamp': firestore.SERVER_TIMESTAMP,
                                        'type': 'voice',
                                        'uri': uri,
                                        'prompt': full_script, # The full script used for generation
                                        'params': voice_params
                                    })
                                    logger.debug(f"Added voice {uri} to Firestore history.")
                                except Exception as e:
                                    logger.error(f"Could not add voice {uri} to history: {str(e)}")
                        st.success("Files successfully uploaded to GCS")
                        for i, uri in enumerate(uploaded_uris):
                            with st.expander(f"Voiceover Segment {i + 1}", expanded=True):
                                try:
                                    st.markdown(f"**File URI:** {uri}")
                                    st.audio(client.generate_signed_url(uri), format="audio/wav")
                                except Exception as e:
                                    st.error(f"Error playing or displaying audio: {str(e)}")                                   
                    else:
                        st.error("Failed to upload files to GCS.")
                    
                        with st.expander(f"Voiceover Segment {i + 1}", expanded=True):
                            st.audio(file_paths)
                else:
                    st.error("Voiceover generation failed to return audio files.")

                try:
                    # Delete the temporary file
                    os.remove(file_paths)
                    print(f"Deleted temporary file: {file_paths}")
                except Exception as e:
                    st.error(f"Error deleting temporary audio file: {str(e)}")
        except Exception as e:
            st.error(f"An error occurred: {str(e)}")

def video_editing_tab():
    """Video editing features tab."""
    st.header("Video Editing Tools")
    
    BUCKET_NAME = None
    storage_uri_config = st.session_state.get("storage_uri", config.STORAGE_URI)
    if storage_uri_config and storage_uri_config.startswith("gs://"):
        BUCKET_NAME = storage_uri_config.replace("gs://", "").split("/")[0]
    else:
        st.warning("A valid GCS Storage URI is required for video editing.")
        return
    
    # Manage radio button state to allow programmatic changes
    options = ("Concatenate Videos", "Change Playback Speed", "Frame Interpolation", "Dubbing")    
    # Initialize the session state for the video editing tab if it doesn't exist.
    if 'video_edit_option' not in st.session_state:
        st.session_state.video_edit_option = "Concatenate Videos"
    
    # Use a key to make this a "controlled" widget. Its state is now directly
    # read from and written to st.session_state.video_edit_option.
    # This resolves the "double-click" issue.
    st.radio(
        "Choose an editing tool:",
        options,
        key="video_edit_option",
        horizontal=True,
        label_visibility="collapsed"
    )
    
    # The active option is now always read directly from the session state.
    edit_option = st.session_state.video_edit_option

    if edit_option == "Concatenate Videos":
        st.subheader("Concatenate Multiple Videos")

        newly_uploaded_videos = st.file_uploader(
            "Upload videos to concatenate (or load from history)",
            type=["mp4", "mov", "avi"],
            accept_multiple_files=True,
            key="concat_video_uploader"
        )

        if newly_uploaded_videos:
            st.session_state.concat_video_files = newly_uploaded_videos

        uploaded_videos = st.session_state.get('concat_video_files', [])

        if uploaded_videos:
            st.info(f"{len(uploaded_videos)} video(s) loaded for concatenation.")
            if st.button("Clear Loaded Videos", key="clear_concat"):
                st.session_state.concat_video_files = []
                st.session_state.concat_video_uploader = []
                st.rerun()

        if uploaded_videos and len(uploaded_videos) > 1:
            if st.button("🔗 Concatenate Videos", type="primary"):
                # Initialize variables to None before the try block for safe cleanup
                temp_files, clips = [], []
                output_filename, final_clip = None, None
                with st.spinner("Concatenating and uploading..."):
                    try:
                        for uploaded_video in uploaded_videos:
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
                                tmp.write(uploaded_video.read())
                                temp_files.append(tmp.name)

                        clips = [VideoFileClip(f) for f in temp_files]
                        final_clip = concatenate_videoclips(clips, method="compose")

                        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as out:
                            final_clip.write_videofile(out.name, codec="libx264", audio_codec="aac", threads=4, preset="ultrafast")
                            output_filename = out.name
                        
                        final_video_uri = video_upload_to_gcs(output_filename, BUCKET_NAME, "concatenated-video.mp4")
                        
                        if final_video_uri:
                            signed_url = client.generate_signed_url(final_video_uri)
                            st.subheader("Concatenated Video Preview")
                            st.video(signed_url)
                            if FIRESTORE_AVAILABLE:
                                db.collection('history').add({
                                    'user_id': st.session_state.user_id,
                                    'timestamp': firestore.SERVER_TIMESTAMP,
                                    'type': 'video',
                                    'uri': final_video_uri,
                                    'prompt': f'{len(uploaded_videos)} videos concatenated.',
                                    'params': {'operation': 'concatenate_videos'}
                                })
                    except Exception as e:
                        st.error(f"An error occurred during concatenation: {e}")
                    finally:
                        # Safely clean up all temporary files and moviepy clips
                        if final_clip: final_clip.close()
                        for clip in clips: clip.close()
                        for f in temp_files:
                            if os.path.exists(f): os.remove(f)
                        if output_filename and os.path.exists(output_filename):
                            os.remove(output_filename)

                        # with open(output_filename, "rb") as f:
                        #     video_bytes = f.read()

                        # st.video(video_bytes)
                        # st.download_button(
                        #     label="Download Concatenated Video",
                        #     data=video_bytes,
                        #     file_name="concatenated_video.mp4",
                        #     mime="video/mp4"
                        # )

                        # # Clean up
                        # final_clip.close()
                        # for clip in clips:
                        #     clip.close()
                        # os.remove(output_filename)
                        # for f in temp_files:
                        #     os.remove(f)

                    # except Exception as e:
                    #     st.error(f"An error occurred during concatenation: {e}")

        elif uploaded_videos:
            st.warning("Please upload at least two videos to concatenate.")

    elif edit_option == "Change Playback Speed":
        st.subheader("Alter Video Playback Speed")
        
        newly_uploaded_video = st.file_uploader(
            "Upload a video to alter its speed (or load from history)",
            type=["mp4", "mov", "avi"],
            key="speed_video_uploader"
        )

        # If a new file is uploaded, it becomes the current video for speed change.
        if newly_uploaded_video:
            st.session_state.speed_change_video_file = newly_uploaded_video

        # Get the video to be processed from session state.
        # This will be either the one from history or the one just uploaded.
        uploaded_video = st.session_state.get('speed_change_video_file', None)

        if uploaded_video:
            st.video(uploaded_video.getvalue())

            if st.button("Clear Loaded Video", key="clear_speed_video"):
                st.session_state.speed_change_video_file = None
                st.session_state.speed_video_uploader = None # Also clear uploader state
                st.rerun()

        
            speed_factor = st.number_input(
                "Playback Speed Factor",
                min_value=0.1,
                value=1.0,
                step=0.1,
                format="%.1f",
                help="0.5 for half speed, 1.0 for normal, 2.0 for double speed."
            )

            if st.button("⏩ Apply Speed Change", type="primary"):
               
                with st.spinner("Applying speed change and uploading..."):
                    
                    run_temp_dir = os.path.join("temp_processing_space", str(uuid.uuid4()))
                    os.makedirs(run_temp_dir, exist_ok=True)
                    
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4", dir=run_temp_dir) as tmp_in:
                        tmp_in.write(uploaded_video.getvalue())
                        input_path = tmp_in.name

                    output_path = os.path.join(run_temp_dir, f"speed_adjusted_{os.path.basename(input_path)}")
                    
                    # Using the API helper function
                    processed_path = Veo2API.alter_video_speed(input_path, output_path, speed_factor, run_temp_dir)

                    if processed_path and os.path.exists(processed_path):
                        final_video_uri = video_upload_to_gcs(processed_path, BUCKET_NAME, f"speed-edited-{uploaded_video.name}")
                        if final_video_uri:
                            signed_url = client.generate_signed_url(final_video_uri)
                            st.subheader("Edited Video Preview")
                            st.video(signed_url)
                            if FIRESTORE_AVAILABLE:
                                db.collection('history').add({
                                    'user_id': st.session_state.user_id,
                                    'timestamp': firestore.SERVER_TIMESTAMP,
                                    'type': 'video', 'uri': final_video_uri,
                                    'prompt': f'Video speed changed by factor of {speed_factor}',
                                    'params': {'operation': 'change_speed', 'factor': speed_factor}
                                })
                    else:
                        st.error("Failed to process video speed.")

                    # Cleanup
                    if os.path.exists(run_temp_dir):
                        shutil.rmtree(run_temp_dir)

                    # except Exception as e:
                    #     st.error(f"An error occurred while changing speed: {e}")


    elif edit_option == "Frame Interpolation":
        st.subheader("Frame Interpolation")

        col1, col2 = st.columns(2)
        with col1:
            first_frame_file = st.file_uploader(
                "Upload First Frame",
                type=["jpg", "png", "jpeg"],
                key="interpolate_first_frame"
            )
            if first_frame_file:
                st.image(first_frame_file, caption="First Frame")

        with col2:
            last_frame_file = st.file_uploader(
                "Upload Last Frame",
                type=["jpg", "png", "jpeg"],
                key="interpolate_last_frame"
            )
            if last_frame_file:
                st.image(last_frame_file, caption="Last Frame")

        interpolation_prompt = st.text_area(
            "Prompt",
            value="Seamlessly transition from the first frame to the last frame.",
            height=100,
            help="Describe the transition between the frames.",
            key="frame_interpolation_prompt"
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            interpolation_model = st.selectbox(
                "Model Version", 
                options=["veo-3.1-fast-generate-preview", "veo-3.1-generate-preview"],
                key="interpolate_model_version",
                help="Select the model for frame interpolation."
            )
        with col2:
            interpolation_resolution = st.selectbox(
                "Output Resolution",
                options=["720p", "1080p"],
                key="interpolate_resolution",
                help="Select the output resolution for the video."
            )
        with col3:
            aspect_ratio = st.selectbox(
                "Aspect Ratio",
                options=["16:9", "9:16"],
                key="interpolate_aspect_ratio"
            )

        # Veo 3.1 models support audio generation during interpolation.
        generate_audio = st.checkbox(
            "Generate Audio",
            value=True,
            disabled=False,
            key="interpolate_audio"
        )

        col1, col2 = st.columns(2)
        with col1:
            interpolation_sample_count = st.slider(
                "Sample Count",
                min_value=1,
                max_value=4,
                value=1,
                step=1,
                key="interpolate_sample_count",
                help="Number of video variations to generate."
            )
        with col2:
            interpolation_duration = st.select_slider(
                "Duration (seconds)",
                options=[4, 7, 8],
                value=8,
                key="interpolate_duration",
                help="Set the duration of the generated video."
            )

        if st.button("✨ Interpolate Frames", type="primary"):
            if not first_frame_file or not last_frame_file:
                st.error("Please upload both a first frame and a last frame.")
                return

            run_temp_dir = None
            with st.spinner("Interpolating frames and uploading..."):
                try:
                    # 1. SETUP TEMPORARY DIRECTORY
                    run_id = str(uuid.uuid4())
                    run_temp_dir = os.path.join("temp_processing_space", run_id)
                    os.makedirs(run_temp_dir, exist_ok=True)

                    # 2. SAVE UPLOADED IMAGES TO TEMP FILES
                    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(first_frame_file.name)[1], dir=run_temp_dir) as tmp_first:
                        tmp_first.write(first_frame_file.getvalue())
                        start_image_path = tmp_first.name

                    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(last_frame_file.name)[1], dir=run_temp_dir) as tmp_last:
                        tmp_last.write(last_frame_file.getvalue())
                        end_image_path = tmp_last.name

                    # 3. GENERATE INTERPOLATED VIDEO
                    st.info(f"Calling {interpolation_model} API for interpolation...")
                    output_local_path = os.path.join(run_temp_dir, "interpolated_video.mp4")

                    interpolated_video_gcs_uris = client.interpolate_video_veo3(
                        start_image_path=start_image_path,
                        end_image_path=end_image_path,
                        prompt_text=interpolation_prompt,
                        model=interpolation_model,
                        output_local_video_path=output_local_path, # This is used for naming in GCS
                        resolution=interpolation_resolution,
                        aspect_ratio=aspect_ratio,
                        generate_audio=generate_audio,
                        duration_seconds=interpolation_duration,
                        sample_count=interpolation_sample_count,
                        storage_uri=f"gs://{BUCKET_NAME}/interpolated_videos/"
                    )

                    if not interpolated_video_gcs_uris:
                        st.error("Frame interpolation failed. The API did not return a video URI.")
                        return

                    st.subheader("Interpolation Results")
                    for i, uri in enumerate(interpolated_video_gcs_uris):
                        with st.expander(f"Video Result {i+1}", expanded=True):
                            # 4. DOWNLOAD THE GENERATED VIDEO FOR DISPLAY AND HISTORY
                            st.info(f"Downloading generated video {i+1} from GCS...")
                            # Extract the blob name from the full GCS URI
                            blob_name = uri.replace(f"gs://{BUCKET_NAME}/", "")
                            
                            # Use a unique local path for each download
                            downloaded_local_path = os.path.join(run_temp_dir, f"interpolated_video_{i}.mp4")
                            Veo2API.download_blob(BUCKET_NAME, blob_name, downloaded_local_path)

                            if not os.path.exists(downloaded_local_path):
                                st.error(f"Failed to download the generated video {i+1}.")
                                continue

                            # 5. UPLOAD AND DISPLAY FINAL VIDEO
                            final_gcs_uri = video_upload_to_gcs(downloaded_local_path, BUCKET_NAME, f"interpolated-video-{run_id}-{i}.mp4")
                            if final_gcs_uri:
                                signed_url = client.generate_signed_url(final_gcs_uri)
                                st.video(signed_url)
                                if FIRESTORE_AVAILABLE:
                                    db.collection('history').add({
                                        'user_id': st.session_state.user_id,
                                        'timestamp': firestore.SERVER_TIMESTAMP,
                                        'type': 'video', 'uri': final_gcs_uri,
                                        'prompt': f'Video interpolated with prompt: {interpolation_prompt}',
                                        'params': {'operation': 'frame_interpolation', 'aspect_ratio': aspect_ratio, 'sample': i+1},
                                        'model': interpolation_model, 'aspect_ratio': aspect_ratio,
                                        'resolution': interpolation_resolution, 'audio_generated': generate_audio,
                                        'duration_seconds': interpolation_duration, 'sample_count': interpolation_sample_count
                                    })


                except Exception as e:
                    st.error(f"An error occurred during frame interpolation: {e}")
                    import traceback
                    st.code(traceback.format_exc())
                finally:
                    # 6. SAFE CLEANUP
                    if run_temp_dir and os.path.exists(run_temp_dir):
                        shutil.rmtree(run_temp_dir)
                        logger.info(f"Cleaned up temporary directory: {run_temp_dir}")

    elif edit_option == "Dubbing":
        st.subheader("Dub Video")
        
        # If a new file is uploaded, it becomes the current video for dubbing.
        newly_uploaded_video = st.file_uploader(
            "Upload a video to dub (MP4, MOV, AVI)",
            type=["mp4", "mov", "avi"],
            key="dub_video_uploader"
        )
        if newly_uploaded_video:
            st.session_state.dub_video_file = newly_uploaded_video

        # Get the video to be processed from session state.
        uploaded_video = st.session_state.get('dub_video_file', None)

        if uploaded_video:
            # Display the video preview
            st.video(uploaded_video.getvalue())

            if st.button("Clear Loaded Video", key="clear_dub_video"):
                st.session_state.dub_video_file = None
                st.session_state.dub_video_uploader = [] # Clear the widget's state
                st.rerun()
            col1, col2 = st.columns(2)
            with col1:
                input_language = st.selectbox(
                    "Original Language",
                    options=dubbing_lib.LANGUAGES,
                    index=4, # Default to English
                    key="input_language",
                    help="The language spoken in the original video."
                )
            with col2:
                output_language = st.selectbox(
                    "Target Language",
                    options=dubbing_lib.LANGUAGES,
                    index=7, # Default to Hindi
                    key="output_language",
                    help="The language to dub the video into."
                )

            if st.button("🎙️ Dub Video", type="primary"):
                if not BUCKET_NAME:
                    st.error("A valid GCS Storage URI must be configured in settings to save and view the dubbed video.")
                    return
                dub_video(uploaded_video, input_language, output_language, BUCKET_NAME)


def image_to_video_tab():
    """Image-to-Video generation tab."""
    logger.start_section("Image-to-Video Tab")
    logger.info("Rendering Image-to-Video tab")
    st.header("Image-to-Video Generation")

    # Create tabs for different input methods
    upload_tabs = st.tabs(["Upload Image", "Enter Image URL"])
    
    # Upload Image Tab
    with upload_tabs[0]:        
        def _on_image_upload_change():
            """Callback to update the canonical active_image_data state."""
            uploaded_file = st.session_state.get("image_upload")
            if uploaded_file:
                st.session_state.active_image_data = uploaded_file
                st.session_state.current_image_url = "" # Clear URL if a file is uploaded

        st.file_uploader(
            "Upload an image to transform into a video (JPG, JPEG, PNG, WEBP)",
            type=["jpg", "jpeg", "png", "webp"],
            key="image_upload",
            help="Upload an image to transform into a video. Maximum size: 20MB.",
            on_change=_on_image_upload_change,
        )

    # --- SIMPLIFIED STATE LOGIC ---
    # Use the file uploader's state directly.
    active_image_file = st.session_state.get("active_image_data")
    image = None
    if active_image_file:
            image = Image.open(active_image_file)
            st.session_state.current_image = image
    
    # URL Input Tab
    with upload_tabs[1]:
        st.markdown("### Enter Image URL")
        
        # Check if we have a URL in session state
        if 'current_image_url' not in st.session_state:
            st.session_state.current_image_url = ""
        
        image_url = st.text_input(
            "Enter a public URL or GCS URI (gs://bucket/path/to/image.jpg)",
            value=st.session_state.current_image_url,
            placeholder="https://example.com/image.jpg or gs://bucket-name/path/to/image.jpg",
            help="You can enter either a public URL (https://) or a Google Cloud Storage URI (gs://)",
            key="url_input"
        )
        
        # Update URL in session state if changed
        if image_url != st.session_state.current_image_url:
            st.session_state.current_image_url = image_url
        
        # Create containers for the preview and message
        url_preview_container = st.empty()
        url_message_container = st.empty()
        
        # Add button to load from URL
        if image_url and st.button("Load Image from URL", type="primary"):
            with st.spinner("Loading image from URL..."):
                try:
                    # Handle different URL types
                    if image_url.startswith("gs://"):
                        # GCS URI handling
                        logger.info(f"Loading image from GCS URI: {image_url}")
                        
                        # Extract bucket and path
                        bucket_name = image_url.replace("gs://", "").split("/")[0]
                        blob_path = "/".join(image_url.replace(f"gs://{bucket_name}/", "").split("/"))
                        
                        # First try to generate a signed URL
                        try:
                            signed_url = generate_signed_url(image_url, expiration=3600)
                            response = requests.get(signed_url)
                        except Exception as e:
                            # Fallback to direct access (needs public bucket)
                            logger.warning(f"Could not generate signed URL, trying direct access: {str(e)}")
                            img_url = f"https://storage.googleapis.com/{bucket_name}/{blob_path}"
                            response = requests.get(img_url)
                    else:
                        # Regular HTTP(S) URL
                        logger.info(f"Loading image from public URL: {image_url}")
                        response = requests.get(image_url)
                    
                    # Check response
                    if response.status_code == 200:
                        # Create a temporary file object
                        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                        tmp_file.write(response.content)
                        tmp_file.close()
                        
                        # Open the image with PIL
                        image = Image.open(tmp_file.name)
                        
                        # Store image in session state
                        st.session_state.current_image = image
                        
                        # Create a simulated upload file and set it as the uploader's value
                        # This ensures consistency with the file upload tab.
                        st.session_state.image_upload = SimulatedUploadFile(
                            name=image_url.split("/")[-1],
                            content=response.content
                        )
                        
                        # Display a success message - don't display image here
                        url_message_container.success(f"Successfully loaded image: {filename}")
                        
                        # Clean up the temporary file
                        os.unlink(tmp_file.name)
                    else:
                        url_message_container.error(f"Failed to load image. HTTP status code: {response.status_code}")
                except Exception as e:
                    url_message_container.error(f"Error loading image from URL: {str(e)}")
                    if "Access Denied" in str(e):
                        url_message_container.info("If using a GCS URI, make sure the bucket is publicly accessible or you have proper permissions.")
    
    # If an image is loaded (either from uploader or URL), process and display it
    if active_image_file is not None:
        try:
            logger.info(f"Image available: {active_image_file.name}, size: {active_image_file.size} bytes")
            logger.info(f"Image properties: format={image.format}, size={image.size}, mode={image.mode}")
            
            # Display the image preview and details in a cleaner layout
            st.subheader("Image Preview")
            
            # Create two columns for the image and details
            preview_col, details_col = st.columns(2)
            
            with preview_col:
                # Display the image in the left column
                st.image(
                    image, 
                    caption=f"{active_image_file.name}",
                    use_container_width=True
                )
            
            with details_col:
                # Show image details in the right column
                st.markdown(f"**Filename:** {active_image_file.name}")
                st.markdown(f"**Size:** {image.size[0]} × {image.size[1]} pixels")
                st.markdown(f"**Format:** {image.format}")
                st.markdown(f"**Mode:** {image.mode}")
                
                # Add file size
                file_size_kb = active_image_file.size / 1024
                if file_size_kb > 1024:
                    file_size_display = f"{file_size_kb/1024:.2f} MB"
                else:
                    file_size_display = f"{file_size_kb:.2f} KB"
                st.markdown(f"**File Size:** {file_size_display}")

                # Add a button to clear the current image
                def _clear_i2v_image_callback():
                    st.session_state.active_image_data = None
                    st.session_state.current_image_url = ""
                st.button("🗑️ Clear Image", key="clear_i2v_image", on_click=_clear_i2v_image_callback)
        
        except Exception as e:
            st.error(f"Error loading image: {str(e)}")
            logger.error(f"Error displaying image: {str(e)}")
            image = None
            if 'current_image' in st.session_state:
                del st.session_state.current_image
    
    # If no image is loaded, show a helpful message.
    if not active_image_file:
        st.info("👆 Please upload an image or provide an image URL to get started.")
        logger.end_section()
        return
    
    if active_image_file:
        # Prompt section
        st.markdown("### Video Prompt")
        
        # Initialize or get the prompt from session state
        if 'generated_prompt' not in st.session_state or st.session_state.generated_prompt is None:
            default_prompt = config.DEFAULT_IMAGE_PROMPT
        else:
            default_prompt = st.session_state.generated_prompt
        
        # Gemini button and checkbox in a more compact layout
        gemini_col1, gemini_col2 = st.columns([3, 1])
        with gemini_col1:
            generate_button = st.button(
                "✨ Generate Prompt with Gemini AI", 
                key="generate_prompt", 
                help="Use Google's Gemini AI to generate a detailed prompt based on your image"
            )
        with gemini_col2:
            clear_prompt = st.checkbox(
                "Replace text", 
                value=True, 
                key="clear_prompt",
                help="Clear the current prompt before generating a new one"
            )
        
        # Prompt text area directly (no container)
        # Store the current text area value to detect user edits
        prompt = st.text_area(
            "Describe how the image should be transformed into a video:",
            value=default_prompt,
            height=150,
            key="image_prompt"
        )
        
        # Model selection
        model = st.selectbox(
            "Model",
            options=["veo-3.1-generate-preview", "veo-3.1-generate-fast-preview", "veo-3.0-generate-preview", "veo-3.0-fast-generate-001", "veo-2.0-generate-001"],  # Assuming these are the model IDs
            index=0,  # Default to Veo 2
            help="Choose the video generation model (Veo 2 or Veo 3)",
            key="image_model"
        )

        # Audio and resolution options (Veo 3.0 only)
        enable_audio = st.checkbox(
            "Add Audio", 
            value=False if model == "veo-2.0-generate-001" else True, 
            disabled=model == "veo-2.0-generate-001", 
            key="image_enable_audio"
        )
        resolution = st.selectbox(
            "Resolution", 
            options=["720p"] if model == "veo-2.0-generate-001" else ["720p", "1080p"], 
            index=0, 
            disabled=model == "veo-2.0-generate-001", 
            help="Choose video resolution", 
            key="image_resolution"
        )

        # Capture the user's manually entered prompt
        if 'image_prompt' in st.session_state:
            # Only update if it's different from the generated prompt
            # This prevents overwriting the generated prompt with itself
            current_prompt = st.session_state.image_prompt
            if 'generated_prompt' not in st.session_state or current_prompt != st.session_state.generated_prompt:
                st.session_state.last_entered_prompt = current_prompt
        
        # Handle Gemini prompt generation
        if generate_button:
            logger.start_section("Prompt Generation")
            logger.info("Generate Prompt button clicked")
            
            if image is None:
                st.error("No image is available. Please upload an image or provide a URL first.")
                logger.error("Generate prompt clicked but no image available")
                logger.end_section()
                return
                
            try:
                # Use a better spinner with more information
                spinner_text = "Analyzing image and crafting a detailed prompt with Gemini AI..."
                with st.spinner(spinner_text):
                    # Generate the prompt
                    logger.info("Calling gemini_helper.generate_prompt_from_image()")
                    generated_prompt = gemini_helper.generate_prompt_from_image(image)
                    
                    # Log the prompt
                    logger.debug(f"Generated prompt: {generated_prompt[:50]}...")
                    
                    # Update session state based on clear preference
                    if clear_prompt:
                        # Replace the entire prompt
                        st.session_state.generated_prompt = generated_prompt
                        logger.info("Replacing prompt with generated text")
                    else:
                        # Add to the existing prompt
                        current = st.session_state.get("last_entered_prompt", "")
                        if current.strip():
                            combined_prompt = f"{current}\n\n{generated_prompt}"
                            st.session_state.generated_prompt = combined_prompt
                            logger.info("Appending generated text to existing prompt")
                        else:
                            st.session_state.generated_prompt = generated_prompt
                            logger.info("Setting prompt to generated text (existing was empty)")
                    
                    logger.success("Updated generated_prompt in session state")
                    
                    # Don't modify image_prompt directly - it's linked to the text area widget
                    # Instead, show success message and rerun to refresh the UI with new prompt
                    st.success("✅ Prompt generated successfully! Updating the text area...")
                    time.sleep(0.5)  # Small delay so user can see the success message
                    st.rerun()  # Rerun to refresh the UI with the new prompt
                    
            except Exception as e:
                logger.error(f"Error generating prompt: {str(e)}")
                st.error(f"Error generating prompt: {str(e)}")
                if "403" in str(e):
                    st.info("This could be due to Gemini API access issues. Check your credentials and permissions.")
            logger.end_section()
        
        # Video settings with better organization
        st.markdown("### Video Settings")
        
        # Create a simplified settings layout in single container
        settings_row = st.columns(3)
        with settings_row[0]:
            aspect_ratio = st.selectbox(
                "Aspect Ratio", 
                options=["16:9", "9:16"],
                index=0,
                help="Choose orientation.",
                key="image_aspect_ratio"
            )
        with settings_row[1]:
            duration = st.slider(
                "Duration (seconds)", 
                min_value=5, 
                max_value=8,
                value=config.DEFAULT_DURATION_SECONDS,
                help="Video length",
                key="image_duration"
            )
        with settings_row[2]:
            sample_count = st.slider(
                "Number of Videos", 
                min_value=1, 
                max_value=4,
                value=config.DEFAULT_SAMPLE_COUNT,
                help="Generate variations",
                key="image_sample_count"
            )
        
        # Advanced options in a cleaner expandable section
        with st.expander("Advanced Options", expanded=False):
            neg_prompt_col, options_col = st.columns([2, 1])
            
            with neg_prompt_col:
                # Negative prompt with guidance
                negative_prompt = st.text_area(
                    "Negative Prompt (elements to avoid)", 
                    value=config.DEFAULT_NEGATIVE_PROMPT,
                    height=80,
                    key="image_negative_prompt"
                )
                
            with options_col:
                # Streamlined options
                person_generation = st.radio(
                    "People", 
                    options=["allow_adult", "disallow"],
                    horizontal=True,
                    key="image_person_generation",
                    help="Safety setting"
                )
                
                enhance_prompt = st.checkbox(
                    "AI Enhancement",
                    value=True,
                    key="image_enhance_prompt",
                    help="Improve prompt"
                )
                
                seed = st.number_input(
                    "Seed (optional)",
                    min_value=0,
                    max_value=4294967295,
                    value=None,
                    key="image_seed",
                    help="For reproducibility"
                )
                if seed is not None and seed == 0:
                    seed = None  # Treat 0 as None
        
        # Generate button - more prominent with better placement
        st.markdown("<div style='margin-top: 20px; margin-bottom: 20px;'></div>", unsafe_allow_html=True)
        if st.button("🚀 Generate Video", key="image_generate", type="primary", use_container_width=True):
            if active_image_file is None and image is None:
                st.error("No image is available. Please upload an image or provide a URL first.")
                return
                
            try:
                # Save the current prompt to session state to persist it
                if 'image_prompt' in st.session_state:
                    st.session_state.last_entered_prompt = st.session_state.image_prompt
                
                # Create a temporary file for the image
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
                    # If we're working with a PIL image object directly (from URL)
                    if active_image_file is None and image is not None:
                        # Save the PIL image to the temporary file
                        if image.mode == 'RGBA':
                            # Convert RGBA to RGB for JPEG compatibility
                            background = Image.new('RGB', image.size, (255, 255, 255))
                            background.paste(image, mask=image.split()[3])
                            background.save(tmp_file.name, format='JPEG')
                        else:
                            image.save(tmp_file.name, format='JPEG')
                        
                        # Create a simulated upload file if needed
                        if active_image_file is None:
                            with open(tmp_file.name, "rb") as f:
                                image_data = f.read()
                            
                            filename = "image_from_url.jpg"
                            if 'current_image_url' in st.session_state and st.session_state.current_image_url:
                                # Extract filename from URL if available
                                url_filename = st.session_state.current_image_url.split("/")[-1]
                                if url_filename and '.' in url_filename:
                                    filename = url_filename
                            
                            active_image_file = SimulatedUploadFile(
                                name=filename,
                                content=image_data
                            )
                            
                            # Save to session state
                            st.session_state.active_image_data = active_image_file
                    else:
                        # We have a regular uploaded_file
                        tmp_file.write(active_image_file.getvalue())
                
                tmp_image_path = tmp_file.name
                image_path = tmp_image_path
                
                # Convert WebP to PNG if needed
                if image_path.lower().endswith('.webp'):
                    with st.spinner("Converting WebP to PNG..."):
                        png_path = image_path.rsplit('.', 1)[0] + '.png'
                        img = Image.open(image_path)
                        img.save(png_path, 'PNG')
                        image_path = png_path
                        st.success("WebP image successfully converted to PNG")
                
                # Upload image to history
                try:
                    # Make sure image is in session state
                    if image is None and 'current_image' in st.session_state:
                        image = st.session_state.current_image

                    if image is not None:
                        uploaded_image_uri = history_manager.upload_image_to_history(image)
                        if uploaded_image_uri:
                            # Add to history - store proper JSON for parameters
                            image_params = {
                                "filename": active_image_file.name,
                                "size": f"{image.size[0]}x{image.size[1]}",
                                "format": image.format if hasattr(image, 'format') else "Unknown",
                                "mode": image.mode if hasattr(image, 'mode') else "Unknown"
                            }
                            # Add image entry to Firestore
                            if FIRESTORE_AVAILABLE:
                                doc_ref = db.collection('history').document()
                                doc_ref.set({
                                    'user_id': st.session_state.user_id,
                                    'timestamp': firestore.SERVER_TIMESTAMP,
                                    'type': 'image',
                                    'uri': uploaded_image_uri,
                                    'prompt': 'Input image',
                                    'params': image_params
                                })
                                logger.info(f"Added image {uploaded_image_uri} to Firestore history.")
                    else:
                        st.warning("Could not save image to history: No image data available")
                except Exception as e:
                    st.warning(f"Could not save image to history: {str(e)}")
                
                # Generate the video
                generate_video(
                    project_id=st.session_state.get("project_id", config.PROJECT_ID),
                    prompt=prompt,
                    input_image_path=image_path,
                    aspect_ratio=aspect_ratio,
                    negative_prompt=negative_prompt,
                    model=model, #Add model parameter
                    person_generation=person_generation,
                    resolution=resolution,
                    enable_audio=enable_audio,
                    sample_count=sample_count,
                    seed=seed,
                    storage_uri=st.session_state.get("storage_uri", config.STORAGE_URI),
                    duration_seconds=duration,
                    enhance_prompt=enhance_prompt,
                    wait_for_completion=st.session_state.get("wait_for_completion", True),
                    poll_interval=st.session_state.get("poll_interval", config.DEFAULT_POLL_INTERVAL),
                    max_attempts=st.session_state.get("max_poll_attempts", config.DEFAULT_MAX_POLL_ATTEMPTS),
                    show_full_response=st.session_state.get("show_full_response", False),
                    enable_streaming=st.session_state.get("enable_streaming", True)
                )
            except Exception as e:
                st.error(f"Error generating video: {str(e)}")
                logger.error(f"Error during video generation: {str(e)}")
            finally:
                # Clean up the temporary files
                try:
                    if 'tmp_image_path' in locals() and os.path.exists(tmp_image_path):
                        os.unlink(tmp_image_path)
                    
                    # Also remove PNG conversion if it was created
                    if 'tmp_image_path' in locals() and tmp_image_path.lower().endswith('.webp'):
                        png_path = tmp_image_path.rsplit('.', 1)[0] + '.png'
                        if os.path.exists(png_path):
                            os.unlink(png_path)
                except Exception as cleanup_error:
                    logger.error(f"Error cleaning up temporary files: {str(cleanup_error)}")
    
    logger.end_section()


def get_history_from_firestore(user_id, limit=200):
    """
    Get the history of generated content from Firestore.
    
    Args:
        user_id (str): The ID of the user to fetch history for.
        limit (int): Maximum number of entries to return.
        
    Returns:
        pandas.DataFrame: DataFrame containing the history entries
    """
    if not FIRESTORE_AVAILABLE:
        logger.error("Firestore is not available. Cannot get history.")
        return pd.DataFrame(columns=['timestamp', 'type', 'uri', 'prompt', 'params'])

    try:
        # Fetch all documents for the user first, then sort and limit in pandas.
        # This avoids the need for a composite index in Firestore.
        history_ref = db.collection('history').where('user_id', '==', user_id)
        
        docs = history_ref.stream()
        
        history_list = [doc.to_dict() for doc in docs]
        for item in history_list:
            # Add the Firestore document ID to each item
            item['doc_id'] = item.get('doc_id', str(uuid.uuid4())) # Fallback for older entries if doc_id isn't directly available
        if not history_list:
            return pd.DataFrame(columns=['timestamp', 'type', 'uri', 'prompt', 'params', 'doc_id'])
            
        df = pd.DataFrame(history_list)
        # Ensure timestamp column is of datetime type for proper sorting
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
            # Sort by timestamp descending and then take the top 'limit' results
            return df.sort_values('timestamp', ascending=False).head(limit)
        return df

    except Exception as e:
        logger.error(f"Error getting history from Firestore: {str(e)}")
        st.error(f"Error getting history from Firestore: {str(e)}")
        return pd.DataFrame(columns=['timestamp', 'type', 'uri', 'prompt', 'params', 'doc_id'])

def display_recent_videos(history_data):
    """Displays the 'Recent Videos' sub-tab content."""
    video_history = history_data[history_data['type'] == 'video'].copy()
        
    if video_history.empty:
        st.info("No videos in history yet. Generate some videos to see them here!")
    else:
        video_header_col, clear_col = st.columns([5, 1])
        with video_header_col:
            st.markdown(f"### Recent Generated Videos ({len(video_history)})")
        with clear_col:
            if st.button("🗑️ Clear All", key="clear_history_btn", type="secondary"):
                if st.session_state.get("confirm_clear_history", False):
                    if not FIRESTORE_AVAILABLE:
                        st.error("Firestore is not available. Cannot clear history.")
                        st.session_state.confirm_clear_history = False
                        st.rerun()
                        return
                    try:
                        clear_history()
                        st.success("History cleared successfully!")
                        st.session_state.history_loaded = False
                        st.session_state.confirm_clear_history = False
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error clearing history: {str(e)}")
                else:
                    st.session_state.confirm_clear_history = True
                    st.warning("⚠️ This will permanently delete all history. Are you sure?")
                    confirm_col1, confirm_col2 = st.columns(2)
                    with confirm_col1:
                        if st.button("✅ Yes, Delete All"):
                            try:
                                clear_history()
                                st.success("History cleared successfully!")
                                st.session_state.history_loaded = False
                                st.session_state.confirm_clear_history = False
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error clearing history: {str(e)}")
                    with confirm_col2:
                        if st.button("❌ Cancel"):
                            st.session_state.confirm_clear_history = False
                            st.rerun()
    
        video_history = video_history.sort_values('timestamp', ascending=False).reset_index(drop=True)
        total_videos = len(video_history)
        items_per_page = 9 # Adjusted for 3 columns
        max_pages = (total_videos + items_per_page - 1) // items_per_page
        if "video_page" not in st.session_state:
            st.session_state.video_page = 0
            
        col1, col2, col3 = st.columns([1, 3, 1])
        with col1:
            if st.button("◀ Previous", disabled=(st.session_state.video_page <= 0), key="prev_video"):
                st.session_state.video_page = max(0, st.session_state.video_page - 1)
                st.rerun()
        with col2:
            st.markdown(f"**Page {st.session_state.video_page + 1} of {max(1, max_pages)}** (showing {min(items_per_page, total_videos - st.session_state.video_page * items_per_page)} of {total_videos} videos)")
        with col3:
            if st.button("Next ▶", disabled=(st.session_state.video_page >= max_pages - 1), key="next_video"):
                st.session_state.video_page = min(max_pages - 1, st.session_state.video_page + 1)
                st.rerun()
    
        start_idx = st.session_state.video_page * items_per_page
        end_idx = min(start_idx + items_per_page, total_videos)
        page_videos = video_history.iloc[start_idx:end_idx]
        
        st.markdown('<div class="history-grid">', unsafe_allow_html=True)
        rows = [page_videos.iloc[i:i+3] for i in range(0, len(page_videos), 3)]
        for row_items in rows:
            cols = st.columns(3)
            for i, (_, row) in enumerate(row_items.iterrows()):
                if i < len(cols):
                    with cols[i]:
                        display_history_video_card(row)
        st.markdown('</div>', unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([1, 3, 1])
        with col1:
            if st.button("◀ Previous", disabled=(st.session_state.video_page <= 0), key="prev_video_bottom"):
                st.session_state.video_page = max(0, st.session_state.video_page - 1)
                st.rerun()
        with col2:
            st.markdown(f"**Page {st.session_state.video_page + 1} of {max(1, max_pages)}**")
        with col3:
            if st.button("Next ▶", disabled=(st.session_state.video_page >= max_pages - 1), key="next_video_bottom"):
                st.session_state.video_page = min(max_pages - 1, st.session_state.video_page + 1)
                st.rerun()

def display_recent_audios(history_data):
    """Displays the 'Recent Audios' sub-tab content."""
    st.markdown("### Recent Generated Audios")
    audio_history = history_data[history_data['type'] == 'audio'].copy()
    
    if audio_history.empty:
        st.info("No audio generation history found.")
    else:
        st.markdown(f"Found {len(audio_history)} audio generations.")
        audio_history = audio_history.sort_values('timestamp', ascending=False)
        st.markdown('<div class="history-grid">', unsafe_allow_html=True)
        rows = [audio_history.iloc[i:i+3] for i in range(0, len(audio_history), 3)]
        for row_items in rows:
            cols = st.columns(3)
            for i, (_, row) in enumerate(row_items.iterrows()):
                if i < len(cols):
                    with cols[i]:
                        with st.container(border=True, height=350):
                            display_history_audio_card(row)
        st.markdown('</div>', unsafe_allow_html=True)

def display_recent_voices(history_data):
    """Displays the 'Recent Voices' sub-tab content."""
    st.markdown("### Recent Generated Voiceovers")
    voice_history = history_data[history_data['type'] == 'voice'].copy()
    
    if voice_history.empty:
        st.info("No voiceover generation history found.")
    else:
        st.markdown(f"Found {len(voice_history)} voiceover generations.")
        voice_history = voice_history.sort_values('timestamp', ascending=False)
        st.markdown('<div class="history-grid">', unsafe_allow_html=True)
        rows = [voice_history.iloc[i:i+3] for i in range(0, len(voice_history), 3)]
        for row_items in rows:
            cols = st.columns(3)
            for i, (_, row) in enumerate(row_items.iterrows()):
                if i < len(cols):
                    with cols[i]:
                        with st.container(border=True, height=350):
                            display_history_voice_card(row)
        st.markdown('</div>', unsafe_allow_html=True)

def display_all_images(history_data):
    """Displays the 'All Images' sub-tab content."""
    # Filter for images and remove any duplicates based on the URI.
    # This prevents the StreamlitDuplicateElementKey error if the same image
    # appears multiple times in the history. We keep the most recent entry.
    image_history = history_data[history_data['type'] == 'image'].copy()
    image_history = image_history.drop_duplicates(subset=['uri'], keep='first')
    
    if image_history.empty:
        st.info("No source images in history yet.")
    else:
        st.markdown("### Filter Source Images")
        col1, col2 = st.columns([3, 2])
        with col1:
            search_term = st.text_input("Search by filename:", key="image_search", placeholder="Enter filename or leave empty to show all")
        with col2:
            sort_order = st.selectbox("Sort by:", ["Newest first", "Oldest first"], key="image_sort")
        
        if search_term:
            image_history = image_history[image_history['params'].apply(
                lambda x: search_term.lower() in json.loads(x).get('filename', '').lower() if pd.notna(x) and x else False
            )]
        
        if sort_order == "Newest first":
            image_history = image_history.sort_values('timestamp', ascending=False)
        else:
            image_history = image_history.sort_values('timestamp', ascending=True)
        
        total_images = len(image_history)
        items_per_page = 9 # Adjusted for 3 columns
        max_pages = max(1, (total_images + items_per_page - 1) // items_per_page)
        if "image_page" not in st.session_state:
            st.session_state.image_page = 0
            
        st.markdown(f"### Source Images ({total_images})")
        
        col1, col2, col3 = st.columns([1, 3, 1])
        with col1:
            if st.button("◀ Previous", disabled=(st.session_state.image_page <= 0), key="prev_image"):
                st.session_state.image_page = max(0, st.session_state.image_page - 1)
                st.rerun()
        with col2:
            st.markdown(f"**Page {st.session_state.image_page + 1} of {max(1, max_pages)}** (showing {min(items_per_page, total_images - st.session_state.image_page * items_per_page)} of {total_images} images)")
        with col3:
            if st.button("Next ▶", disabled=(st.session_state.image_page >= max_pages - 1), key="next_image"):
                st.session_state.image_page = min(max_pages - 1, st.session_state.image_page + 1)
                st.rerun()
        start_idx = st.session_state.image_page * items_per_page
        end_idx = min(start_idx + items_per_page, total_images)
        page_images = image_history.iloc[start_idx:end_idx]
        
        st.markdown('<div class="history-grid">', unsafe_allow_html=True)
        rows = [page_images.iloc[i:i+3] for i in range(0, len(page_images), 3)]
        for row_items in rows:
            cols = st.columns(3)
            for i, (_, row) in enumerate(row_items.iterrows()):
                if i < len(cols):
                    with cols[i]:
                        display_history_image_card(row)
        st.markdown('</div>', unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([1, 3, 1])
        with col1:
            if st.button("◀ Previous", disabled=(st.session_state.image_page <= 0), key="prev_image_bottom"):
                st.session_state.image_page = max(0, st.session_state.image_page - 1)
                st.rerun()
        with col2:
            st.markdown(f"**Page {st.session_state.image_page + 1} of {max(1, max_pages)}**")
        with col3:
            if st.button("Next ▶", disabled=(st.session_state.image_page >= max_pages - 1), key="next_image_bottom"):
                st.session_state.image_page = min(max_pages - 1, st.session_state.image_page + 1)
                st.rerun()

def display_all_history(history_data):
    """Displays the 'All History' sub-tab content."""
    st.markdown("### Complete History")
    
    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
    with col1:
        filter_type = st.selectbox("Filter by type:", ["All", "Video", "Image"], key="type_filter")
    with col2:
        sort_field = st.selectbox("Sort by:", ["Date", "Type"], key="sort_field")
    with col3:
        sort_order = st.selectbox("Order:", ["Newest first", "Oldest first"], key="sort_order")
    with col4:
        view_mode = st.selectbox("View as:", ["Table", "Grid"], key="view_mode")
    
    filtered_history = history_data.copy()
    if filter_type == "Video":
        filtered_history = filtered_history[filtered_history['type'] == 'video']
    elif filter_type == "Image":
        filtered_history = filtered_history[filtered_history['type'] == 'image']
    
    if sort_field == "Date":
        if sort_order == "Newest first":
            filtered_history = filtered_history.sort_values('timestamp', ascending=False)
        else:
            filtered_history = filtered_history.sort_values('timestamp', ascending=True)
    else:
        if sort_order == "Newest first":
            filtered_history = filtered_history.sort_values(['type', 'timestamp'], ascending=[True, False])
        else:
            filtered_history = filtered_history.sort_values(['type', 'timestamp'], ascending=[True, True])
    
    if filtered_history.empty:
        st.info("No history data found with these filters.")
    else:
        if view_mode == "Table":
            display_df = filtered_history.copy()
            display_df['timestamp'] = pd.to_datetime(display_df['timestamp']).dt.strftime("%Y-%m-%d %H:%M:%S")
            display_df = display_df.rename(columns={'timestamp': 'Generated', 'type': 'Type', 'uri': 'URI', 'prompt': 'Prompt'})
            if 'params' in display_df.columns:
                display_df = display_df.drop(columns=['params'])
            display_df['Prompt'] = display_df['Prompt'].apply(lambda x: x[:50] + "..." if isinstance(x, str) and len(x) > 50 else x)
            st.dataframe(display_df, use_container_width=True, column_config={
                "Generated": st.column_config.DatetimeColumn("Generated", help="When this item was created", format="MMM DD, YYYY, hh:mm a", width="medium"),
                "Type": st.column_config.TextColumn("Type", help="Item type (video or image)", width="small"),
                "URI": st.column_config.TextColumn("URI", help="Google Cloud Storage URI", width="large"),
                "Prompt": st.column_config.TextColumn("Prompt", help="Prompt used for generation", width="large")
            })
        else:
            st.markdown('<div class="history-grid">', unsafe_allow_html=True)
            rows = [filtered_history.iloc[i:i+3] for i in range(0, len(filtered_history), 3)]
            for row_items in rows:
                cols = st.columns(3)
                for i, (_, row) in enumerate(row_items.iterrows()):
                    if i < len(cols):
                        with cols[i]:
                            if row['type'] == 'video':
                                display_history_video_card(row)
                            else:
                                display_history_image_card(row)
            st.markdown('</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Download as CSV"):
                csv = filtered_history.to_csv(index=False)
                st.download_button(label="Download CSV", data=csv, file_name="veo2_history.csv", mime="text/csv")

def history_tab():
    """History of generated videos and images."""
    logger.start_section("History Tab")
    logger.info("Rendering History tab")
    
    # Display the action panel if items are selected
    if st.session_state.get('selected_history_items'):
        display_history_actions()

    # Use header and button in same line with columns
    header_col, button_col = st.columns([5, 1])
    with header_col:
        st.header("Generation History")
    with button_col:
        if st.button("🔄 Refresh History", key="refresh_history"):
            logger.info("Manually refreshing history...")
            st.session_state.history_loaded = False
            st.success("Refreshing history...")
            st.rerun()
    
    # Load history data
    try:
        if not st.session_state.get("history_loaded", False) or "history_data" not in st.session_state:
            with st.spinner("Loading history data..."):
                history_data = get_history_from_firestore(user_id=st.session_state.user_id, limit=200)
                st.session_state.history_data = history_data
                st.session_state.history_loaded = True
        else:
            history_data = st.session_state.history_data
    except Exception as e:
        st.error(f"Error loading history: {str(e)}")
        history_data = pd.DataFrame()

    if not history_data.empty:
        HISTORY_SUB_TABS = OrderedDict([
            ("🎬 Recent Videos", display_recent_videos),
            ("🎵 Recent Audios", display_recent_audios),
            ("🎤 Recent Voices", display_recent_voices),
            ("🖼️ All Images", display_all_images),
            ("📋 All History", display_all_history)
        ])

        # Use a key to make this a "controlled" widget. Its state is now directly
        # read from and written to st.session_state.active_history_sub_tab.
        # This resolves the "double-click" issue.
        st.radio(
            "History Sub-Navigation",
            options=list(HISTORY_SUB_TABS.keys()),
            key="active_history_sub_tab", # This is the fix
            horizontal=True,
            label_visibility="collapsed",
        )

        # If the user clicks a new tab, clear selections to prevent errors
        if 'previous_history_sub_tab' not in st.session_state:
            st.session_state.previous_history_sub_tab = st.session_state.active_history_sub_tab
        if st.session_state.active_history_sub_tab != st.session_state.previous_history_sub_tab:
            st.session_state.selected_history_items.clear()
            logger.info(f"History sub-tab changed to '{st.session_state.active_history_sub_tab}'. Clearing selection.")
            st.session_state.previous_history_sub_tab = st.session_state.active_history_sub_tab
        # Call the appropriate function to display the content of the active tab
        HISTORY_SUB_TABS[st.session_state.active_history_sub_tab](history_data)
    else:
        st.info("No generation history found. Generate some videos or images to see them here!")
    
    logger.end_section()
        
def display_history_video_card(row):
    """Display a video history card with details and buttons."""
    uri = row['uri']
    doc_id = row['doc_id'] # Get the unique Firestore document ID
    timestamp = row['timestamp']
    prompt = row.get('prompt', 'No prompt available.')
    params = _parse_history_params(row.get('params', {}))

    # --- Selection Checkbox ---
    is_selected = uri in st.session_state.get('selected_history_items', {})

    def toggle_selection():
        if uri in st.session_state.selected_history_items:
            del st.session_state.selected_history_items[uri]
        else:
            st.session_state.selected_history_items[uri] = 'video'

    st.checkbox("Select this video", value=is_selected, key=f"select_{doc_id}", on_change=toggle_selection, label_visibility="collapsed")
    # Generate a signed URL for the video
    try:
        # Check if we already have a cached signed URL for this video
        cache_key = f"signed_url_{uri}"
        if cache_key in st.session_state and st.session_state[cache_key]["expiry"] > time.time():
            signed_url = st.session_state[cache_key]["url"]

            print(f"generated signed url {signed_url}")
        else:
            signed_url = generate_signed_url(uri, expiration=3600)  # 1 hour expiration
            # Cache the signed URL with expiration
            st.session_state[cache_key] = {
                "url": signed_url,
                "expiry": time.time() + 3500  # Cache for slightly less than the actual expiration
            }
    except Exception as e:
        st.error(f"Error generating signed URL: {e}")
        signed_url = None

    # Display the video
    if signed_url:
        print(f"generated signed url {signed_url}")
        try:
            st.video(signed_url)
        except Exception as e:
            st.error(f"Error displaying video: {e}")
            st.markdown(f'<a href="{signed_url}" target="_blank">Open video in new tab</a>', unsafe_allow_html=True)
    else:
        st.error("Could not generate a signed URL for this video.")

    # Handle the timestamp which may be a datetime object or NaT
    try:
        if pd.notna(timestamp):
            # Format the datetime object
            formatted_time = timestamp.strftime('%Y-%m-%d %H:%M:%S')
        else:
            formatted_time = "Unknown"
    except AttributeError:
        # Fallback for older data that might not be a datetime object
        formatted_time = str(timestamp)

    st.markdown(f'<div class="history-meta">Generated: {formatted_time}</div>', unsafe_allow_html=True)

    # Display URI in a code block for easy copying
    st.code(uri, language="bash")

    # Create a clean parameters display
    # Include prompt in the parameters if available
    display_params = params.copy() if params else {}
    if prompt and prompt.strip() and prompt != 'No prompt available.':
        if 'prompt' not in display_params:
            display_params['prompt'] = prompt

    if display_params:
        # Ensure parameters use proper API camelCase naming convention
        if 'negative_prompt' in display_params and 'negativePrompt' not in display_params:
            display_params['negativePrompt'] = display_params.pop('negative_prompt')
        if 'aspect_ratio' in display_params and 'aspectRatio' not in display_params:
            display_params['aspectRatio'] = display_params.pop('aspect_ratio')
        if 'duration_seconds' in display_params and 'durationSeconds' not in display_params:
            display_params['durationSeconds'] = display_params.pop('duration_seconds')
        if 'sample_count' in display_params and 'sampleCount' not in display_params:
            display_params['sampleCount'] = display_params.pop('sample_count')
        if 'person_generation' in display_params and 'personGeneration' not in display_params:
            display_params['personGeneration'] = display_params.pop('person_generation')

        # Format speed change factor for better display
        if display_params.get('operation') == 'change_speed' and 'factor' in display_params:
            try:
                factor = float(display_params['factor'])
                # Format to one decimal place and add 'x'
                display_params['factor'] = f"{factor:.1f}x"
            except (ValueError, TypeError):
                # If it's not a number for some reason, leave it as is
                pass

        # Display parameters in an expander with a clear title
        with st.expander("Video Details", expanded=False):
            params_str = json.dumps(display_params, indent=2)
            st.code(params_str, language="json")

    # Provide direct link to open in new tab
    if signed_url:
        st.markdown(f'<div style="text-align: right;"><a href="{signed_url}" target="_blank" style="font-size: 0.8rem;">Open in new tab</a></div>', unsafe_allow_html=True)

def clear_history():
    """Clear all history data from Firestore and associated GCS files."""
    logger.start_section("Clear History")

    if not FIRESTORE_AVAILABLE:
        logger.error("Attempted to clear history, but Firestore is not available.")
        raise Exception("Firestore is not available. Cannot clear history.")

    logger.info("Clearing history data...")
    
    try:
        # 1. Delete all documents in the 'history' collection from Firestore using batches
        history_ref = db.collection('history')
        docs_deleted_count = 0
        while True:
            # Get a batch of documents
            docs = history_ref.limit(500).stream()
            batch = db.batch()
            count_in_batch = 0
            for doc in docs:
                batch.delete(doc.reference)
                count_in_batch += 1
            
            if count_in_batch == 0:
                # No more documents to delete
                break
            
            # Commit the batch
            batch.commit()
            docs_deleted_count += count_in_batch
            logger.debug(f"Deleted {count_in_batch} Firestore documents in a batch.")
        
        logger.info(f"Deleted {docs_deleted_count} documents from the 'history' collection in Firestore.")

        # 2. Delete all images in the history images directory from GCS
        try:
            storage_client = storage.Client()
            bucket_name = config.STORAGE_URI.replace("gs://", "").split("/")[0]
            history_path = config.HISTORY_FOLDER
            bucket = storage_client.bucket(bucket_name)
            
            image_prefix = f"{history_path}/images/"
            blobs_to_delete = list(bucket.list_blobs(prefix=image_prefix))
            
            if blobs_to_delete:
                for blob in blobs_to_delete:
                    blob.delete()
                logger.info(f"Deleted {len(blobs_to_delete)} images from GCS history folder: {image_prefix}")
            else:
                logger.info("No images found in GCS history folder to delete.")

        except Exception as gcs_e:
            logger.error(f"Error clearing GCS history images: {str(gcs_e)}")
            st.warning(f"Could not clear all GCS history images: {str(gcs_e)}")

        logger.success("History cleared successfully")
        
        # 3. Clear session state
        if "history_data" in st.session_state:
            st.session_state.history_data = pd.DataFrame(columns=['timestamp', 'type', 'uri', 'prompt', 'params'])
        st.session_state.history_loaded = False
        
        return True
    except Exception as e:
        logger.error(f"Error clearing history: {str(e)}")
        raise e

def _parse_storage_uri(uri):
    """Parse a GCS URI to extract bucket name and folder path."""
    # Remove gs:// prefix
    if uri.startswith('gs://'):
        uri = uri[5:]
    
    # Split into bucket and folder path
    parts = uri.split('/', 1)
    bucket_name = parts[0]
    folder_path = parts[1] if len(parts) > 1 else ''
    
    return bucket_name, folder_path

def generate_video(
    project_id,
    prompt,
    input_image=None,
    input_image_path=None,
    aspect_ratio="16:9",
    resolution=None,
    enable_audio=None,
    negative_prompt=None,
    model=None,
    person_generation="allow_adult",
    sample_count=1,
    seed=None,
    storage_uri=None,
    duration_seconds=8,
    enhance_prompt=True,
    wait_for_completion=True,
    poll_interval=10,
    max_attempts=30,
    show_full_response=False,
    enable_streaming=True
):
    """Generate a video using the Veo2 API and display results in Streamlit.
    
    This function handles the entire video generation workflow including:
    1. Initializing the API client
    2. Encoding images if provided
    3. Submitting the generation request with proper API parameters
    4. Polling for completion
    5. Processing results
    6. Adding to history
    7. Displaying the generated videos
    
    Note: The Veo2API client expects snake_case parameters but internally converts them
    to camelCase as required by the API (aspectRatio, negativePrompt, etc.)
    """
    
    # Input validation
    if not project_id:
        st.error("⚠️ Please enter a valid Google Cloud Project ID")
        return
    
    if sample_count > 1 and not storage_uri:
        st.warning("⚠️ When generating multiple videos, it's recommended to provide a storage URI")
    
    # Show a spinner while generating
    with st.spinner("🎬 Generating your video... This may take several minutes"):
        try:
            # Initialize the Veo2 API client
            client = Veo2API(project_id)
            
            # Prepare image if provided
            if input_image_path:
                input_image = client.encode_image_file(input_image_path)
            
            # Save parameters for history tracking using the exact API parameter names (camelCase)
            # These match what the Veo2API client will send to the API
            params = {
                "prompt": prompt,
                "aspectRatio": aspect_ratio,
                "durationSeconds": duration_seconds,
                "sampleCount": sample_count,
                "negativePrompt": negative_prompt if negative_prompt else "",
                "personGeneration": person_generation,
                "seed": seed if seed else "random"
            }

            if model == "veo-2.0-generate-001":
            
            # Generate the video - The Veo2API client internally converts snake_case to camelCase
                response = client.generate_video(
                    prompt=prompt,
                    input_image=input_image,
                    aspect_ratio=aspect_ratio,
                    negative_prompt=negative_prompt,
                    person_generation=person_generation,
                    model=model,  # Use the selected model
                    sample_count=sample_count,
                    seed=seed,
                    storage_uri=storage_uri,
                    duration_seconds=duration_seconds,
                    enhance_prompt=enhance_prompt
                )
            else:
                response = client.generate_video_veo3(
                    prompt=prompt,
                    input_image=input_image,
                    aspect_ratio=aspect_ratio,
                    negative_prompt=negative_prompt,
                    person_generation=person_generation,
                    model=model,  # Use the selected model
                    sample_count=sample_count,
                    # aspect_ratio=aspect_ratio,
                    resolution=resolution,
                    seed=seed,
                    storage_uri=storage_uri,
                    duration_seconds=duration_seconds,
                    enhance_prompt=enhance_prompt,
                    generateAudio=enable_audio
                )
            
            st.markdown(f"{model} model is being used")

            # Extract operation ID
            operation_name = response.get("name", "")
            if not operation_name:
                st.error("⚠️ Failed to start video generation")
                st.json(response)
                return
            
            operation_id = operation_name.split("/")[-1]
            st.info(f"✅ Operation started: {operation_id}")
            
            add_pending_operation_to_firestore(operation_id, "video", params, model)
            # Wait for completion if requested
            if wait_for_completion:
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for attempt in range(max_attempts):
                    progress = min(attempt / max_attempts, 0.95)  # Cap at 95% until complete
                    progress_bar.progress(progress)
                    status_text.text(f"Checking status... Attempt {attempt+1}/{max_attempts}")
                    
                    response = client.poll_operation(operation_id)
                    
                    if response.get("done", False):
                        progress_bar.progress(1.0)
                        status_text.text("Video generation complete!")
                        break
                    
                    if attempt < max_attempts - 1:
                        status_text.text(f"Still processing... Waiting {poll_interval} seconds")
                        time.sleep(poll_interval)
                else:
                    st.warning("⚠️ Operation timeout - The video generation is still in progress but we've stopped waiting")
                    st.warning(f"You can check the status later with operation ID: {operation_id}")
                    return
                
                result = response
                
                # Check if there's an error in the response
                if "error" in result:
                    error_msg = result.get("error", {}).get("message", "Unknown error")
                    st.error(f"⚠️ Video generation failed: {error_msg}")
                    if show_full_response:
                        with st.expander("Error details"):
                            st.json(result)
                    return
                
                # Display the results
                st.success("✅ Video generation complete!")
                
                # Display the full response if requested
                if show_full_response:
                    with st.expander("Full API Response"):
                        st.json(result)
                
                # Extract video URIs
                video_uris = client.extract_video_uris(result)
                
                if video_uris:
                    # Store videos in session state
                    if 'generated_videos' not in st.session_state:
                        st.session_state.generated_videos = []
                    
                    # Add new videos to session state and history
                    for uri in video_uris:
                        # Only add if not already in the list
                        if uri not in [v['uri'] for v in st.session_state.generated_videos]:
                            # Create timestamp for this video
                            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                            
                            # Add to session state
                            st.session_state.generated_videos.append({
                                'uri': uri,
                                'timestamp': timestamp
                            })
                            
                            # Add to history - ONLY done after successful generation
                            try:
                                logger.info(f"Adding video to history: {uri}")
                                if FIRESTORE_AVAILABLE:
                                    doc_ref = db.collection('history').document()
                                    doc_ref.set({
                                        'timestamp': firestore.SERVER_TIMESTAMP,
                                        'user_id': st.session_state.user_id,
                                        'type': "video", 'uri': uri, 'prompt': prompt, 'params': params
                                    })
                                    logger.info(f"Added video {uri} to Firestore history.")

                                logger.success("Successfully added video to Firestore history")
                            except Exception as e:
                                logger.error(f"Could not add video to history: {str(e)}")
                                st.warning(f"Could not add video to history: {str(e)}")
                    
                    display_videos(video_uris, client, enable_streaming)
                else:
                    st.warning("No video URIs found in the response. The video might still be processing or available in a different format.")
                    if not show_full_response:
                        st.info("Try enabling 'Show full API response' in the sidebar to see the complete response.")
            else:
                st.info(f"✅ Operation started: {operation_id}")
                st.info("Check back later for results")
        
        except Exception as e:
            logger.error(f"Error during video generation: {str(e)}")
            st.error(f"⚠️ Error: {str(e)}")
            st.exception(e)

def generate_image(
    project_id,
    prompt,
    model,
    negative_prompt,
    sample_count,
    aspect_ratio,
    seed,
    resolution,
    person_generation,
    safety_filter_level,
    storage_uri,
    enhance_prompt,
):
    """Generate an image using Imagen and display results."""
    if not project_id:
        st.error("⚠️ Please enter a valid Google Cloud Project ID.")
        return
    if not storage_uri:
        st.error("⚠️ Please provide a GCS Storage URI in the settings to save generated images.")
        return

    with st.spinner("🎨 Generating your image with Imagen..."):
        try:
            client = Veo2API(project_id) # Reusing the client

            # Prepare image if provided
            # if input_image_path:
            #     input_image = client.encode_image_file(input_image_path)
            # if reference_image_path:
            #     reference_image = client.encode_image_file(reference_image_path)

            # Generate the image

            response = client.generate_image_imagen(
                # input_image=input_image,
                prompt=prompt,
                model=model,
                negative_prompt=negative_prompt,
                sample_count=sample_count,
                aspect_ratio=aspect_ratio,
                seed=seed,
                resolution=resolution,
                person_generation= person_generation,
                safety_filter_level=safety_filter_level,
                storage_uri=storage_uri,
                enhance_prompt=enhance_prompt
            )

            add_pending_operation_to_firestore(None, "image", {"prompt": prompt, "model": model}, model, response)
            if "error" in response:
                error_msg = response.get("error", {}).get("message", "Unknown error")
                st.error(f"⚠️ Image generation failed: {error_msg}")
                st.json(response)
                return

            # Try to get URIs first, as this is the expected response when storage_uri is provided
            image_uris = client.extract_image_uris(response)
            image_data_list = []

            # If no URIs are found, fall back to checking for base64 encoded data
            if not image_uris:
                image_data_list = client.extract_image_data(response)

            if not image_uris and not image_data_list:
                st.warning("Image generation succeeded, but no images were returned. This could be due to safety filters.")
                st.json(response)
                return

            st.success(f"✅ Successfully generated {len(image_uris) or len(image_data_list)} image(s)!")

            # If we received base64 data, we need to upload it to GCS to get a URI
            if image_data_list:
                st.info("Uploading generated images to your history bucket...")
                uploaded_uris = []
                for i, image_data in enumerate(image_data_list):
                    image_to_upload = Image.open(io.BytesIO(image_data))
                    # Use history manager to upload
                    uri = history_manager.upload_image_to_history(image_to_upload, image_name=f"imagen_{uuid.uuid4().hex}.png")
                    uploaded_uris.append(uri)
                # The final list of URIs is the one we just uploaded
                image_uris = uploaded_uris

            # Add to history
            if image_uris and FIRESTORE_AVAILABLE:
                params = {
                    "prompt": prompt, "model": model, "negativePrompt": negative_prompt,
                    "sampleCount": sample_count, "aspectRatio": aspect_ratio, "seed": seed if seed else "random",
                    "person_generation": person_generation, "safetyFilterThreshold": safety_filter_level,
                }
                for uri in image_uris:
                    db.collection('history').document().set({
                        'timestamp': firestore.SERVER_TIMESTAMP, 'type': 'image', 'uri': uri,
                        'user_id': st.session_state.user_id,
                        'prompt': prompt, 'params': params
                    })

            # Display images
            display_images(image_uris)

        except Exception as e:
            logger.error(f"Error during image generation: {str(e)}")
            st.error(f"⚠️ Error: {str(e)}")
            st.exception(e)

def edit_image(
    project_id,
    prompt,
    model,
    aspect_ratio,
    seed,
    person_generation,
    safety_filter_level,
    storage_uri,
    enhance_prompt,
    input_image_paths: Optional[List[str]] = None, # Expect a list of paths
):
    """Edit an image using Gemini and display results."""
    # ... (project_id and storage_uri checks remain the same) ...

    with st.spinner("🎨 Generating your image with Gemini..."):
        try:
            client = Veo2API(project_id)

            # Prepare a list of input images
            input_images_data = []
            if input_image_paths:
                for image_path in input_image_paths:
                    # 1. Get the base64 encoded data
                    encoded_dict = client.encode_image_file(image_path)
                    base64_data = encoded_dict['bytesBase64Encoded']

                    # 2. Determine the mime type from the file extension
                    mime_type, _ = mimetypes.guess_type(image_path)
                    if mime_type is None:
                        # Fallback for unknown types
                        mime_type = "application/octet-stream"

                    # 3. Construct the correct dictionary and append it
                    input_images_data.append({
                        "data": base64_data,
                        "mime_type": mime_type
                    })

            # Call the new API function
            response = client.generate_image_gemini_image_preview(
                prompt=prompt,
                input_images=input_images_data, # Pass the list of encoded images
                model=model,
                aspectRatio=aspect_ratio,
                safety_threshold=safety_filter_level,
                # Note: 'seed' and other unused parameters are ignored by the new function
            )

            if "error" in response:
                error_msg = response.get("error", {}).get("message", "Unknown error")
                st.error(f"⚠️ Image editing failed: {error_msg}")
            # Try to get URIs first, as this is the expected response when storage_uri is provided
            image_uris = client.extract_image_uris(response)
            image_data_list = []

            # If no URIs are found, fall back to checking for base64 encoded data
            if not image_uris:
                image_data_list = client.extract_image_data(response)

            if not image_uris and not image_data_list:
                st.warning("Image editing succeeded, but no images were returned. This could be due to safety filters.")
                st.json(response)
                return

            st.success(f"✅ Successfully edited {len(image_uris) or len(image_data_list)} image(s)!")

            # If we received base64 data, we need to upload it to GCS to get a URI
            if image_data_list:
                st.info("Uploading edited images to your history bucket...")
                uploaded_uris = []
                for i, image_data in enumerate(image_data_list):
                    image_to_upload = Image.open(io.BytesIO(image_data))
                    # Use history manager to upload
                    uri = history_manager.upload_image_to_history(image_to_upload, image_name=f"gemini_edit_{uuid.uuid4().hex}.png")
                    uploaded_uris.append(uri)
                # The final list of URIs is the one we just uploaded
                image_uris = uploaded_uris

            # Add to history
            if image_uris and FIRESTORE_AVAILABLE:
                params = {
                    "prompt": prompt, "model": model, "aspectRatio": aspect_ratio, "safetyFilterThreshold": safety_filter_level,
                    "input_images": [os.path.basename(p) for p in input_image_paths or []]
                }
                for uri in image_uris:
                    db.collection('history').document().set({
                        'timestamp': firestore.SERVER_TIMESTAMP, 'type': 'image', 'uri': uri,
                        'user_id': st.session_state.user_id,
                        'prompt': f"Edited image with prompt: {prompt}", 'params': params
                    })

            # Display images
            display_images(image_uris)

        except Exception as e:
            logger.error(f"Error during image editing: {str(e)}")
            st.error(f"⚠️ Error: {str(e)}")
            st.exception(e)

            
def display_videos(video_uris, client, enable_streaming=True):
    """Display a list of videos in Streamlit."""
    if not video_uris:
        st.warning("No videos were generated")
        return
    
    st.subheader(f"Generated {len(video_uris)} video(s):")
    
    for i, uri in enumerate(video_uris):
        # Create a collapsible section for each video
        with st.expander(f"Video {i+1}", expanded=True):
             display_single_video(uri, client, enable_streaming)

def display_single_video(uri, client, enable_streaming):
    """Helper function to display a single video."""
    # Display the raw URI
    st.markdown(f"**URI**: {uri}")
    
    # Always display GCS links clearly
    if uri.startswith("gs://"):
        st.code(uri, language="bash")
    
    try:
        # Handle different URI types
        if uri.startswith("http") and not uri.startswith("[Base64"):
            # Direct HTTP URL - can be embedded directly
            st.markdown(f"**Direct streaming link**: [Open in new tab]({uri})")
            
            # Embed with HTML for better controls including fullscreen
            st.markdown(
                f"""
                <div style="position: relative; padding-bottom: 56.25%; height: 0;">
                    <iframe src="{uri}" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;" 
                        frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; fullscreen" 
                        allowfullscreen>
                    </iframe>
                </div>
                """, 
                unsafe_allow_html=True
            )
            
        elif uri.startswith("gs://") and enable_streaming:
            # GCS URI - use cached URL if available, otherwise generate a new one
            auth_url = None
            current_time = time.time()
            
            # Check if URL is cached and still valid
            if uri in st.session_state.signed_url_cache:
                cached_url, expiry_time = st.session_state.signed_url_cache[uri]
                if current_time < expiry_time:
                    auth_url = cached_url
                    logger.debug(f"Using cached URL for {uri}, valid for {int(expiry_time - current_time)} more seconds")
            
            # Generate a new URL if not cached or expired
            if auth_url is None:
                with st.spinner("Generating streaming URL..."):
                    try:
                        auth_url = client.generate_signed_url(uri)
                        
                        # Cache the URL with a 50-minute expiry (tokens typically last 1 hour)
                        expiry_time = current_time + (50 * 60)  # 50 minutes in seconds
                        st.session_state.signed_url_cache[uri] = (auth_url, expiry_time)
                        logger.debug(f"Generated and cached new URL for {uri}, expires in 50 minutes")
                        
                        st.success(f"✅ Streaming URL generated")
                    except Exception as e:
                        st.error(f"⚠️ Failed to generate streaming URL: {str(e)}")
                        st.info("""
                        To access the video manually:
                        1. Use the Google Cloud Console: https://console.cloud.google.com/storage/browser
                        2. Navigate to the bucket and folder
                        3. Download the video file
                        """)
                        return
            
            # Show direct streaming link
            st.markdown(f"**Streaming link**: [Open in new tab]({auth_url})")
            
            # Embed with HTML for better controls including fullscreen
            st.markdown(
                f"""
                <div style="position: relative; padding-bottom: 56.25%; height: 0;">
                    <video controls style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;">
                        <source src="{auth_url}" type="video/mp4">
                        Your browser does not support the video tag.
                    </video>
                </div>
                """, 
                unsafe_allow_html=True
            )
        
        elif uri.startswith("gs://") and not enable_streaming:
            # GCS URI without streaming
            st.info("""
            ⚠️ Video is available in Google Cloud Storage. To access it:
            1. Use the Google Cloud Console: https://console.cloud.google.com/storage/browser
            2. Navigate to the bucket and folder
            3. Download the video file
            
            You can enable streaming in the sidebar to view the video directly here.
            """)
            
        elif uri.startswith("[Base64"):
            # Base64 encoded data
            st.info("The video is available as base64-encoded data in the API response. Enable 'Show full API response' to see it.")
            
        else:
            # Unknown format
            st.warning(f"Unknown URI format: {uri}")
            
    except Exception as e:
        st.error(f"Error displaying video: {str(e)}")

def display_images(image_uris):
    """Display a list of generated images."""
    if not image_uris:
        return

    num_images = len(image_uris)
    cols = st.columns(num_images) if num_images > 0 else [st]
    for i, uri in enumerate(image_uris):
        with cols[i % len(cols)]:
            try:
                signed_url = get_cached_signed_url(uri)
                st.image(signed_url, caption=f"Generated Image {i+1}", use_container_width=True)
                st.markdown(f'<div style="text-align: center;"><a href="{signed_url}" target="_blank" style="font-size: 0.8rem;">Open in new tab</a></div>', unsafe_allow_html=True)
            except Exception as e:
                st.error(f"Error displaying image {i+1}: {e}")

def get_cached_signed_url(uri, expiration=3600):
    """Get a cached signed URL or generate a new one."""
    cache_key = f"signed_url_{uri}"
    current_time = time.time()
    
    if cache_key in st.session_state and st.session_state[cache_key]["expiry"] > current_time:
        signed_url = st.session_state[cache_key]["url"]
        logger.debug(f"Using cached URL for {uri}")
        return signed_url
    else:
        logger.debug(f"Generating new signed URL for {uri}")
        signed_url = generate_signed_url(uri, expiration=expiration)
        # Cache the URL with expiration
        st.session_state[cache_key] = {
            "url": signed_url,
            "expiry": current_time + (expiration - 100)  # Cache for slightly less than the actual expiration
        }
        return signed_url

def _parse_history_params(params_json):
    """Safely parse the params JSON/string from a history record."""
    try:
        if isinstance(params_json, dict):
            return params_json
        if not isinstance(params_json, str):
            return {}
        # First try to parse as JSON
        try:
            return json.loads(params_json)
        except (json.JSONDecodeError, TypeError):
            # If that fails, try to evaluate as a string representation of a dict
            import ast
            try:
                return ast.literal_eval(params_json)
            except (SyntaxError, ValueError):
                return {}
    except Exception as e:
        print(f"Error parsing params: {e}")
        return {}

def display_history_audio_card(row):
    """Display an audio history card with details and buttons."""
    uri = row['uri']
    timestamp = row['timestamp']
    prompt = row.get('prompt', 'No prompt available.')
    params = _parse_history_params(row.get('params', {}))

    try:
        signed_url = get_cached_signed_url(uri)
    except Exception as e:
        st.error(f"Error generating signed URL: {e}")
        signed_url = None

    if signed_url:
        st.audio(signed_url, format="audio/wav") # The API saves as WAV
    else:
        st.error("Could not generate a signed URL for this audio.")

    try:
        if pd.notna(timestamp):
            formatted_time = timestamp.strftime('%Y-%m-%d %H:%M:%S')
        else:
            formatted_time = "Unknown"
    except AttributeError:
        formatted_time = str(timestamp)
    
    st.markdown(f'<div class="history-meta">Generated: {formatted_time}</div>', unsafe_allow_html=True)
    st.code(uri, language="bash")

    with st.expander("Audio Details", expanded=False):
        st.markdown(f"**Prompt:**")
        st.text(prompt)
        if params:
            st.markdown(f"**Parameters:**")
            st.json(params)

    if signed_url:
        st.markdown(f'<div style="text-align: right;"><a href="{signed_url}" target="_blank" style="font-size: 0.8rem;">Open in new tab</a></div>', unsafe_allow_html=True)

def display_history_voice_card(row):
    """Display a voiceover history card with details and buttons."""
    uri = row['uri']
    timestamp = row['timestamp']
    script = row.get('prompt', 'No script available.')
    params = _parse_history_params(row.get('params', {}))

    try:
        signed_url = get_cached_signed_url(uri)
    except Exception as e:
        st.error(f"Error generating signed URL: {e}")
        signed_url = None

    if signed_url:
        st.audio(signed_url, format="audio/wav") # TTS often produces WAV
    else:
        st.error("Could not generate a signed URL for this voiceover.")

    try:
        if pd.notna(timestamp):
            formatted_time = timestamp.strftime('%Y-%m-%d %H:%M:%S')
        else:
            formatted_time = "Unknown"
    except AttributeError:
        formatted_time = str(timestamp)
    
    st.markdown(f'<div class="history-meta">Generated: {formatted_time}</div>', unsafe_allow_html=True)
    st.code(uri, language="bash")

    with st.expander("Voiceover Details", expanded=False):
        st.markdown(f"**Script:**")
        st.text(script)
        if params:
            st.markdown(f"**Parameters:**")
            st.json(params)

    if signed_url:
        st.markdown(f'<div style="text-align: right;"><a href="{signed_url}" target="_blank" style="font-size: 0.8rem;">Open in new tab</a></div>', unsafe_allow_html=True)

def dub_video(uploaded_video, input_language, output_language, bucket_name):
    """
    Dubs a video using the app.py library functions.
    """
    # 1. Save uploaded video to a temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_video.name)[1]) as tmp_in:
        tmp_in.write(uploaded_video.getvalue())
        input_video_path = tmp_in.name

    try:
        # Create UI elements for logging
        st.subheader("⚙️ Processing Status")
        log_container = st.empty()
        synthesis_log_area = st.container()
        
        # Set up logger and session state for live logging
        log_queue = queue.Queue()
        st.session_state.log_messages = []
        logger = dubbing_lib.StatusLogger(log_queue)

        # Prepare config dictionary
        # These models can be exposed in the UI later if needed
        config_dict = {
            "USE_VERTEX_AI": False,
            "PROJECT_ID": st.session_state.get("project_id", config.PROJECT_ID),
            "LOCATION": "us-central1",
            "GOOGLE_API_KEY": config.GEMINI_API_KEY,
            "VIDEO_ANALYSIS_PROMPT": dubbing_lib.DEFAULT_VIDEO_ANALYSIS_PROMPT,
            "INPUT_LANGUAGE": input_language.split(' (')[0],
            "OUTPUT_LANGUAGE": output_language.split(' (')[0],
            "MODEL_NAME": "gemini-2.5-pro",
            "TTS_MODEL": "gemini-2.5-pro-preview-tts",
            "BUCKET_NAME": bucket_name
        }

        # Call the main dubbing function from app.py
        final_video_gcs_path = dubbing_lib.process_video_dubbing(
            video_path=input_video_path,
            config=config_dict,
            logger=logger,
            log_container=log_container,
            synthesis_log_area=synthesis_log_area
        )

        if final_video_gcs_path:
            full_gcs_uri = f"gs://{bucket_name}/{final_video_gcs_path}"
            st.success("✅ Dubbing process completed successfully!")
            signed_url = client.generate_signed_url(full_gcs_uri)
            st.subheader("Dubbed Video Preview")
            st.video(signed_url)
            
            if FIRESTORE_AVAILABLE:
                db.collection('history').add({
                    'user_id': st.session_state.user_id,
                    'timestamp': firestore.SERVER_TIMESTAMP,
                    'type': 'video',
                    'uri': full_gcs_uri,
                    'prompt': f'Video dubbed from {input_language} to {output_language}.',
                    'params': {'operation': 'dub_video', 'input_language': input_language, 'output_language': output_language}
                })
                st.success(f"✅ Dubbed video saved to history: {full_gcs_uri}")
        else:
            st.error("⚠️ Dubbing process failed. Check the logs above for details.")

    except Exception as e:
        st.error(f"An unexpected error occurred during the dubbing process: {e}")
        import traceback
        st.code(traceback.format_exc())
    finally:
        # Clean up the temporary file
        if os.path.exists(input_video_path):
            os.unlink(input_video_path)

def generate_audio(
    project_id,
    prompt,
    sample_count=1,
    negative_prompt=None,
    seed=None,
    storage_uri=None,
    wait_for_completion=True,
    poll_interval=10,
    max_attempts=30,
    show_full_response=False,
    enable_streaming=True
):
    """Generate audio using the generative audio API and display results in Streamlit."""
    # Input validation (as needed)
    if not project_id:
        st.error("⚠️ Please enter a valid Google Cloud Project ID")
        return

    if sample_count > 1 and not storage_uri:
        st.warning("⚠️ When generating multiple audio samples, it's recommended to provide a storage URI")

    # Placeholder spinner
    with st.spinner("🎵 Generating your audio... This may take a moment"):
        try:
            # Prepare API parameters for history
            params = {
                "prompt": prompt,
                "sampleCount": sample_count,
                "negativePrompt": negative_prompt if negative_prompt else "",
                "seed": seed if seed else "random",
            }

            # Create a unique ID for this synchronous operation to track it
            operation_id = f"audio-{uuid.uuid4().hex}"

            # Add to pending operations BEFORE the API call
            add_pending_operation_to_firestore(
                operation_id=operation_id,
                operation_type='audio',
                params=params,
                model_id='lyria-002', # Hardcoded model for Lyria
            )

            # Make the API call
            response = client.generate_audio(
                prompt=prompt,
                sample_count=sample_count,
                negative_prompt=negative_prompt,
                seed=seed,
                storage_uri=storage_uri,
            )

            # The response will contain the URIs of the generated audio files.
            audio_uris = response if isinstance(response, list) else []

            # Add to history if URIs were generated
            if audio_uris and FIRESTORE_AVAILABLE:
                logger.info(f"Adding {len(audio_uris)} audio entries to Firestore history.")
                for uri in audio_uris:
                    try:
                        doc_ref = db.collection('history').document()
                        doc_ref.set({
                            'timestamp': firestore.SERVER_TIMESTAMP,
                            'user_id': st.session_state.user_id,
                            'type': "audio",
                            'uri': uri,
                            'prompt': prompt,
                            'params': params
                        })
                        logger.debug(f"Added audio {uri} to Firestore history.")
                    except Exception as e:
                        logger.error(f"Could not add audio {uri} to history: {str(e)}")
                logger.success("Successfully added audio generation details to Firestore.")

        except Exception as e:
            logger.error(f"Error during audio generation: {str(e)}")
            st.error(f"⚠️ Error: {str(e)}")
            st.exception(e)


def display_audios(audio_uris, enable_streaming=True):
    """Display a list of audio samples in Streamlit (placeholder)."""
    if not audio_uris:
        st.warning("No audio samples were generated (placeholder)")
        return

    st.subheader(f"Generated {len(audio_uris)} audio sample(s): (Placeholder)")

    for i, uri in enumerate(audio_uris):
        # Create a collapsible section for each audio
        with st.expander(f"Audio {i+1}", expanded=True):
            display_single_audio(uri, enable_streaming)


def display_single_audio(uri, enable_streaming):
    """Helper function to display a single audio sample (placeholder)."""
    # Display the raw URI
    st.markdown(f"**URI**: {uri} (Placeholder)")

    # Always display GCS links clearly
    if uri.startswith("gs://"):
        st.code(uri, language="bash")

    try:
        # Handle different URI types (adjust for your audio API)
        if uri.startswith("http") and not uri.startswith("[Base64"):
            # Direct HTTP URL - can be embedded directly (adjust if needed for audio)
            st.markdown(f"**Direct link**: [Open in new tab]({uri}) (Placeholder)")
            st.audio(uri)  # Use st.audio for playback
        elif uri.startswith("gs://") and enable_streaming:
            # GCS URI - generate a signed URL (if needed by your audio API)
            auth_url = None
            # You might need to adjust the logic here depending on your audio API's
            # streaming capabilities and authentication requirements.
            # auth_url = client.generate_signed_url(uri)  # Example (adjust as needed)
            auth_url = uri # Placeholder - assuming direct access or other logic

            if auth_url:
                st.markdown(f"**Streaming link**: [Open in new tab]({auth_url}) (Placeholder)")
                st.audio(auth_url)  # Use st.audio for playback
            else:
                st.error("⚠️ Failed to generate streaming URL (placeholder)")
        elif uri.startswith("gs://") and not enable_streaming:
            # GCS URI without streaming (provide instructions)
            st.info("""
            ⚠️ Audio is available in Google Cloud Storage. To access it:
            1. Use the Google Cloud Console: https://console.cloud.google.com/storage/browser
            2. Navigate to the bucket and folder
            3. Download the audio file

            You can enable streaming in the sidebar to attempt direct playback.
            """)
        elif uri.startswith("[Base64"):
            # Base64 encoded data (handle as needed by your audio API)
            st.info("The audio is available as base64-encoded data (placeholder)")
            # You'd need to decode and handle the audio data here.
        else:
            # Unknown format
            st.warning(f"Unknown URI format: {uri} (Placeholder)")

    except Exception as e:
        st.error(f"Error displaying audio: {str(e)} (Placeholder)")


# --- Helper Function to Upload to GCS ---
def upload_to_gcs(file_obj, bucket_name: str) -> str | None:
    """
    Uploads a file-like object to a GCS bucket.

    Args:
        file_obj: The file-like object to upload (e.g., from st.file_uploader or BytesIO).
        bucket_name: The name of the target GCS bucket.

    Returns:
        The GCS URI of the uploaded file (gs://bucket/object), or None on failure.
    """
    if not bucket_name:
        st.error("GCS_BUCKET_NAME environment variable is not set.")
        logger.error("GCS_BUCKET_NAME is not set.")
        return None

    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)

        # Secure the original filename and add a unique prefix
        original_filename = secure_filename(file_obj.name)
        unique_filename = f"{uuid.uuid4()}-{original_filename}"

        blob = bucket.blob(unique_filename)

        # Reset file pointer to the beginning before reading
        file_obj.seek(0)

        # Upload the file
        content_type = getattr(file_obj, 'content_type', file_obj.type)
        blob.upload_from_file(file_obj, content_type=content_type)

        gcs_uri = f"gs://{bucket_name}/{unique_filename}"
        logger.info(f"Successfully uploaded file to {gcs_uri}")
        st.success(f"✅ Image uploaded to Cloud Storage: {unique_filename}")
        return gcs_uri

    except Exception as e:
        logger.error(f"Failed to upload to GCS: {e}")
        st.error(f"Error uploading to Cloud Storage: {e}")
        return None

def video_upload_to_gcs(file_path: str, bucket_name: str, object_name: str) -> str | None:
    """Uploads a local video file to a GCS bucket."""
    if not bucket_name:
        st.error("GCS Bucket Name is not configured correctly.")
        return None
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        
        unique_object_name = f"edited-videos/{uuid.uuid4()}-{secure_filename(object_name)}"
        blob = bucket.blob(unique_object_name)

        blob.upload_from_filename(file_path, content_type="video/mp4")

        gcs_uri = f"gs://{bucket_name}/{unique_object_name}"
        logger.info(f"Successfully uploaded video to {gcs_uri}")
        st.success("✅ Edited video uploaded to Cloud Storage.")
        return gcs_uri
    except Exception as e:
        logger.error(f"Failed to upload video to GCS: {e}")
        st.error(f"Error uploading video to Cloud Storage: {e}")
        return None


def display_history_image_card(row):
    """Display an image history card with details and buttons."""
    # Extract data
    doc_id = row['doc_id'] # Get the unique Firestore document ID
    uri = row['uri']
    # Generate a unique identifier for this image based on more of the URI
    unique_id = uri.replace("/", "_").replace(".", "_").replace(":", "_")[-20:]
    
    timestamp = row['timestamp']
    params_json = row['params'] if pd.notna(row['params']) else "{}"
    
    # Extract the filename from the URI if nothing else is available
    default_filename = uri.split('/')[-1] if uri else "Unknown file"
    
    # Parse params to get filename and other info
    params = _parse_history_params(params_json)
    is_generated = 'model' in params
    filename = params.get('filename', default_filename)
    
    # --- Selection Checkbox ---
    is_selected = uri in st.session_state.get('selected_history_items', {})

    def toggle_selection():
        if uri in st.session_state.selected_history_items:
            del st.session_state.selected_history_items[uri]
        else:
            st.session_state.selected_history_items[uri] = 'image'
    # Use the unique Firestore document ID for the checkbox key
    st.checkbox("Select this image", value=is_selected, key=f"select_{doc_id}", on_change=toggle_selection, label_visibility="collapsed")
    try:

        signed_url = get_cached_signed_url(uri)
    except Exception as e:
        st.error(f"Error generating signed URL: {e}")
        signed_url = None
    
    # Display the image with controlled size
    if signed_url:
        try:
            st.image(signed_url, use_container_width=True)
        except Exception as e:
            st.error(f"Error displaying image: {e}")
            st.markdown(f'<a href="{signed_url}" target="_blank">Open image in new tab</a>', unsafe_allow_html=True)
    else:
        st.error("Could not generate a signed URL for this image.")
    
    # Display image details
    # Handle the timestamp which may be a datetime object or NaT
    try:
        if pd.notna(timestamp):
            # Format the datetime object
            formatted_time = timestamp.strftime('%Y-%m-%d %H:%M:%S')
        else:
            formatted_time = "Unknown"
    except AttributeError:
        # Fallback for older data that might not be a datetime object
        formatted_time = str(timestamp)
    
    label = "Generated" if is_generated else "Uploaded"
    st.markdown(f'<div class="history-meta">{label}: {formatted_time}</div>', unsafe_allow_html=True)
    if not is_generated:
        st.markdown(f'<div class="history-meta">Filename: {filename}</div>', unsafe_allow_html=True)
    
    # Display parameters info if available
    if params:
        with st.expander("Image Details", expanded=False):
            params_str = json.dumps(params, indent=2)
            st.code(params_str, language="json")
    
    # Display URI for copying - make it more visible
    st.markdown("**GCS URI:**")
    st.code(uri, language="bash")
    
    # Provide direct link to open in new tab
    if signed_url:
        st.markdown(f'<div style="text-align: right;"><a href="{signed_url}" target="_blank" style="font-size: 0.8rem;">Open in new tab</a></div>', unsafe_allow_html=True)

def download_gcs_file_and_simulate_upload(uri: str) -> Optional[SimulatedUploadFile]:
    """Downloads a file from GCS and wraps it in a file-like object for Streamlit."""
    try:
        logger.info(f"Downloading {uri} from GCS...")
        # Use the global client to generate a signed URL
        signed_url = get_cached_signed_url(uri)
        response = requests.get(signed_url)
        response.raise_for_status()

        content = response.content
        filename = uri.split('/')[-1]

        logger.success(f"Successfully downloaded {filename}.")
        return SimulatedUploadFile(name=filename, content=content)
    except Exception as e:
        logger.error(f"Failed to download and simulate upload for {uri}: {e}")
        st.error(f"Failed to load {uri.split('/')[-1]} from history.")
        return None

def handle_history_action(operation: str, uris: List[str]):
    """Processes the selected action from the history tab."""
    with st.spinner(f"Preparing assets for '{operation}'..."):
        simulated_files = [download_gcs_file_and_simulate_upload(uri) for uri in uris]
        simulated_files = [f for f in simulated_files if f] # Filter out None on failure

        if not simulated_files:
            st.error("Failed to load any of the selected files from storage.")
            return

        if operation == "Edit Image(s)":
            st.session_state.edit_image_files = simulated_files
            st.session_state.active_image_sub_tab = "Image Editing (Nano Banana)"
            st.session_state.next_active_main_tab = "🎨 Image"
        elif operation == "Use for Image-to-Video":
            # Set the canonical active image data. The Image-to-Video tab will
            # pick this up on the next run. This is the safe way.
            st.session_state.active_image_data = simulated_files[0]
            # Clear any URL that might have been there to avoid conflicts
            st.session_state.current_image_url = ""
            st.session_state.active_video_sub_tab = "Image-to-Video"
            st.session_state.next_active_main_tab = "🎬 Video"
        elif operation == "Concatenate Videos":
            st.session_state.concat_video_files = simulated_files
            st.session_state.video_edit_option = "Concatenate Videos"
            st.session_state.active_video_sub_tab = "Video Editing"
            st.session_state.next_active_main_tab = "🎬 Video"
        elif operation == "Change Video Speed":
            st.session_state.speed_change_video_file = simulated_files[0]
            st.session_state.video_edit_option = "Change Playback Speed"
            st.session_state.active_video_sub_tab = "Video Editing"
            st.session_state.next_active_main_tab = "🎬 Video"
        elif operation == "Dubbing":
            st.session_state.dub_video_file = simulated_files[0]
            st.session_state.video_edit_option = "Dubbing"
            st.session_state.active_video_sub_tab = "Video Editing"
            st.session_state.next_active_main_tab = "🎬 Video"

        # Clear selection and rerun to switch tab and apply state changes
        st.session_state.selected_history_items.clear()
        st.rerun()

def display_history_actions():
    """Displays the action panel for selected history items."""
    with st.container(border=True):
        items = st.session_state.selected_history_items
        st.subheader(f"{len(items)} item(s) selected")

        item_types = set(items.values())
        operations = ["-- Select an action --"]

        if item_types == {'image'}:
            operations.append("Edit Image(s)")
            if len(items) == 1:
                operations.append("Use for Image-to-Video")
        elif item_types == {'video'}:
            if len(items) > 1:
                operations.append("Concatenate Videos")
            if len(items) == 1:
                operations.append("Change Video Speed")
                operations.append("Dubbing") # Add Dubbing option for single video


        if len(operations) > 1:
            selected_op = st.selectbox("Perform an action:", options=operations, key="history_action_selector", index=0)
            if selected_op != "-- Select an action --":
                handle_history_action(selected_op, list(items.keys()))
        else:
            st.warning("No actions available for the current selection (e.g., mixed types or unsupported count).")

        if st.button("Clear Selection"):
            st.session_state.selected_history_items.clear()
            st.rerun()

if __name__ == "__main__":
    # Initialize minimal session state variables
    if "selected_video_uri" not in st.session_state:
        st.session_state.selected_video_uri = None
        
    if "selected_video_prompt" not in st.session_state:
        st.session_state.selected_video_prompt = None
    
    # Removed the history image selection state
    # if "selected_source_image" not in st.session_state:
    #     st.session_state.selected_source_image = None
    
    if "confirm_clear_history" not in st.session_state:
        st.session_state.confirm_clear_history = False
    
    # Create a custom logger instance
    logger = Logger(debug=config.DEBUG_MODE)
    logger.info("Starting Veo2 Video Generator app")
    
    main()
