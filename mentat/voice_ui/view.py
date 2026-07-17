import asyncio
import traceback
from datetime import datetime
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

class VoiceView:
    """Renders the voice chat UI using rich."""

    def __init__(self):
        self.console = Console()
        self.layout = self.make_layout()
        self.transcript_content = Text()
        self.status = "LISTENING"
        self.session_start_time = datetime.now()
        self.is_running = True
        self.messages = []  # Store individual messages for better management

    def make_layout(self) -> Layout:
        """Defines the UI layout."""
        layout = Layout(name="root")
        layout.split(
            Layout(name="transcript", ratio=4),
            Layout(name="status", size=3),
        )
        return layout

    def update_transcript(self, role: str, text: str):
        """Adds or updates a message in the transcript panel."""
        if role == "YOU":
            color = "cyan"
            icon = "👤"
        elif role == "ASSISTANT":
            color = "magenta"
            icon = "🤖"
        else:  # SYSTEM
            color = "yellow"
            icon = "⚙️"
        
        # Check if this is an update to the last message of the same role
        if self.messages and self.messages[-1]['role'] == role:
            # Update the existing message (for streaming)
            self.messages[-1]['text'] = text
        else:
            # Add a new message
            self.messages.append({'role': role, 'text': text, 'icon': icon, 'color': color})
        
        # Rebuild the transcript content
        self._rebuild_transcript()

    def _rebuild_transcript(self):
        """Rebuilds the transcript content showing only the most recent exchange."""
        # Show only the last 2-4 messages (current exchange) for better readability
        # Full transcript is still saved in MentatVoiceSession.conversation_transcript
        max_recent = 4
        recent_messages = self.messages[-max_recent:] if len(self.messages) > max_recent else self.messages

        self.transcript_content = Text()

        # Add counter showing total conversation length
        total_messages = len(self.messages)
        if total_messages > max_recent:
            self.transcript_content.append(
                f"[Showing last {len(recent_messages)} of {total_messages} messages]\n\n",
                style="dim italic"
            )

        for message in recent_messages:
            if len(self.transcript_content) > 0 and not self.transcript_content.plain.endswith("\n\n"):
                self.transcript_content.append("\n")
            self.transcript_content.append(f"{message['icon']} {message['role']}: ", style=f"bold {message['color']}")
            self.transcript_content.append(message['text'] + "\n")

    def update_status_bar(self) -> Panel:
        """Creates the status bar panel based on the current state."""
        timer = datetime.now() - self.session_start_time
        timer_str = f"{int(timer.total_seconds() // 60):02}:{int(timer.total_seconds() % 60):02}"

        if self.status == "CONNECTING":
            status_text = "[🔌 CONNECTING...]"
        elif self.status == "INITIALIZING":
            status_text = "[⚙️ INITIALIZING...]"
        elif self.status == "LISTENING":
            status_text = "[👂 LISTENING]"
        elif self.status == "CAPTURING":
            status_text = "[🗣️ CAPTURING]"
        elif self.status == "THINKING":
            status_text = "[🧠 THINKING...]"
        elif self.status == "SPEAKING":
            status_text = "[💬 SPEAKING]"
        elif self.status == "ENDING":
            status_text = "[💾 CAPTURING...] Session ended. Analyzing transcript..."
        else:
            status_text = ""

        return Panel(
            f"{status_text} [🔴 REC] [ {timer_str} ] Press Ctrl+C to End",
            style="white on blue",
        )

    async def render(self, update_queue: asyncio.Queue):
        """Renders the UI and updates it based on messages from the queue."""
        self.layout["transcript"].update(Panel(self.transcript_content, title="Live Conversation"))
        self.layout["status"].update(self.update_status_bar())

        with Live(self.layout, screen=True, redirect_stderr=False) as live:
            while self.is_running:
                try:
                    # Check for updates from the voice session with timeout
                    try:
                        update = await asyncio.wait_for(update_queue.get(), timeout=0.1)
                        if update["type"] == "status":
                            self.status = update["value"]
                        elif update["type"] == "transcript":
                            self.update_transcript(update["role"], update["text"])
                        elif update["type"] == "exit":
                            self.is_running = False
                            self.status = "ENDING"
                    except asyncio.TimeoutError:
                        # No update available, continue with UI refresh
                        pass

                    # Refresh UI
                    self.layout["transcript"].update(Panel(self.transcript_content, title="Live Conversation", border_style="green"))
                    self.layout["status"].update(self.update_status_bar())
                    live.refresh()
                except KeyboardInterrupt:
                    # Let the caller handle Ctrl+C so it can prompt for save.
                    self.is_running = False
                    self.status = "ENDING"
                    raise asyncio.CancelledError()
                except Exception as e:
                    self.is_running = False
                    error_message = f"Error in UI rendering: {e}"
                    traceback_info = traceback.format_exc()
                    print(f'''
--- UI RENDER CRASH ---
{error_message}
{traceback_info}
-----------------------''')
                    # Display error in the UI itself if possible
                    self.transcript_content.append(f"\n[bold red]UI ERROR: {e}[/bold red]")
                    self.layout["transcript"].update(Panel(self.transcript_content, title="[bold red]CRASH[/bold red]"))
                    live.refresh()
                    await asyncio.sleep(5) # Keep the error on screen
