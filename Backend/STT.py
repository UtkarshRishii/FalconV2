import speech_recognition as sr
import time

def recognize_speech(callback=None, timeout=10, phrase_time_limit=5):
    """
    Enhanced speech recognition with better error handling and configuration.

    Args:
        callback: Function to call with recognized text
        timeout: Maximum time to wait for speech to start
        phrase_time_limit: Maximum time to listen for a phrase
    """
    recognizer = sr.Recognizer()

    # Enhanced recognizer settings for better accuracy
    recognizer.energy_threshold = 300  # Minimum audio energy to consider for recording
    recognizer.dynamic_energy_threshold = True
    recognizer.dynamic_energy_adjustment_damping = 0.15
    recognizer.dynamic_energy_ratio = 1.5
    recognizer.pause_threshold = 0.8  # Seconds of non-speaking audio before phrase is complete
    recognizer.operation_timeout = None  # No timeout for operations
    recognizer.phrase_threshold = 0.3  # Minimum seconds of speaking audio before considering phrase
    recognizer.non_speaking_duration = 0.5  # Seconds of non-speaking audio to keep on both sides

    # Get the default microphone
    mic = sr.Microphone()

    with mic as source:
        print("🎤 Falcon is listening...")
        # Adjust for ambient noise with longer duration for better calibration
        recognizer.adjust_for_ambient_noise(source, duration=1)
        print("🔧 Audio calibrated. Speak now...")

        try:
            # Listen for audio with timeout and phrase limit
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
        except sr.WaitTimeoutError:
            print("⏰ Listening timeout - no speech detected")
            return None

    try:
        # Use Google's speech recognition with enhanced language support
        text = recognizer.recognize_google(
            audio,
            language='en-US',  # Changed to US English for better recognition
            show_all=False  # Return only the most likely result
        )

        print(f"🗣️  User: {text}")
        if callback:
            callback(text)
        return text

    except sr.UnknownValueError:
        print("🤖 Could not understand audio - please speak clearly")
        return None
    except sr.RequestError as e:
        print(f"🔌 Could not request results from Google Speech Recognition service; {e}")
        return None
    except Exception as e:
        print(f"❌ Unexpected error in speech recognition: {e}")
        return None

def continuous_listen(callback=None, wake_word="falcon"):
    """
    Continuous listening mode with wake word detection.

    Args:
        callback: Function to call with recognized text
        wake_word: Word to activate listening mode
    """
    recognizer = sr.Recognizer()
    mic = sr.Microphone()

    print(f"🎯 Continuous listening mode activated. Say '{wake_word}' to start...")

    with mic as source:
        recognizer.adjust_for_ambient_noise(source)

    while True:
        try:
            with mic as source:
                # Listen for wake word with shorter timeout
                audio = recognizer.listen(source, timeout=1, phrase_time_limit=3)

            text = recognizer.recognize_google(audio, language='en-US')

            if wake_word.lower() in text.lower():
                print(f"🎯 Wake word '{wake_word}' detected!")
                # Extract command after wake word
                command = text.lower().replace(wake_word.lower(), "").strip()
                if command:
                    print(f"🗣️  Command: {command}")
                    if callback:
                        callback(command)
                else:
                    # Listen for the actual command
                    print("🎤 Listening for command...")
                    command_text = recognize_speech(callback, timeout=5, phrase_time_limit=10)
                    return command_text

        except sr.WaitTimeoutError:
            continue  # Keep listening
        except sr.UnknownValueError:
            continue  # Keep listening
        except sr.RequestError as e:
            print(f"🔌 Speech recognition error: {e}")
            time.sleep(1)
        except KeyboardInterrupt:
            print("🛑 Continuous listening stopped")
            break
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            time.sleep(1)