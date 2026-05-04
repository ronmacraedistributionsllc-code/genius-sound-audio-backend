# Genius Sound Video Backend

Creates 1080p or 4K MP4 videos from an uploaded audio file and cover art image.

## Endpoints

GET /
Returns status.

POST /render-video
Form fields:
- audio: MP3/WAV/M4A file
- image: JPG/PNG cover art
- resolution: 1080p or 4k
- artist: optional
- title: optional

## Render settings

Build Command:
pip install -r requirements.txt

Start Command:
uvicorn main:app --host 0.0.0.0 --port 10000
