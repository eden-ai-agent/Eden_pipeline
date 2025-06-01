import os
import queue
import threading
import time
import numpy as np
from faster_whisper import WhisperModel

# Set HuggingFace cache directory to be local if needed
# os.environ["HF_HOME"] = os.path.join(os.getcwd(), "models", "huggingface")
# os.makedirs(os.environ["HF_HOME"], exist_ok=True)


class LiveTranscriber:
    def __init__(self, audio_input_queue, model_size="tiny",
                 device="cpu", compute_type="int8",
                 sample_rate=16000, accumulation_seconds=2):
        self.audio_input_queue = audio_input_queue
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.sample_rate = sample_rate # Whisper expects 16kHz
        self.accumulation_seconds = accumulation_seconds
        self.frames_to_accumulate = self.sample_rate * self.accumulation_seconds

        self.transcribed_text_queue = queue.Queue()
        self.model = None
        self.is_running = False
        self.transcription_thread = None
        self.current_audio_offset = 0.0 # To track absolute time for word timestamps

        self._load_model()

    def _load_model(self):
        print(f"Loading Whisper model: {self.model_size} ({self.device}, {self.compute_type})")
        try:
            self.model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
            print("Whisper model loaded successfully.")
        except Exception as e:
            print(f"Error loading Whisper model: {e}")
            # Potentially re-raise or handle as a critical error
            raise

    def _transcription_loop(self):
        accumulated_frames = []
        current_audio_length_samples = 0

        print("Transcription loop started.")
        while self.is_running:
            try:
                # Get audio chunk from the input queue
                # Timeout allows checking self.is_running periodically
                audio_chunk = self.audio_input_queue.get(timeout=0.1)

                if audio_chunk is not None:
                    accumulated_frames.append(audio_chunk)
                    current_audio_length_samples += len(audio_chunk)

                    if current_audio_length_samples >= self.frames_to_accumulate:
                        # Concatenate accumulated frames into a single NumPy array
                        segment_to_transcribe = np.concatenate(accumulated_frames)
                        accumulated_frames = [] # Reset for next segment
                        current_audio_length_samples = 0

                        # Ensure data is float32 as Whisper expects
                        segment_to_transcribe = segment_to_transcribe.astype(np.float32)

                        # Normalize if necessary, though Whisper handles this well.
                        # Max value for float32 is 1.0. If it's int16, divide by 32768.0
                        # Sounddevice usually gives float32 in [-1.0, 1.0] range.

                        # print(f"Transcribing segment of {len(segment_to_transcribe)/self.sample_rate:.2f}s")
                        # Record the starting offset for this specific segment
                        segment_start_offset = self.current_audio_offset
                        # Update the global offset by the duration of the segment just processed
                        segment_duration = len(segment_to_transcribe) / self.sample_rate
                        self.current_audio_offset += segment_duration

                        # print(f"Transcribing segment of {segment_duration:.2f}s, offset: {segment_start_offset:.2f}s")
                        try:
                            # Enable word timestamps
                            segments_iterable, info = self.model.transcribe(
                                segment_to_transcribe,
                                beam_size=5,
                                word_timestamps=True # Request word-level timestamps
                                # language="en", # Optional
                            )
                            for segment in segments_iterable:
                                adjusted_word_info = []
                                if segment.words:
                                    for word in segment.words:
                                        adjusted_word_info.append({
                                            'word': word.word,
                                            'start': word.start + segment_start_offset,
                                            'end': word.end + segment_start_offset,
                                            'probability': word.probability
                                        })
                                # Output tuple: (full_segment_text, list_of_word_timestamp_dicts)
                                output_tuple = (segment.text.strip(), adjusted_word_info)
                                self.transcribed_text_queue.put(output_tuple)
                        except Exception as e:
                            print(f"Error during transcription with word timestamps: {e}")
                            # If transcription fails, roll back offset update for this failed segment
                            self.current_audio_offset -= segment_duration
                            accumulated_frames = []
                            current_audio_length_samples = 0


            except queue.Empty:
                # Timeout occurred, queue is empty. Loop again to check self.is_running.
                continue
            except Exception as e:
                print(f"Error in transcription loop: {e}")
                time.sleep(0.1) # Avoid busy-looping on unexpected errors

        print("Transcription loop finished.")

    def start(self):
        if self.is_running:
            print("Transcription is already running.")
            return

        if self.model is None:
            print("Model not loaded. Cannot start transcription.")
            # Or try loading again: self._load_model() if it failed before.
            return

        self.is_running = True
        self.current_audio_offset = 0.0 # Reset offset for a new session
        # Clear queue from previous run
        while not self.transcribed_text_queue.empty():
            try: self.transcribed_text_queue.get_nowait()
            except queue.Empty: break

        self.transcription_thread = threading.Thread(target=self._transcription_loop)
        self.transcription_thread.daemon = True
        self.transcription_thread.start()
        print("LiveTranscriber started.")

    def stop(self):
        if not self.is_running:
            print("Transcription is not running.")
            return

        print("Stopping LiveTranscriber...")
        self.is_running = False
        if self.transcription_thread and self.transcription_thread.is_alive():
            self.transcription_thread.join(timeout=2) # Wait for 2 seconds
            if self.transcription_thread.is_alive():
                print("Transcription thread did not join in time.")
        self.transcription_thread = None
        print("LiveTranscriber stopped.")

    def get_transcribed_text_queue(self):
        return self.transcribed_text_queue


