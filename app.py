import os
import streamlit as st
import google.genai as genai
import time
import json
from moviepy.editor import VideoFileClip, AudioFileClip
from pydub import AudioSegment
import subprocess
from google.genai import types
import wave
import tempfile
import datetime
from google.cloud import storage
import pyrubberband as rb
import soundfile as sf
import concurrent.futures
import queue

# --- UI HELPER DATA ---

# A curated list of common languages for the dropdowns
LANGUAGES = [
    "Arabic", "Bengali", "Chinese", "Dutch", "English", "French", "German",
    "Hindi", "Indonesian", "Italian", "Japanese", "Korean", "Malayalam",
    "Marathi", "Polish", "Portuguese", "Punjabi", "Russian", "Spanish",
    "Tamil", "Telugu", "Turkish", "Ukrainian", "Urdu", "Vietnamese"
]

# List of GCP regions for the dropdown
GCP_REGIONS = [
    "global", "africa-south1", "us-central1", "us-east1", "us-east4",
    "us-east5", "us-south1", "us-west1", "us-west2", "us-west3", "us-west4",
    "asia-east1", "asia-east2", "asia-northeast1", "asia-northeast2",
    "asia-northeast3", "asia-south1", "asia-south2", "asia-southeast1",
    "asia-southeast2", "australia-southeast1", "australia-southeast2",
    "europe-central2", "europe-north1", "europe-southwest1", "europe-west1",
    "europe-west2", "europe-west3", "europe-west4", "europe-west6",
    "europe-west8", "europe-west9", "europe-west10", "europe-west12",
    "me-central1", "me-central2", "me-west1", "southamerica-east1",
    "southamerica-west1"
]

# --- VOICE CONFIG (From original script) ---
MALE_VOICE_LIST = ['Puck', 'Orus', 'Enceladus', 'Charon', 'Fenrir', 'Iapetus', 'Umbriel']
FEMALE_VOICE_LIST = ['Kore', 'Zephyr', 'Leda', 'Sulafat', 'Aoede', 'Callirrhoe', 'Autonoe']
CHILD_VOICE_LIST = ['Leda', 'Kore']
FALLBACK_VOICE = 'Leda'

