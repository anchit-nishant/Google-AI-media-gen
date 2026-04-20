import base64
import json
import uuid
import re
from typing import List, Dict, Any, Optional

import apis.gemini_helper as gemini_helper
from apis.veo2_api import Veo2API


def generate_slide_outline(client: Veo2API, main_prompt: str, num_slides: int) -> Optional[List[Dict[str, str]]]:
    """
    Uses Gemini to generate a structured outline for a presentation.

    Args:
        client: An instance of the Veo2API client for authentication.
        main_prompt: The user's high-level prompt for the presentation.
        num_slides: The number of slides to create.

    Returns:
        A list of dictionaries, where each dictionary represents a slide
        with 'title' and 'content' keys, or None on failure.
    """
    system_prompt = f"""
    You are a world-class presentation designer. Your task is to create a structured outline for a {num_slides}-slide presentation based on the user's request that adheres to the Seven Fundamental Principles of Designt.
    For each slide, you will generate a title and the slide's content as a self-contained HTML `<div>` block styled with Tailwind CSS.

    **The Design Principles:**

    1. Balance & Composition:

    Avoid static symmetry. Use Asymmetrical Balance by offsetting large headlines with Nano Banana 3D assets.

    Implement a 12-column grid. Ensure visual weight is distributed so no single quadrant feels "empty" or "overcrowded."

    2. Contrast & Emphasis:

    Establish a clear Focal Point. Use high-contrast color pairs (e.g., #0A0A0A background with #CCFF00 accents).

    Apply Scale Contrast: Key metrics or "Power Words" must be at least 3x the size of body copy.

    Use text-transparent bg-clip-text bg-gradient-to-r to emphasize primary keywords.

    3. Movement & Rhythm:

    Guide the eye using a Z-pattern layout.

    Create Visual Rhythm by repeating card structures (Bento Boxes) with consistent p-8, rounded-3xl, and border-white/10.

    Use CSS animate-in and slide-in-from-bottom classes to create sequential entrance rhythms for content.

    4. Unity, Harmony & Variety:

    Unity: Maintain a strict design system. Use a single font family (Sans-Serif), a unified border-radius (3xl), and a consistent glassmorphism effect (backdrop-blur-md bg-white/5).

    Variety: Do not repeat layouts. Alternate between "Cinematic Hero" (Single focus), "The Bento" (Multi-data), and "The Split" (Comparison) layouts to maintain audience engagement.

    **Design Constraints (Strict):**
    1.  **NO BULLET POINTS**: Do not use `<ul>` or `<li>` tags. Instead, represent information using modern layouts like "Feature Grids," "Bento Grids," or "Step-Flow" diagrams.
    2.  **VISUAL HIERARCHY**: Use large, bold typography for main messages. Each slide should have one clear takeaway.
    3.  **MODERN AESTHETICS**: Employ glassmorphism (e.g., `backdrop-blur-md bg-white/10`), rounded corners (`rounded-xl`), and subtle shadows (`shadow-lg`) to create depth.
    4.  **BENTO GRIDS**: When presenting multiple points, organize them in a grid of cards (a "Bento Box" layout). But DO NOT add empty Bento Boxes wihtout any text content.
    5.  Whenever a visual is needed, insert a placeholder tag for Nano Banana : [IMAGE_PROMPT: "Detailed description of a 3D abstract object, claymorphism style, neon accents, 8k resolution"]

    Your output MUST be a valid JSON array of objects. Do not include any text or explanations outside of this array. Do not write the title twice on the slides. MAINTAIN A CONSISTENT DESIGN THEME AND PATTERN ACROSS ALL SLIDES
    Each object in the array represents a slide and must have the following structure:
    {{
      "title": "string (The title of the slide)",
      "content": "string (A single HTML `<div>` block using Tailwind CSS classes for the slide body. It must include an [IMAGE_PROMPT: '...'] placeholder.)"
    }}

    **Example: Make a slide about AI growth.**
    {{
      <div class="p-8 bg-[#0a0a0a] text-white rounded-3xl border border-white/10 font-sans h-[500px] flex flex-col justify-between">
            <!-- Header -->
            <h1 class="text-7xl font-black tracking-tighter bg-gradient-to-r from-lime-400 to-emerald-500 bg-clip-text text-transparent">
                EXPONENTIAL<br/>INTELLIGENCE.
            </h1>

            <!-- Bento Grid -->
            <div class="grid grid-cols-3 gap-4 mt-8">
                <div class="p-6 bg-white/5 rounded-2xl border border-white/10 backdrop-blur-md">
                <div class="text-lime-400 text-2xl mb-2">01</div>
                <p class="text-sm uppercase tracking-widest opacity-50">Compute Power</p>
                <p class="text-2xl font-bold mt-2">10x YoY</p>
                </div>
                
                <div class="p-6 bg-white/5 rounded-2xl border border-white/10 backdrop-blur-md">
                <div class="text-lime-400 text-2xl mb-2">02</div>
                <p class="text-sm uppercase tracking-widest opacity-50">Market Cap</p>
                <p class="text-2xl font-bold mt-2">$4.2 Trillion</p>
                </div>

                <!-- Nano Banana Image Placeholder -->
                <div class="relative overflow-hidden rounded-2xl bg-gradient-to-br from-lime-500/20 to-transparent border border-white/10">
                [IMAGE_PROMPT: "A futuristic neural network core made of glowing green fiber optics, dark background, cinematic lighting, macro photography"]
                </div>
            </div>
      </div>
    }}
    """
    try:
        # We can use the gemini_chat_response helper for this text-generation task
        response = gemini_helper.generate_gemini_chat_response(
            model_name="gemini-3.1-pro-preview", # A good model for structured data generation
            prompt=main_prompt,
            system_instructions=system_prompt,
            temperature=0.6,
            enable_grounding=True,
            max_output_tokens=20000,
        )
        
        # 1. Safely extract text from the response object.
        # The helper function returns a dictionary, so we access the 'text' key.
        raw_text = response.get('text')
        if not raw_text:
            print("Error: Gemini response did not contain any text.")
            return None

        # 2. Clean the text: Remove Markdown code fences and strip whitespace.
        # This regex handles ```json ... ``` and ``` ... ```.
        clean_json = re.sub(r'```(?:json)?\n?|```', '', raw_text).strip()
        
        # 3. Load the JSON.
        outline = json.loads(clean_json)
        
        # 4. Final verification.
        if isinstance(outline, list) and all(isinstance(s, dict) and 'title' in s and 'content' in s for s in outline):
            return outline
        else:
            print("Error: Parsed JSON is not a valid list of slide objects.")
            return None
            
    except (json.JSONDecodeError, KeyError, Exception) as e:
        # Enhanced error logging for better debugging
        import traceback
        print(f"❌ An error occurred in generate_slide_outline: {e}")
        print("--- Traceback ---")
        traceback.print_exc()
        print("-----------------")
        return None

