from datetime import timedelta
from urllib.parse import quote_plus
import random
import time
import json
import re

import streamlit as st
import streamlit.components.v1 as components
import yt_dlp

# AI Agent Integration
try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# ==========================================
# Fetch from Streamlit Cloud Secrets safely
# ==========================================
GLOBAL_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

if HAS_GENAI and GLOBAL_API_KEY:
    try:
        client = genai.Client(api_key=GLOBAL_API_KEY)
    except Exception:
        pass
# ==========================================

SEARCH_AUDIO_SUFFIX = "High Quality Audio"
AUTO_ADVANCE_SECONDS_DEFAULT = 30  # seconds before auto-playing next song
MAX_PLAY_SECONDS = 180  # hard cap on how long each song plays

# 20 colors → Mood + UI hex color
COLOR_VIBE_MAP: dict[str, dict[str, str]] = {
    "red": {"mood": "Energetic / Passionate", "hex": "#e53935"},
    "crimson": {"mood": "Intense / Romantic", "hex": "#b80f2a"},
    "navy": {"mood": "Deep / Serene", "hex": "#0b1f3a"},
    "sky blue": {"mood": "Light / Airy", "hex": "#87ceeb"},
    "emerald": {"mood": "Rich / Natural", "hex": "#2ecc71"},
    "lime": {"mood": "Fresh / Vibrant", "hex": "#a3e635"},
    "gold": {"mood": "Warm / Luxurious", "hex": "#d4af37"},
    "amber": {"mood": "Cozy / Nostalgic", "hex": "#ffbf00"},
    "lavender": {"mood": "Dreamy / Atmospheric", "hex": "#b57edc"},
    "deep purple": {"mood": "Mysterious / Sophisticated", "hex": "#4a148c"},
    "hot pink": {"mood": "Bold / Playful", "hex": "#ff1493"},
    "rose": {"mood": "Soft / Romantic", "hex": "#ff66b2"},
    "chocolate": {"mood": "Warm / Comforting", "hex": "#7b3f00"},
    "sand": {"mood": "Calm / Neutral", "hex": "#c2b280"},
    "charcoal": {"mood": "Dark / Industrial", "hex": "#36454f"},
    "silver": {"mood": "Cool / Modern", "hex": "#c0c0c0"},
    "teal": {"mood": "Balanced / Refreshing", "hex": "#008080"},
    "coral": {"mood": "Warm / Playful", "hex": "#ff7f50"},
    "magenta": {"mood": "Vibrant / Artistic", "hex": "#ff00ff"},
    "indigo": {"mood": "Deep / Introspective", "hex": "#4b0082"},
}

def _normalize_color_key(name: str) -> str:
    return name.lower().strip()

def get_mood_for_color(color: str) -> str | None:
    return COLOR_VIBE_MAP.get(_normalize_color_key(color), {}).get("mood")

def get_hex_for_color(color: str) -> str | None:
    return COLOR_VIBE_MAP.get(_normalize_color_key(color), {}).get("hex")

def _mood_to_search_words(mood: str) -> list[str]:
    words: list[str] =[]
    for part in mood.split("/"):
        for word in part.split():
            w = word.strip()
            if w:
                words.append(w)
    return words

def combine_moods(mood1: str, mood2: str) -> str:
    words = _mood_to_search_words(mood1) + _mood_to_search_words(mood2)
    seen: set[str] = set()
    unique: list[str] =[]
    for w in words:
        lw = w.lower()
        if lw not in seen:
            seen.add(lw)
            unique.append(w)
    phrase = " ".join(unique)
    return f"{phrase} Music" if phrase else "Music"

def build_query(selected_colors: list[str]) -> tuple[str, str]:
    if not selected_colors:
        return ("", "")

    if len(selected_colors) == 1:
        mood = get_mood_for_color(selected_colors[0]) or "Music"
        vibe_label = f"{selected_colors[0].title()} — {mood}"
        base = " ".join(_mood_to_search_words(mood)) + " Music"
        query = f"{base} {SEARCH_AUDIO_SUFFIX}"
        return (vibe_label, query)

    mood1 = get_mood_for_color(selected_colors[0]) or ""
    mood2 = get_mood_for_color(selected_colors[1]) or ""
    combined = combine_moods(mood1, mood2)
    vibe_label = f"{selected_colors[0].title()} + {selected_colors[1].title()} — {combined}"
    query = f"{combined} {SEARCH_AUDIO_SUFFIX}"
    return (vibe_label, query)

def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"

def blend_hex(hex_colors: list[str | None]) -> str:
    colors = [c for c in hex_colors if c]
    if not colors:
        return "#0f172a"
    rgbs =[_hex_to_rgb(c) for c in colors]
    r = sum(v[0] for v in rgbs) // len(rgbs)
    g = sum(v[1] for v in rgbs) // len(rgbs)
    b = sum(v[2] for v in rgbs) // len(rgbs)
    return _rgb_to_hex(r, g, b)

