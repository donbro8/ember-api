from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ember_shared import setup_logging, settings
from .routes import health, chat

setup_logging(level=settings.LOG_LEVEL, json_format=settings.LOG_JSON_FORMAT)

app = FastAPI(title="Ember Bio API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(chat.router)
