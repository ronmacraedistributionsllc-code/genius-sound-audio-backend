from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import subprocess
import uuid
import os
from pathlib import Path

try:
    import imageio_ffmpeg
except Exception:
    imageio_ffmpeg = None

app = FastAPI(title="Genius Sound Video Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"status": "Video backend running", "supports": ["1080p", "4k"]}

def ffmpeg_bin():
    if imageio_ffmpeg:
        return imageio_ffmpeg.get_ffmpeg_exe()
    return "ffmpeg"

def safe_ext(filename, default):
    ext = Path(filename or "").suffix.lower()
    if not ext:
        return default
    return ext

@app.post("/render-video")
async def render_video(
    audio: UploadFile = File(...),
    image: UploadFile = File(...),
    resolution: str = Form("1080p"),
    artist: str = Form("genius-sound"),
    title: str = Form("video")
):
    uid = str(uuid.uuid4())
    audio_ext = safe_ext(audio.filename, ".mp3")
    image_ext = safe_ext(image.filename, ".png")

    audio_path = f"/tmp/{uid}_audio{audio_ext}"
    image_path = f"/tmp/{uid}_image{image_ext}"
    output_path = f"/tmp/{uid}_{resolution}.mp4"

    with open(audio_path, "wb") as f:
        f.write(await audio.read())

    with open(image_path, "wb") as f:
        f.write(await image.read())

    res = (resolution or "1080p").lower().strip()
    if res in ["4k", "2160p", "uhd"]:
        width, height = 3840, 2160
        crf = "24"
        preset = "veryfast"
    else:
        width, height = 1920, 1080
        crf = "23"
        preset = "veryfast"
        res = "1080p"

    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        "format=yuv420p"
    )

    cmd = [
        ffmpeg_bin(),
        "-y",
        "-loop", "1",
        "-framerate", "30",
        "-i", image_path,
        "-i", audio_path,
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", preset,
        "-tune", "stillimage",
        "-crf", crf,
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        output_path
    ]

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if result.returncode != 0 or not os.path.exists(output_path):
        return JSONResponse(
            status_code=500,
            content={
                "error": "FFmpeg render failed",
                "details": result.stderr[-4000:]
            }
        )

    clean_artist = "".join(c if c.isalnum() else "-" for c in (artist or "genius-sound")).strip("-")
    clean_title = "".join(c if c.isalnum() else "-" for c in (title or "video")).strip("-")
    filename = f"{clean_artist}-{clean_title}-{res}.mp4"

    return FileResponse(
        output_path,
        media_type="video/mp4",
        filename=filename
    )
