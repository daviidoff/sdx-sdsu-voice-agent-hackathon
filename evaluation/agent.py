"""Actual deployed agent via text-only WebSocket; never records or requests audio."""
import hashlib
import json
import subprocess
import time
import certifi
import httpx
import websocket
from evaluation.backend import ROOT


class AgentError(RuntimeError):
    pass


def fingerprint(config):
    conversation = config.get('conversation_config', {})
    prompt = conversation.get('agent', {}).get('prompt', {})
    return {'model': prompt.get('llm'), 'agent_version': config.get('version_id'),
            'config_sha256': hashlib.sha256(json.dumps(conversation, sort_keys=True).encode()).hexdigest(),
            'prompt_sha256': hashlib.sha256(str(prompt.get('prompt', '')).encode()).hexdigest(),
            'tool_ids': prompt.get('tool_ids', []), 'text_only': True}


class TextAgent:
    def __init__(self, api_key, agent_id, sandbox, timeout=35):
        self.key, self.agent_id, self.sandbox = api_key, agent_id, sandbox
        self.timeout = timeout
        self.connection = None
        self.messages = []
        self.metadata = {}
        self.seen_tools = {}
        self.response_ids = set()
        self.audio_events = 0
        self.context_ids = set()
        self.last_sync = 0

    def send(self, payload):
        self.connection.send(json.dumps(payload))

    def start(self):
        with httpx.Client(timeout=20) as client:
            response = client.get('https://api.elevenlabs.io/v1/convai/conversation/get-signed-url',
                                  params={'agent_id': self.agent_id}, headers={'xi-api-key': self.key})
            if not response.is_success:
                raise AgentError(f'Authorization HTTP {response.status_code}')
            url = response.json()['signed_url']
        self.connection = websocket.create_connection(url, timeout=20, sslopt={'ca_certs': certifi.where()})
        self.connection.settimeout(.2)
        self.send({'type': 'conversation_initiation_client_data',
                   'conversation_config_override': {'conversation': {'text_only': True}},
                   'dynamic_variables': {'call_id': self.sandbox.call_id, 'scenario_id': 'dashboard'}})
        self.receive_turn()
        self.context('Shared dashboard context; synthetic test records: '+json.dumps(self.sandbox.api('/api/dashboard/context')))

    def context(self, text):
        self.send({'type': 'contextual_update', 'text': text})

    def sync_context(self):
        """Use the production browser filter for persisted backend updates."""
        call = self.sandbox.call()
        wanted = {'assessment.updated','instruction.updated','job.completed','job.failed','steering.queued'}
        events = [e for e in call['events'] if e['type'] in wanted and e['id'] not in self.context_ids]
        if not events:
            return
        result = subprocess.run(['node',str(ROOT/'evaluation/context.mjs')],
                                input=json.dumps({'events':events,'call':call}),capture_output=True,text=True,check=True)
        for event, text in zip(events,json.loads(result.stdout),strict=True):
            self.context_ids.add(event['id'])
            if text is not None:
                self.context(text)

    def utter(self, text):
        self.sandbox.transcript('user', text)
        self.messages.append({'role': 'caller', 'text': text})
        self.send({'type': 'user_message', 'text': text})
        return self.receive_turn()

    def handle(self, message):
        kind = message.get('type')
        if kind == 'ping':
            self.send({'type': 'pong', 'event_id': message['ping_event']['event_id']})
        elif kind == 'conversation_initiation_metadata':
            self.metadata = message.get('conversation_initiation_metadata_event', {})
        elif kind == 'audio':
            self.audio_events += 1
            raise AgentError('Audio received despite text-only override; stopped, no audio saved.')
        elif kind == 'agent_response':
            data = message['agent_response_event']
            identifier = data.get('event_id', data.get('response_id'))
            if identifier is not None and identifier in self.response_ids:
                return kind
            if identifier is not None:
                self.response_ids.add(identifier)
            text = data['agent_response']
            self.messages.append({'role': 'agent', 'text': text, 'segment_id': str(identifier) if identifier is not None else None})
            self.sandbox.transcript('agent', text, str(identifier) if identifier is not None else None)
        elif kind == 'agent_response_correction':
            data = message.get('agent_response_correction_event', {})
            text = data.get('corrected_agent_response', '')
            original = data.get('original_agent_response')
            previous = next((m for m in reversed(self.messages) if m['role']=='agent' and (not original or m['text']==original)), None)
            if previous and previous.get('segment_id'):
                previous['text'] = text
                self.sandbox.transcript('agent', text, previous['segment_id'], True)
        elif kind == 'client_tool_call':
            tool = message['client_tool_call']
            tool_id = tool['tool_call_id']
            if tool_id not in self.seen_tools:
                result, error = self.sandbox.tool(tool['tool_name'], tool.get('parameters') or {})
                self.seen_tools[tool_id] = {'type': 'client_tool_result', 'tool_call_id': tool_id,
                                            'result': json.dumps(result), 'is_error': error}
            self.send(self.seen_tools[tool_id])
            self.sync_context()
        elif kind in {'error', 'client_error'}:
            raise AgentError('Provider returned an error event; no sensitive error payload saved.')
        return kind

    def receive_turn(self):
        deadline = time.monotonic()+self.timeout
        before = len(self.messages)
        last = time.monotonic()
        # A response is complete only after a final agent_response, not a tool preamble.
        response_since_tool = False
        while time.monotonic() < deadline:
            if time.monotonic()-self.last_sync > .5:
                self.sync_context()
                self.last_sync=time.monotonic()
            try:
                raw = self.connection.recv()
                if not raw:
                    raise AgentError('Connection closed before response completed')
                kind = self.handle(json.loads(raw))
                if kind == 'client_tool_call':
                    response_since_tool = False
                if kind == 'agent_response':
                    response_since_tool = True
                if kind in {'agent_response', 'client_tool_call', 'agent_response_correction', 'agent_chat_response_part'}:
                    last = time.monotonic()
            except websocket.WebSocketTimeoutException:
                pass
            if response_since_tool and time.monotonic()-last >= .8:
                return [m['text'] for m in self.messages[before:] if m['role']=='agent']
        raise AgentError('Timed out awaiting complete text response')

    def close(self):
        if self.connection:
            self.connection.close()
