import os
import glob
import json
import random
import textwrap
import subprocess
import requests
from google import genai
from google.genai import errors as genai_errors
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

# ---------------------------------------------------------
# LOAD ENVIRONMENT VARIABLES
# ---------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

# ---------------------------------------------------------
# MOVIEPY 2.0 IMPORTS
# ---------------------------------------------------------
from moviepy import (
    VideoFileClip, AudioFileClip, TextClip, 
    CompositeVideoClip, concatenate_videoclips, CompositeAudioClip
)

# ==========================================
# 1. CONFIGURATION & SETUP
# ==========================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
CLIENT_SECRET_FILE = "client_secret.json"
VOICE_NAME = "en-US-AnaNeural" 

ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# ==========================================
# 2. WORKSPACE CLEANUP
# ==========================================
def cleanup_temp_files():
    """Removes previous video/audio assets before generating a new short."""
    patterns = ["vid_*.mp4", "voice.mp3", "voice.vtt", "final_short.mp4"]
    for pattern in patterns:
        for file_path in glob.glob(pattern):
            try:
                os.remove(file_path)
                print(f"🧹 Cleaned up old file: {file_path}")
            except Exception as e:
                print(f"⚠️ Could not delete {file_path}: {e}")

# ==========================================
# 3. MODULE 1: BRAIN WITH OFFLINE EMERGENCY BACKUP
# ==========================================
def generate_offline_concept():
    """Fallback concept pool when all APIs fail or hit rate limits."""
    fallback_pool = [
        {
            "title": "Why Metals Float in Space",
            "description": "Amazing space science fact #shorts #science",
            "narration": "Did you know that in space, if you touch two pieces of bare metal together, they will instantly melt and fuse permanently into one single piece? It is called cold welding!",
            "search_keywords": ["outer space", "metal welding"]
        },
        {
            "title": "Diamonds Rain on Planets",
            "description": "Crazy planet facts #shorts #science",
            "narration": "Jupiter and Saturn are so wild that storms turn methane gas into actual falling diamonds! Imagine a weather forecast calling for diamond rain!",
            "search_keywords": ["planet earth", "galaxy stars"]
        },
        {
            "title": "Water Freezing and Boiling",
            "description": "Triple point science #shorts #science",
            "narration": "There is a special temperature where water can freeze, boil, and turn into vapor all at the exact same time! Physics is pure magic!",
            "search_keywords": ["boiling water", "ice cubes"]
        }
    ]
    selected = random.choice(fallback_pool)
    print(f"🛡️ Using offline backup concept: {selected['title']}")
    return selected

def generate_with_groq_sdk(prompt):
    try:
        from groq import Groq
    except ImportError:
        return None

    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        return None

    client = Groq(api_key=key)
    for model_name in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]:
        try:
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "Output strictly valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                model=model_name,
                response_format={"type": "json_object"}
            )
            return json.loads(chat_completion.choices[0].message.content)
        except Exception:
            continue
    return None

def generate_short_concept():
    prompt = """
    Write a 60-word maximum YouTube Short script for 6-year-olds about an amazing science fact. 
    Output a valid JSON object matching this exact schema:
    {
        "title": "Short Title",
        "description": "Short desc #shorts #science",
        "narration": "The full voiceover text. No brackets or stage directions.",
        "search_keywords": ["keyword1", "keyword2"]
    }
    """

    # 1. Try Gemini
    if ai_client:
        try:
            print("🤖 Generating script with Gemini (gemini-3.8-flash)...")
            response = ai_client.models.generate_content(
                model="gemini-3.8-flash",
                contents=prompt,
                config={"response_mime_type": "application/json"}
            )
            return json.loads(response.text)
        except Exception:
            print("⚠️ Gemini failed or quota exceeded.")

    # 2. Try Groq SDK Backup
    print("🔄 Trying Groq API backup...")
    groq_result = generate_with_groq_sdk(prompt)
    if groq_result:
        return groq_result

    # 3. Ultimate Safety: Fallback to Offline Preset so pipeline completes
    print("🔄 All API keys exhausted/invalid. Engaging local fallback generator...")
    return generate_offline_concept()

# ==========================================
# 4. MODULE 2: VOICE & VTT SUBTITLE GENERATION
# ==========================================
def generate_voice_and_subs(text, audio_path, vtt_path):
    cmd = [
        "edge-tts",
        "--voice", VOICE_NAME,
        "--text", text,
        "--write-media", audio_path,
        "--write-subtitles", vtt_path
    ]
    subprocess.run(cmd, check=True)

# ==========================================
# 5. MODULE 3: VERTICAL STOCK VISUALS
# ==========================================
def fetch_vertical_video(keyword, output_path):
    headers = {"Authorization": PEXELS_API_KEY}
    url = f"https://api.pexels.com/videos/search?query={keyword}&per_page=5&orientation=portrait"
    
    response = requests.get(url, headers=headers).json()
    if response.get("videos") and len(response["videos"]) > 0:
        video_files = response["videos"][0]["video_files"]
        hd_file = next((f["link"] for f in video_files if f.get("width") == 1080), video_files[0]["link"])
        
        video_data = requests.get(hd_file).content
        with open(output_path, "wb") as f:
            f.write(video_data)
        return True
    return False