def generate_image_for_slide(client: Veo2API, slide_content: Dict, style_prompt: str, reference_images_b64: List[str], storage_uri: str) -> Optional[str]:
    """
    Generates an image for a single slide using Gemini (Nano Banana).

    Args:
        client: An instance of the Veo2API client.
        slide_content: A dictionary with 'title' and 'content' for the slide.
        style_prompt: A prompt describing the desired visual style.
        reference_images_b64: A list of base64-encoded reference images.
        storage_uri: The GCS URI to store the generated image.

    Returns:
        The GCS URI of the generated image, or None on failure.
    """
    # Extract the image prompt from the content
    content_text = slide_content['content']
    image_prompt_match = re.search(r'\[IMAGE_PROMPT: "([^"]+)"\]', content_text)
    
    if image_prompt_match:
        image_gen_prompt = image_prompt_match.group(1)
        # Add the user's overall style prompt
        full_image_prompt = f"{image_gen_prompt}, in the style of: {style_prompt}"
    else:
        # Fallback if the placeholder is missing
        full_image_prompt = f"""
        Create a visually appealing, professional image for a presentation slide.
        The slide title is: '{slide_content['title']}'
        The overall style should be: {style_prompt}
        The image should be a high-quality, cinematic, and relevant background or illustration. Avoid text in the image.
        """

    # Construct the chat history for the image generation model
    chat_history = [{
        "role": "user",
        "content": {"text": full_image_prompt, "images": reference_images_b64}
    }]

    try:
        response = client.generate_image_gemini_image_preview(
            chat_history=chat_history,
            system_instructions="You are an expert image generation AI. Your task is to create a visually stunning, high-quality, and photorealistic image based on the user's prompt. The image should be suitable for a professional presentation. CRITICAL: Do NOT include any text, letters, or words in the generated image.",
            aspectRatio="16:9",
            model="gemini-3-pro-image-preview", # Use a fast model for this
            storage_uri=storage_uri
        )
        
        image_uris = response.get("content", {}).get("image_uris", [])
        return image_uris[0] if image_uris else None

    except Exception as e:
        print(f"Error generating image for slide '{slide_content['title']}': {e}")
        return None

