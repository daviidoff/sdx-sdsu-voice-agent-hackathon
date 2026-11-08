"""Provision the dedicated browser mock outreach agent; preserve existing inbound configuration."""
import json
import os
from pathlib import Path
import sys
import httpx
from dotenv import load_dotenv
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.outreach_agent import STATE, TOOL, configuration


def main():
    load_dotenv(ROOT / '.env')
    if '--dry-run' in sys.argv:
        print(json.dumps(configuration('<tool-id>'), indent=2)); return
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    STATE.parent.mkdir(exist_ok=True)
    def save(): STATE.write_text(json.dumps(state, indent=2))
    with httpx.Client(base_url='https://api.elevenlabs.io', headers={'xi-api-key': os.environ['ELEVENLABS_API_KEY']}, timeout=30) as client:
        if not state.get('tool_id'):
            result = client.post('/v1/convai/tools', json=TOOL); result.raise_for_status()
            state['tool_id'] = result.json()['id']; save()
        if not state.get('agent_id'):
            result = client.post('/v1/convai/agents/create', json=configuration(state['tool_id'])); result.raise_for_status()
            state['agent_id'] = result.json()['agent_id']; save()
        result = client.get('/v1/convai/agents/' + state['agent_id']); result.raise_for_status()
        assert state['tool_id'] in result.json()['conversation_config']['agent']['prompt']['tool_ids']
    print('Dedicated mock outreach agent configured and tool attachment verified.')


if __name__ == '__main__': main()