if __name__ == '__main__':
    # --- Configuration ---
    MODEL_DIR = "./models/faster_whisper" # Example: store models locally
    os.makedirs(MODEL_DIR, exist_ok=True)
    # For faster_whisper, model files are typically managed by huggingface_hub cache.
    # You can set HF_HUB_CACHE or XDG_CACHE_HOME to control global Hugging Face cache.
    # WhisperModel constructor also has a 'download_root' parameter.
    # For this example, we'll rely on the default caching mechanism of faster_whisper/huggingface_hub.
    # If specific download control is needed, WhisperModel(..., download_root=MODEL_DIR) could be used.

    SAMPLE_RATE = 16000  # Hz (Whisper standard)
    CHUNK_DURATION = 0.2 # seconds per chunk from AudioRecorder (example)
    ACCUMULATION_SECONDS = 2 # seconds of audio to accumulate before transcribing
    SIMULATION_DURATION = 10 # seconds for the test simulation

    # --- Setup ---
    audio_q = queue.Queue()

    print("Initializing LiveTranscriber for testing...")
    try:
        # Using download_root to attempt to control model storage location for this test
        transcriber = LiveTranscriber(
            audio_q,
            model_size="tiny", # "tiny.en" for English-only tiny model
            sample_rate=SAMPLE_RATE,
            accumulation_seconds=ACCUMULATION_SECONDS
        )
    except Exception as e:
        print(f"Failed to initialize LiveTranscriber: {e}")
        sys.exit(1)

    transcriber.start()

    # --- Simulation ---
    print(f"\nSimulating audio input for {SIMULATION_DURATION} seconds...")
    start_time = time.time()
    chunk_samples = int(SAMPLE_RATE * CHUNK_DURATION)

    def audio_producer():
        for i in range(int(SIMULATION_DURATION / CHUNK_DURATION)):
            if not transcriber.is_running:
                break
            # Simulate an audio chunk (e.g., silence or noise)
            # For a real test, one might feed actual spoken audio chunks.
            # This creates 0.2s of audio at 16kHz.
            sim_chunk = np.random.uniform(low=-0.1, high=0.1, size=(chunk_samples,)).astype(np.float32)
            # For first few seconds, make it silent to test silence handling.
            if time.time() - start_time < 2:
                 sim_chunk = np.zeros(chunk_samples, dtype=np.float32)
            audio_q.put(sim_chunk)
            # print(f"Put audio chunk {i+1}, queue size: {audio_q.qsize()}")
            time.sleep(CHUNK_DURATION)
        print("Audio producer finished.")

    producer_thread = threading.Thread(target=audio_producer)
    producer_thread.daemon = True
    producer_thread.start()

    # --- Consume Transcribed Text ---
    print("\nListening for transcribed text...")
    transcribed_something = False
    while time.time() - start_time < SIMULATION_DURATION + ACCUMULATION_SECONDS + 1: # Listen a bit longer
        try:
            text = transcriber.get_transcribed_text_queue().get(timeout=0.5)
            print(f"Transcribed: {text}")
            transcribed_something = True
        except queue.Empty:
            if not producer_thread.is_alive() and audio_q.empty():
                # Producer is done and input queue is empty, check one last time
                try:
                    text = transcriber.get_transcribed_text_queue().get(timeout=0.1)
                    print(f"Transcribed (final): {text}")
                    transcribed_something = True
                except queue.Empty:
                    break # No more text expected
        if not transcriber.is_running and transcriber.get_transcribed_text_queue().empty():
            break # Transcriber stopped and output queue empty

    if not transcribed_something:
        print("No text was transcribed during the simulation.")
        print("This might be expected if only silence/random noise was fed.")
        print("Ensure your microphone is capturing audio if testing with real input via AudioRecorder.")

    # --- Teardown ---
    print("\nStopping transcriber...")
    transcriber.stop()
    if producer_thread.is_alive():
        producer_thread.join(timeout=1)

    print("Test finished.")
    # Note: The HuggingFace model files are downloaded to a cache directory.
    # On first run, this can take some time.
    # Default cache: ~/.cache/huggingface/hub
    # Or if download_root was used effectively by WhisperModel and its dependencies: ./models/faster_whisper
    # Check faster_whisper docs for precise control over model download location.
    # For this script, we assume `WhisperModel` handles downloads transparently.
    import sys
    sys.exit(0)