def assemble_revealjs_deck(slides_data: List[Dict[str, Any]], theme: str = "black", background_opacity: float = 0.3, font_family: str = "'Inter', sans-serif", font_url: str = "https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap") -> str:
    """
    Assembles the generated slide data into a self-contained reveal.js HTML file.

    Args:
        slides_data: A list of slide data, each with 'title', 'content', and 'image_url'.
        theme: The name of the reveal.js theme to use (e.g., 'black', 'white', 'league').
        background_opacity: The opacity of the background image (0.0 to 1.0).
        font_family: The CSS font-family string.
        font_url: The URL to the Google Fonts stylesheet.

    Returns:
        A string containing the full HTML content of the presentation.
    """
    slides_html = ""
    for slide in slides_data:
        # The content is now HTML, so we can use it directly.
        # Remove the [IMAGE_PROMPT: "..."] placeholder from the final HTML.
        slide_body_html = re.sub(r'\[IMAGE_PROMPT: "([^"]+)"\]', '', slide['content'])
        
        slides_html += f"""
        <section data-background-image="{slide['image_url']}" data-background-opacity="{background_opacity}">
            <div class="w-full h-full flex flex-col justify-center items-center text-white">
                <h2 class="text-6xl font-bold mb-8">{slide['title']}</h2>
                <div class="w-4/5">
                    {slide_body_html}
                </div>
            </div>
        </section>
        """

    # Using CDN for reveal.js and Tailwind CSS for simplicity
    html_template = f"""
    <!doctype html>
    <html>
        <head>
            <meta charset="utf-8">
            <title>AI Generated Presentation</title>
            <script src="https://cdn.tailwindcss.com"></script>
            <link rel="preconnect" href="https://fonts.googleapis.com">
            <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
            <link href="{font_url}" rel="stylesheet">
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/reveal.js/4.3.1/reset.min.css">
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/reveal.js/4.3.1/reveal.min.css">
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/reveal.js/4.3.1/theme/{theme}.css" id="theme">
            <style>
                /* Custom styles for better presentation */
                .reveal .slides, .reveal h1, .reveal h2, .reveal h3, .reveal h4, .reveal p, .reveal li {{
                    text-align: left; /* Align slide content to the left */
                    font-family: {font_family} !important;
                }}
                .reveal h2 {{
                    text-align: center !important; /* Keep titles centered */
                }}
            </style>
        </head>
        <body>
            <div class="reveal">
                <div class="slides">
                    {slides_html}
                </div>
            </div>
            <script src="https://cdnjs.cloudflare.com/ajax/libs/reveal.js/4.3.1/reveal.js"></script>
            <script>
                Reveal.initialize({{ hash: true, width: 1920, height: 1080 }});
            </script>
        </body>
    </html>
    """
    return html_template
