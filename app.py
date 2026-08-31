import os
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse
from flask import Flask, jsonify, request
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi
import google.generativeai as genai

app = Flask(__name__)
app.debug = False

CORS(
app,
resources={
    r"/api/*": {
        "origins": "*"
    }
}
)

# [AUTOMATED AI TUNNEL CONFIGURATION]
# TODO: Apni Google Cloud console wali real Gemini Key yahan fit karne:
genai.configure(api_key="https://storage.googleapis.com/cloud-samples-data/adc/setup_adc.sh)")

YOUTUBE_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")

SUPPORTED_HOSTS = {
"youtube.com",
"www.youtube.com",
"youtu.be",
"www.youtu.be",
}

def extract_video_id(value: str) -> Optional[str]:
    if not value:
        return None
    url = value.strip()
    if not url:
        return None
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = f"https://{url}"
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host not in SUPPORTED_HOSTS:
        return None

    if host in {"youtu.be", "www.youtu.be"}:
        path_parts = [part for part in parsed.path.split("/") if part]
        if not path_parts:
            return None
        video_id = path_parts[0]
        return video_id if YOUTUBE_VIDEO_ID_PATTERN.fullmatch(video_id) else None

    query_values = parse_qs(parsed.query)

    if parsed.path.lower() == "/watch":
        video_id_list = query_values.get("v")
        if video_id_list and len(video_id_list) > 0:
            video_id = video_id_list[0]
            if YOUTUBE_VIDEO_ID_PATTERN.fullmatch(video_id):
                return video_id
        return None

    path_parts = [part for part in parsed.path.split("/") if part]

    for route in ("embed", "shorts", "live"):
        if route not in path_parts:
            continue
        index = path_parts.index(route)
        if index + 1 >= len(path_parts):
            return None
        video_id = path_parts[index + 1]
        if YOUTUBE_VIDEO_ID_PATTERN.fullmatch(video_id):
            return video_id
        return None
    return None

def get_transcript(video_id: str):
    try:
        transcript_data = YouTubeTranscriptApi.get_transcript(video_id, languages=['en', 'en-US', 'en-GB'])
        text = " ".join([item['text'] for item in transcript_data]).strip()
        if not text:
            raise ValueError("Empty string token received")
        return text, "en"
    except Exception:
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            selected = None
            try:
                selected = transcript_list.find_manually_created_transcript(['en'])
            except Exception:
                try:
                    selected = transcript_list.find_generated_transcript(['en'])
                except Exception:
                    selected = next(iter(transcript_list))

            if selected is None:
                raise RuntimeError("No transcription block tracking layer available.")

            fetched = selected.fetch()
            text = " ".join([item['text'] for item in fetched]).strip()
            return text, selected.language_code
        except Exception as fallback_error:
            raise RuntimeError(f"YouTube block validation failed: {str(fallback_error)}")

@app.get("/")
def health_check():
    return jsonify({"service": "Scriptifly Backend", "status": "ok"})

@app.get("/api/health")
def api_health():
    return jsonify({"success": True, "service": "Scriptifly Backend", "status": "healthy"})

@app.get("/api/transcript")
def transcript():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({
            "success": False, "video_id": None, "language": None, "transcript": None, "summary": None, "urdu_translation": None, "error": "The YouTube URL is required."
        }), 400

    video_id = extract_video_id(url)
    if video_id is None:
        return jsonify({
            "success": False, "video_id": None, "language": None, "transcript": None, "summary": None, "urdu_translation": None, "error": "Invalid YouTube video URL format."
        }), 400

    try:
        transcript_text, language = get_transcript(video_id)

        model = genai.GenerativeModel('gemini-1.5-flash')

        summary_prompt = f"Provide a brief bulleted summary of this transcript: {transcript_text}"
        summary_response = model.generate_content(summary_prompt)

        translation_prompt = f"Translate this summary into clean conversational Urdu language text layout: {summary_response.text}"
        translation_response = model.generate_content(translation_prompt)

        return jsonify({
            "success": True,
            "video_id": video_id,
            "language": language,
            "transcript": transcript_text,
            "summary": summary_response.text,
            "urdu_translation": translation_response.text,
            "error": None
        }), 200

    except Exception as exception:
        return jsonify({
            "success": False, "video_id": video_id, "language": None, "transcript": None, "summary": None, "urdu_translation": None,
            "error": str(exception) if str(exception).strip() else "Unable to retrieve the transcript data parameters from server."
        }), 422

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
