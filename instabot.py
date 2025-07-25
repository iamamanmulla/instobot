import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from instagrapi import Client
from instagrapi.exceptions import BadPassword
from cryptography.fernet import Fernet
import logging

# ========== Encryption Helpers ==========

#-- generate and save secret key if missing
if not os.path.exists("secret.key"):
    with open("secret.key", "wb") as f:
        f.write(Fernet.generate_key())


def load_key():
    with open("secret.key", "rb") as key_file:
        return key_file.read()

def encrypt_data(data: str) -> str:
    key = load_key()
    return Fernet(key).encrypt(data.encode()).decode()

def decrypt_data(token: str) -> str:
    key = load_key()
    return Fernet(key).decrypt(token.encode()).decode()

# ========== Configuration ==========
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
SESSION_FOLDER = "sessions"
SESSION_FILE = os.path.join(SESSION_FOLDER, "insta_session.json")

for folder in [UPLOAD_FOLDER, SESSION_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

cl = Client()
scheduler = BackgroundScheduler()
scheduler.start()

CREDENTIALS = {}
CAPTIONS = {}
SCHEDULED_POSTS = []

# ========== Helper Functions ==========
def is_valid_video_file(filename):
    valid_extensions = ['.mp4', '.mov', '.avi', '.mkv']
    name, ext = os.path.splitext(filename)
    return (
            not filename.startswith('.')  # Skip hidden files like .DS_Store
            and ext.lower() in valid_extensions
    )


def save_session():
    settings = cl.get_settings()
    with open(SESSION_FILE, "w") as f:
        json.dump(settings, f)

def load_session():
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r") as f:
                settings = json.load(f)
            cl.set_settings(settings)
            username = decrypt_data(CREDENTIALS["username"])
            password = decrypt_data(CREDENTIALS["password"])
            cl.login(username, password)
            print("🔄 Session resumed successfully.")
            return True
        except Exception as e:
            print(f"⚠️ Failed to load session: {e}")
    return False

def upload_scheduled_reel(post):
    print(f"🎬 Attempting to upload scheduled reel at {post['time']}")
    try:
        if not cl.user_id:
            username = decrypt_data(CREDENTIALS["username"])
            password = decrypt_data(CREDENTIALS["password"])
            cl.login(username, password)
        save_session()

        media_files = os.listdir(UPLOAD_FOLDER)
        if not media_files:
            print("🚫 No media files found to upload")
            return

        media_path = os.path.join(UPLOAD_FOLDER, media_files[0])
        caption = post["caption"]

        cl.clip_upload(media_path, caption)
        print(f"✅ Reel uploaded: {media_path}")
        os.remove(media_path)

    except Exception as e:
        print(f"❌ Failed to upload scheduled reel: {e}")

def schedule_file_post(filename, caption="Auto-post", post_type="reel"):
    post_id = len(SCHEDULED_POSTS)
    run_time = datetime.now()
    post = {
        "id": post_id,
        "time": run_time.isoformat(),
        "caption": caption,
        "type": post_type
    }
    SCHEDULED_POSTS.append(post)
    scheduler.add_job(
        func=upload_scheduled_reel,
        trigger="date",
        run_date=run_time,
        args=[post],
        id=f"post_{post_id}"
    )

# Schedule existing uploads
for file in os.listdir(UPLOAD_FOLDER):
    if is_valid_video_file(file):
        schedule_file_post(file)

# ========== API Routes ==========
@app.route("/", methods=["GET"])
def home():
    return "Instagram Bot API (Encrypted) is running"

@app.route("/login", methods=["POST"])
def login_route():
    if load_session():
        return jsonify({"status": "success", "message": "Logged in."}), 200
    return jsonify({"status": "error", "message": "Login failed."}), 401

@app.route("/save_credentials", methods=["POST"])
def save_credentials():
    data = request.json
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"error": "Missing credentials"}), 400

    CREDENTIALS["username"] = encrypt_data(username)
    CREDENTIALS["password"] = encrypt_data(password)
    return jsonify({"message": "Credentials saved successfully"})

@app.route("/save_caption", methods=["POST"])
def save_caption():
    data = request.json
    name = data.get("name")
    content = data.get("content")

    if not name or not content:
        return jsonify({"error": "Missing caption data"}), 400

    CAPTIONS[name] = content
    return jsonify({"message": "Caption saved successfully"})

@app.route("/upload", methods=["POST"])
def upload_media():
    if 'media' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["media"]
    if not is_valid_video_file(file.filename):
        return jsonify({"error": "Invalid video file format"}), 400
    filepath = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(filepath)
    return jsonify({"message": "Media uploaded successfully", "filename": file.filename})

@app.route("/schedule", methods=["POST"])
def schedule_post():
    data = request.json
    schedule_time = data.get("schedule_time")
    caption_key = data.get("caption") or "default"
    post_type = data.get("type", "reel")

    if not schedule_time or caption_key not in CAPTIONS:
        return jsonify({"error": "Missing schedule time or caption"}), 400

    post_id = len(SCHEDULED_POSTS)
    post = {
        "id": post_id,
        "time": schedule_time,
        "caption": CAPTIONS[caption_key],
        "type": post_type
    }
    SCHEDULED_POSTS.append(post)

    run_time = datetime.fromisoformat(schedule_time)
    scheduler.add_job(
        func=upload_scheduled_reel,
        trigger="date",
        run_date=run_time,
        args=[post],
        id=f"post_{post_id}"
    )
    return jsonify({"message": "Post scheduled successfully"})

# ========== Run App ==========
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)