# --- DEFAULT PROMPT ---
# This is the default prompt that will be shown in the UI for editing.
DEFAULT_VIDEO_ANALYSIS_PROMPT = """
You are an expert voice director and video producer creating a script for dubbing.
Analyze the provided video file's audio track with extreme detail. Your goal is to capture the complete performance, including the emotional and dramatic context.

Follow these steps precisely:
1.  **Speaker Diarization**: Use a combination of audio and video to identify every distinct speaker and assign a unique label (e.g., SPEAKER_1).
2.  **Character Classification**: Classify each speaker as MALE, FEMALE, or CHILD.
3.  **Emotional Analysis**: For each dialogue segment, identify the primary emotion being conveyed. Choose from this list: **Love & Affection: PASSIONATE, LONGING, ADORING, FLIRTATIOUS, TENDER, SHY
                  Joy & Happiness: ELATED, AMUSED, CONTENT, RELIEVED, HOPEFUL
                  Anger & Fury: IRRITATED, FRUSTRATED, RAGING, INDIGNANT, VENGEFUL, CONTEMPTUOUS
                  Sadness & Grief: SORROWFUL, HEARTBROKEN, DESPAIRING, MELANCHOLIC, SYMPATHETIC
                  Fear & Anxiety: TERRIFIED, ANXIOUS, NERVOUS, DREADFUL, PANICKED
                  Surprise & Wonder: SHOCKED, ASTONISHED, AWESTRUCK, DISBELIEF
                  Complex & Social: GUILTY, ASHAMED, JEALOUS, BETRAYED, DESPERATE, ARROGANT, SUSPICIOUS
                  Neutral: NEUTRAL**.
4.  **Delivery Style Analysis**: For each dialogue segment, identify the style of delivery. Choose from this list: **NORMAL, SHOUTING, WHISPERING, PLEADING, CRYING / SOBBING, LAUGHING, MOCKING / SARCASTIC,
                         MENACING, FRANTIC, HESITANT, FIRM**.
5.  **Transcription & Translation**: Provide the timestamped original '{INPUT_LANGUAGE}' transcript and its accurate and meaningful '{OUTPUT_LANGUAGE}' translation as used in movies.
6.  **Pace of Speech**: For each dialogue segment, identify the pace of delivery. Choose from this list: **NORMAL, FAST, VERY FAST, SLOW, MEDIUM, VERY SLOW**.
7.  **Time Conversion**: Always assign the start and end time in seconds. Do not consider minutes. For example, if a time shows as 1:12, it should be converted to 72 seconds (60+12 seconds) and not 112 seconds.
8.  **Non-Dialogue Sounds**: Capture any significant non-dialogue vocal sounds like sighs, gasps, laughs, or cries and include them in the transcript.
9.  **Output Format**: Your final output MUST be a valid JSON array of objects. Do not include any text or explanations outside of this array. Each object represents a single line of dialogue and must have the following structure:
    {{
          "start_time": float,
          "end_time": float,
          "speaker_label": "string",
          "character_type": "string (MALE, FEMALE, or CHILD)",
          "emotion": "string (e.g., Love & Affection: PASSIONATE, LONGING, ADORING, FLIRTATIOUS, TENDER, SHY
                      Joy & Happiness: ELATED, AMUSED, CONTENT, RELIEVED, HOPEFUL
                      Anger & Fury: IRRITATED, FRUSTRATED, RAGING, INDIGNANT, VENGEFUL, CONTEMPTUOUS
                      Sadness & Grief: SORROWFUL, HEARTBROKEN, DESPAIRING, MELANCHOLIC, SYMPATHETIC
                      Fear & Anxiety: TERRIFIED, ANXIOUS, NERVOUS, DREADFUL, PANICKED
                      Surprise & Wonder: SHOCKED, ASTONISHED, AWESTRUCK, DISBELIEF
                      Complex & Social: GUILTY, ASHAMED, JEALOUS, BETRAYED, DESPERATE, ARROGANT, SUSPICIOUS
                      Neutral: NEUTRAL)",
          "delivery_style": "string (NORMAL, SHOUTING, WHISPERING, PLEADING, CRYING / SOBBING, LAUGHING, MOCKING / SARCASTIC,
                             MENACING, FRANTIC, HESITANT, FIRM)",
          "original_transcript": "string ('{INPUT_LANGUAGE}' text)",
          "{OUTPUT_LANGUAGE}_translation": "string ('{OUTPUT_LANGUAGE}' text)",
          "pace": "string (NORMAL, FAST, VERY FAST, SLOW, MEDIUM or VERY SLOW)"
    }}
"""

# @st.cache_resource
def get_gcs_client(key_path=None):
    """Get GCS client, cached for performance."""
    try:
        if key_path and os.path.exists(key_path):
            st.session_state['gcs_client_auth_method'] = 'service_account'
            return storage.Client.from_service_account_json(key_path)
        else:
            st.session_state['gcs_client_auth_method'] = 'default_credentials'
            return storage.Client()
    except Exception as e:
        st.error(f"Failed to initialize GCS client: {e}")
        return None

def download_gcs_file(client, bucket_name, source_blob_name, logger):
    """Downloads a blob from the bucket to a local temporary file."""
    try:
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(source_blob_name)
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(source_blob_name)[1]) as tmpfile:
            logger.log(f"⬇️ Downloading gs://{bucket_name}/{source_blob_name}...")
            blob.download_to_filename(tmpfile.name)
            logger.log("✅ Download complete.")
            return tmpfile.name
    except Exception as e:
        logger.log(f"❌ Failed to download file from GCS: {e}")
        st.error(f"Failed to download gs://{bucket_name}/{source_blob_name}. Error: {e}")
        return None

def upload_to_gcs(client, bucket_name, source_file_path, destination_blob_name, logger):
    """Uploads a file to the bucket."""
    try:
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)
        logger.log(f"⬆️ Uploading final video to gs://{bucket_name}/{destination_blob_name}...")
        blob.upload_from_filename(source_file_path)
        logger.log("✅ Upload complete.")
        return True
    except Exception as e:
        logger.log(f"❌ Failed to upload file to GCS: {e}")
        st.error(f"Failed to upload to gs://{bucket_name}/{destination_blob_name}. Error: {e}")
        return False

