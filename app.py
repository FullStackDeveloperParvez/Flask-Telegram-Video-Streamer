import threading
import time
from datetime import datetime, timedelta
import asyncio
from functools import wraps
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional
import json
import io
import os
import sqlite3
from dotenv import load_dotenv
import random

from flask import Flask, render_template, Response, request, jsonify, send_file, url_for
from flask import redirect, flash, session
from flask_bcrypt import Bcrypt
from telethon import TelegramClient
from telethon.tl.types import Message, DocumentAttributeVideo, InputMessagesFilterPhotoVideo

import cv2
import tempfile
import os
import json
from werkzeug.utils import secure_filename
from telethon.tl.types import InputMediaUploadedPhoto, InputMediaUploadedDocument
from telethon.tl.types import DocumentAttributeVideo, DocumentAttributeFilename

# Configuration
load_dotenv()
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
SESSION_NAME = os.getenv("SESSION_NAME")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
DATABASE_FILE = os.getenv("DATABASE_FILE")

# Flask app setup
app = Flask(__name__)
app.secret_key = os.urandom(24)
bcrypt = Bcrypt(app)

# Global variables for client management
client = None
loop = None
executor = None


def init_app():
    global client, loop, executor

    # Create event loop and executor
    loop = asyncio.new_event_loop()
    executor = ThreadPoolExecutor(max_workers=5)

    # Initialize Telethon client
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH, loop=loop)

    # Start the event loop in a separate thread
    def run_event_loop():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    threading.Thread(target=run_event_loop, daemon=True).start()


# Database initialization
def init_db():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS usr (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0
    )
    ''')

    # Check if admin user exists
    cursor.execute("SELECT * FROM usr WHERE username = 'admin'")
    if not cursor.fetchone():
        # Create default admin user
        hashed_password = bcrypt.generate_password_hash('Welcome1').decode('utf-8')
        cursor.execute("INSERT INTO usr (username, password, is_admin) VALUES (?, ?, ?)",
                       ('admin', hashed_password, 1))

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS med (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        msg_id INTEGER,
        title TEXT,
        tags TEXT,
        file_size INTEGER,
        mime_type TEXT,
        duration INTEGER,
        width INTEGER,
        height INTEGER,
        thumbnail BLOB
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS fav (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usr_id INTEGER,
        med_id INTEGER    
    )               
    ''')

    conn.commit()
    conn.close()


# Helper to run async functions in the shared event loop
def run_async(coro):
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()


async def connect_client_if_needed():
    """Connect the client if not already connected"""
    if not client.is_connected():
        await client.connect()

    if not await client.is_user_authorized():
        print("You need to login to Telegram. Check your terminal for instructions.")
        phone = input("Enter your phone number with country code: ")
        await client.send_code_request(phone)
        code = input("Enter the code you received: ")
        await client.sign_in(phone, code)
        print("Telegram client initialized!")


