import os
import sys
import json
import base64
import asyncio
import array
import websockets
import pyaudio
import threading
import logging
from datetime import datetime
from dotenv import load_dotenv
from contextlib import contextmanager

# Import MENTAT modules for integration
try:
    from mentat.core.ai import analyze_capture_content
    from mentat.core.database import MemoryDatabase
    MENTAT_AVAILABLE = True
except ImportError:
    MENTAT_AVAILABLE = False

load_dotenv()

# Import voice configuration from separate modules
from mentat.chat.voice_prompts import SYSTEM_MESSAGE, VOICE, SAMPLE_RATE, CHUNK
from mentat.chat.tools import get_conversation_tools
from mentat.chat.voice_tool_handlers import execute_tool as execute_voice_tool
from mentat.core.private_files import create_private_file, open_private_text

# Configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
XAI_API_KEY = os.getenv('XAI_API_KEY')
VOICE_PROVIDER = os.getenv('VOICE_PROVIDER', 'openai').lower()
VOICE_REALTIME_URL = os.getenv('VOICE_REALTIME_URL')
VOICE_MODEL = os.getenv('VOICE_MODEL')
VOICE_TRANSCRIBE_MODEL = os.getenv('VOICE_TRANSCRIBE_MODEL')
VOICE_NAME = os.getenv('VOICE_NAME')
FORMAT = pyaudio.paInt16
CHANNELS = 1

# VAD Configuration
VAD_TYPE = os.getenv('VAD_TYPE', 'semantic_vad')  # 'server_vad' or 'semantic_vad'
VAD_EAGERNESS = os.getenv('VAD_EAGERNESS', 'medium')  # 'low', 'medium', 'high', 'auto'
VAD_THRESHOLD = float(os.getenv('VAD_THRESHOLD', '0.8'))  # 0.0 to 1.0
VAD_PREFIX_PADDING_MS = int(os.getenv('VAD_PREFIX_PADDING_MS', '300'))
VAD_SILENCE_DURATION_MS = int(os.getenv('VAD_SILENCE_DURATION_MS', '800'))

@contextmanager
def suppress_alsa_warnings():
    """Suppress ALSA warnings from PyAudio initialization."""
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr = os.dup(2)
    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(old_stderr, 2)
        os.close(devnull)
        os.close(old_stderr)