class StatusLogger:
    """A thread-safe logger that puts messages onto a queue."""
    def __init__(self, log_queue: queue.Queue):
        self.queue = log_queue
    
    def log(self, message: str):
        """Puts a message onto the log queue."""
        self.queue.put(message)

def render_logs(container, current_logs: list):
    """Renders a list of log messages into a Streamlit container."""
    with container:
        if not current_logs:
            st.info("Waiting to start...")
            return

        # Show the latest status message prominently
        latest_msg = current_logs[-1]
        timestamp_str, _, message_body = latest_msg.partition(" - ")
        if "✅" in message_body or "🎉" in message_body:
            st.success(f"**LATEST:** {message_body}")
        elif "❌" in message_body or "⚠️" in message_body:
            st.warning(f"**LATEST:** {message_body}")
        else:
            st.info(f"**LATEST:** {message_body}")

        # Show the full log in an expander
        with st.expander("View full processing log", expanded=False):
            log_text = "\n".join(reversed(current_logs))
            # Ensure the key is unique for each render pass to avoid Streamlit errors in loops.
            if 'log_render_count' not in st.session_state:
                st.session_state.log_render_count = 0
            st.session_state.log_render_count += 1
            st.text_area("Full Log", value=log_text, height=300, disabled=True, key=f"full_log_textarea_{st.session_state.log_render_count}")

# --- CORE LOGIC ---

def get_dubbing_script_from_video(video_path, config, logger):
    """
    Uploads a video to the Gemini API and analyzes it using a provided prompt.
    """
    try:
        if config["USE_VERTEX_AI"]:
            logger.log(f"Authenticating with Vertex AI (Project: {config['PROJECT_ID']}, Location: {config['LOCATION']})")
            client = genai.Client(project=config["PROJECT_ID"], location=config["LOCATION"])
        else:
            logger.log("Authenticating with Google API Key")
            client = genai.Client(api_key=config["GOOGLE_API_KEY"])
    except Exception as e:
        logger.log(f"❌ Authentication failed: {e}")
        return None

    logger.log(f"Uploading video '{os.path.basename(video_path)}' to the Gemini API...")
    video_file = client.files.upload(file=video_path)
    
    logger.log("...Video is processing on the server")
    while video_file.state.name == "PROCESSING":
        time.sleep(10)
        video_file = client.files.get(name=video_file.name)

    if video_file.state.name == "FAILED":
        logger.log(f"❌ Video processing failed: {video_file.state}")
        raise ValueError(f"Video processing failed: {video_file.state}")

    logger.log(f"✅ Video uploaded and processed successfully: {video_file.name}")

    # <<< MODIFIED: Get the prompt from the config and format it >>>
    raw_prompt = config['VIDEO_ANALYSIS_PROMPT']
    prompt = raw_prompt.format(
        INPUT_LANGUAGE=config["INPUT_LANGUAGE"],
        OUTPUT_LANGUAGE=config["OUTPUT_LANGUAGE"]
    )
    
    logger.log(f"🤖 Sending request to {config['MODEL_NAME']} for analysis...")
    response = client.models.generate_content(
        model=config['MODEL_NAME'],
        contents=[video_file, "\n\n", prompt]
    )
    client.files.delete(name=video_file.name)
    logger.log(f"Cleaned up uploaded file on server.")

    try:
        json_text = response.text.strip().lstrip("```json").rstrip("```")
        dubbing_script = json.loads(json_text)
        dubbing_script.sort(key=lambda x: x['start_time'])
        logger.log("✅ Successfully received and parsed the dubbing script from Gemini.")
        #with st.expander("Show Generated Dubbing Script (JSON)"):
        #    st.json(dubbing_script)
        return dubbing_script
    except (json.JSONDecodeError, IndexError, AttributeError) as e:
        logger.log(f"❌ Failed to parse JSON from Gemini's response: {e}")
        logger.log(f"RAW RESPONSE:\n{response.text}")
        return None