async def fetch_videos_from_channel():
    """Fetch videos from the Telegram channel and store metadata with thumbnail in SQLite"""
    # Ensure client is connected
    await connect_client_if_needed()

    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    try:
        channel = await client.get_entity(CHANNEL_USERNAME)
        videos = []
        messages = []
        async for msg in client.iter_messages(channel, reverse=True):
            messages.append(msg)
        
        for msg in messages:
            # Check if the message contains media
            if not msg.media:
                continue

            # Initialize for grouped media
            video_doc = None
            image_msg = None
            video_msg = None
            json_data = {"media_name": None, "tags": None}

            # Handle grouped media
            if hasattr(msg, 'grouped_id') and msg.grouped_id:
                group_messages = [m for m in messages if
                                  hasattr(m, 'grouped_id') and m.grouped_id == msg.grouped_id]

                if msg not in group_messages:
                    group_messages.append(msg)

                # Find the first image and video in the group
                for group_msg in group_messages:
                    if group_msg.message:
                        try:
                            possible_json = group_msg.message.strip()
                            if possible_json.startswith('{') and possible_json.endswith('}'):
                                parsed_data = json.loads(possible_json)
                                if 'media_name' in parsed_data or 'tags' in parsed_data:
                                    json_data = parsed_data
                        except json.JSONDecodeError:
                            pass
                    if group_msg.photo:
                        image_msg = group_msg
                    elif group_msg.media and hasattr(group_msg.media, 'document'):
                        doc = group_msg.media.document
                        if doc.mime_type.startswith('video/'):
                            video_doc = doc
                            video_msg = group_msg

            # Handle single video message
            elif hasattr(msg.media, 'document') and msg.media.document.mime_type.startswith('video/'):
                video_doc = msg.media.document
                video_msg = msg

                # Check for JSON in the message text
                if msg.message:
                    try:
                        possible_json = msg.message.strip()
                        if possible_json.startswith('{') and possible_json.endswith('}'):
                            parsed_data = json.loads(possible_json)
                            if 'media_name' in parsed_data or 'tags' in parsed_data:
                                json_data = parsed_data
                    except json.JSONDecodeError:
                        pass

            # Skip if no video found
            if not video_doc or not video_msg:
                continue

            # Get video attributes
            video_attr = next((attr for attr in video_doc.attributes
                               if isinstance(attr, DocumentAttributeVideo)), None)

            # Get video ID
            video_id = video_msg.id

            # Check if video already exists in database
            cursor.execute("SELECT id FROM med WHERE msg_id = ?", (video_id,))
            if cursor.fetchone():
                print(f"Video {video_id} already in database, skipping")
                continue

            # Prepare video info for database
            title = json_data.get('media_name', None) or getattr(video_msg, 'message',
                                                                 f'Video {video_id}') or f'Video {video_id}'
            tags = json_data.get('tags', "")

            video_info = {
                'msg_id': video_id,
                'file_size': video_doc.size,
                'mime_type': video_doc.mime_type,
                'duration': video_attr.duration if video_attr else 0,
                'width': video_attr.w if video_attr else 0,
                'height': video_attr.h if video_attr else 0,
                'title': title,
                'tags': tags
            }

            # Download thumbnail as binary data
            thumbnail_data = None
            if video_info.get('duration') > 300:
                try:
                    if image_msg:
                        # Use BytesIO to capture the image data directly
                        thumbnail_buffer = io.BytesIO()
                        await client.download_media(image_msg, thumbnail_buffer)
                        thumbnail_data = thumbnail_buffer.getvalue()

                    elif video_doc.thumbs:
                        # Fallback to video's built-in thumbnail
                        best_thumb = max(video_doc.thumbs, key=lambda t: getattr(t, 'w', 0) * getattr(t, 'h', 0))
                        thumbnail_buffer = io.BytesIO()
                        await client.download_media(
                            message=video_msg,
                            file=thumbnail_buffer,
                            thumb=video_doc.thumbs.index(best_thumb)
                        )
                        thumbnail_data = thumbnail_buffer.getvalue()
                except Exception as e:
                    print(f"Error downloading thumbnail for video {video_id}: {e}")

            # Insert data into SQLite
            try:
                cursor.execute('''
                INSERT INTO med (msg_id, title, tags, file_size, mime_type, duration, width, height, thumbnail)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    video_info['msg_id'],
                    video_info['title'],
                    video_info['tags'],
                    video_info['file_size'],
                    video_info['mime_type'],
                    video_info['duration'],
                    video_info['width'],
                    video_info['height'],
                    thumbnail_data
                ))
                conn.commit()

                # Add to return list (without the binary data for cleaner output)
                videos.append(video_info)

            except sqlite3.Error as e:
                print(f"SQLite error: {e}")

    except Exception as e:
        print(f"Error fetching videos: {e}")
    finally:
        conn.close()

    return videos


def schedule_fetch(interval_seconds=86400):  # Default 2 days
    """Schedule periodic fetches of videos from the channel"""
    while True:
        try:
            print(f"Starting video fetch at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            run_async(fetch_videos_from_channel())
            print(
                f"Next fetch scheduled at {(datetime.now() + timedelta(seconds=interval_seconds)).strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception as e:
            print(f"Error in scheduled fetch: {e}")

        time.sleep(interval_seconds)


# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated_function


# Admin required decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'is_admin' not in session or not session['is_admin']:
            flash('Admin access required', 'error')
            return redirect(url_for('home'))
        return f(*args, **kwargs)

    return decorated_function


@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('home'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = sqlite3.connect(DATABASE_FILE)  # Use consistent database file
        cursor = conn.cursor()
        cursor.execute("SELECT id, password, is_admin FROM usr WHERE username = ?", (username,))
        user = cursor.fetchone()
        conn.close()

        if user and bcrypt.check_password_hash(user[1], password):
            session['user_id'] = user[0]
            session['username'] = username
            session['is_admin'] = user[2]
            flash('Login successful', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid username or password', 'error')

    return render_template('login.html')


@app.route('/home')
@login_required
def home():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, msg_id, title, tags, duration FROM med WHERE duration > 300 ORDER BY id DESC")
    videos = cursor.fetchall()
    random.shuffle(videos)
    conn.close()

    return render_template('home.html', username=session.get('username'), videos=videos)


@app.route('/admin')
@login_required
@admin_required
def admin():
    conn = sqlite3.connect(DATABASE_FILE)  # Use consistent database file
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, is_admin FROM usr")
    users = cursor.fetchall()
    conn.close()

    return render_template('admin.html', users=users)


@app.route('/admin/create_user', methods=['POST'])
@login_required
@admin_required
def create_user():
    username = request.form['username']
    password = request.form['password']
    is_admin = 1 if request.form.get('is_admin') else 0

    if not username or not password:
        flash('Username and password are required', 'error')
        return redirect(url_for('admin'))

    try:
        conn = sqlite3.connect(DATABASE_FILE)  # Use consistent database file
        cursor = conn.cursor()
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        cursor.execute("INSERT INTO usr (username, password, is_admin) VALUES (?, ?, ?)",
                       (username, hashed_password, is_admin))
        conn.commit()
        conn.close()
        flash('User created successfully', 'success')
    except sqlite3.IntegrityError:
        flash('Username already exists', 'error')

    return redirect(url_for('admin'))


@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    if session.get('user_id') == user_id:
        flash('Cannot delete your own account', 'error')
        return redirect(url_for('admin'))

    conn = sqlite3.connect(DATABASE_FILE)  # Use consistent database file
    cursor = conn.cursor()
    cursor.execute("DELETE FROM usr WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    flash('User deleted successfully', 'success')
    return redirect(url_for('admin'))


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'success')
    return redirect(url_for('login'))


@app.route('/video/<int:msg_id>')
@login_required
def view_video(msg_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, msg_id, title, tags, duration, mime_type FROM med WHERE msg_id = ?", (msg_id,))
    video = cursor.fetchone()
    
    # Check if video is in user's favorites
    is_favorite = False
    if video:
        cursor.execute("SELECT id FROM fav WHERE usr_id = ? AND med_id = ?", 
                      (session.get('user_id'), video[0]))
        is_favorite = cursor.fetchone() is not None
    
    conn.close()

    if not video:
        flash('Video not found', 'error')
        return redirect(url_for('home'))

    return render_template('video.html', video=video, is_favorite=is_favorite)


@app.route('/thumbnail/<int:msg_id>')
@login_required
def get_thumbnail(msg_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT thumbnail FROM med WHERE msg_id = ?", (msg_id,))
    result = cursor.fetchone()
    conn.close()

    if not result or not result[0]:
        return send_file('static/default-thumbnail.jpg', mimetype='image/jpeg')

    return Response(result[0], mimetype='image/jpeg')


@app.route('/stream/<int:msg_id>')
@login_required
def stream_video(msg_id):
    # This function will handle streaming the video from Telegram
    # We'll need to implement proper streaming with range requests
    async def get_video_chunk(msg_id, offset=0, limit=1024*1024*10):
        """Get a chunk of video data for streaming"""
        channel = await client.get_entity(CHANNEL_USERNAME)
        message = await client.get_messages(channel, ids=msg_id)
        
        if not message or not message.media:
            return None, None, 0
        
        doc = message.media.document
        total_size = doc.size
        
        # Use client.iter_download instead of download_media for streaming
        buffer = b''
        async for chunk in client.iter_download(message.media, offset=offset, request_size=limit):
            buffer += chunk
            if len(buffer) >= limit:
                break
        
        return buffer, doc.mime_type, total_size

    # Get range header
    range_header = request.headers.get('Range', 'bytes=0-')
    offset = int(range_header.replace('bytes=', '').split('-')[0])
    chunk_size = 1024 * 1024 * 10 # 10MB chunks

    
    try:
        # Get the video chunk
        chunk, mime_type, total_size = run_async(get_video_chunk(msg_id, offset, chunk_size))
        
        if not chunk:
            return "Error streaming video", 500
            
        # Calculate end byte position
        end = min(offset + len(chunk) - 1, total_size - 1)
        
        # Create response
        response = Response(
            chunk,
            206,  # Partial Content
            mimetype=mime_type,
            direct_passthrough=True
        )
        
        # Set response headers
        response.headers.add('Content-Range', f'bytes {offset}-{end}/{total_size}')
        response.headers.add('Accept-Ranges', 'bytes')
        response.headers.add('Content-Length', str(len(chunk)))
        
        return response
    
    except Exception as e:
        print(f"Error streaming video: {e}")
        return "Error streaming video", 500


@app.route('/favourites')
@login_required
def favourites():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    # Join med and fav tables to get user's favorite videos
    cursor.execute("""
        SELECT med.id, med.msg_id, med.title, med.tags, med.duration 
        FROM med 
        INNER JOIN fav ON med.id = fav.med_id 
        WHERE fav.usr_id = ? 
        ORDER BY fav.id DESC
    """, (session.get('user_id'),))
    videos = cursor.fetchall()
    random.shuffle(videos)
    conn.close()

    return render_template('favourites.html', username=session.get('username'), videos=videos)


@app.route('/add_favourite/<int:med_id>', methods=['POST'])
@login_required
def add_favourite(med_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # Check if already in favorites
    cursor.execute("SELECT id FROM fav WHERE usr_id = ? AND med_id = ?", 
                  (session.get('user_id'), med_id))
    existing = cursor.fetchone()
    
    if existing:
        flash('Video already in favourites', 'info')
    else:
        cursor.execute("INSERT INTO fav (usr_id, med_id) VALUES (?, ?)", 
                      (session.get('user_id'), med_id))
        conn.commit()
        flash('Added to favourites', 'success')
    
    conn.close()
    return redirect(request.referrer or url_for('home'))


@app.route('/remove_favourite/<int:med_id>', methods=['POST'])
@login_required
def remove_favourite(med_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM fav WHERE usr_id = ? AND med_id = ?", 
                  (session.get('user_id'), med_id))
    conn.commit()
    conn.close()
    flash('Removed from favourites', 'success')
    return redirect(request.referrer or url_for('favourites'))


@app.route('/upload', methods=['GET'])
@login_required
def upload_page():
    return render_template('upload.html')


@app.route('/generate_thumbnail', methods=['POST'])
@login_required
def generate_thumbnail():
    if 'video' not in request.files:
        return jsonify({'error': 'No video file uploaded'}), 400

    video_file = request.files['video']
    timestamp = request.form.get('timestamp', 'random')
    
    # Create temp file with unique name for video
    temp_video_fd, video_path = tempfile.mkstemp(suffix='.mp4')
    os.close(temp_video_fd)  # Close the file descriptor
    
    # Create temp file with unique name for thumbnail
    temp_thumb_fd, thumbnail_path = tempfile.mkstemp(suffix='.jpg')
    os.close(temp_thumb_fd)  # Close the file descriptor
    
    try:
        # Save the uploaded video to the temp file
        video_file.save(video_path)
        
        # Open video with OpenCV
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            cap.release()
            os.unlink(video_path)
            os.unlink(thumbnail_path)
            return jsonify({'error': 'Could not open video file'}), 400
        
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        if frame_count <= 0:
            cap.release()
            os.unlink(video_path)
            os.unlink(thumbnail_path)
            return jsonify({'error': 'Invalid video file'}), 400
        
        # Get timestamp for the frame
        if timestamp == 'random':
            frame_number = int(frame_count * 0.3)  # At 30% of the video
        else:
            try:
                # Convert timestamp (in seconds) to frame number
                frame_number = int(float(timestamp) * fps)
                if frame_number >= frame_count:
                    frame_number = int(frame_count / 2)
            except:
                frame_number = int(frame_count / 2)
        
        # Seek to the specific frame
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()
        
        # Release the video capture
        cap.release()
        
        if not ret:
            os.unlink(video_path)
            os.unlink(thumbnail_path)
            return jsonify({'error': 'Could not extract frame from video'}), 400
        
        # Save thumbnail
        cv2.imwrite(thumbnail_path, frame)
        
        # Read thumbnail as base64
        with open(thumbnail_path, 'rb') as f:
            thumbnail_data = f.read()
        
        import base64
        thumbnail_base64 = base64.b64encode(thumbnail_data).decode('utf-8')
        
        # Clean up temporary files
        os.unlink(video_path)
        os.unlink(thumbnail_path)
        
        return jsonify({
            'thumbnail': f'data:image/jpeg;base64,{thumbnail_base64}',
            'width': width,
            'height': height
        })
        
    except Exception as e:
        # Make sure to clean up resources in case of exception
        if 'cap' in locals() and cap is not None:
            cap.release()
        
        # Try to clean up temporary files
        try:
            os.unlink(video_path)
        except:
            pass
            
        try:
            os.unlink(thumbnail_path)
        except:
            pass
            
        return jsonify({'error': f'Error generating thumbnail: {str(e)}'}), 500
    

@app.route('/upload_video', methods=['POST'])
@login_required
def upload_video():
    if 'video' not in request.files:
        return jsonify({'error': 'No video file uploaded'}), 400
    
    video_file = request.files['video']
    title = request.form.get('title', '')
    tags = request.form.get('tags', '')
    thumbnail_data = None
    
    # Check if a thumbnail was uploaded
    if 'thumbnail' in request.files and request.files['thumbnail'].filename:
        thumbnail_file = request.files['thumbnail']
        thumbnail_data = thumbnail_file.read()
    # Otherwise use the base64 thumbnail data
    elif 'thumbnail_data' in request.form and request.form['thumbnail_data']:
        import base64
        thumbnail_base64 = request.form['thumbnail_data'].split(',')[1]
        thumbnail_data = base64.b64decode(thumbnail_base64)
    else:
        return jsonify({'error': 'No thumbnail provided'}), 400
    
    # Check file size (1GB limit)
    video_file.seek(0, os.SEEK_END)
    file_size = video_file.tell()
    video_file.seek(0)
    
    if file_size > 1024 * 1024 * 1024:  # 1GB
        return jsonify({'error': 'Video file too large (max 1GB)'}), 400
    
    # Check file extension
    filename = secure_filename(video_file.filename)
    if not filename.lower().endswith('.mp4'):
        return jsonify({'error': 'Only MP4 videos are supported'}), 400
    
    # Create temporary files
    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_video, \
         tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp_thumb:
        
        video_path = temp_video.name
        thumbnail_path = temp_thumb.name
        
        # Save files
        video_file.save(video_path)
        with open(thumbnail_path, 'wb') as f:
            f.write(thumbnail_data)
    
    try:
        # Get video metadata using OpenCV
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            cap.release()  # Make sure to release before any return or exception
            os.unlink(video_path)
            os.unlink(thumbnail_path)
            return jsonify({'error': 'Could not open video file'}), 400
        
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS))
        
        # Important: Release the video capture BEFORE trying to delete the file
        cap.release()
        
        # Create JSON message
        message_json = {
            "media_name": title,
            "tags": tags
        }
        
        # Upload to Telegram using async function
        async def upload_to_telegram():
            await connect_client_if_needed()
            
            # Get channel entity
            channel = await client.get_entity(CHANNEL_USERNAME)
            
            # Upload thumbnail image first
            thumbnail_file = await client.upload_file(thumbnail_path, file_name="thumbnail.jpg")
            thumb_media = InputMediaUploadedPhoto(thumbnail_file)
            
            # Upload video file
            video_file = await client.upload_file(video_path, file_name=filename)
            
            # Video attributes
            attributes = [
                DocumentAttributeVideo(
                    duration=duration,
                    w=width,
                    h=height,
                    supports_streaming=True
                ),
                DocumentAttributeFilename(filename)
            ]
            
            video_media = InputMediaUploadedDocument(
                file=video_file,
                mime_type="video/mp4",
                attributes=attributes,
                thumb=thumbnail_file
            )
            
            # Send as a group message
            await client.send_message(
                channel,
                json.dumps(message_json),
                file=video_media
            )
        
        # Run the async function
        run_async(upload_to_telegram())
        
        # Clean up temporary files
        os.unlink(video_path)
        os.unlink(thumbnail_path)
        
        return jsonify({'success': True, 'message': 'Video uploaded successfully'})
        
    except Exception as e:
        # Make sure cap is released if it exists
        try:
            if 'cap' in locals() and cap is not None:
                cap.release()
        except:
            pass
            
        # Clean up temporary files
        try:
            os.unlink(video_path)
        except:
            pass
            
        try:
            os.unlink(thumbnail_path)
        except:
            pass
            
        return jsonify({'error': str(e)}), 500


@app.route('/shorts')
@login_required
def shorts():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    # Select only videos less than 5 minutes (300 seconds)
    cursor.execute("""
        SELECT id, msg_id, title, tags, duration, mime_type
        FROM med 
        WHERE duration < 300 
        ORDER BY id DESC
    """)
    short_videos = cursor.fetchall()
    
    # Convert to list of dictionaries for easier handling in template
    videos = []
    for video in short_videos:
        # Check if in favorites
        cursor.execute("SELECT id FROM fav WHERE usr_id = ? AND med_id = ?", 
                      (session.get('user_id'), video[0]))
        is_favorite = cursor.fetchone() is not None
        
        videos.append({
            'id': video[0],
            'msg_id': video[1],
            'title': video[2],
            'tags': video[3].split(',') if video[3] else [],
            'duration': video[4],
            'is_favorite': is_favorite
        })
    random.shuffle(videos)
    conn.close()
    return render_template('shorts.html', videos=videos)

                                                           
if __name__ == '__main__':
    # Initialize database
    init_db()

    # Initialize app components (event loop, client, etc.)
    init_app()

    # Start scheduler in a separate thread
    scheduler_thread = threading.Thread(
        target=schedule_fetch,
        kwargs={'interval_seconds': 604800},  # 1 week
        daemon=True
    )
    scheduler_thread.start()

    # Run Flask app
    app.run(debug=True, port=5001, threaded=True, use_reloader=False)  # use_reloader=False to prevent duplicate threads