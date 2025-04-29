# 🎥 Flask Telegram Video Streamer

[![Python](https://img.shields.io/badge/python-3.8%2B-blue)](#) [![Flask](https://img.shields.io/badge/flask-2.x-green)](#) [![Telethon](https://img.shields.io/badge/telethon-1.x-orange)](#)

---

## 📖 Table of Contents

- [✨ Features](#✨-features)  
- [🚀 Quick Start](#🚀-quick-start)  
  - [1. Clone the Repo](#1-clone-the-repo)  
  - [2. Create & Configure `.env`](#2-create--configure-env)  
  - [3. Install Dependencies](#3-install-dependencies)  
  - [4. Initialize & Run](#4-initialize--run)  
- [🛠️ Configuration](#🛠️-configuration)  
- [📂 Project Structure](#📂-project-structure)  
- [👩‍💻 Usage](#👩‍💻-usage)  
- [🤝 Contributing](#🤝-contributing)  
- [📝 License](#📝-license)  

---

## ✨ Features

- 🔐 **User Authentication**  
  - Secure login/registration with `Flask-Bcrypt`  
  - Admin dashboard to manage users
- 🎞️ **Fetch & Stream Videos**  
  - Periodic background fetch from a Telegram channel  
  - Smooth HTTP Range streaming for large MP4s  
- ⭐ **Favorites & Shorts**  
  - Mark/unmark favorites  
  - Separate view for videos under 5 minutes
- 📷 **Thumbnail Generation**  
  - Auto-generate from a timestamp or upload custom thumbnail  
- 🔍 **Search & Tag API**  
  - Full-text search on titles & tags  
  - REST endpoint: `/api/videos/by_tag/<tag>`
- 🧰 **Admin Tools**  
  - Create/delete users via web UI  
  - Secure admin-only routes

---

## 🚀 Quick Start

### 1. Clone the Repo

```bash
git clone https://github.com/yourusername/flask-telegram-streamer.git
cd flask-telegram-streamer
2. Create & Configure .env
Copy the example and fill in your credentials:

bash
Copy
Edit
cp .env.example .env
ini
Copy
Edit
API_ID=your_telegram_api_id
API_HASH=your_telegram_api_hash
SESSION_NAME=session   # e.g. "anon_session"
CHANNEL_USERNAME=@your_channel
DATABASE_FILE=app.db
3. Install Dependencies
bash
Copy
Edit
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
4. Initialize & Run
bash
Copy
Edit
# Create database & default admin user
python app.py       # (Will auto-run init_db and start scheduler)

# In another terminal (optional), tail logs:
tail -f flask.log

# Open in browser:
http://localhost:5001
Default Admin:
Username: admin
Password: Welcome1

🛠️ Configuration

Variable	Description	Example
API_ID	Telegram API ID	123456
API_HASH	Telegram API hash	abcdef1234567890
SESSION_NAME	Name for Telethon session file	my_session
CHANNEL_USERNAME	Telegram channel (with @)	@mychannel
DATABASE_FILE	SQLite database filename	videos.db
📂 Project Structure
arduino
Copy
Edit
├── app.py
├── requirements.txt
├── .env.example
├── templates/
│   ├── login.html
│   ├── home.html
│   ├── video.html
│   └── …
└── static/
    ├── css/
    └── default-thumbnail.jpg
👩‍💻 Usage
Login with your credentials

Browse fetched videos or jump to Shorts

Click a video to stream or add to Favorites

Use the Upload form to post new videos

Explore JSON API for integration:

swift
Copy
Edit
GET /api/videos/by_tag/tutorial
🤝 Contributing
Fork the repo

Create a feature branch (git checkout -b feat/YourFeature)

Commit & push your changes

Open a Pull Request

📝 License
Distributed under the MIT License. See LICENSE for details.