def extract_audio(video_path, audio_path, logger):
    logger.log(f"🎥 Extracting audio from '{os.path.basename(video_path)}'...")
    try:
        with VideoFileClip(video_path) as video_clip:
            video_clip.audio.write_audiofile(audio_path, codec='pcm_s16le', logger=None)
        logger.log(f"✅ Audio extracted to '{os.path.basename(audio_path)}'")
        return audio_path
    except Exception as e:
        logger.log(f"❌ Error extracting audio: {e}")
        return None

def separate_background_music(audio_path, output_dir, logger):
    logger.log("🎶 Separating background music with Demucs...")
    try:
        command = ["python3", "-m", "demucs.separate", "-n", "htdemucs", "-o", str(output_dir), "--two-stems", "vocals", str(audio_path)]
        #with st.spinner('Demucs is separating audio tracks... This may take some time.'):
        subprocess.run(command, check=True, capture_output=True, text=True)
        
        audio_filename = os.path.splitext(os.path.basename(audio_path))[0]
        background_path = os.path.join(output_dir, "htdemucs", audio_filename, "no_vocals.wav")

        if os.path.exists(background_path):
            logger.log("✅ Background music separated successfully.")
            return background_path
        else:
            logger.log("❌ Demucs did not produce the background music file.")
            return None
    except Exception as e:
        logger.log(f"❌ An error occurred during audio separation: {e}")
        return None

def wave_file(filename, pcm, channels=1, rate=24000, sample_width=2):
    with wave.open(filename, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm)

def synthesize_speech_with_gemini(text, segment_details, config, logger):
    logger.log(f"   Synthesizing: '{text[:40]}...' for {segment_details['speaker_label']}")
    try:
        if config["USE_VERTEX_AI"]:
            client = genai.Client(project=config["PROJECT_ID"], location=config["LOCATION"])
        else:
            client = genai.Client(api_key=config["GOOGLE_API_KEY"])
    except Exception as e:
        logger.log(f"❌ TTS Authentication failed: {e}")
        return None, ""
    
    # Build enhanced TTS prompt using the advanced logic from the CLI
    full_prompt = _build_tts_prompt(text, segment_details, config)

    try:
        response = client.models.generate_content(
            model=config['TTS_MODEL'],
            contents=full_prompt,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                           voice_name=segment_details['selected_voice'],
                        )
                    )
                ),
            )
        )

        if not response.candidates or not response.candidates[0].content or not response.candidates[0].content.parts:
            logger.log(f"❌ Gemini returned an empty response for the text. Skipping.")
            return None, full_prompt

        audio_data = response.candidates[0].content.parts[0].inline_data.data
        if not audio_data:
            logger.log(f"❌ Gemini did not return audio data for the text.")
            return None, full_prompt

        wave_file(segment_details['output_path'], audio_data)
        return segment_details['output_path'], full_prompt
    except Exception as e:
        logger.log(f"❌ Error synthesizing speech with Gemini: {e}")
        return None, full_prompt

def _build_tts_prompt(text, segment_details, config):
    """Build enhanced TTS prompt with naturalistic performance guidance."""
    
    # Character voice foundation
    voice_foundation = _build_character_voice_foundation(segment_details, config)
    
    # Prosodic delivery instructions
    prosodic_guidance = _build_prosodic_instructions(segment_details)
    
    # Contextual performance notes
    contextual_delivery = _build_contextual_delivery(segment_details)
    
    # Naturalness and timing instructions
    naturalness_guidance = _build_naturalness_instructions(segment_details)
    
    # Add accent enforcement for consistency
    accent_enforcement = _build_accent_enforcement(config)
    
    # Add dubbing script compliance instructions
    script_compliance = _build_script_compliance_instructions(segment_details)
    
    return f"""
    You are voicing {segment_details.get('speaker_label', 'the character')} in a professional film dubbing session.
    
    CHARACTER VOICE: {voice_foundation}
    
    ACCENT CONSISTENCY: {accent_enforcement}
    
    PROSODIC DELIVERY: {prosodic_guidance}
    
    PERFORMANCE CONTEXT: {contextual_delivery}
    
    SCRIPT COMPLIANCE: {script_compliance}
    
    NATURALNESS: {naturalness_guidance}
    
    TIMING: Deliver naturally within {segment_details['clip_duration']}ms, maintaining organic rhythm and flow.
    
    TEXT: "{text}"
    
    CRITICAL: Maintain consistent accent throughout. Perform this line as the character in this exact emotional moment, not as script reading.
    Focus on authentic human speech patterns, emotional authenticity, and strict adherence to accent specifications.
    """

