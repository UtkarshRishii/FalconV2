# --- START OF FILE Falcon.py ---

import eel
import os
import sys
import threading
import time
import json
from datetime import datetime

# Add current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Import backend modules
try:
    from Backend.Brain import FALCONAssistant
    # Import your custom TTS function
    from Backend.TTS import SpeakFalcon
except ImportError as e:
    print(f"Critical Import Error: {e}. Ensure Backend/Brain.py and Backend/TTS.py exist.")
    sys.exit(1)
except Exception as ex:
    print(f"An unexpected error occurred during initial imports: {ex}")
    sys.exit(1)


# --- TTS Manager for Stoppable, Threaded Speech using your SpeakFalcon ---
class TTSManager:
    """
    Manages TTS playback in a non-blocking thread, allowing for interruption.
    This class is a wrapper around your existing SpeakFalcon function.
    """
    def __init__(self):
        self.tts_thread = None
        self.stop_event = threading.Event()
        self.is_speaking = False
        self.lock = threading.Lock()

    def speak(self, text_to_speak):
        """
        Speaks the given text in a non-blocking thread.
        If speech is already playing, it stops it first.
        """
        with self.lock:
            if self.tts_thread and self.tts_thread.is_alive():
                self.stop()
                self.tts_thread.join(timeout=2.0)  # Wait for the previous thread to terminate

            self.stop_event.clear()  # Reset the stop signal for the new speech task
            
            self.tts_thread = threading.Thread(
                target=self._run_tts_in_thread,
                args=(text_to_speak,),
                daemon=True
            )
            self.tts_thread.start()

    def _run_tts_in_thread(self, text):
        """
        The actual worker function that runs in a separate thread.
        """
        try:
            with self.lock:
                self.is_speaking = True
            
            # Notify frontend that speech has started
            try:
                eel.notify_tts_status('speaking')
            except Exception as e:
                print(f"Could not notify frontend of TTS start: {e}")
            
            print(f"TTS Playback initiated: {text[:50]}...")
            
            # The callback function checks our stop_event.
            # If stop() is called, the event is set, the callback returns False,
            # and your SpeakFalcon's while loop breaks.
            def stoppable_callback():
                return not self.stop_event.is_set()
            
            # Call your function with the stoppable callback
            # Add error handling for SpeakFalcon
            try:
                # Check if SpeakFalcon accepts callback_func parameter
                # If not, you may need to modify your TTS.py to support interruption
                SpeakFalcon(text, callback_func=stoppable_callback)
            except TypeError:
                # Fallback if SpeakFalcon doesn't accept callback_func
                print("Warning: SpeakFalcon doesn't support callback. TTS won't be interruptible.")
                SpeakFalcon(text)
            except Exception as tts_error:
                print(f"Error in SpeakFalcon: {tts_error}")

        except Exception as e:
            print(f"Error during TTS playback in thread: {e}")
        finally:
            # This block runs whether the speech finished naturally or was stopped.
            with self.lock:
                self.is_speaking = False
            
            print("TTS playback finished or was stopped.")
            self.stop_event.clear()  # Reset the event for the next run
            
            # Notify frontend that speech is no longer active
            try:
                eel.notify_tts_status('idle')
            except Exception as e:
                print(f"Could not notify frontend of TTS end: {e}")

    def stop(self):
        """
        Signals the currently running TTS thread to stop playback.
        This is used for the "barge-in" feature.
        """
        print("TTS stop request received.")
        self.stop_event.set()

    def is_currently_speaking(self):
        """Check if TTS is currently active"""
        with self.lock:
            return self.is_speaking

# --- End of TTS Manager ---


# Initialize the TTS Manager and FALCON Assistant
tts_manager = TTSManager()
assistant = None

def initialize_assistant():
    """Initialize assistant with proper error handling"""
    global assistant
    try:
        print("Initializing FALCON Assistant...")
        assistant = FALCONAssistant()
        print("FALCON Assistant initialized successfully.")
        return True
    except ValueError as ve:
        print(f"Configuration Error: {ve}")
        return False
    except Exception as e:
        print(f"Error initializing FALCONAssistant: {e}")
        return False

# Initialize assistant
assistant_ready = initialize_assistant()
if not assistant_ready:
    print("Failed to initialize FALCON Assistant. Will attempt to continue with limited functionality...")

# Verify web folder exists
web_folder = os.path.join(current_dir, 'web')
if not os.path.isdir(web_folder):
    print(f"Error: The 'web' folder ('{web_folder}') was not found.")
    print("Creating web folder and copying HTML file...")
    os.makedirs(web_folder, exist_ok=True)
    
    # If the HTML is in the current directory, copy it to web folder
    html_file = os.path.join(current_dir, 'index.html')
    if os.path.exists(html_file):
        import shutil
        shutil.copy(html_file, os.path.join(web_folder, 'index.html'))
        print("HTML file copied to web folder.")

eel.init(web_folder)

@eel.expose
def process_user_query(user_query_text: str):
    """
    Process user query with FALCONAssistant and return response.
    This function matches exactly what the HTML expects.
    """
    print(f"User Query: {user_query_text}")
    
    # Validate input
    if not user_query_text or not user_query_text.strip():
        no_input_response = "I didn't quite catch that. Could you please repeat?"
        return {'response': no_input_response, 'should_speak': True}

    if not assistant:
        error_response = "Assistant is not initialized. Please restart the application."
        return {'response': error_response, 'should_speak': True}

    try:
        # Stop any ongoing TTS before processing new query
        if tts_manager.is_currently_speaking():
            print("Stopping ongoing TTS due to new query...")
            tts_manager.stop()
            time.sleep(0.1)  # Brief pause to ensure TTS stops
        
        # Process the query
        ai_response_text = assistant.process_message(user_query_text)
        print(f"FALCON Response: {ai_response_text}")
        
        # Determine if we should speak the response
        should_speak = bool(ai_response_text and ai_response_text.strip())

        return {
            'response': ai_response_text or "I'm not sure how to respond to that.", 
            'should_speak': should_speak
        }
    
    except Exception as e:
        print(f"Critical Error in process_user_query: {str(e)}")
        error_response = "I've encountered an issue processing your request. Please try again."
        return {'response': error_response, 'should_speak': True}

