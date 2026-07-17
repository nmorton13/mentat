
import asyncio
import traceback
import time
import logging
from datetime import datetime
from mentat.chat.mentat_voice_session import MentatVoiceSession
from mentat.core.private_files import create_private_file
from mentat.voice_ui.view import VoiceView

# Configure error logging
def setup_voice_error_logging():
    log_filename = f"voice_errors_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    create_private_file(log_filename)
    logging.basicConfig(
        filename=log_filename,
        level=logging.ERROR,
        format='%(asctime)s - %(levelname)s - %(message)s',
        filemode='w'
    )
    return log_filename


async def voice_command(user_id: str = "mentat", auto_capture: bool = None):
    """Starts the voice chat session with the rich UI."""
    log_filename = setup_voice_error_logging()
    logger = logging.getLogger(__name__)

    # Load auto_capture from config if not specified
    if auto_capture is None:
        try:
            from mentat.core.config import VOICE_AUTO_CAPTURE
            auto_capture = VOICE_AUTO_CAPTURE
        except ImportError:
            auto_capture = True

    update_queue = asyncio.Queue()
    view = VoiceView()
    session = MentatVoiceSession(
        update_queue, user_id,
        auto_capture=auto_capture
    )

    try:
        logger.info(f"Starting voice session for user: {user_id} (auto_capture={auto_capture})")

        # Add initial status message to help UI startup
        await update_queue.put({"type": "status", "value": "CONNECTING"})

        # Run the UI and the voice session concurrently
        ui_task = asyncio.create_task(view.render(update_queue))
        session_task = asyncio.create_task(session.start_session())

        # Gather both tasks
        try:
            results = await asyncio.gather(ui_task, session_task, return_exceptions=True)

            # Check if any task failed
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    task_name = "UI" if i == 0 else "Voice Session"
                    logger.error(f"{task_name} task failed: {result}")
                    raise result

            logger.info("Voice session completed successfully")

            # If the session ended normally, still offer/save capture as needed.
            conversation_data = None
            if session.conversation_transcript:
                session_duration = datetime.now() - session.session_start_time
                conversation_data = {
                    "transcript": session.conversation_transcript,
                    "duration": str(session_duration).split(".")[0],
                    "start_time": session.session_start_time,
                }

            if conversation_data and not auto_capture:
                conv_length = len(conversation_data["transcript"])
                duration = conversation_data["duration"]

                print("\n" + "=" * 60)
                print("🎙️  Voice Session Summary")
                print("=" * 60)
                print(f"Conversation turns: {conv_length}")
                print(f"Session duration: {duration}")
                print("\nWould you like to save this conversation to MENTAT?")
                print("  [y] Yes - Save as voice_conversation")
                print("  [n] No - Discard conversation")
                print("=" * 60)

                try:
                    response = input("Your choice: ").strip().lower()

                    if response in ["y", "yes"]:
                        print("✓ Saving conversation...")
                        await session.capture_conversation_from_data(conversation_data)
                        print("✓ Conversation saved!")
                    elif response in ["n", "no"]:
                        print("✗ Conversation discarded")
                    else:
                        print("⊘ Invalid input - conversation not saved")
                except (EOFError, KeyboardInterrupt):
                    print("\n⊘ Prompt cancelled - conversation not saved")
            elif conversation_data and auto_capture:
                await session.capture_conversation_from_data(conversation_data)
        except asyncio.CancelledError:
            logger.info("Voice command tasks cancelled - treating as KeyboardInterrupt")
            # This happens when Ctrl+C is pressed - convert to KeyboardInterrupt
            raise KeyboardInterrupt()

    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully - end voice session and return to CLI
        print("\n\n🔴 Voice session ended by user")
        logger.info("Voice session ended by user (KeyboardInterrupt)")

        # End session and get conversation data
        conversation_data = await session.end_session()

        # Handle capture prompt synchronously AFTER async cleanup
        if conversation_data and not auto_capture:
            conv_length = len(conversation_data['transcript'])
            duration = conversation_data['duration']

            print("\n" + "="*60)
            print("🎙️  Voice Session Summary")
            print("="*60)
            print(f"Conversation turns: {conv_length}")
            print(f"Session duration: {duration}")
            print("\nWould you like to save this conversation to MENTAT?")
            print("  [y] Yes - Save as voice_conversation")
            print("  [n] No - Discard conversation")
            print("="*60)

            try:
                response = input("Your choice: ").strip().lower()

                if response in ['y', 'yes']:
                    print("✓ Saving conversation...")
                    await session.capture_conversation_from_data(conversation_data)
                    print("✓ Conversation saved!")
                elif response in ['n', 'no']:
                    print("✗ Conversation discarded")
                else:
                    print("⊘ Invalid input - conversation not saved")
            except (EOFError, KeyboardInterrupt):
                print("\n⊘ Prompt cancelled - conversation not saved")

        elif conversation_data and auto_capture:
            # Auto-capture mode: save automatically
            await session.capture_conversation_from_data(conversation_data)

        return

    except Exception as e:
        # Catch any exception that might bubble up and cause a crash
        error_msg = f"Voice command crashed: {str(e)}"
        full_traceback = traceback.format_exc()

        # Log detailed error information
        logger.error(f"VOICE COMMAND CRASH: {error_msg}")
        logger.error(f"Full traceback:\n{full_traceback}")

        # Print to console with log file reference
        print("\n--- VOICE COMMAND CRASH ---")
        print(f"Error: {error_msg}")
        print(f"Full error details saved to: {log_filename}")
        traceback.print_exc()
        print("---------------------------")

    finally:
        # Ensure cleanup happens
        session.cleanup_audio()
        logger.info("Voice session cleanup completed")