def _build_character_voice_foundation(segment_details, config):
    """Build character voice description with accent specification."""
    char_type = segment_details.get("character_type", "ADULT")
    language = config['OUTPUT_LANGUAGE']
    
    # Specify accent variant for English
    accent_specification = _get_accent_specification(language)
    
    if char_type == "MALE":
        return f"Adult male {accent_specification} speaker with natural masculine vocal characteristics"
    elif char_type == "FEMALE":
        return f"Adult female {accent_specification} speaker with natural feminine vocal characteristics"
    elif char_type == "CHILD":
        return f"Young {accent_specification} speaker with age-appropriate higher pitch and youthful speech patterns"
    elif char_type == "ELDERLY":
        return f"Elderly {accent_specification} speaker with mature vocal characteristics and life experience"
    else:
        return f"Natural {accent_specification} speaker with conversational vocal characteristics"

def _get_accent_specification(language):
    """Get accent specification for the language with Indian English default."""
    language_lower = language.lower()
    
    # Explicit accent mapping for English variants
    if language_lower in ['english', 'english (indian)', 'indian english']:
        return "Indian English"
    elif language_lower in ['english (british)', 'british english']:
        return "British English"
    elif language_lower in ['english (american)', 'american english']:
        return "American English"
    elif language_lower in ['english (australian)', 'australian english']:
        return "Australian English"
    elif language_lower in ['english (canadian)', 'canadian english']:
        return "Canadian English"
    
    # Default any unspecified English to Indian English
    elif 'english' in language_lower:
        return "Indian English"
    
    # For non-English languages, return as-is
    else:
        return language

def _build_prosodic_instructions(segment_details):
    """Build detailed prosodic delivery guidance."""
    intonation = segment_details.get("intonation_pattern", "FALLING")
    voice_quality = segment_details.get("voice_quality", "MODAL")
    pace = segment_details.get("pace", "NORMAL")
    
    prosodic_notes = []
    
    # Intonation guidance
    if intonation == "RISING":
        prosodic_notes.append("Use rising intonation (↗) - questioning, uncertain, or list-like delivery")
    elif intonation == "FALLING":
        prosodic_notes.append("Use falling intonation (↘) - declarative, completion, authority")
    elif intonation == "RISE_FALL":
        prosodic_notes.append("Use rise-fall pattern (↗↘) - emphasis, contrast, significance")
    elif intonation == "FLAT":
        prosodic_notes.append("Use flat intonation (→) - monotone, boredom, or controlled emotion")
    
    # Voice quality guidance
    if voice_quality == "BREATHY":
        prosodic_notes.append("Breathy voice quality - intimate, tired, or sensual delivery")
    elif voice_quality == "CREAKY":
        prosodic_notes.append("Creaky voice quality - authority, low pitch, vocal fry characteristics")
    elif voice_quality == "TENSE":
        prosodic_notes.append("Tense voice quality - stress, anger, physical effort")
    else:
        prosodic_notes.append("Modal voice quality - natural, relaxed vocal delivery")
    
    # Pace guidance
    pace_guidance = {
        "VERY_SLOW": "Very deliberate, drawn-out delivery with dramatic emphasis",
        "SLOW": "Measured, thoughtful speech with careful articulation", 
        "NORMAL": "Standard conversational rhythm and timing",
        "FAST": "Quick, energetic delivery with increased tempo",
        "VERY_FAST": "Rapid, rushed delivery suggesting excitement or urgency",
        "IRREGULAR": "Varied pace within the segment for natural speech patterns"
    }
    prosodic_notes.append(pace_guidance.get(pace, "Natural conversational pace"))
    
    return " • ".join(prosodic_notes)

