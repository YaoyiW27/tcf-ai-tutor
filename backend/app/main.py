from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import questions

app = FastAPI(title="TCF AI Tutor Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(questions.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
