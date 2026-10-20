import os

from app import create_app

app = create_app()
if app.config.get('FOCUS_ENV') == 'production':
    os.environ['FOCUS_DEBUG'] = 'false'

if __name__ == "__main__":
    port = int(os.environ.get("FOCUS_APP_PORT", "5151"))
    debug = os.environ.get("FOCUS_DEBUG", "false").strip().lower() in {"1", "true", "yes"}
    app.run(debug=debug, host="127.0.0.1", port=port)
