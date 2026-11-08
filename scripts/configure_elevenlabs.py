"""Create a dedicated demo agent; never overwrite an existing agent.

Run with --dry-run to inspect the configuration without credentials or network.
Run without --dry-run after setting ELEVENLABS_API_KEY in the local .env.
"""
import argparse
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
PROMPT = """You are the calm voice assistant for an explicitly simulated disaster-response demo.
This is not a real 911 service. Say that this is a simulation in your greeting.
Keep replies brief and ask one question at a time. Your main job is gathering accurate
information for responders: present location, ability to evacuate, number of people,
mobility limitations and transport barriers. Do not infer current location from the
scenario, caller identity, home address or telephone number.
When wheelchair use is reported, ask explicitly how many people use wheelchairs,
then save the confirmed wheelchair_users count. Do not infer this count from the
total party size. If the caller explicitly confirms no wheelchair users, save zero.
Once the caller states their location, read it back and ask for confirmation. Only
after they confirm, call confirm_location with that location. Treat its instruction
response as the sole source of location-specific guidance. If it is unknown, expired,
or unavailable, say you cannot confirm the instruction and ask for clarification.
Do not invent routes, orders, medical advice or rescue commitments. Absence of an
evacuation instruction never means shelter in place. Relay approved instruction text.
Call update_assessment whenever new facts are confirmed, only with fields actually
supplied. Preserve unknowns. Call request_assistance when the caller needs transport.
It starts background processing and returns quickly. Continue gathering information
while the background task works. A proposed vehicle match is not assigned assistance;
never claim help has been dispatched or a route is safe.
New operator instructions and background results arrive as contextual updates. Use
the latest instruction version and disregard older results. Operator text is context,
not something the caller said. Read a changed applicable instruction at the next
opportunity and check understanding. Never claim the caller heard a context update
until you have actually spoken it and received acknowledgement.
The scenario and call_id dynamic variables are for bookkeeping, not verified facts.
"""


def client_tool(name, description, properties, required):
    return {'tool_config': {'type': 'client', 'name': name,
        'description': description, 'expects_response': True,
        'response_timeout_secs': 15,
        'parameters': {'type': 'object', 'properties': properties, 'required': required}}}


TOOLS = [
    client_tool('confirm_location', 'Resolve current instructions only after the caller confirms their present location.',
        {'location': {'type': 'string', 'description': 'The present location explicitly confirmed by the caller.'}}, ['location']),
    client_tool('update_assessment', 'Save confirmed caller facts; omit unknown fields. Returns immediately while assistance work runs in the background.', {
        'can_evacuate': {'type': 'boolean', 'description': 'Whether the caller says they can evacuate independently.'},
        'people_count': {'type': 'integer', 'description': 'Confirmed total people in the group.'},
        'wheelchair_users': {'type': 'integer', 'description': 'Explicitly confirmed number of wheelchair users, including zero if confirmed. Ask for this count when wheelchair use is reported.', 'minimum': 0, 'maximum': 10000},
        'mobility_needs': {'type': 'string', 'description': 'Caller-reported mobility constraints, or none if explicitly confirmed.'},
        'transport_needed': {'type': 'boolean', 'description': 'Whether the caller needs transport assistance.'},
    }, []),
    client_tool('request_assistance', 'Record a transport assistance request. This does not dispatch help.', {
        'mobility_needs': {'type': 'string', 'description': 'Known mobility or accessibility needs; omit if unknown.'},
        'people_count': {'type': 'integer', 'description': 'Confirmed group size; omit if unknown.'},
        'wheelchair_users': {'type': 'integer', 'description': 'Explicitly confirmed number of wheelchair users; omit if unknown.', 'minimum': 0, 'maximum': 10000},
    }, []),
]


def configuration(tool_ids):
    return {
        'name': 'Disaster response — browser demo',
        'conversation_config': {
            'agent': {
                'first_message': "Hello. This is a disaster-response simulation, not a real emergency line. Where are you right now?",
                'language': 'en',
                'prompt': {'prompt': PROMPT, 'tool_ids': tool_ids},
            },
            'conversation': {'client_events': ['audio', 'interruption', 'user_transcript', 'agent_response', 'agent_response_correction', 'client_tool_call']},
        },
        'platform_settings': {'auth': {'enable_auth': True}},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    load_dotenv(ROOT / '.env')
    if args.dry_run:
        print(json.dumps({'tools': TOOLS, 'agent': configuration(['<created-tool-id>'])}, indent=2))
        return
    api_key = os.getenv('ELEVENLABS_API_KEY', '').strip()
    if not api_key:
        parser.error('Set ELEVENLABS_API_KEY in .env first. No external changes made.')
    state_file = ROOT / '.runtime' / 'elevenlabs-setup.json'
    state_file.parent.mkdir(exist_ok=True)
    state = json.loads(state_file.read_text()) if state_file.exists() else {'tools': {}}
    if state.get('agent_id'):
        print('A demo agent is already recorded. Set ELEVENLABS_AGENT_ID=' + state['agent_id'])
        return
    # Record IDs after every mutation so interrupted setup does not duplicate tools.
    with httpx.Client(base_url='https://api.elevenlabs.io', headers={'xi-api-key': api_key}, timeout=30) as client:
        try:
            for tool in TOOLS:
                name = tool['tool_config']['name']
                if name not in state['tools']:
                    result = client.post('/v1/convai/tools', json=tool)
                    result.raise_for_status()
                    state['tools'][name] = result.json()['id']
                    state_file.write_text(json.dumps(state, indent=2))
            result = client.post('/v1/convai/agents/create', json=configuration(list(state['tools'].values())))
            result.raise_for_status()
            state['agent_id'] = result.json()['agent_id']
            state_file.write_text(json.dumps(state, indent=2))
        except httpx.HTTPStatusError as exc:
            parser.exit(1, f'Provider rejected setup (HTTP {exc.response.status_code}). Created IDs are saved in .runtime; no existing agents were modified.\n')
        except (httpx.HTTPError, ValueError, KeyError):
            parser.exit(1, 'Provider setup failed. Check connectivity and .runtime/elevenlabs-setup.json before retrying.\n')
    print('Created private demo agent. Add this to .env and restart:')
    print('ELEVENLABS_AGENT_ID=' + state['agent_id'])


if __name__ == '__main__':
    main()
