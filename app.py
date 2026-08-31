import re
from typing import Optional

from flask import Flask, jsonify, request
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi

app = Flask(__name__)
app.debug = False  # Debug hamesha false rakhein

CORS(
    app,
    resources={
        r"/api/*": {
            "origins": "*"
        }
    }
)

YOUTUBE_VIDEO_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9_-]{11}$"
)

SUPPORTED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
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

    from urllib.parse import parse_qs, urlparse

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
        video_id = query_values.get("v", [None])[0]
        if video_id and YOUTUBE_VIDEO_ID_PATTERN.fullmatch(video_id):
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

def normalize_transcript(transcript_entries) -> str:
    text_parts = []
    for entry in transcript_entries:
        if isinstance(entry, dict):
            text = entry.get("text", "")
        else:
            text = getattr(entry, "text", "")

        if text is None:
            continue

        cleaned = str(text).strip()
        if cleaned:
            text_parts.append(cleaned)

    return " ".join(text_parts).strip()

def get_transcript(video_id: str):
    api = YouTubeTranscriptApi()
    transcript_list = api.list(video_id)
    transcripts = list(transcript_list)

    if not transcripts:
        raise RuntimeError("No transcript is available for this video.")

    preferred_languages = ("en", "en-US", "en-GB")
    selected = None

    for language in preferred_languages:
        selected = next((t for t in transcripts if t.language_code == language), None)
        if selected is not None:
            break

    if selected is None:
        selected = next((t for t in transcripts if not t.is_generated), None)

    if selected is None:
        selected = transcripts[0]

    fetched = selected.fetch()
    text = normalize_transcript(fetched)

    if not text:
        raise RuntimeError("The transcript was empty.")

    return text, selected.language_code

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
            "success": False, "video_id": None, "language": None, "transcript": None, "error": "The YouTube URL is required."
        }), 400

    video_id = extract_video_id(url)
    if video_id is None:
        return jsonify({
            "success": False, "video_id": None, "language": None, "transcript": None, "error": "Invalid YouTube video URL."
        }), 400

    try:
        transcript_text, language = get_transcript(video_id)
        return jsonify({
            "success": True, "video_id": video_id, "language": language, "transcript": transcript_text, "error": None
        })
    except Exception as exception:
        return jsonify({
            "success": False, "video_id": video_id, "language": None, "transcript": None,
            "error": str(exception) if str(exception).strip() else "Unable to retrieve the transcript."
        }), 422

@app.errorhandler(404)
def not_found(_error):
    return jsonify({"success": False, "error": "Endpoint not found."}), 404

@app.errorhandler(405)
def method_not_allowed(_error):
    return jsonify({"success": False, "error": "HTTP method not allowed."}), 405

@app.errorhandler(500)
def internal_server_error(_error):
    return jsonify({"success": False, "error": "Internal server error."}), 500

# Vercel serverless deployment handler logic compatibility setup
app.debug = False

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5001,
        debug=False
    )
