from fastapi import FastAPI

app = FastAPI(title="TCF AI Tutor Backend")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