class MentatVoiceSession:
    def __init__(self, update_queue, user_id: str = "mentat", auto_capture: bool = None):
        self.update_queue = update_queue
        self.user_id = user_id
        self.websocket = None
        # Initialize PyAudio with ALSA warnings suppressed
        with suppress_alsa_warnings():
            self.audio = pyaudio.PyAudio()
        self.input_stream = None
        self.output_stream = None
        self.is_recording = False
        self.is_speaking = False
        self.conversation_transcript = []
        self.session_start_time = datetime.now()

        # Connection health monitoring
        self.connection_healthy = False
        self.keepalive_task = None
        self.websocket_task = None
        self.audio_task = None

        # Auto-reconnect configuration
        self.max_reconnect_attempts = 3
        self.current_reconnect_attempt = 0
        self.reconnecting = False
        self.should_exit = False  # Flag to indicate intentional exit vs reconnectable closure

        # Voice capture configuration
        if auto_capture is None:
            try:
                from mentat.core.config import VOICE_AUTO_CAPTURE
                self.auto_capture = VOICE_AUTO_CAPTURE
            except ImportError:
                self.auto_capture = True  # Default to original behavior
        else:
            self.auto_capture = auto_capture

        # Setup error logging for voice session
        self.log_filename = f"voice_session_errors_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self.logger = self._setup_logger()
        self.voice_provider = VOICE_PROVIDER
        self.voice_api_key = self._resolve_voice_api_key()
        self.voice_url, self.voice_headers = self._resolve_connection_params()
        self.voice_name = self._resolve_voice_name()

        # Lightweight realtime diagnostics. These stay in the voice session log
        # and are intentionally rate-limited for high-frequency audio events.
        self._realtime_event_counts = {}
        self._audio_chunks_sent = 0
        self._audio_bytes_sent = 0
        self._audio_peak_rms = 0
        self._audio_log_every_chunks = 100
        
    def _setup_logger(self):
        """Setup dedicated logger for this voice session."""
        logger = logging.getLogger(f'voice_session_{self.user_id}')
        logger.setLevel(logging.INFO)

        # Pre-create privately; FileHandler preserves the inode's permissions.
        create_private_file(self.log_filename)
        handler = logging.FileHandler(self.log_filename)
        handler.setLevel(logging.INFO)

        # Create formatter
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)

        # Add handler to logger
        logger.addHandler(handler)

        return logger

    def _summarize_session_for_log(self, session: dict) -> dict:
        """Return a log-safe summary of a realtime session config."""
        summary = dict(session)
        instructions = summary.get("instructions")
        if instructions is not None:
            summary["instructions"] = f"<redacted {len(instructions)} chars>"
        tools = summary.get("tools")
        if isinstance(tools, list):
            summary["tools"] = [tool.get("name", "<unnamed>") for tool in tools if isinstance(tool, dict)]
        return summary

    def _log_realtime_event(self, response: dict):
        """Log inbound realtime event types without flooding on audio deltas."""
        event_type = response.get("type", "<missing>")
        count = self._realtime_event_counts.get(event_type, 0) + 1
        self._realtime_event_counts[event_type] = count

        high_volume = {
            "response.audio.delta",
            "response.output_audio.delta",
            "response.audio_transcript.delta",
            "response.output_audio_transcript.delta",
            "response.text.delta",
            "response.output_text.delta",
            "conversation.item.input_audio_transcription.delta",
            "conversation.item.input_audio_transcription.updated",
        }
        if event_type in high_volume and count not in {1, 10, 50} and count % 100 != 0:
            return

        log_payload = {k: v for k, v in response.items() if k not in {"delta", "audio"}}
        if isinstance(log_payload.get("session"), dict):
            log_payload["session"] = self._summarize_session_for_log(log_payload["session"])
        if event_type in high_volume:
            if "delta" in response:
                log_payload["delta"] = f"<redacted {len(str(response.get('delta', '')))} chars>"
            if "audio" in response:
                log_payload["audio"] = f"<redacted {len(str(response.get('audio', '')))} chars>"
        self.logger.info("Realtime event #%s for %s: %s", count, event_type, json.dumps(log_payload, default=str)[:2000])

    def _is_end_session_phrase(self, text: str) -> bool:
        normalized = "".join(ch for ch in text.lower() if ch.isalnum() or ch.isspace())
        normalized = " ".join(normalized.split())
        end_phrases = {
            "end session",
            "stop session",
            "stop listening",
            "im done",
            "i am done",
            "ok im done",
            "ok i am done",
            "thats it",
            "thats it im done",
            "thats it i am done",
        }
        return normalized in end_phrases

    def _resolve_voice_api_key(self):
        if self.voice_provider == "openai":
            return OPENAI_API_KEY
        if self.voice_provider == "xai":
            return XAI_API_KEY
        return None

    def _resolve_voice_name(self):
        if VOICE_NAME:
            return VOICE_NAME
        if self.voice_provider == "xai":
            return "Ara"
        return VOICE

    def _resolve_connection_params(self):
        if self.voice_provider not in {"openai", "xai"}:
            return None, None

        if VOICE_REALTIME_URL:
            url = VOICE_REALTIME_URL
        elif self.voice_provider == "openai":
            model = VOICE_MODEL or "gpt-realtime-mini"
            url = f"wss://api.openai.com/v1/realtime?model={model}"
        else:
            url = "wss://api.x.ai/v1/realtime"

        headers = {}
        if self.voice_api_key:
            headers["Authorization"] = f"Bearer {self.voice_api_key}"
        if self.voice_provider == "openai":
            headers["OpenAI-Beta"] = "realtime=v1"

        return url, headers

    def _provider_label(self):
        if self.voice_provider == "xai":
            return "xAI Realtime API"
        return "OpenAI Realtime API"

    def _get_conversation_tools(self):
        """Get tool definitions for memory access during voice conversations."""
        return get_conversation_tools()

    def _build_ambient_context(self, user_id: str) -> str:
        """Build rich context from recent activity to prime the AI with actual content."""
        if not MENTAT_AVAILABLE:
            return ""

        try:
            from datetime import timedelta

            db = MemoryDatabase()

            # Get recent memories (most recent 8 for content preview)
            recent = db.get_all_memories(user_id=user_id, limit=8)

            if not recent:
                return "\n\n## CURRENT CONTEXT\nNo recent activity - this might be a new session or returning after a break.\nBe extra curious about what they've been thinking about lately."

            # Extract themes/tags from recent memories
            themes = {}
            for mem in recent:
                # Get tags from the memory
                tags = mem.get('tags', [])
                if isinstance(tags, str):
                    # Handle case where tags might be stored as comma-separated string
                    tags = [t.strip() for t in tags.split(',') if t.strip()]

                for tag in tags[:3]:  # Top 3 tags per memory
                    themes[tag] = themes.get(tag, 0) + 1

            # Top 3 themes
            top_themes = sorted(themes.items(), key=lambda x: x[1], reverse=True)[:3]
            theme_list = [f"- **{t[0]}** ({t[1]} notes)" for t in top_themes]

            # Get most recent memory timestamp
            last_activity = "unknown"
            if recent and recent[0].get('timestamp'):
                last_activity = recent[0]['timestamp'][:10]

            # Build content previews from recent memories
            content_previews = []
            for i, mem in enumerate(recent[:5], 1):  # Top 5 most recent with content
                content_type = mem.get('command_type', 'note').upper()
                timestamp = mem.get('timestamp', '')[:10] if mem.get('timestamp') else 'unknown'

                # Truncate content to 150 chars for voice-appropriate context
                content = mem.get('content', '')
                if len(content) > 150:
                    content = content[:150] + "..."

                # Get tags if available
                tags = mem.get('tags', [])
                if isinstance(tags, str):
                    tags = [t.strip() for t in tags.split(',') if t.strip()]
                tag_str = f" (tags: {', '.join(tags[:2])})" if tags else ""

                content_previews.append(
                    f"{i}. [{content_type}] {timestamp}{tag_str}\n   {content}"
                )

            context = f"""

## CURRENT CONTEXT (Recent Activity Overview)

**Active Themes** (last 7 days):
{chr(10).join(theme_list) if theme_list else "- No clear themes yet"}

**Recent Activity Summary**:
- {len(recent)} recent captures
- Last activity: {last_activity}
- Most active area: {top_themes[0][0] if top_themes else 'varied topics'}

**Latest Content** (for context - don't recite unless asked):
{chr(10).join(content_previews)}

**How to Use This Context**:
- This gives you concrete examples of what they're working on
- Reference specific items naturally when relevant ("Oh, that relates to your work on X...")
- Don't recite this back unless they ask about recent activity
- Use this to make more informed decisions about when to search for related thoughts
- Let this inform your understanding of their current mental space

Remember: This is ambient context to help you be a thoughtful thinking partner. They're not asking about their recent activity unless they explicitly do.
"""
            return context

        except Exception as e:
            self.logger.error(f"Error building ambient context: {str(e)}", exc_info=True)
            return ""

    async def _handle_function_call(self, func_call: dict):
        """Handle function call from AI with accumulated arguments."""
        function_name = func_call.get('name')
        call_id = func_call.get('call_id')
        arguments_json = func_call.get('arguments', '{}')

        try:
            # Parse accumulated arguments
            arguments = json.loads(arguments_json) if arguments_json else {}

            self.logger.info(f"=== TOOL CALL START ===")
            self.logger.info(f"Function: {function_name}")
            self.logger.info(f"Call ID: {call_id}")
            self.logger.info(f"Arguments: {arguments}")

            # Execute the tool
            result = await self.execute_tool(function_name, arguments)

            self.logger.info(f"Tool result: {json.dumps(result, indent=2)}")
            self.logger.info(f"=== TOOL CALL END ===")

            # Return result to AI
            output_message = {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result)
                }
            }
            await self.websocket.send(json.dumps(output_message))
            self.logger.info(f"Sent function output to AI for call_id: {call_id}")

            # Trigger AI response with function result
            await self.websocket.send(json.dumps({
                "type": "response.create"
            }))
            self.logger.info("Triggered AI response generation with tool result")

        except Exception as e:
            self.logger.error(f"Function call error: {str(e)}", exc_info=True)

            # Return error to AI
            await self.websocket.send(json.dumps({
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps({
                        "error": str(e),
                        "success": False
                    })
                }
            }))

    async def execute_tool(self, function_name: str, arguments: dict) -> dict:
        """Execute memory database tools using imported tool handlers."""
        return await execute_voice_tool(
            function_name=function_name,
            arguments=arguments,
            user_id=self.user_id,
            logger=self.logger
        )

    async def start_session(self):
        if self.voice_provider not in {"openai", "xai"}:
            error_msg = f"Unsupported voice provider '{self.voice_provider}'. Use 'openai' or 'xai'."
            self.logger.error(error_msg)
            raise ValueError(error_msg)
        if not self.voice_api_key:
            if self.voice_provider == "xai":
                error_msg = 'Missing xAI API key. Please set XAI_API_KEY in .env file.'
            else:
                error_msg = 'Missing OpenAI API key. Please set OPENAI_API_KEY in .env file.'
            self.logger.error(error_msg)
            raise ValueError(error_msg)
        
        self.logger.info(f"Starting voice session for user: {self.user_id}")

        try:
            self.logger.info(f"Initiating connection to {self._provider_label()}")
            await self.update_queue.put({"type": "status", "value": "CONNECTING"})
            
            url = self.voice_url
            headers = self.voice_headers
            
            # Connect using websockets library with automatic ping/pong handling
            # OpenAI's server sends pings every 20 seconds - we need to respond or connection dies
            # We disable client-initiated pings (ping_interval=None) and rely on server pings
            # ping_timeout must be longer than server's ping interval to avoid false timeouts
            self.logger.info("Connecting with websockets library (server-driven ping/pong)")
            self.websocket = await websockets.connect(
                url,
                additional_headers=headers,
                ping_interval=None,  # Disable client pings - rely on OpenAI's server pings
                ping_timeout=30,     # Allow 30 seconds for server ping/pong cycle (OpenAI pings every 20s)
                close_timeout=10     # 10 seconds to close connection gracefully
            )
            
            self.connection_healthy = True
            self.logger.info("WebSocket connected successfully")
            await self.update_queue.put({"type": "status", "value": "INITIALIZING"})
            
            # Start WebSocket message handling and audio processing concurrently
            self.websocket_task = asyncio.create_task(self.websocket_handler())
            self.audio_task = asyncio.create_task(self.audio_handler())
            
            await self.initialize_session()
            self.setup_audio_streams()
            await self.update_queue.put({"type": "status", "value": "LISTENING"})
            
            self.logger.info("Voice session fully initialized and listening")
            
            # Start session keepalive for additional reliability
            self.keepalive_task = asyncio.create_task(self.session_keepalive())

            # Wait for all tasks to complete
            try:
                await asyncio.gather(
                    self.websocket_task,
                    self.audio_task,
                    self.keepalive_task,
                    return_exceptions=True
                )
            except asyncio.CancelledError:
                self.logger.info("Session tasks cancelled during gather")
                # Don't re-raise here, let the outer handlers deal with it

        except KeyboardInterrupt:
            self.logger.info("Voice session interrupted by user")
            await self.end_session()
        except Exception as e:
            error_msg = f"Error in voice session: {str(e)}"
            self.logger.error(f"VOICE SESSION ERROR: {error_msg}", exc_info=True)
            await self.update_queue.put({"type": "transcript", "role": "SYSTEM", "text": error_msg})
            print(f"Error in voice session: {e}")
            print(f"Full error details saved to: {self.log_filename}")
        finally:
            self.logger.info("Voice session ending - starting cleanup")
            self.cleanup_audio()

    async def websocket_handler(self):
        """Handle incoming WebSocket messages."""
        try:
            self.logger.info("WebSocket message handler started")
            async for message in self.websocket:
                if not self.is_recording or self.should_exit:
                    break
                await self.handle_message(message)
        except asyncio.CancelledError:
            self.logger.info("WebSocket handler task cancelled gracefully")
            raise  # Re-raise to allow proper cleanup
        except websockets.exceptions.ConnectionClosed as e:
            session_duration = datetime.now() - self.session_start_time
            self.logger.info(f"WebSocket connection closed after {session_duration}. Code: {e.code}, Reason: {e.reason}")

            # Check if this is a reconnectable error code
            # 1006: Abnormal closure (no close frame)
            # 1011: Server error / keepalive ping timeout
            reconnectable_codes = [1006, 1011]

            if e.code in reconnectable_codes and not self.should_exit and self.current_reconnect_attempt < self.max_reconnect_attempts:
                self.logger.info(f"Code {e.code} detected - attempting reconnect ({self.current_reconnect_attempt + 1}/{self.max_reconnect_attempts})")
                await self.attempt_reconnect()
            else:
                # Either not a reconnectable code, intentional exit, or max attempts reached
                self.is_recording = False
                self.connection_healthy = False
                if self.current_reconnect_attempt >= self.max_reconnect_attempts:
                    await self.update_queue.put({"type": "transcript", "role": "SYSTEM", "text": "Connection lost. Max reconnection attempts reached."})
                await self.update_queue.put({"type": "exit"})
        except Exception as e:
            self.logger.error(f"WebSocket handler error: {str(e)}", exc_info=True)
            self.is_recording = False
            self.connection_healthy = False
            await self.update_queue.put({"type": "transcript", "role": "SYSTEM", "text": f"Connection error: {e}"})
        finally:
            self.logger.info("WebSocket message handler ended")
    
    async def handle_message(self, message):
        """Called when a message is received from the websocket."""
        try:
            response = json.loads(message)
            self._log_realtime_event(response)
            if response.get('type') in {'response.audio.delta', 'response.output_audio.delta'} and 'delta' in response:
                if not self.is_speaking:
                    self.is_speaking = True
                    await self.update_queue.put({"type": "status", "value": "SPEAKING"})
                audio_data = base64.b64decode(response['delta'])
                if self.output_stream:
                    self.output_stream.write(audio_data)
            elif response.get('type') in {'response.audio.done', 'response.output_audio.done'}:
                # AI finished speaking - reset speaking flag
                self.is_speaking = False
                await self.update_queue.put({"type": "status", "value": "LISTENING"})
            elif response.get('type') == 'response.function_call_arguments.delta':
                # Accumulate streaming function arguments
                delta = response.get('delta', '')
                call_id = response.get('call_id', '')

                if not hasattr(self, '_function_call_arguments'):
                    self._function_call_arguments = {}

                if call_id not in self._function_call_arguments:
                    self._function_call_arguments[call_id] = {
                        'arguments': '',
                        'name': '',
                        'call_id': call_id
                    }

                # Accumulate arguments
                self._function_call_arguments[call_id]['arguments'] += delta

            elif response.get('type') == 'response.function_call_arguments.done':
                # Function call arguments complete - now execute
                call_id = response.get('call_id', '')

                if hasattr(self, '_function_call_arguments') and call_id in self._function_call_arguments:
                    # The function name arrives in the .done event, not the deltas!
                    self._function_call_arguments[call_id]['name'] = response.get('name', '')
                    self.logger.info(f"Captured function name from .done event: {response.get('name')} for call_id: {call_id}")

                    func_call = self._function_call_arguments[call_id]
                    await self._handle_function_call(func_call)
                    del self._function_call_arguments[call_id]

            elif response.get('type') in {'conversation.item.created', 'conversation.item.added'}:
                item = response.get('item', {})

                # Note: function_call items are now handled via streaming deltas above
                if item.get('role') and item.get('content'):
                    content_text = self.extract_text_content(item['content'])
                    if content_text:
                        role = item['role']
                        display_role = "SYSTEM"
                        if role == 'user':
                            display_role = "YOU"
                        elif role == 'assistant':
                            display_role = "ASSISTANT"

                        self.conversation_transcript.append({'role': role, 'content': content_text})
                        await self.update_queue.put({"type": "transcript", "role": display_role, "text": content_text})
                        
            elif response.get('type') == 'input_audio_buffer.speech_started':
                await self.update_queue.put({"type": "status", "value": "CAPTURING"})
            elif response.get('type') == 'input_audio_buffer.speech_stopped':
                await self.update_queue.put({"type": "status", "value": "THINKING"})
            elif response.get('type') in {
                'conversation.item.input_audio_transcription.delta',
                'conversation.item.input_audio_transcription.updated'
            }:
                # Handle streaming user speech transcription. OpenAI sends deltas;
                # xAI sends cumulative `updated` transcripts.
                event_type = response.get('type')
                item_id = response.get('item_id', '')
                partial_text = response.get('delta', '') if event_type.endswith('.delta') else response.get('transcript', '')

                if partial_text:
                    if not hasattr(self, '_user_transcripts'):
                        self._user_transcripts = {}

                    if event_type.endswith('.delta'):
                        self._user_transcripts[item_id] = self._user_transcripts.get(item_id, '') + partial_text
                    else:
                        self._user_transcripts[item_id] = partial_text

                    # Update UI with current partial transcript
                    await self.update_queue.put({"type": "transcript", "role": "YOU", "text": self._user_transcripts[item_id]})
                    
            elif response.get('type') == 'conversation.item.input_audio_transcription.completed':
                # Handle completed user speech transcription
                transcript = response.get('transcript', '')
                item_id = response.get('item_id', '')
                
                if transcript:
                    self.conversation_transcript.append({'role': 'user', 'content': transcript})
                    await self.update_queue.put({"type": "transcript", "role": "YOU", "text": transcript})

                    if not self.should_exit and self._is_end_session_phrase(transcript):
                        await self.update_queue.put({"type": "status", "value": "ENDING"})
                        asyncio.create_task(self.end_session())
                        return
                    
                    # Clean up streaming transcript for this item
                    if hasattr(self, '_user_transcripts') and item_id in self._user_transcripts:
                        del self._user_transcripts[item_id]
                        
            elif response.get('type') == 'response.text.delta':
                # Handle streaming assistant text responses
                delta = response.get('delta', '')
                if delta:
                    if not hasattr(self, '_current_assistant_message'):
                        self._current_assistant_message = ''
                    self._current_assistant_message += delta
                    
                    # Update UI with streaming response
                    await self.update_queue.put({"type": "transcript", "role": "ASSISTANT", "text": self._current_assistant_message})
                        
            elif response.get('type') == 'response.text.done':
                # Complete assistant text response
                if hasattr(self, '_current_assistant_message'):
                    full_text = self._current_assistant_message
                    self.conversation_transcript.append({'role': 'assistant', 'content': full_text})
                    await self.update_queue.put({"type": "transcript", "role": "ASSISTANT", "text": full_text})
                    delattr(self, '_current_assistant_message')
                    
            elif response.get('type') == 'response.output_item.added':
                # Handle when assistant starts responding
                item = response.get('item', {})
                if item.get('type') == 'message' and item.get('role') == 'assistant':
                    # Assistant started responding
                    pass
                    
            elif response.get('type') in {'response.audio_transcript.delta', 'response.output_audio_transcript.delta'}:
                # Handle streaming AI speech transcription
                delta = response.get('delta', '')
                if delta:
                    if not hasattr(self, '_current_assistant_transcript'):
                        self._current_assistant_transcript = ''
                    self._current_assistant_transcript += delta
                    
                    # Update UI with streaming transcript
                    await self.update_queue.put({"type": "transcript", "role": "ASSISTANT", "text": self._current_assistant_transcript})
                        
            elif response.get('type') in {'response.audio_transcript.done', 'response.output_audio_transcript.done'}:
                # Complete AI speech transcription
                transcript = response.get('transcript', '')
                if hasattr(self, '_current_assistant_transcript') and self._current_assistant_transcript:
                    # Use the accumulated transcript if available
                    full_transcript = self._current_assistant_transcript
                    delattr(self, '_current_assistant_transcript')
                elif transcript:
                    # Fall back to the complete transcript
                    full_transcript = transcript
                else:
                    full_transcript = None
                    
                if full_transcript:
                    self.conversation_transcript.append({'role': 'assistant', 'content': full_transcript})
                    await self.update_queue.put({"type": "transcript", "role": "ASSISTANT", "text": full_transcript})
                        
            elif response.get('type') == 'response.done':
                # Response completed - clean up any remaining state
                if hasattr(self, '_current_assistant_transcript'):
                    delattr(self, '_current_assistant_transcript')
                    
                await self.update_queue.put({"type": "status", "value": "LISTENING"})
            elif response.get('type') == 'error':
                # Handle OpenAI API error events - connection stays open
                error_info = response.get('error', {})
                error_type = error_info.get('type', 'unknown')
                error_code = error_info.get('code', 'unknown')
                error_message = error_info.get('message', 'Unknown error')
                error_event_id = error_info.get('event_id', 'unknown')
                
                error_msg = f"Realtime API Error - Type: {error_type}, Code: {error_code}, Message: {error_message}"
                self.logger.error(f"OpenAI API error event: {error_msg} (Event ID: {error_event_id})")
                
                # Send error to UI
                await self.update_queue.put({"type": "transcript", "role": "SYSTEM", "text": f"API Error: {error_message}"})
                
                # Reset to listening state after error
                await self.update_queue.put({"type": "status", "value": "LISTENING"})
        except Exception as e:
            self.logger.error(f"Error handling WebSocket message: {str(e)}", exc_info=True)
            print(f"Error handling message: {e}")

    async def session_keepalive(self):
        """Monitor connection health passively.

        The websockets library handles TCP-level ping/pong automatically via the
        ping_interval and ping_timeout parameters. OpenAI's Realtime API does not
        require additional session-level keepalive messages.

        This task simply monitors the connection without sending additional messages.
        """
        self.logger.info("Session keepalive monitor started (passive monitoring)")
        try:
            # Monitor connection health without sending messages
            while self.is_recording and self.connection_healthy:
                await asyncio.sleep(20)

                # Log connection status periodically for debugging
                if self.websocket:
                    self.logger.debug(f"Connection status check - healthy: {self.connection_healthy}, recording: {self.is_recording}")

        except asyncio.CancelledError:
            self.logger.info("Keepalive monitor task cancelled gracefully")
            raise  # Re-raise to allow proper cleanup
        finally:
            self.logger.info("Session keepalive monitor stopped")

    async def audio_handler(self):
        """Handle audio input in an async manner."""
        self.logger.info("Audio handler started")
        consecutive_errors = 0
        max_consecutive_errors = 5

        try:
            # Wait for audio streams to be set up
            while not self.input_stream and self.is_recording:
                await asyncio.sleep(0.1)

            while self.is_recording:
                try:
                    # Check if stream is still active before reading
                    if not self.input_stream or not self.input_stream.is_active():
                        self.logger.warning("Input stream is no longer active, stopping audio handler")
                        break

                    # Check if WebSocket is still connected
                    if not self.websocket or not self.connection_healthy:
                        self.logger.warning("WebSocket connection lost, stopping audio handler")
                        break

                    # Use run_in_executor to avoid blocking the event loop
                    data = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: self.input_stream.read(CHUNK, exception_on_overflow=False)
                    )

                    # Only send audio when AI is not speaking to prevent feedback/echo
                    if self.websocket and self.is_recording and not self.is_speaking:
                        audio_b64 = base64.b64encode(data).decode('utf-8')
                        audio_message = {"type": "input_audio_buffer.append", "audio": audio_b64}
                        await self.websocket.send(json.dumps(audio_message))

                        self._audio_chunks_sent += 1
                        self._audio_bytes_sent += len(data)
                        samples = array.array('h')
                        samples.frombytes(data)
                        if sys.byteorder != 'little':
                            samples.byteswap()
                        rms = int((sum(sample * sample for sample in samples) / len(samples)) ** 0.5) if samples else 0
                        self._audio_peak_rms = max(self._audio_peak_rms, rms)
                        if self._audio_chunks_sent in {1, 10} or self._audio_chunks_sent % self._audio_log_every_chunks == 0:
                            self.logger.info(
                                "Audio append sent: chunks=%s bytes=%s latest_rms=%s peak_rms=%s speaking=%s recording=%s",
                                self._audio_chunks_sent,
                                self._audio_bytes_sent,
                                rms,
                                self._audio_peak_rms,
                                self.is_speaking,
                                self.is_recording,
                            )

                    # Reset error counter on successful operation
                    consecutive_errors = 0

                    # Small delay to prevent overwhelming the CPU
                    await asyncio.sleep(0.001)

                except Exception as e:
                    consecutive_errors += 1

                    # Only log/print error if it's not a stream closed error during shutdown
                    if self.is_recording and "[Errno -9988]" not in str(e):
                        self.logger.error(f"Audio input error #{consecutive_errors}: {str(e)}")

                        # Stop if too many consecutive errors
                        if consecutive_errors >= max_consecutive_errors:
                            self.logger.error(f"Too many consecutive audio errors ({consecutive_errors}), stopping audio handler")
                            break
                        else:
                            # Brief pause before retrying
                            await asyncio.sleep(0.1)
                            continue
                    else:
                        # Stream closed error during shutdown - exit gracefully
                        break
        except asyncio.CancelledError:
            self.logger.info("Audio handler task cancelled gracefully")
            raise  # Re-raise to allow proper cleanup
        finally:
            self.logger.info("Audio handler ended")

    async def attempt_reconnect(self):
        """Attempt to reconnect after unexpected connection closure."""
        self.current_reconnect_attempt += 1
        self.reconnecting = True
        self.connection_healthy = False

        # Notify user
        await self.update_queue.put({"type": "transcript", "role": "SYSTEM", "text": f"Connection interrupted. Reconnecting... (attempt {self.current_reconnect_attempt}/{self.max_reconnect_attempts})"})
        await self.update_queue.put({"type": "status", "value": "RECONNECTING"})

        # Exponential backoff: 1s, 2s, 4s
        backoff_delay = 2 ** (self.current_reconnect_attempt - 1)
        self.logger.info(f"Waiting {backoff_delay}s before reconnect attempt")
        await asyncio.sleep(backoff_delay)

        try:
            # Close old websocket if still exists
            if self.websocket:
                try:
                    await self.websocket.close()
                except:
                    pass

            # Create conversation context summary for new session
            context_summary = self._create_conversation_context()

            # Reconnect to API
            url = self.voice_url
            headers = self.voice_headers

            self.logger.info(f"Reconnecting to {self._provider_label()} (attempt {self.current_reconnect_attempt})")
            self.websocket = await websockets.connect(
                url,
                additional_headers=headers,
                ping_interval=None,  # Server-driven pings (OpenAI pings every 20s)
                ping_timeout=30,     # Allow time for server ping/pong cycle
                close_timeout=10
            )

            self.connection_healthy = True
            self.reconnecting = False
            self.logger.info("Reconnection successful")

            # Reinitialize session with conversation context
            await self.initialize_session(context_summary)

            # Re-enable recording and ensure audio streams are ready before restarting tasks
            # This is critical: audio_handler checks 'while self.is_recording' immediately
            self.logger.info("Re-enabling recording and recreating audio streams")

            # ALWAYS recreate audio streams after reconnection
            # The streams may appear "active" but not actually capture audio after connection drop
            self.logger.info("Cleaning up existing audio streams before recreating")

            # Clean up any existing streams
            if self.input_stream:
                try:
                    if hasattr(self.input_stream, 'is_active') and self.input_stream.is_active():
                        self.input_stream.stop_stream()
                    self.input_stream.close()
                    self.logger.info("Closed existing input stream")
                except Exception as e:
                    self.logger.warning(f"Error closing input stream during reconnect: {e}")
                finally:
                    self.input_stream = None

            if self.output_stream:
                try:
                    if hasattr(self.output_stream, 'is_active') and self.output_stream.is_active():
                        self.output_stream.stop_stream()
                    self.output_stream.close()
                    self.logger.info("Closed existing output stream")
                except Exception as e:
                    self.logger.warning(f"Error closing output stream during reconnect: {e}")
                finally:
                    self.output_stream = None

            # Recreate audio streams fresh (setup_audio_streams sets is_recording=True)
            self.logger.info("Creating fresh audio streams for reconnected session")
            self.setup_audio_streams()

            # Verify streams are actually working
            self.logger.info(f"Audio streams recreated - Input active: {self.input_stream.is_active()}, Output active: {self.output_stream.is_active()}")

            # Restart tasks (audio_handler will now succeed with is_recording=True)
            self.websocket_task = asyncio.create_task(self.websocket_handler())
            self.audio_task = asyncio.create_task(self.audio_handler())
            self.keepalive_task = asyncio.create_task(self.session_keepalive())

            await self.update_queue.put({"type": "status", "value": "LISTENING"})
            await self.update_queue.put({"type": "transcript", "role": "SYSTEM", "text": "Reconnected successfully. Continuing conversation..."})

            # Wait for tasks to complete
            try:
                await asyncio.gather(
                    self.websocket_task,
                    self.audio_task,
                    self.keepalive_task,
                    return_exceptions=True
                )
            except asyncio.CancelledError:
                self.logger.info("Reconnect tasks cancelled during gather")
                # Don't re-raise here, let the outer handlers deal with it

        except Exception as e:
            self.logger.error(f"Reconnection attempt {self.current_reconnect_attempt} failed: {str(e)}", exc_info=True)

            # Try again if we haven't hit max attempts
            if self.current_reconnect_attempt < self.max_reconnect_attempts:
                await self.attempt_reconnect()
            else:
                # Max attempts reached
                self.is_recording = False
                self.connection_healthy = False
                await self.update_queue.put({"type": "transcript", "role": "SYSTEM", "text": "Unable to reconnect. Please restart the voice session."})
                await self.update_queue.put({"type": "exit"})

    def _create_conversation_context(self):
        """Create a summary of the conversation so far for context preservation."""
        if not self.conversation_transcript:
            return None

        # Get last 6 turns (last 3 exchanges) for context
        recent_turns = self.conversation_transcript[-6:] if len(self.conversation_transcript) > 6 else self.conversation_transcript

        context_lines = ["Previous conversation context:"]
        for turn in recent_turns:
            role = "User" if turn['role'] == 'user' else "Assistant"
            # Truncate long messages
            content = turn['content'][:150] + "..." if len(turn['content']) > 150 else turn['content']
            context_lines.append(f"{role}: {content}")

        return "\n".join(context_lines)

    async def initialize_session(self, context_summary=None):
        """Initialize session with optional conversation context and memory tools."""
        # Build ambient context from recent activity
        ambient_context = self._build_ambient_context(self.user_id)

        # Build instructions with context
        instructions = SYSTEM_MESSAGE + ambient_context

        # If reconnecting, add conversation context
        if context_summary:
            instructions += f"\n\n{context_summary}\n\nContinue the conversation naturally from where we left off."

        session = {
            "turn_detection": {
                "type": "server_vad",
                "threshold": VAD_THRESHOLD,
                "prefix_padding_ms": VAD_PREFIX_PADDING_MS,
                "silence_duration_ms": VAD_SILENCE_DURATION_MS
            },
            "voice": self.voice_name,
            "instructions": instructions,
            "modalities": ["text", "audio"],
            "temperature": 0.8,  # Higher temp for more natural exploration
            "tools": self._get_conversation_tools(),  # Add memory access tools
            "tool_choice": "auto"  # Let AI decide when to use tools
        }

        if self.voice_provider == "xai":
            session["audio"] = {
                "input": {
                    "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
                    # xAI emits `conversation.item.input_audio_transcription.updated`
                    # only when this nested transcription model is configured.
                    "transcription": {"model": VOICE_TRANSCRIBE_MODEL or "grok-transcribe"}
                },
                "output": {"format": {"type": "audio/pcm", "rate": SAMPLE_RATE}}
            }
        else:
            session["input_audio_format"] = "pcm16"
            session["output_audio_format"] = "pcm16"
            session["input_audio_transcription"] = {
                "model": VOICE_TRANSCRIBE_MODEL or "gpt-4o-mini-transcribe"
            }

        session_update = {
            "type": "session.update",
            "session": session
        }
        self.logger.info(
            "Sending realtime session.update to %s: %s",
            self._provider_label(),
            json.dumps(self._summarize_session_for_log(session), default=str)[:4000]
        )
        await self.websocket.send(json.dumps(session_update))
        # Don't send initial message - wait for user to speak first

    def setup_audio_streams(self):
        try:
            self.logger.info("Setting up audio streams")
            self.input_stream = self.audio.open(
                format=FORMAT, channels=CHANNELS, rate=SAMPLE_RATE, input=True, frames_per_buffer=CHUNK
            )
            self.output_stream = self.audio.open(
                format=FORMAT, channels=CHANNELS, rate=SAMPLE_RATE, output=True, frames_per_buffer=CHUNK
            )
            self.is_recording = True
            self.logger.info("Audio streams setup successfully - async handler will manage audio input")
        except Exception as e:
            self.logger.error(f"Failed to setup audio streams: {str(e)}", exc_info=True)
            raise

    def extract_text_content(self, content_list):
        for content_item in content_list:
            if content_item.get('type') in {'text', 'input_text', 'output_text'}:
                return content_item.get('text', '')
        return ''

    async def end_session(self):
        """
        End the voice session and return conversation data.

        Returns:
            dict or None: Conversation data if there was a conversation, None otherwise
        """
        # Mark as intentional exit to prevent reconnection attempts
        self.should_exit = True
        self.is_recording = False
        self.connection_healthy = False

        # Cancel all async tasks
        for task, name in [(self.keepalive_task, "keepalive"), (self.websocket_task, "websocket"), (self.audio_task, "audio")]:
            if task and not task.done():
                self.logger.info(f"Cancelling {name} task")
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Close WebSocket connection
        if self.websocket:
            try:
                await self.websocket.close()
                self.logger.info("WebSocket closed successfully")
            except Exception as e:
                self.logger.error(f"Error closing WebSocket: {str(e)}")

        # Clean up audio streams
        self.cleanup_audio()

        # Send exit signal to UI
        await self.update_queue.put({"type": "exit"})

        # Return conversation data for caller to handle
        if self.conversation_transcript:
            session_duration = datetime.now() - self.session_start_time
            return {
                'transcript': self.conversation_transcript,
                'duration': str(session_duration).split('.')[0],
                'start_time': self.session_start_time
            }
        return None

    async def capture_conversation_from_data(self, conversation_data, command_type: str = None):
        """
        Capture conversation from provided conversation data.

        Args:
            conversation_data: Dict with 'transcript', 'duration', 'start_time'
            command_type: Type to save as (defaults to VOICE_CAPTURE_TYPE from config)
        """
        # Get command type from config if not specified
        if command_type is None:
            try:
                from mentat.core.config import VOICE_CAPTURE_TYPE
                command_type = VOICE_CAPTURE_TYPE
            except ImportError:
                command_type = "voice_conversation"  # Fallback default

        # Format conversation text
        header = f"Voice Chat Session - {conversation_data['start_time'].strftime('%Y-%m-%d %H:%M:%S')}\n"
        header += f"Duration: {conversation_data['duration']}\n\n"
        transcript = ""
        for entry in conversation_data['transcript']:
            role = "You" if entry['role'] == 'user' else "AI"
            transcript += f"{role}: {entry['content']}\n\n"
        conversation_text = header + transcript

        if MENTAT_AVAILABLE:
            try:
                from mentat.core.config import get_chat_api_key, get_chat_base_url, get_current_model
                from openai import OpenAI

                # Get normal chat client for AI analysis
                chat_api_key = get_chat_api_key()
                if chat_api_key:
                    chat_client = OpenAI(
                        api_key=chat_api_key,
                        base_url=get_chat_base_url()
                    )
                    current_model = get_current_model()

                    # Analyze content to extract themes, entities, actionable items
                    analysis = analyze_capture_content(conversation_text, command_type, model=current_model, client=chat_client)
                else:
                    # No AI analysis available
                    analysis = {
                        'themes': [],
                        'entities': {},
                        'actionable_items': [],
                        'summary': '',
                        'confidence': 0.5
                    }

                # Build metadata from analysis (same pattern as /capture uses in process_content_with_ai)
                metadata = {
                    'entities': analysis.get('entities', {}),
                    'actionable_items': analysis.get('actionable_items', []),
                    'ai_summary': analysis.get('summary', ''),
                    'ai_confidence': analysis.get('confidence', 0.5),
                    'ai_analyzed': True
                }

                db = MemoryDatabase()
                memory_id = db.save_memory(
                    content=conversation_text,
                    user_id=self.user_id,
                    command_type=command_type,  # Keep as voice_conversation
                    tags=analysis.get('themes', []),
                    metadata=metadata
                )

                self.logger.info(f"Conversation saved as {command_type} (ID: {memory_id})")
            except Exception as e:
                self.logger.error(f"Failed to capture conversation: {e}")
                self.save_conversation_fallback(conversation_text)
        else:
            self.save_conversation_fallback(conversation_text)

    async def capture_conversation(self, command_type: str = None):
        """
        Capture and save conversation with AI analysis.

        Args:
            command_type: Type to save as (defaults to VOICE_CAPTURE_TYPE from config)
        """
        # Get command type from config if not specified
        if command_type is None:
            try:
                from mentat.core.config import VOICE_CAPTURE_TYPE
                command_type = VOICE_CAPTURE_TYPE
            except ImportError:
                command_type = "voice_conversation"  # Fallback default

        conversation_text = self.format_conversation_for_capture()
        if MENTAT_AVAILABLE:
            try:
                from mentat.core.config import get_chat_api_key, get_chat_base_url, get_current_model
                from openai import OpenAI

                # Get normal chat client for AI analysis
                chat_api_key = get_chat_api_key()
                if chat_api_key:
                    chat_client = OpenAI(
                        api_key=chat_api_key,
                        base_url=get_chat_base_url()
                    )
                    current_model = get_current_model()

                    # Analyze content to extract themes, entities, actionable items
                    analysis = analyze_capture_content(conversation_text, command_type, model=current_model, client=chat_client)
                else:
                    # No AI analysis available
                    analysis = {
                        'themes': [],
                        'entities': {},
                        'actionable_items': [],
                        'summary': '',
                        'confidence': 0.5
                    }

                # Build metadata from analysis (same pattern as /capture uses in process_content_with_ai)
                metadata = {
                    'entities': analysis.get('entities', {}),
                    'actionable_items': analysis.get('actionable_items', []),
                    'ai_summary': analysis.get('summary', ''),
                    'ai_confidence': analysis.get('confidence', 0.5),
                    'ai_analyzed': True
                }

                db = MemoryDatabase()
                memory_id = db.save_memory(
                    content=conversation_text,
                    user_id=self.user_id,
                    command_type=command_type,  # Keep as voice_conversation
                    tags=analysis.get('themes', []),
                    metadata=metadata
                )

                self.logger.info(f"Conversation saved as {command_type} (ID: {memory_id})")

                # Notify UI of successful capture
                await self.update_queue.put({
                    "type": "capture_success",
                    "memory_id": memory_id,
                    "command_type": command_type
                })

            except Exception as e:
                self.logger.error(f"Failed to capture conversation: {e}")
                self.save_conversation_fallback(conversation_text)
        else:
            self.save_conversation_fallback(conversation_text)

    def format_conversation_for_capture(self):
        session_duration = datetime.now() - self.session_start_time
        header = f"Voice Chat Session - {self.session_start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        header += f"Duration: {str(session_duration).split('.')[0]}\n\n"
        transcript = ""
        for entry in self.conversation_transcript:
            role = "You" if entry['role'] == 'user' else "AI"
            transcript += f"{role}: {entry['content']}\n\n"
        return header + transcript

    def save_conversation_fallback(self, conversation_text):
        filename = f"voice_chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open_private_text(filename) as f:
            f.write(conversation_text)

    def cleanup_audio(self):
        # Stop recording first to signal threads to stop
        self.logger.info("Starting audio cleanup")
        self.is_recording = False
        
        # Give threads a moment to stop naturally
        import time
        time.sleep(0.1)
        
        # Close input stream
        try:
            if self.input_stream:
                if hasattr(self.input_stream, 'is_active') and self.input_stream.is_active():
                    self.input_stream.stop_stream()
                    self.logger.info("Input stream stopped")
                self.input_stream.close()
                self.input_stream = None
                self.logger.info("Input stream closed successfully")
        except Exception as e:
            self.logger.error(f"Error cleaning up input stream: {str(e)}")
        
        # Close output stream
        try:
            if self.output_stream:
                if hasattr(self.output_stream, 'is_active') and self.output_stream.is_active():
                    self.output_stream.stop_stream()
                    self.logger.info("Output stream stopped")
                self.output_stream.close()
                self.output_stream = None
                self.logger.info("Output stream closed successfully")
        except Exception as e:
            self.logger.error(f"Error cleaning up output stream: {str(e)}")
            
        # Terminate PyAudio
        try:
            if self.audio:
                self.audio.terminate()
                self.audio = None
                self.logger.info("PyAudio terminated successfully")
        except Exception as e:
            self.logger.error(f"Error terminating PyAudio: {str(e)}")
        
        self.logger.info("Audio cleanup completed")