def build_youtube_search_url(query: str) -> str:
    encoded = quote_plus(query)
    return f"https://www.youtube.com/results?search_query={encoded}"

def play_youtube_video(url: str, max_seconds: int) -> None:
    if "watch?v=" in url:
        video_id = url.split("watch?v=")[-1].split("&")[0]
        embed_url = f"https://www.youtube.com/embed/{video_id}?autoplay=1&start=0&end={max_seconds}"
        
        iframe_html = f"""
        <iframe width="100%" height="400" 
                src="{embed_url}" 
                title="YouTube video player" 
                frameborder="0" 
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
                allowfullscreen>
        </iframe>
        """
        components.html(iframe_html, height=420)
    else:
        try:
            st.video(url, autoplay=True)
        except TypeError:
            st.video(url)

@st.cache_data(show_spinner=False, ttl=60 * 20)
def fetch_videos(query: str, limit: int = 10) -> list[dict]:
    if not query:
        return[]

    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": "in_playlist",
    }
    search_query = f"ytsearch{limit}:{query}"
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_query, download=False)

        entries = info.get("entries") or []
        videos: list[dict] =[]
        for entry in entries:
            url = entry.get("webpage_url") or entry.get("url")
            title = entry.get("title") or "Unknown title"
            if not url:
                continue
            videos.append({"title": title, "url": url})
        return videos
    except Exception:
        return[]

def set_dynamic_theme(bg_hex: str) -> None:
    st.markdown(
        f"""
<style>
  .stApp {{
    background: radial-gradient(circle at 10% 10%, {bg_hex} 0%, #0b1220 60%, #050814 100%);
  }}
  .color-pill {{
    display: inline-block;
    padding: 0.25rem 0.6rem;
    border-radius: 999px;
    margin-right: 0.35rem;
    margin-bottom: 1rem;
    background: rgba(255,255,255,0.12);
    border: 1px solid rgba(255,255,255,0.18);
  }}
  .sidebar-note {{
    font-size: 0.9rem;
    opacity: 0.9;
  }}
</style>
""",
        unsafe_allow_html=True,
    )

