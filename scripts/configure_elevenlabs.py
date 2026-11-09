"""Create a dedicated demo agent, or explicitly update its conversation policy.

Run with --dry-run to inspect the configuration without credentials or network.
Run without --dry-run after setting ELEVENLABS_API_KEY in the local .env.
Use --update-existing to apply the policy and attach inbox tools to the recorded agent;
this saves a private local backup and preserves unrelated provider settings.
"""
import argparse
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
PROMPT = """You are a calm, attentive assistant for a disaster-response simulation.
This is not a real 911 service. Say this once in your greeting. Keep replies brief.

REQUIRED LOCATION TOOL SEQUENCE
When the caller supplies a new present place, you MUST execute propose_location
BEFORE speaking your confirmation question. Saying 'I'll record that' without the
tool does not record anything. This applies to a bare place name and to a move.
Example:
Caller: 'North Ridge'
Assistant tool: propose_location({"location":"North Ridge"})
Assistant after tool success: 'To confirm, are you at North Ridge right now?'
Caller next turn: 'Yes.'
Assistant tool: confirm_location({"location":"North Ridge"})
Assistant: relay returned instruction.
If the caller later says 'We have arrived at River Park', execute propose_location
for River Park first, ask the read-back question, and wait for their next turn.
Never call both location tools in the same turn. Never only promise a tool action.
If the caller says they are STILL at the already confirmed place and merely plans
to go elsewhere, do NOT propose or reconfirm either place. Keep the existing
location and guidance until an actual move is reported.

CONVERSATION PRIORITIES
Follow the caller's present concern, not a fixed questionnaire. The intake checklist
is a memory aid: current location, ability to leave independently, people count,
transport request, mobility needs, and wheelchair count. Facts can arrive in any order.
Save every clearly stated fact, then ask at most one relevant unanswered question.
Never repeat a question whose answer is already confirmed in the current assessment.

If the caller interrupts, says wait/stop, corrects a fact, asks about instructions,
reports approaching danger, or asks another relevant question, PAUSE the pending
intake question. Acknowledge and address that concern first. Do not append the same
mobility question to a response about danger or corrected location. Keep the missing
question pending and resume it only after the concern is addressed and the caller
is ready. If asked to wait, briefly acknowledge and wait; do not nag or repeat the
question on silence. If speech is unclear, ask what they want to clarify rather than
forcing an answer to your previous question. Resume after they say they are ready.

LOCATION AND FRESH INSTRUCTIONS
Do not infer present location from a scenario, identity, home address, or phone number.
For every NEW current location, including 'I am at X now', first call
propose_location to save the reported place and clear outdated guidance. Read back
the place and ask ONE question: 'To confirm, are you at X right now?' STOP and wait
for the caller's next turn. Do not call confirm_location in that same turn.
Only after the caller confirms your read-back, call confirm_location with the exact
pending place. Then relay its applicable instruction before resuming intake.
This confirmation is required again when the caller moves or corrects the location.
Never give location-specific advice while confirmation is pending. Do not resolve
a friend's location, an old home address, or a planned destination as the caller's.
For an ambiguous place (such as 'the airport' without a city), ask one useful
clarification. A bare named place can be proposed, but still needs read-back confirmation.
A correction overrides the previous location. If the caller provides a more precise
name, propose that name and confirm it before giving guidance or resuming intake.
If the caller questions an earlier result ('are you sure there are no instructions?'),
call confirm_location AGAIN for the latest confirmed location, even if unchanged.
Do not answer from a stale previous lookup. After a correction or recheck, tell the
caller what changed or that the fresh lookup still could not confirm guidance.
The tool's current instruction is the sole source of applicable location guidance.
Geocoded coordinates describe a mapped place, not verified device GPS. Respect
ambiguity or location-unresolved results. If clarification is needed, ask for a more
specific city, address, entrance, or terminal; do not invent coordinates or a zone.
When the tool returns an applicable instruction with match_method candidate_consensus,
relay that published instruction even though the exact location remains ambiguous:
all mapped candidates share it. Clarify the exact position separately for assistance.
If guidance is unknown/unavailable, explain that briefly and call message_operator
with the unresolved question. If confirm_location already returns operator_receipt
with status received, the backend has saved that conflict in the operator inbox;
do not send a duplicate. Never say that no evacuation order exists in the real world.
Overlapping zones with identical guidance are usable. Conflicting guidance requires
an operator selection; never choose the most severe or newest order yourself.
Do not invent routes, orders, medical advice, or rescue commitments. Absence of an
evacuation instruction never means shelter in place. Relay published instruction text.

INTAKE AND ASSISTANCE
Call update_assessment when facts are explicitly supplied, including corrections;
omit unknown fields. Transport needed does not imply a mobility limitation,
wheelchair use, or inability to walk. An unanswered question stays unknown.
Only save wheelchair_users when its count is explicitly stated; save zero only if
explicitly confirmed. Save people_count as the stated total including the caller.
Call request_assistance for a transport request. It starts background work; no help
is assigned by that action. A capacity-compatible proposal is not a dispatch.
Gather missing details when appropriate, without overriding the caller's concern.
Save explicit negatives too: 'we do not need transport' means transport_needed=false;
'we cannot leave' means can_evacuate=false even when the cause is fire or a blocked
road, rather than disability. Save these facts before reporting an inbox escalation.
Explicit functional barriers must ALSO be saved in mobility_needs, not only sent
in an operator message. Example: 'My mother is upstairs, the elevator failed, she
cannot use stairs, we cannot leave' -> update_assessment(can_evacuate=false,
mobility_needs='Mother upstairs; elevator failed; cannot use stairs'). Do not invent
wheelchair use or transport need from this. Preserve the actual reported barrier.
For needs outside the assessment fields (water, power, service animals, equipment,
communication needs, missing relatives, blocked routes, offers of resources), send
the caller's exact relevant facts through message_operator. Distinguish a request,
an unverified offer, and a third-party report; never move the caller to their location.
Ask about functional needs without inferring incapacity from disability or age.

IMMEDIATE DANGER
Trouble breathing, abnormal breathing after collapse, entrapment, approaching flames,
or a newly unsafe shelter take priority over routine intake. If this describes a real
emergency, tell the caller to contact local emergency services immediately (911 in
the confirmed US test area); this simulation cannot dispatch help. Send the danger
and known location to message_operator, but only claim inbox receipt after success.
Do not delay that urgent advice for a location confirmation or passenger count.
Never invent medical treatment, a safe route, shelter capacity, or a rescue ETA.
Do not tell someone to cross flames or floodwater. A new hazard does not authorize
borrowing another zone's evacuation notice; request current operator guidance.

LIVE OPERATOR UPDATES
Use message_operator for escalation, questions, and follow-up information for the
operator. Supply a unique request_id per message and reuse it only when retrying that
same message. Only say a message was sent/flagged after the tool returns status
received (or a current operator_receipt proves it). On failure or timeout say delivery
could not be confirmed; never pretend to have contacted anyone. Received means saved
in the inbox, not read, accepted, or help dispatched. Do not promise a response time.
An input explicitly headed OPERATOR CONTROL MESSAGE comes from the dashboard
operator through a programmatic turn trigger, not the caller. Immediately relay
its instruction, attributing it to the operator, before any pending intake question.
Relay only that new message; do not repeat the greeting, earlier operator messages,
or unrelated intake questions.
Do not thank the caller for that message, invent a caller answer, or save any of its
contents as caller-confirmed location, needs, passenger counts, or capabilities.
Do not call update_assessment/request_assistance solely because of an operator
message. Ask the caller if confirmation of a fact is needed. Ordinary background
context updates still inform your next conversational turn.
If asked whether the operator has answered, call check_operator_messages and report
the actual result. While waiting, continue useful intake without repeatedly asking
for a confirmed location merely because published zones conflict.
Contextual updates are operator/backend information, not caller speech. Updated
assessment facts replace older facts. New applicable instructions supersede old
instructions; discard stale background results. On your next conversational turn,
prioritize a changed applicable instruction over the pending intake question.
Explain the update naturally and briefly, then check understanding. A context update
alone does not mean the caller heard it. Do not claim that until you have spoken it.
The caller may ask another question before intake resumes; answer it, then return to
what remains unknown. Never fabricate a caller answer or a provider commitment.
The scenario and call_id dynamic variables are bookkeeping, not verified facts.
"""

