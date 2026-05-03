from fastapi import FastAPI, UploadFile, File
import tempfile
import os

app = FastAPI()

@app.get("/")
def root():
    return {"status": "Audio Analyzer Running"}

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    temp = tempfile.NamedTemporaryFile(delete=False)
    temp.write(await file.read())
    temp.close()

    size = os.path.getsize(temp.name)

    rating = 8.0
    feedback = []

    if size < 500000:
        rating -= 1
        feedback.append("File seems low quality or too short")

    feedback.append("Check low mids (200–400Hz)")
    feedback.append("Check high mids (3k–6k) for harshness")

    return {
        "rating": rating,
        "feedback": feedback
    }
