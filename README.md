# Genius Sound Pro Audio Analyzer Backend

This is the stronger backend audio engine for Genius Sound Command Center.

## What it does

- Upload MP3/WAV/M4A/AIFF
- Uses FFmpeg loudnorm for LUFS / true peak estimates
- Uses Python + NumPy/SoundFile for:
  - peak
  - RMS
  - crest factor
  - clipping detection
  - stereo width/correlation
  - frequency balance
  - mud/harshness/air detection
- Returns a rating and plugin-style fix suggestions.

## Run locally

Install FFmpeg first.

Mac:
```bash
brew install ffmpeg
```

Then:

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

Analyze endpoint:

```text
POST /analyze
```

## Deploy

Use Render, Railway, or any Python server host that supports FFmpeg.

Set environment variable:

```text
ALLOWED_ORIGINS=https://ronmacraedistributions.com
```

For testing you can leave `*`.