@eel.expose
def request_tts(text_to_speak: str):
    """
    Handle text-to-speech requests using the threaded TTS Manager.
    Returns True if TTS was initiated successfully, False otherwise.
    """
    print(f"TTS Request: '{text_to_speak[:50]}...'")
    
    if not text_to_speak or not isinstance(text_to_speak, str) or not text_to_speak.strip():
        print("TTS Request Ignored: No valid text provided.")
        return False
    
    try:
        tts_manager.speak(text_to_speak.strip())
        return True
    except Exception as e:
        print(f"Error initiating TTS: {e}")
        return False

@eel.expose
def stop_tts():
    """
    Exposed function to stop TTS from the frontend (for barge-in functionality).
    """
    print("Stop TTS requested from frontend")
    try:
        tts_manager.stop()
        return True
    except Exception as e:
        print(f"Error stopping TTS: {e}")
        return False

@eel.expose
def get_system_status():
    """
    Get current system status - matches what the HTML interface expects.
    """
    try:
        status = {
            'assistant_ready': assistant is not None and assistant_ready,
            'tts_speaking': tts_manager.is_currently_speaking(),
            'system_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'microphone_available': True,  # This would need proper detection
            'speech_recognition_available': True  # This would need proper detection
        }
        return status
    except Exception as e:
        print(f"Error getting system status: {e}")
        return {
            'assistant_ready': False,
            'tts_speaking': False,
            'system_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'microphone_available': False,
            'speech_recognition_available': False
        }

@eel.expose
def get_conversation_history():
    """Get recent conversation history"""
    if not assistant:
        return []
    
    try:
        # Check if your assistant has a method to get conversation history
        if hasattr(assistant, 'db') and hasattr(assistant.db, 'get_recent_conversation'):
            history = assistant.db.get_recent_conversation(limit=50)
            return history if history else []
        elif hasattr(assistant, 'get_conversation_history'):
            return assistant.get_conversation_history()
        else:
            print("No method found to retrieve conversation history")
            return []
    except Exception as e:
        print(f"Error getting conversation history: {e}")
        return []

@eel.expose
def search_conversations(keyword: str):
    """Search conversations by keyword"""
    if not keyword or not keyword.strip() or not assistant:
        return []
    
    try:
        if hasattr(assistant, 'search_messages'):
            return assistant.search_messages(keyword.strip())
        else:
            print("Search functionality not available in assistant")
            return []
    except Exception as e:
        print(f"Error searching conversations: {e}")
        return []

@eel.expose
def export_chat_history(format_type: str = 'csv'):
    """Export chat history in specified format"""
    if not assistant:
        return None
    
    try:
        if hasattr(assistant, 'export_chat_history'):
            exported_data = assistant.export_chat_history(format_type)
            return {'format': format_type, 'data': exported_data}
        else:
            print("Export functionality not available in assistant")
            return None
    except Exception as e:
        print(f"Error exporting chat history: {e}")
        return None

# Function that the HTML calls to get TTS status updates
@eel.expose
def notify_tts_status(status):
    """
    This function is called BY the Python backend TO notify the frontend.
    The HTML expects this function to exist so it can receive TTS status updates.
    """
    # This is actually called from Python to JavaScript, not the other way around
    # The frontend will receive this via eel.notify_tts_status() calls
    pass

def main():
    """Main function to start the application"""
    host = 'localhost'
    port = 8000
    
    print("=" * 60)
    print("🚀 Starting FALCON AI Assistant Interface")
    print("=" * 60)
    print(f"🌐 Web Interface: http://{host}:{port}")
    print(f"📁 Web Folder: {web_folder}")
    print(f"🤖 Assistant Ready: {assistant_ready}")
    print(f"🔊 TTS Manager: Ready")
    print("=" * 60)
    
    if not assistant_ready:
        print("⚠️  WARNING: Assistant not initialized. Some features may not work.")
    
    try:
        # Check if index.html exists in web folder
        index_path = os.path.join(web_folder, 'index.html')
        if not os.path.exists(index_path):
            print(f"❌ Error: index.html not found at {index_path}")
            print("Please ensure your HTML file is in the web/ folder")
            return
        
        print("🎯 Starting web server...")
        eel.start('index.html', 
                 size=(1200, 800), 
                 block=True, 
                 host=host, 
                 port=port,
                 mode='chrome',  # Try to use Chrome if available
                 cmdline_args=['--disable-web-security', '--allow-running-insecure-content'])
        
    except (OSError, IOError) as e:
        print(f"❌ Could not start Eel: {e}")
        print(f"Please ensure port {port} is not already in use.")
        print("Try changing the port in the script or closing other applications using this port.")
    except KeyboardInterrupt:
        print("\n🛑 Shutting down FALCON gracefully...")
    except Exception as e:
        print(f"❌ An unexpected error occurred while starting Eel: {e}")
    finally:
        # Clean shutdown
        if tts_manager and tts_manager.is_currently_speaking():
            print("🔇 Stopping TTS...")
            tts_manager.stop()
        print("✅ FALCON UI application has closed.")

if __name__ == '__main__':
    main()

# --- END OF FILE Falcon.py ---