# ==========================================
# 6. MODULE 4: SAFE VTT PARSER & IN-FRAME CAPTION CLIPS
# ==========================================
def time_to_seconds(time_str):
    time_str = time_str.replace(',', '.') 
    h, m, s = time_str.split(':')
    return int(h) * 3600 + int(m) * 60 + float(s)

def parse_vtt_safely(vtt_path):
    captions = []
    with open(vtt_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    for i, line in enumerate(lines):
        if '-->' in line:
            times = line.strip().split(' --> ')
            if len(times) == 2 and i + 1 < len(lines):
                text = lines[i+1].strip()
                if text:
                    captions.append({
                        'start': times[0].strip(),
                        'end': times[1].strip(),
                        'text': text
                    })
    return captions

def build_caption_clips(vtt_path):
    captions = parse_vtt_safely(vtt_path)
    text_clips = []
    
    font_file = "arial.ttf"
    if os.path.exists("C:/Windows/Fonts/arial.ttf"):
        font_file = "C:/Windows/Fonts/arial.ttf"
    
    for caption in captions:
        start_time = time_to_seconds(caption['start'])
        end_time = time_to_seconds(caption['end'])
        duration = end_time - start_time
        
        if duration <= 0:
            continue
            
        wrapped_text = textwrap.fill(caption['text'], width=18)
            
        txt_clip = (
            TextClip(
                text=wrapped_text,
                font=font_file, 
                font_size=80,
                color='yellow',
                stroke_color='black',
                stroke_width=4,
                text_align="center"
            )
            .with_position('center')
            .with_start(start_time)
            .with_duration(duration)
        )
        text_clips.append(txt_clip)
    return text_clips

# ==========================================
# 7. MODULE 5: VIDEO ASSEMBLY WITH AUDIO
# ==========================================
def assemble_short(concept_data):
    audio_path = "voice.mp3"
    vtt_path = "voice.vtt"
    
    # 1. Generate Voice & Timestamps
    generate_voice_and_subs(concept_data["narration"], audio_path, vtt_path)
    voice_clip = AudioFileClip(audio_path)
    
    # 2. Fetch Vertical Visuals
    videos = []
    clip_duration = voice_clip.duration / len(concept_data["search_keywords"])
    
    for idx, keyword in enumerate(concept_data["search_keywords"]):
        vid_path = f"vid_{idx}.mp4"
        if not fetch_vertical_video(keyword, vid_path):
            fetch_vertical_video("science background", vid_path)
            
        vid = VideoFileClip(vid_path).without_audio()
        vid = vid.resized(height=1920)
        
        if vid.size[0] > 1080:
            vid = vid.cropped(x_center=vid.size[0]/2, width=1080)
            
        if vid.duration < clip_duration:
            repeats = int(clip_duration / vid.duration) + 1
            vid = concatenate_videoclips([vid] * repeats)
            
        vid = vid.subclipped(0, clip_duration)
        videos.append(vid)
    
    # 3. Assemble Background Visuals
    base_video = concatenate_videoclips(videos, method="compose")
    
    # 4. Attach Audio
    if os.path.exists("bg_music.mp3"):
        bg_music = (
            AudioFileClip("bg_music.mp3")
            .subclipped(0, base_video.duration) 
            .with_volume_scaled(0.15)
        )
        final_audio = CompositeAudioClip([voice_clip, bg_music])
    else:
        final_audio = voice_clip
        
    base_video = base_video.with_audio(final_audio)
        
    # 5. Overlay Captions & Re-attach Audio Track
    caption_clips = build_caption_clips(vtt_path)
    final_video = CompositeVideoClip([base_video] + caption_clips)
    final_video = final_video.with_audio(final_audio)
    
    # 6. Render
    output_filename = "final_short.mp4"
    final_video.write_videofile(
        output_filename,
        fps=30,
        codec="libx264",
        audio_codec="aac",
        threads=4
    )
    return output_filename

# ==========================================
# 8. MODULE 6: YOUTUBE PUBLISHER
# ==========================================
def upload_short(video_path, metadata):
    scopes = ["https://www.googleapis.com/auth/youtube.upload"]
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", scopes)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, scopes)
        creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
            
    youtube = build("youtube", "v3", credentials=creds)
    
    body = {
        "snippet": {
            "title": metadata["title"],
            "description": metadata["description"],
            "tags": ["shorts", "science", "kids"],
            "categoryId": "27"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": True
        }
    }
    
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploaded {int(status.progress() * 100)}%")
            
    print(f"🎉 Short Uploaded Successfully! Video ID: {response['id']}")

# ==========================================
# 9. EXECUTION FLOW
# ==========================================
if __name__ == "__main__":
    print("🧹 Cleaning workspace...")
    cleanup_temp_files()
    
    print("🧠 Generating Short Concept...")
    concept = generate_short_concept()
    print(f"Topic: {concept['title']}")
    
    print("🎬 Assembling Vertical Video & Syncing Captions...")
    video_file = assemble_short(concept)
    
    print("🚀 Publishing to YouTube Shorts...")
    upload_short(video_file, concept)