def _build_contextual_delivery(segment_details):
    """Build contextual performance guidance."""
    emotion = segment_details.get("emotion", "NEUTRAL")
    emotion_intensity = segment_details.get("emotion_intensity", "MODERATE")
    delivery_style = segment_details.get("delivery_style", "NORMAL")
    
    context_notes = []
    
    # Emotional delivery
    if emotion != "NEUTRAL":
        intensity_modifier = {
            "MILD": "subtle",
            "MODERATE": "clear",
            "INTENSE": "strong"
        }.get(emotion_intensity, "moderate")
        context_notes.append(f"{intensity_modifier} {emotion.lower()} emotional coloring")
    
    # Delivery style specifics
    style_guidance = {
        "SHOUTING": "Loud, projected delivery with increased volume",
        "WHISPERING": "Quiet, intimate delivery with reduced volume",
        "CRYING": "Voice breaking with emotional distress",
        "PLEADING": "Urgent, desperate tone with begging quality",
        "LAUGHING": "Joyful delivery with laughter elements",
        "STORYTELLING": "Engaging, narrative rhythm",
        "EXPLAINING": "Clear, methodical delivery",
        "ARGUING": "Confrontational with sharp edges",
        "COMMANDING": "Authoritative, direct delivery"
    }
    if delivery_style in style_guidance:
        context_notes.append(style_guidance[delivery_style])
    
    return " • ".join(context_notes)

def _build_naturalness_instructions(segment_details):
    """Build naturalness and authentic speech guidance."""
    natural_pauses = segment_details.get("natural_pauses", [])
    prosodic_notes = segment_details.get("prosodic_notes", "")
    
    naturalness_guidance = []
    
    # Pause integration
    if natural_pauses:
        pause_types = ", ".join(natural_pauses)
        naturalness_guidance.append(f"Include natural {pause_types.lower().replace('_', ' ')} for authentic speech flow")
    
    # Prosodic notes from analysis
    if prosodic_notes:
        naturalness_guidance.append(f"Performance notes: {prosodic_notes}")
    
    # General naturalness
    naturalness_guidance.extend([
        "Maintain natural speech rhythm with organic timing",
        "Use authentic vocal expressions and micro-variations",
        "Avoid robotic or overly perfect pronunciation", 
        "Include natural vocal characteristics like slight hesitations or emphasis variations"
    ])
    
    return " • ".join(naturalness_guidance)

def _build_accent_enforcement(config):
    """Build accent enforcement instructions."""
    language = config['OUTPUT_LANGUAGE']
    accent_specification = _get_accent_specification(language)
    
    # Strong accent enforcement for English variants
    if 'english' in language.lower():
        return f"MANDATORY: Use ONLY {accent_specification} pronunciation, intonation, and speech patterns."
    else:
        return f"Maintain consistent {accent_specification} pronunciation and speech characteristics throughout."

def _build_script_compliance_instructions(segment_details):
    """Build instructions to ensure TTS follows dubbing script directions."""
    compliance_instructions = []
    
    emotion = segment_details.get("emotion", "NEUTRAL")
    if emotion != "NEUTRAL":
        compliance_instructions.append(f"EXPRESS {emotion.upper()} emotion")
    
    delivery_style = segment_details.get("delivery_style", "NORMAL")
    if delivery_style != "NORMAL":
        compliance_instructions.append(f"Use {delivery_style.upper()} delivery style")
    
    if compliance_instructions:
        return "FOLLOW SCRIPT ANALYSIS: " + " • ".join(compliance_instructions)
    else:
        return "Follow all emotional and delivery specifications from the dubbing script analysis."

def merge_audio_with_video(video_path, audio_path, output_path, logger):
    logger.log(f"🎬 Merging final audio with video...")
    try:
        with VideoFileClip(video_path) as video_clip, AudioFileClip(audio_path) as audio_clip:
            video_clip.audio = audio_clip
            video_clip.write_videofile(output_path, codec="libx264", audio_codec="aac", logger=None)
        logger.log(f"🎉 Final video saved successfully to '{os.path.basename(output_path)}'")
        return output_path
    except Exception as e:
        logger.log(f"❌ An error occurred during video merging: {e}")
        return None

