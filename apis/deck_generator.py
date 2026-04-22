import base64
import json
import uuid
import re
from typing import List, Dict, Any, Optional
import requests

import apis.gemini_helper as gemini_helper
from apis.veo2_api import Veo2API


def generate_slide_outline(client: Veo2API, main_prompt: str, num_slides: int, custom_system_instructions: str = "") -> Optional[tuple[list, dict]]:
    """
    Uses Gemini to generate a structured outline for a presentation.

    Args:
        client: An instance of the Veo2API client for authentication.
        main_prompt: The user's high-level prompt for the presentation.
        num_slides: The number of slides to create.
        custom_system_instructions: Optional user-provided instructions to append to the system prompt.

    Returns:
        A tuple containing:
        - A list of slide dictionaries.
        - A dictionary with the API usage metadata.
    """

    layouts = ["Cinematic Split", "Bento Masonry", "Data Hero", "Immersive Background"]
    layout_instructions = "\n".join([f"Slide {i+1} must use the '{layouts[i % len(layouts)]}' layout." for i in range(num_slides)])

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

    {layout_instructions}

    **Design Constraints (Strict):**
    1.  **NO BULLET POINTS**: Do not use `<ul>` or `<li>` tags. Instead, represent information using modern layouts like "Feature Grids," "Bento Grids," or "Step-Flow" diagrams.
    2.  **VISUAL HIERARCHY**: Use large, bold typography for main messages. Each slide should have one clear takeaway.
    3.  **MODERN AESTHETICS**: Employ glassmorphism (e.g., `backdrop-blur-md bg-white/10`), rounded corners (`rounded-xl`), and subtle shadows (`shadow-lg`) to create depth.
    4.  **BENTO GRIDS**: When presenting multiple points, organize them in a grid of cards (a "Bento Box" layout). But DO NOT add empty Bento Boxes wihtout any text content.
    5.  Whenever a visual is needed, insert a placeholder tag for Nano Banana : [IMAGE_PROMPT: "Detailed description of a 3D abstract object, claymorphism style, neon accents, 8k resolution"]
    6. Explicit Content Rule: "Every grid cell (Bento box) MUST contain at least one of the following: a Heading (<h3>), a Paragraph (<p>), or an Icon/Metric. NEVER generate an empty div or a box with only a background gradient."
    7. The 'Metric First' Rule: "For Bento grids, every card must lead with a 'Hero Metric' (e.g., a large number or percentage) to ensure high-impact data visualization."
    8. For images, ensure they occupy at least 30% of the slide area. Use `mix-blend-mode: plus-lighter` or `object-cover` for maximum clarity
    9. CRITICAL: If any companies or products are mentioned, use Google Search to find their official logos and incorporate them into the image. The image should be a high-quality, cinematic, and relevant background or illustration. Avoid any other text in the image
    10. LAYOUT MODES (Must alternate every slide):

        Mode A (The Cinematic Impact): Use flex-col justify-end. Headline is at the bottom. The [IMAGE_PROMPT] is the entire background of the div (not just a side box).

        Mode B (The Data Masonry): Use an asymmetrical grid (e.g., grid-cols-5). One card takes col-span-3, another takes col-span-2.

        Mode C (The Hero Comparison): Use a split-screen but with a vertical divider and high-contrast colors (e.g., Left: #0A0A0A, Right: #CCFF00).

        Mode D (The Interactive Flow): Use a horizontal sequence of 4 small "step" cards with directional arrows.
    11. DYNAMIC THEMING:

        If the topic is Finance/Security: Use "Electric Blue" (#0070FF) and "Silver."

        If the topic is AI/Innovation: Use "Cyber Lime" (#CCFF00) and "Emerald."

        If the topic is Creativity/Media: Use "Vivid Magenta" (#FF00CC) and "Deep Purple."

        Constraint: Never use the same accent color for two different presentations unless requested.

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
    # Append custom instructions if they are provided by the user
    if custom_system_instructions:
        system_prompt += f"\n\n**Additional User Instructions:**\n{custom_system_instructions}"

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
        usage_metadata = response.get('usage_metadata', {})

        # --- THE POST-PROCESSING CODE ---

        def clean_html_content(html):
            # Remove empty divs that don't have text or image placeholders
            cleaned = re.sub(r'<div[^>]*>\s*</div>', '', html)
            # Ensure [IMAGE_PROMPT] is wrapped in a styled container if Gemini forgot
            if "[IMAGE_PROMPT" in cleaned and "<img" not in cleaned:
                cleaned = cleaned.replace('[IMAGE_PROMPT', '<div class="overflow-hidden rounded-2xl border border-white/10 bg-white/5">[IMAGE_PROMPT')
                cleaned = cleaned.replace('"]', '"]</div>')
            return cleaned
        
        # 4. Final verification.
        if isinstance(outline, list) and all(isinstance(s, dict) and 'title' in s and 'content' in s for s in outline):
            return outline, usage_metadata
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

def get_base64_from_url(url: str) -> Optional[str]:
    """Fetches an image from a URL and returns it as a base64 string."""
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return base64.b64encode(response.content).decode('utf-8')
    except requests.exceptions.RequestException as e:
        print(f"Warning: Could not fetch image from {url}. Error: {e}")
        return None

def find_and_fetch_logos(text: str) -> List[str]:
    """
    Extracts potential company names from text, fetches their logos, and returns them as base64 strings.

    Args:
        text: The text to search for company names (e.g., the user's main prompt).

    Returns:
        A list of base64-encoded logo images.
    """
    print("Attempting to find and fetch logos from prompt...")
    # Use Gemini to extract company names and their domains from the text.
    # This is much more reliable than simple regex.
    try:
        extraction_prompt = f"""
        Analyze the following text and extract all company names, product names, or names of people.
        For each entity found, use your search capabilities to find a direct URL to a high-quality, publicly accessible image (e.g., an official logo for a company, a professional headshot for a person). The URL should point directly to an image file (e.g., .png, .jpg, .svg).
        Your output MUST be a valid JSON object where keys are the names of the entities and values are the direct image URLs you found.

        Example:
        Input: "A presentation about Google Cloud, its competitor AWS, and featuring our CEO, Sundar Pichai."
        Output: {{"Google Cloud": "https://upload.wikimedia.org/wikipedia/commons/5/51/Google_Cloud_logo.svg", "AWS": "https://upload.wikimedia.org/wikipedia/commons/9/93/Amazon_Web_Services_Logo.svg", "Sundar Pichai": "https://upload.wikimedia.org/wikipedia/commons/d/d6/Sundar_Pichai.jpg"}}

        Input text to analyze: "{text}"
        """
        response = gemini_helper.generate_gemini_chat_response(
            model_name="gemini-1.5-flash", # Use a fast model for this task
            prompt=extraction_prompt,
            temperature=0.0,
            enable_grounding=True, # Ensure the model can use search
        )
        raw_json = re.sub(r'```(?:json)?\n?|```', '', response.get('text', '{}')).strip()
        entity_image_urls = json.loads(raw_json)
    except Exception as e:
        print(f"Warning: Failed to extract entity image URLs with Gemini. Error: {e}")
        entity_image_urls = {}

    fetched_logos_b64 = []
    urls_tried = set()

    for name, image_url in entity_image_urls.items():
        if not image_url or image_url in urls_tried:
            continue
        
        urls_tried.add(image_url)
        
        print(f"  Trying to fetch image for '{name}' from {image_url}")
        logo_b64 = get_base64_from_url(image_url)
        
        
        if logo_b64:
            print(f"  ✅ Successfully fetched image for {name}")
            fetched_logos_b64.append(logo_b64)
            
    return fetched_logos_b64

def generate_image_for_slide(client: Veo2API, slide_content: Dict, style_prompt: str, reference_images_b64: List[str], storage_uri: str, custom_system_instructions: str = "") -> Optional[tuple[str, dict]]:
    """
    Generates an image for a single slide using Gemini (Nano Banana).

    Args:
        client: An instance of the Veo2API client.
        slide_content: A dictionary with 'title' and 'content' for the slide.
        style_prompt: A prompt describing the desired visual style.
        reference_images_b64: A list of base64-encoded reference images.
        storage_uri: The GCS URI to store the generated image.
        custom_system_instructions: Optional user-provided instructions to append to the system prompt.

    Returns:
        A tuple containing:
        - The GCS URI of the generated image.
        - A dictionary with the API usage metadata.
    """
    # Extract the image prompt from the content
    content_text = slide_content['content']
    image_prompt_match = re.search(r'\[IMAGE_PROMPT: "([^"]+)"\]', content_text)
    
    if image_prompt_match:
        image_gen_prompt = image_prompt_match.group(1)
        # Add the user's overall style prompt and the new logo instruction
        full_image_prompt = f"{image_gen_prompt}, in the style of: {style_prompt}. If any logos are provided as reference images, incorporate them naturally into the composition (e.g., on a glass wall, a 3D tablet, or as a subtle watermark)."
    else:
        # Fallback if the placeholder is missing
        full_image_prompt = f"""
        Create a visually appealing, professional image for a presentation slide.
        The slide title is: '{slide_content['title']}'
        The overall style should be: {style_prompt}. If any logos are provided as reference images, incorporate them naturally into the composition.
        """
        
    #If any companies or products are mentioned, use Google Search to find their official logos and incorporate them into the image. The image should be a high-quality, cinematic, and relevant background or illustration. Avoid any other text in the image.

    # Construct the chat history for the image generation model
    chat_history = [{
        "role": "user",
        "content": {"text": full_image_prompt, "images": reference_images_b64}
    }]

    base_system_instructions = """
    You are an expert image generation AI. Your task is to create a visually stunning, high-quality, and photorealistic image based on the user's prompt. The image should be suitable for a professional presentation. STRICT TECHNICAL SPECIFICATIONS:

    Bento Logic: If using a grid, each col-span must have a specific purpose: Fact, Metric, or Visual.

    No Placeholders: Do not output comments like <!-- Image here -->. If you don't have content for a box, do not create the box.
    """
    # Append custom instructions if they are provided
    if custom_system_instructions:
        base_system_instructions += f"\n\n**Additional User Instructions:**\n{custom_system_instructions}"

    try:
        response = client.generate_image_gemini_image_preview(
            chat_history=chat_history,
            system_instructions=base_system_instructions,
            aspectRatio="16:9",
            model="gemini-3-pro-image-preview", # Use a fast model for this
            storage_uri=storage_uri
        )
        

        ##Image Placement: All [IMAGE_PROMPT] tags must be placed inside a container that has relative overflow-hidden rounded-3xl.

        ## Typography: Headlines must use text-6xl to text-8xl with font-black. Body text must never exceed text-xl to maintain Hierarchy.

        image_uris = response.get("content", {}).get("image_uris", [])
        usage_metadata = response.get('usageMetadata', {})
        return (image_uris[0], usage_metadata) if image_uris else (None, usage_metadata)

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
            <div class="reveal-slide-container w-full h-full flex flex-col justify-center items-center">
                {slide_body_html}
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