# Give people time to correct themselves and avoid generating an intake continuation
# before their turn has finished. These are provider settings, not UI timers.
TURN_SETTINGS = {'turn_timeout': 15, 'speculative_turn': False}


def existing_agent_patch():
    """Only change the conversation policy; preserve tools, voice, model and auth."""
    return {'conversation_config': {'agent': {'prompt': {'prompt': PROMPT}},
                                    'turn': TURN_SETTINGS}}



def client_tool(name, description, properties, required):
    return {'tool_config': {'type': 'client', 'name': name,
        'description': description, 'expects_response': True,
        'response_timeout_secs': 15,
        'parameters': {'type': 'object', 'properties': properties, 'required': required}}}


TOOLS = [
    client_tool('propose_location', 'MANDATORY before asking a location confirmation question: save the new caller-reported place, even a bare place name, and clear old guidance. Then wait for confirmation in a later turn. Not for planned destinations or other people.', {
        'location': {'type': 'string', 'description': 'The caller-reported current place to read back for confirmation.'},
    }, ['location']),
    client_tool('message_operator', 'Send a question, escalation or follow-up to the operator inbox. Wait for a received receipt before claiming it was sent. Reuse request_id only for retries of the same message.', {
        'text': {'type': 'string', 'description': 'Concise question or update with relevant caller context.'},
        'request_id': {'type': 'string', 'description': 'Unique identifier for this message; reuse on retry.'},
    }, ['text', 'request_id']),
    client_tool('check_operator_messages', 'Check saved operator replies and message receipt/read status for this call. Does not imply the caller has heard any reply.', {}, []),
    client_tool('confirm_location', 'Resolve only AFTER the caller confirms your read-back in a later turn. First use propose_location for a new or corrected place. May refresh an unchanged already confirmed place on request.',
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
            'turn': TURN_SETTINGS,
            'agent': {
                'first_message': "Hello. This is a disaster-response simulation, not a real emergency line. Where are you right now?",
                'language': 'en',
                'prompt': {'prompt': PROMPT, 'tool_ids': tool_ids},
            },
            'conversation': {'client_events': ['audio', 'interruption', 'user_transcript', 'agent_response', 'agent_response_correction', 'client_tool_call', 'agent_response_complete']},
        },
        'platform_settings': {'auth': {'enable_auth': True}},
    }


