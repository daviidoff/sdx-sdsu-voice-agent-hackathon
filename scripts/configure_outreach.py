"""Provision the dedicated browser mock outreach agent; preserve existing inbound configuration."""
import json
import os
from pathlib import Path
import sys
import httpx
from dotenv import load_dotenv
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.outreach_agent import STATE, TOOL, CONTEXT_TOOL, configuration


def main():
    load_dotenv(ROOT / '.env')
    if '--dry-run' in sys.argv:
        print(json.dumps(configuration('<tool-id>', '<context-tool-id>'), indent=2)); return
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    STATE.parent.mkdir(exist_ok=True)
    def save(): STATE.write_text(json.dumps(state, indent=2))
    with httpx.Client(base_url='https://api.elevenlabs.io', headers={'xi-api-key': os.environ['ELEVENLABS_API_KEY']}, timeout=30) as client:
        if not state.get('tool_id'):
            result = client.post('/v1/convai/tools', json=TOOL); result.raise_for_status()
            state['tool_id'] = result.json()['id']; save()
        if not state.get('context_tool_id'):
            result = client.post('/v1/convai/tools', json=CONTEXT_TOOL); result.raise_for_status()
            state['context_tool_id'] = result.json()['id']; save()
        if not state.get('agent_id'):
            result = client.post('/v1/convai/agents/create', json=configuration(state['tool_id'], state['context_tool_id'])); result.raise_for_status()
            state['agent_id'] = result.json()['agent_id']; save()
        elif '--update-existing' in sys.argv:
            result = client.get('/v1/convai/agents/' + state['agent_id']); result.raise_for_status()
            before = result.json()
            from datetime import datetime, timezone
            backup = STATE.with_name('outreach-before-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '.json')
            backup.write_text(json.dumps(before, indent=2))
            desired = configuration(state['tool_id'], state['context_tool_id'])['conversation_config']['agent']
            prompt = before['conversation_config']['agent']['prompt']
            desired['prompt'] = {**prompt, **desired['prompt'], 'tool_ids': list(dict.fromkeys([
                *prompt.get('tool_ids', []), state['tool_id'], state['context_tool_id']]))}
            desired['prompt'].pop('tools', None)
            result = client.patch('/v1/convai/agents/' + state['agent_id'], json={'conversation_config': {'agent': desired}})
            result.raise_for_status()
        result = client.get('/v1/convai/agents/' + state['agent_id']); result.raise_for_status()
        assert state['tool_id'] in result.json()['conversation_config']['agent']['prompt']['tool_ids']
        if '--update-existing' in sys.argv:
            assert state['context_tool_id'] in result.json()['conversation_config']['agent']['prompt']['tool_ids']
    print('Dedicated mock outreach agent configured and tool attachment verified.')


if __name__ == '__main__': main()