def assign_specific_voices(transcript_data):
    speaker_info = {item['speaker_label']: item['character_type'] for item in transcript_data if item['speaker_label'] not in {}}
    voice_indices = {'MALE': 0, 'FEMALE': 0, 'CHILD': 0}
    speaker_voice_array = []
    for speaker in sorted(speaker_info.keys()):
        char_type = speaker_info[speaker]
        voice_list = globals().get(f"{char_type}_VOICE_LIST", [])
        if voice_list:
            index = voice_indices[char_type] % len(voice_list)
            selected_voice = voice_list[index]
            voice_indices[char_type] += 1
        else:
            selected_voice = FALLBACK_VOICE
        speaker_voice_array.append({"speaker_label": speaker, "character_type": char_type, "selected_voice": selected_voice})
    return speaker_voice_array

def process_video_dubbing(video_path, config, logger, log_container, synthesis_log_area):
    """Main function to orchestrate the entire dubbing process."""
    base_name = os.path.splitext(os.path.basename(video_path))[0]
    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = os.path.join(temp_dir, f"output_{base_name}")
        os.makedirs(output_dir, exist_ok=True)
        
        original_audio_path = os.path.join(output_dir, f"{base_name}_original_audio.wav")
        extract_audio(video_path, original_audio_path, logger)
        # --- MODIFIED: Run Demucs and Gemini analysis in parallel ---
        background_track_path = None
        dubbing_script = None

                # --- NEW: Polling loop for live logging ---
        with concurrent.futures.ThreadPoolExecutor() as executor:
            logger.log("🚀 Starting parallel processing for audio separation and video analysis...")
            render_logs(log_container, st.session_state.log_messages)
            demucs_output_dir = os.path.join(output_dir, "separated")
            future_audio = executor.submit(separate_background_music, original_audio_path, demucs_output_dir, logger)
            future_script = executor.submit(get_dubbing_script_from_video, video_path, config, logger)
            
            futures = [future_audio, future_script]
            while any(not f.done() for f in futures):
                while not logger.queue.empty():
                    message = logger.queue.get_nowait()
                    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")
                    st.session_state.log_messages.append(f"{timestamp} UTC - {message}")
                render_logs(log_container, st.session_state.log_messages)
                time.sleep(0.5)
            
            dubbing_script = future_script.result()
            background_track_path = future_audio.result()

        # Final log render to catch any remaining messages
        while not logger.queue.empty():
            message = logger.queue.get_nowait()
            timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")
            st.session_state.log_messages.append(f"{timestamp} UTC - {message}")
        render_logs(log_container, st.session_state.log_messages)
        # --- END NEW ---

        logger.log("✅ Parallel processing finished.")
        
        if not dubbing_script:
            logger.log("❌ Aborting due to failure in script generation.")
            return None
 
        # >>>>> CHANGE: ADDED st.expander HERE IN THE MAIN THREAD <<<<<
        with st.expander("Show Generated Dubbing Script (JSON)", expanded=True):
            st.json(dubbing_script)

        logger.log(f"🔊 Initializing {config['TTS_MODEL']} for Text-to-Speech...")
        
        with VideoFileClip(video_path) as clip:
            video_duration_ms = int(clip.duration * 1000)

        if background_track_path and os.path.exists(background_track_path):
            background_music = AudioSegment.from_wav(background_track_path)
            if len(background_music) < video_duration_ms:
                 background_music += AudioSegment.silent(duration=video_duration_ms - len(background_music))
        else:
            logger.log("⚠️ Could not separate background music. Using a silent background.")
            background_music = AudioSegment.silent(duration=video_duration_ms)

        final_vocal_track = AudioSegment.silent(duration=len(background_music))
        speaker_assignments = assign_specific_voices(dubbing_script)
        logger.log("Assigned voices to speakers.")

        output_lang_key = f"{config['OUTPUT_LANGUAGE']}_translation"
        progress_bar = st.progress(0, text="Synthesizing audio segments...")

        for i, segment in enumerate(dubbing_script):
            output_text = segment.get(output_lang_key, "...")
            start_time_ms = int(segment['start_time'] * 1000)
            end_time_ms = int(segment['end_time'] * 1000)
            
            selected_voice = next((item['selected_voice'] for item in speaker_assignments if item['speaker_label'] == segment['speaker_label']), FALLBACK_VOICE)
            
            segment_details = {
                'character_type': segment['character_type'], 'emotion': segment.get('emotion', 'NEUTRAL'),
                'delivery_style': segment.get('delivery_style', 'NORMAL'), 'speaker_label': segment.get('speaker_label', 'DEFAULT'),
                'pace': segment.get('pace', 'NORMAL'), 'clip_duration': end_time_ms - start_time_ms,
                'selected_voice': selected_voice, 'output_path': os.path.join(output_dir, f"segment_{i}.wav")
            }
            
            time.sleep(2)
            synthesized_path, tts_prompt = synthesize_speech_with_gemini(output_text, segment_details, config, logger)
            
            with synthesis_log_area.expander(f"Segment {i+1}: Speaker - {segment.get('speaker_label', 'N/A')} ({segment['start_time']:.2f}s - {segment['end_time']:.2f}s)"):
                st.markdown(f"**🗣️ Translated Text:** `{output_text}`")
                st.markdown(f"**🤖 TTS Prompt:** `{tts_prompt}`")
                if synthesized_path and os.path.exists(synthesized_path):
                    st.markdown("**🔊 Generated Audio:**")
                    with open(synthesized_path, "rb") as audio_file:
                        st.audio(audio_file.read(), format="audio/wav")
                else:
                    st.warning("Audio synthesis failed for this segment.")

            if synthesized_path and os.path.exists(synthesized_path):
                with open(synthesized_path, "rb") as f:
                    dub_segment = AudioSegment.from_wav(f)
                                # --- NEW: AUDIO SPEED ADJUSTMENT LOGIC ---
                    try:
                      original_duration_ms = len(dub_segment)
                      target_duration_ms = segment_details['clip_duration']
                    
                      if target_duration_ms > 0 and original_duration_ms > 0:
                        speed_ratio = original_duration_ms / target_duration_ms
                        if speed_ratio > 1.5:
                            speed_ratio = 1.27
                        
                        # Only adjust if the speed difference is significant (e.g., > 5%)
                        if abs(1 - speed_ratio) > 0.05:
                            logger.log(f"   ⏱️ Adjusting speed for segment {i}. Ratio: {speed_ratio:.2f} (Original: {original_duration_ms}ms, Target: {target_duration_ms}ms)")
                            
                            stretched_audio_path = os.path.join(output_dir, f"segment_{i}_stretched.wav")
                            
                            # Read audio data, stretch it with pyrubberband, and write to a new file
                            y, sr = sf.read(synthesized_path)
                            y_stretched = rb.time_stretch(y, sr, speed_ratio)
                            sf.write(stretched_audio_path, y_stretched, sr)

                            # Load the new, time-adjusted audio segment
                            dub_segment = AudioSegment.from_wav(stretched_audio_path)
                            #os.remove(stretched_audio_path) # Clean up intermediate file
                    except Exception as e:
                      logger.log(f"   ⚠️ Could not time-stretch segment {i}: {e}")
                
                final_vocal_track = final_vocal_track.overlay(dub_segment, position=start_time_ms)
                os.remove(synthesized_path)
            else:
                logger.log(f"⚠️ Segment {i} could not be synthesized and will be silent.")
            
            progress_bar.progress((i + 1) / len(dubbing_script), text=f"Synthesizing audio segment {i+1}/{len(dubbing_script)}")
        
        logger.log("🎤 Speech synthesis complete. Combining audio tracks...")
        final_audio_track = background_music.overlay(final_vocal_track)
        final_audio_path = os.path.join(output_dir, f"{base_name}_dubbed_audio.wav")
        final_audio_track.export(final_audio_path, format="wav")
        logger.log("✅ Final audio track created.")

        final_video_path = os.path.join(output_dir, f"dubbed_{base_name}.mp4")
        merged_video_path = merge_audio_with_video(video_path, final_audio_path, final_video_path, logger)
        
        if merged_video_path and os.path.exists(merged_video_path):
            gcs_client = get_gcs_client()
            destination_blob_name = f"dubbed_videos/{os.path.basename(merged_video_path)}"
            if upload_to_gcs(gcs_client, config['BUCKET_NAME'], merged_video_path, destination_blob_name, logger):
                return destination_blob_name
        
        return None