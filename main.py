import os
import math
import tempfile
import subprocess
from pathlib import Path
from typing import Dict, Any

import numpy as np
import soundfile as sf
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Genius Sound Pro Audio Analyzer")

# IMPORTANT:
# Set this to your real website before production.
# Example: ["https://ronmacraedistributions.com"]
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS if ALLOWED_ORIGINS != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def run_ffmpeg_convert(input_path: str, output_path: str) -> None:
    """
    Converts any common audio format to WAV.
    Requires ffmpeg installed on the server.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-acodec",
        "pcm_f32le",
        "-ar",
        "48000",
        output_path,
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)


def get_loudnorm(input_path: str) -> Dict[str, Any]:
    """
    Uses ffmpeg loudnorm to get real integrated loudness / true peak estimates.
    """
    cmd = [
        "ffmpeg",
        "-i",
        input_path,
        "-af",
        "loudnorm=I=-14:TP=-1.0:LRA=11:print_format=json",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stderr = result.stderr

    # ffmpeg prints loudnorm JSON in stderr near the end.
    start = stderr.rfind("{")
    end = stderr.rfind("}")

    if start == -1 or end == -1:
        return {}

    import json
    try:
        return json.loads(stderr[start:end + 1])
    except Exception:
        return {}


def db(value: float) -> float:
    return 20 * math.log10(max(value, 1e-12))


def band_power(signal: np.ndarray, sr: int, low: float, high: float) -> float:
    mono = signal.mean(axis=1) if signal.ndim > 1 else signal
    n = len(mono)
    if n == 0:
        return 0.0

    # Use a capped FFT window for speed.
    max_len = min(n, sr * 60)  # first 60 seconds max
    mono = mono[:max_len]
    window = np.hanning(len(mono))
    spectrum = np.fft.rfft(mono * window)
    freqs = np.fft.rfftfreq(len(mono), 1 / sr)
    mag = np.abs(spectrum) ** 2

    mask = (freqs >= low) & (freqs < high)
    return float(np.sum(mag[mask]))


def analyze_wav(wav_path: str, original_name: str, loudnorm: Dict[str, Any]) -> Dict[str, Any]:
    audio, sr = sf.read(wav_path, always_2d=True)
    duration = len(audio) / sr
    channels = audio.shape[1]

    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(audio ** 2)))
    peak_db = db(peak)
    rms_db = db(rms)
    crest = peak_db - rms_db

    clipped_samples = int(np.sum(np.max(np.abs(audio), axis=1) >= 0.999))
    clip_percent = clipped_samples / max(len(audio), 1) * 100

    left = audio[:, 0]
    right = audio[:, 1] if channels > 1 else audio[:, 0]
    correlation = float(np.corrcoef(left, right)[0, 1]) if channels > 1 else 1.0
    mid = (left + right) / 2
    side = (left - right) / 2
    width = float(np.sqrt(np.mean(side ** 2)) / (np.sqrt(np.mean(mid ** 2)) + 1e-12) * 100)

    bands = {
        "sub_20_60": band_power(audio, sr, 20, 60),
        "bass_60_160": band_power(audio, sr, 60, 160),
        "mud_160_450": band_power(audio, sr, 160, 450),
        "mid_450_2500": band_power(audio, sr, 450, 2500),
        "presence_2500_4000": band_power(audio, sr, 2500, 4000),
        "harsh_4000_7000": band_power(audio, sr, 4000, 7000),
        "air_7000_16000": band_power(audio, sr, 7000, 16000),
    }

    total_power = sum(bands.values()) or 1.0
    band_pct = {k: (v / total_power) * 100 for k, v in bands.items()}

    integrated_lufs = safe_float(loudnorm.get("input_i"))
    true_peak = safe_float(loudnorm.get("input_tp"))
    lra = safe_float(loudnorm.get("input_lra"))

    rating = 8.5
    issues = []
    fixes = []

    if true_peak is not None and true_peak > -0.5:
        rating -= 0.7
        issues.append("True peak is too close to 0 dBTP.")
        fixes.append("Limiter: set ceiling to -1.0 dBTP and reduce input/threshold pressure.")
    elif peak_db > -0.3:
        rating -= 0.5
        issues.append("Sample peak is too close to 0 dBFS.")
        fixes.append("Lower master input 1 dB or use a true-peak limiter ceiling around -1.0 dBTP.")

    if clip_percent > 0.02:
        rating -= 0.7
        issues.append("Possible clipped samples detected.")
        fixes.append("Back off clipper/limiter input 1–2 dB; check if distortion is intentional.")

    if integrated_lufs is not None:
        if integrated_lufs > -7:
            rating -= 0.5
            issues.append("Master is extremely loud; punch may be reduced.")
            fixes.append("Ease limiter threshold and preserve kick/snare transient movement.")
        if integrated_lufs < -14:
            rating -= 0.4
            issues.append("Master may be quiet for modern dancehall release level.")
            fixes.append("Increase limiter gain carefully while keeping true peak below -1.0 dBTP.")

    if crest < 7:
        rating -= 0.7
        issues.append("Crest factor is low; the mix may feel flat or over-limited.")
        fixes.append("Reduce bus compression/limiting; use slower attack on bus compressor.")
    elif crest > 15:
        rating -= 0.3
        issues.append("Crest factor is high; level may feel inconsistent.")
        fixes.append("Use gentle bus compression 1.5:1–2:1 with slow attack and medium release.")

    if band_pct["mud_160_450"] > 23:
        rating -= 0.6
        issues.append("Low-mid mud is elevated around 160–450 Hz.")
        fixes.append("Pro-Q4: dynamic cut around 250–350 Hz, -1.5 to -3 dB, Q 1.0–1.5.")

    if band_pct["harsh_4000_7000"] > 18:
        rating -= 0.5
        issues.append("Harshness zone is elevated around 4–7 kHz.")
        fixes.append("Soothe2/Pro-Q4: dynamic tame 4–6 kHz, 1–3 dB reduction.")

    if band_pct["air_7000_16000"] < 4:
        rating -= 0.25
        issues.append("Top-end air may be dark.")
        fixes.append("Pro-Q4: gentle high shelf at 12–16 kHz, +0.5 to +1.5 dB if clean.")

    if width < 12 and channels > 1:
        rating -= 0.3
        issues.append("Stereo width is narrow.")
        fixes.append("Widen instruments/effects above 150 Hz; keep bass mono.")
    elif width > 80:
        rating -= 0.4
        issues.append("Stereo width may be excessive; check mono compatibility.")
        fixes.append("Reduce stereo widening and keep lead/vocal/kick/snare centered.")

    rating = max(1.0, min(10.0, rating))

    report = build_report(
        original_name=original_name,
        duration=duration,
        sr=sr,
        channels=channels,
        peak_db=peak_db,
        rms_db=rms_db,
        crest=crest,
        clip_percent=clip_percent,
        correlation=correlation,
        width=width,
        integrated_lufs=integrated_lufs,
        true_peak=true_peak,
        lra=lra,
        band_pct=band_pct,
        rating=rating,
        issues=issues,
        fixes=fixes,
    )

    return {
        "file": original_name,
        "rating": round(rating, 1),
        "metrics": {
            "duration_sec": round(duration, 2),
            "sample_rate": sr,
            "channels": channels,
            "peak_dbfs": round(peak_db, 2),
            "rms_dbfs": round(rms_db, 2),
            "crest_factor_db": round(crest, 2),
            "clip_percent": round(clip_percent, 5),
            "stereo_correlation": round(correlation, 3),
            "stereo_width_percent": round(width, 2),
            "integrated_lufs": integrated_lufs,
            "true_peak_dbtp": true_peak,
            "loudness_range_lra": lra,
        },
        "bands_percent": {k: round(v, 2) for k, v in band_pct.items()},
        "issues": issues,
        "fixes": fixes,
        "report": report,
    }


def safe_float(value):
    try:
        if value is None:
            return None
        return round(float(value), 2)
    except Exception:
        return None


def build_report(**kwargs) -> str:
    band_pct = kwargs["band_pct"]
    issues = kwargs["issues"]
    fixes = kwargs["fixes"]

    return f"""GENIUS SOUND PRO AUDIO ANALYSIS