def fetch_vibe_from_ai(prompt: str, api_key: str) -> dict:
    if not HAS_GENAI:
        st.error("Missing `google-genai` library. Please install it using: pip install google-genai")
        return {}
    try:
        client = genai.Client(api_key=api_key)
        sys_instruct = (
            "You are an expert music and color therapy AI agent. Analyze the user's situation or feeling. "
            "Autonomously infer the most suitable Hex Color Code and YouTube search keywords for them. "
            "Output ONLY a valid JSON object with exactly three keys:\n"
            '1. "hex": A valid hex color code matching the mood (e.g., "#4fa1db").\n'
            f'2. "query": A YouTube search query for music matching the vibe. It MUST end with "{SEARCH_AUDIO_SUFFIX}" (e.g., "Relaxing beach waves acoustic guitar {SEARCH_AUDIO_SUFFIX}").\n'
            '3. "vibe_label": A short, 3-6 word title summarizing the mood (e.g., "Ocean Breeze / Relaxed").'
        )
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=sys_instruct,
                temperature=0.7,
                response_mime_type="application/json"
            )
        )
        
        text = response.text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?|```$", "", text).strip()
        return json.loads(text)
    except Exception as e:
        st.error(f"AI Generation failed: {e}")
        return {}

# =====================================================================
# MUST BE DEFINED AT THE GLOBAL LEVEL TO PREVENT AUTO-RERUN BUGS
# =====================================================================
@st.fragment(run_every=timedelta(seconds=5))
def auto_play_next():
    if "playlist_video_count" not in st.session_state or "now_playing_idx" not in st.session_state:
        return
        
    idx = st.session_state["now_playing_idx"]
    start = st.session_state.get("song_start_time", time.time())
    n = st.session_state["playlist_video_count"]
    auto_adv = st.session_state.get("auto_advance_sec", AUTO_ADVANCE_SECONDS_DEFAULT)
    
    if n > 0 and (time.time() - start) >= auto_adv:
        next_idx = (idx + 1) % n
        st.session_state["now_playing_idx"] = next_idx
        st.session_state["now_playing_radio"] = next_idx  # keep radio in sync
        st.session_state["song_start_time"] = time.time()
        # Clean rerun syntax to force standard Streamlit update
        st.rerun()


def main() -> None:
    st.set_page_config(page_title="Color Vibe Player", page_icon="🎧", layout="wide")
    st.title("Color Vibe Player")
    st.caption("Pick colors manually OR let our AI Agent infer the perfect vibe from natural language.")

    # Initialize shared session states
    if "selected_colors" not in st.session_state:
        st.session_state["selected_colors"] =[]
    if "now_playing_idx" not in st.session_state:
        st.session_state["now_playing_idx"] = 0

    # 1. Choose Application Mode
    mode = st.radio("Choose Mode",["🎨 Manual Colors", "🤖 AI Agent Vibe"], horizontal=True)

    query = ""
    bg_hex = "#0f172a"
    vibe_label = ""
    
    st.divider()

    # 2. Input Logic (Manual vs. AI)
    if mode == "🎨 Manual Colors":
        options = [name.title() for name in COLOR_VIBE_MAP.keys()]
        col_select, col_button = st.columns([3, 1])
        selected = col_select.multiselect(
            "Choose up to 2 colors",
            options=options,
            max_selections=2,
            default=st.session_state["selected_colors"],
        )

        if col_button.button("Surprise Me"):
            keys = list(COLOR_VIBE_MAP.keys())
            if len(keys) >= 2:
                c1, c2 = random.sample(keys, 2)
                st.session_state["selected_colors"] =[c1.title(), c2.title()]
                st.rerun()

        st.session_state["selected_colors"] = selected
        selected_keys =[_normalize_color_key(s) for s in selected]
        
        if selected_keys:
            bg_hex = blend_hex([get_hex_for_color(s) for s in selected_keys])
            vibe_label, query = build_query(selected_keys)
            
            # Show manual color pills
            st.markdown(
                " ".join([f"<span class='color-pill'>{s}</span>" for s in selected]),
                unsafe_allow_html=True,
            )
        else:
            st.info("Select 1 or 2 colors to generate a playlist.")

    else:
        # AI AGENT MODE
        st.markdown("**Tell the AI Agent how you are feeling, and it will pick the perfect color and music.**")
        
        col_api, col_prompt = st.columns([1, 2])
        
        # Pre-fill with the Streamlit Cloud advanced setting API key if available
        api_key_input = col_api.text_input(
            "Gemini API Key", 
            value=GLOBAL_API_KEY, 
            type="password", 
            help="Get your API key from Google AI Studio"
        )
        
        user_prompt = col_prompt.text_area(
            "Your Situation / Vibe:", 
            placeholder="e.g., I'm so stressed at work today, I want to go to the beach.",
            height=68
        )

        if st.button("Generate AI Vibe", type="primary"):
            if not api_key_input:
                st.warning("Please enter your Gemini API Key or set it in Streamlit Cloud Advanced Settings.")
            elif not user_prompt:
                st.warning("Please describe how you are feeling.")
            else:
                with st.spinner("Agent is analyzing your vibe and inferring parameters..."):
                    ai_data = fetch_vibe_from_ai(user_prompt, api_key_input)
                    if ai_data:
                        st.session_state["ai_data"] = ai_data

        if "ai_data" in st.session_state:
            ai_data = st.session_state["ai_data"]
            bg_hex = ai_data.get("hex", "#0f172a")
            query = ai_data.get("query", f"Music {SEARCH_AUDIO_SUFFIX}")
            vibe_label = "🤖 " + ai_data.get("vibe_label", "AI Generated Vibe")
            
            st.markdown(f"<span class='color-pill'>AI Inferred: {bg_hex}</span>", unsafe_allow_html=True)
        else:
            st.info("Awaiting your natural language input above...")


    # 3. Apply the generated Vibe
    set_dynamic_theme(bg_hex)

    if not query:
        st.sidebar.markdown("<div class='sidebar-note'>Playlist will appear here.</div>", unsafe_allow_html=True)
        return 

    st.subheader("Vibe")
    st.write(vibe_label)
    st.code(query, language="text")

    with st.spinner("Fetching top 10 songs from YouTube..."):
        videos = fetch_videos(query, limit=10)

    if not videos:
        st.error("No videos found. Try different colors or AI prompts.")
        return

    # --- 4. Playlist & Player Display  ---
    st.sidebar.subheader("Playlist (Top 10)")
    titles = [f"{i+1}. {v.get('title', 'Unknown')}" for i, v in enumerate(videos)]
    

    now_playing_idx = st.sidebar.radio(
        "Now playing",
        options=list(range(len(videos))),
        format_func=lambda i: titles[i],
        key="now_playing_radio",
        index=st.session_state.get("now_playing_idx", 0) if st.session_state.get("now_playing_idx", 0) < len(videos) else 0
    )


    if now_playing_idx != st.session_state.get("now_playing_idx"):
        st.session_state["now_playing_idx"] = now_playing_idx
        st.session_state["song_start_time"] = time.time()

    st.subheader("Now playing")
    st.write(titles[st.session_state["now_playing_idx"]])
    

    current_video_url = videos[st.session_state["now_playing_idx"]].get("url")
    if current_video_url:
        play_youtube_video(current_video_url, MAX_PLAY_SECONDS)

    with st.expander("See full playlist"):
        for i, v in enumerate(videos, start=1):
            st.markdown(f"**{i}.** {v.get('title', 'Unknown')}")