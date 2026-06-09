from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import answers, feedback, questions

app = FastAPI(title="TCF AI Tutor Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(questions.router)
app.include_router(answers.router)
app.include_router(feedback.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