File: {kwargs["original_name"]}
Duration: {kwargs["duration"]:.1f} sec
Sample Rate: {kwargs["sr"]} Hz
Channels: {kwargs["channels"]}

RATING: {kwargs["rating"]:.1f}/10

MASTERING METRICS:
Integrated LUFS: {kwargs["integrated_lufs"]}
True Peak: {kwargs["true_peak"]} dBTP
Loudness Range: {kwargs["lra"]}
Sample Peak: {kwargs["peak_db"]:.2f} dBFS
RMS: {kwargs["rms_db"]:.2f} dBFS
Crest Factor / Punch: {kwargs["crest"]:.2f} dB
Possible Clipping: {kwargs["clip_percent"]:.5f}%
Stereo Correlation: {kwargs["correlation"]:.3f}
Stereo Width Estimate: {kwargs["width"]:.1f}%

FREQUENCY BALANCE:
Sub 20–60 Hz: {band_pct["sub_20_60"]:.1f}%
Bass 60–160 Hz: {band_pct["bass_60_160"]:.1f}%
Mud 160–450 Hz: {band_pct["mud_160_450"]:.1f}%
Mid 450–2500 Hz: {band_pct["mid_450_2500"]:.1f}%
Presence 2500–4000 Hz: {band_pct["presence_2500_4000"]:.1f}%
Harsh 4000–7000 Hz: {band_pct["harsh_4000_7000"]:.1f}%
Air 7000–16000 Hz: {band_pct["air_7000_16000"]:.1f}%

ISSUES FOUND:
{chr(10).join("- " + x for x in issues) if issues else "- No major technical red flags detected."}

PLUGIN-STYLE FIX SUGGESTIONS:
{chr(10).join("- " + x for x in fixes) if fixes else "- Keep current direction; make only taste-based moves."}

DANCEHALL MASTER NOTES:
- Keep kick/bass centered and controlled below 120 Hz.
- Keep vocal or lead presence strong without letting 3–6 kHz get painful.
- If it feels flat, reduce limiter pressure before boosting EQ.
- Check phone, car, headphones, and mono compatibility before release.
"""


@app.get("/")
def root():
    return {"status": "Genius Sound Pro Audio Analyzer API is running"}


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")

    suffix = Path(file.filename).suffix or ".audio"

    with tempfile.TemporaryDirectory() as tmp:
        input_path = str(Path(tmp) / f"input{suffix}")
        wav_path = str(Path(tmp) / "converted.wav")

        with open(input_path, "wb") as f:
            f.write(await file.read())

        try:
            loudnorm = get_loudnorm(input_path)
            run_ffmpeg_convert(input_path, wav_path)
            return analyze_wav(wav_path, file.filename, loudnorm)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
