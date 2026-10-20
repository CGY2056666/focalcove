"""Gunicorn application entrypoint."""
from app import create_app


app = create_app()
