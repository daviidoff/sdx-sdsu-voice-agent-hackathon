"""Server-side credential boundary for browser ElevenLabs sessions."""
import os

import httpx
from fastapi import APIRouter, HTTPException, Response

router = APIRouter()


@router.get('/api/voice/session')
async def voice_session(response: Response, call_id: str):
    # main.py supplies the active-call check as a route dependency.
    agent_id = os.getenv('ELEVENLABS_AGENT_ID', '').strip()
    api_key = os.getenv('ELEVENLABS_API_KEY', '').strip()
    if not agent_id:
        raise HTTPException(503, 'ElevenLabs is not configured. Use Demo walkthrough or configure .env.')
    response.headers['Cache-Control'] = 'no-store'
    if not api_key:
        # Public agents can connect by ID; no credentials are sent to the browser.
        return {'agent_id': agent_id}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            result = await client.get(
                'https://api.elevenlabs.io/v1/convai/conversation/get-signed-url',
                params={'agent_id': agent_id}, headers={'xi-api-key': api_key},
            )
            result.raise_for_status()
            signed_url = result.json()['signed_url']
    except (httpx.HTTPError, ValueError, KeyError):
        raise HTTPException(502, 'Could not authorize ElevenLabs. Check the server API key and agent access.') from None
    return {'signed_url': signed_url}
