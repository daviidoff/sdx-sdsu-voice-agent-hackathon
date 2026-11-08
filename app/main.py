"""Run with: python -m uvicorn app.main:app --host 127.0.0.1 --port 8000."""
from pathlib import Path
from urllib.parse import urlparse
import os

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')

from app.backend import create_app  # noqa: E402
from app.voice import router as voice_router  # noqa: E402

app = create_app()
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', '[::1]', 'testserver'])


@app.middleware('http')
async def local_origin_boundary(request: Request, call_next):
    # This is an intentionally local, unauthenticated demo, not a public service.
    origin = request.headers.get('origin')
    if origin and (request.method not in {'GET', 'HEAD', 'OPTIONS'} or request.url.path == '/api/voice/session'):
        permitted = {'http://localhost:8000', 'http://127.0.0.1:8000',
                     'http://localhost:5173', 'http://127.0.0.1:5173',
                     'http://localhost:5174', 'http://127.0.0.1:5174'}
        permitted.update(s.strip() for s in os.getenv('CORS_ORIGINS', '').split(',') if s.strip())
        # Permit the local listening port when PORT is customized.
        if origin not in permitted and not (urlparse(origin).netloc == request.headers.get('host') and urlparse(origin).scheme == request.url.scheme):
            return JSONResponse({'detail': 'This demo accepts requests from its local interface only.'}, status_code=403)
    return await call_next(request)


async def active_voice_call(call_id: str):
    call = app.state.store.get_call(call_id, writable=True)
    if call['mode'] != 'elevenlabs':
        raise HTTPException(409, 'Start an ElevenLabs voice session first.')


app.include_router(voice_router, dependencies=[Depends(active_voice_call)])


@app.get('/api/health')
async def health():
    return {'status': 'ok', 'simulation': True}


if (ROOT / 'frontend' / 'dist' / 'index.html').exists():
    app.mount('/dashboard', StaticFiles(directory=ROOT / 'frontend' / 'dist', html=True), name='dashboard')


if (ROOT / 'web' / 'dist' / 'index.html').exists():
    app.mount('/', StaticFiles(directory=ROOT / 'web' / 'dist', html=True), name='web')
else:
    @app.get('/')
    async def build_required():
        return JSONResponse({'detail': 'Build the web interface: cd web && npm ci && npm run build'}, status_code=503)