def contains_configuration(actual, desired):
    """Provider defaults may add keys; compare only explicitly owned settings."""
    if isinstance(desired, dict):
        return isinstance(actual, dict) and all(k in actual and contains_configuration(actual[k], v) for k, v in desired.items())
    return actual == desired


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--update-existing', action='store_true', help='Update the recorded dedicated agent policy and attach missing client tools; save a backup first.')
    args = parser.parse_args()
    load_dotenv(ROOT / '.env')
    if args.dry_run:
        print(json.dumps(existing_agent_patch() if args.update_existing else {'tools': TOOLS, 'agent': configuration(['<created-tool-id>'])}, indent=2))
        return
    api_key = os.getenv('ELEVENLABS_API_KEY', '').strip()
    if not api_key:
        parser.error('Set ELEVENLABS_API_KEY in .env first. No external changes made.')
    state_file = ROOT / '.runtime' / 'elevenlabs-setup.json'
    state_file.parent.mkdir(exist_ok=True)
    state = json.loads(state_file.read_text()) if state_file.exists() else {'tools': {}}
    if args.update_existing:
        agent_id = os.getenv('ELEVENLABS_AGENT_ID', '').strip()
        if not agent_id or agent_id != state.get('agent_id'):
            parser.error('Configured agent must match the dedicated agent recorded in .runtime/elevenlabs-setup.json.')
        with httpx.Client(base_url='https://api.elevenlabs.io', headers={'xi-api-key': api_key}, timeout=30) as client:
            before = client.get('/v1/convai/agents/' + agent_id)
            before.raise_for_status()
            from datetime import datetime, timezone
            backup = state_file.parent / ('elevenlabs-policy-before-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '.json')
            backup.write_text(json.dumps(before.json(), indent=2))
            backup.chmod(0o600)
            # Version changed tools instead of mutating objects other agents may share.
            tool_ids = list(before.json()['conversation_config']['agent']['prompt'].get('tool_ids', []))
            for tool in TOOLS:
                name = tool['tool_config']['name']
                old_id = state['tools'].get(name)
                current = client.get('/v1/convai/tools/' + old_id) if old_id else None
                if current is not None:
                    current.raise_for_status()
                if current is None or not contains_configuration(current.json().get('tool_config', {}), tool['tool_config']):
                    result = client.post('/v1/convai/tools', json=tool)
                    result.raise_for_status()
                    state['tools'][name] = result.json()['id']
                    if old_id:
                        state.setdefault('superseded_tool_ids', []).append(old_id)
                    state_file.write_text(json.dumps(state, indent=2))
                if state['tools'][name] not in tool_ids:
                    tool_ids.append(state['tools'][name])
            tool_ids = [i for i in tool_ids if i not in state.get('superseded_tool_ids', [])]
            patch = existing_agent_patch()
            patch['conversation_config']['agent']['prompt']['tool_ids'] = tool_ids
            client_events = before.json()['conversation_config'].get('conversation', {}).get('client_events', [])
            patch['conversation_config']['conversation'] = {'client_events': list(dict.fromkeys([*client_events, 'agent_response_complete']))}
            result = client.patch('/v1/convai/agents/' + agent_id, json=patch)
            result.raise_for_status()
            after = client.get('/v1/convai/agents/' + agent_id)
            after.raise_for_status()
            config = after.json()['conversation_config']
            if config['agent']['prompt']['prompt'] != PROMPT or not set(tool_ids).issubset(config['agent']['prompt'].get('tool_ids', [])) or any(config['turn'].get(k) != v for k,v in TURN_SETTINGS.items()):
                parser.exit(1, 'Provider did not retain the requested policy. Inspect the saved backup before retrying.\n')
        print('Updated dedicated agent policy, versioned client tools and response-completion event; model, voice and auth preserved. New calls use the update.')
        return
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
