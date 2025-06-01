import os
import queue
import threading
import time
import numpy as np
import torch
from transformers import pipeline as hf_pipeline # Alias to avoid conflict if we use pyannote.pipeline

# os.environ["HF_HOME"] = os.path.join(os.getcwd(), "models", "huggingface_cache_ser")
# os.makedirs(os.environ["HF_HOME"], exist_ok=True)

class SpeechEmotionRecognizer:
    def __init__(self, audio_input_queue, sample_rate=16000,
                 model_name="ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition",
                 accumulation_seconds=2.0): # Process 2-second chunks for SER

        self.audio_input_queue = audio_input_queue
        self.sample_rate = sample_rate
        self.model_name = model_name
        self.accumulation_seconds = accumulation_seconds
        self.frames_to_accumulate = int(self.sample_rate * self.accumulation_seconds)

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"SpeechEmotionRecognizer: Using device: {self.device}")

        self.emotion_results_queue = queue.Queue()
        self.classifier = None
        self.is_running = False
        self.recognition_thread = None
        self.current_audio_offset = 0.0

        self._load_model()

    def _load_model(self):
        print(f"Loading Speech Emotion Recognition model: {self.model_name}")
        try:
            self.classifier = hf_pipeline(
                "audio-classification",
                model=self.model_name,
                device=self.device,
                top_k=None # Get scores for all classes
            )
            # Check if the model has expected sample rate info, some pipelines do.
            if hasattr(self.classifier.feature_extractor, 'sampling_rate') and \
               self.classifier.feature_extractor.sampling_rate != self.sample_rate:
                print(f"Warning: Model expected sample rate {self.classifier.feature_extractor.sampling_rate}, "
                      f"input is {self.sample_rate}. Transformers pipeline should handle resampling.")
            print("Speech Emotion Recognition model loaded successfully.")
        except Exception as e:
            print(f"Error loading SER model: {e}")
            # This is a critical error for this component.
            raise

    def _recognition_loop(self):
        accumulated_frames = []
        current_accumulated_samples = 0
        print("Speech Emotion Recognition loop started.")

        while self.is_running:
            try:
                audio_chunk_np = self.audio_input_queue.get(timeout=0.1) # Short timeout

                if audio_chunk_np is not None:
                    accumulated_frames.append(audio_chunk_np)
                    current_accumulated_samples += len(audio_chunk_np)

                    if current_accumulated_samples >= self.frames_to_accumulate:
                        full_segment_np = np.concatenate(accumulated_frames).astype(np.float32)
                        accumulated_frames = [] # Reset for next segment
                        current_accumulated_samples = 0

                        segment_duration = len(full_segment_np) / self.sample_rate
                        chunk_start_time = self.current_audio_offset
                        self.current_audio_offset += segment_duration

                        # print(f"SER: Processing segment, offset {chunk_start_time:.2f}s, duration {segment_duration:.2f}s")
                        try:
                            # The pipeline expects the raw waveform as a NumPy array and the sampling rate.
                            predictions = self.classifier(full_segment_np, sampling_rate=self.sample_rate)

                            if predictions and isinstance(predictions, list) and isinstance(predictions[0], dict):
                                # predictions is like [[{'label': 'angry', 'score': 0.1}, ...], [{'label': 'happy'}]]
                                # or just [{'label': 'angry', 'score': 0.1}, ...] if only one result.
                                # We need to handle the case where it might return a list of lists if audio is too long
                                # and gets auto-chunked by pipeline, or a single list of dicts.
                                if isinstance(predictions[0], list): # It was auto-chunked by transformers pipeline
                                    # For simplicity, take the first chunk's prediction set
                                    # A more advanced handling might average or take max over sub-chunks
                                    actual_predictions_list = predictions[0]
                                else: # Single list of dicts
                                    actual_predictions_list = predictions

                                highest_emotion_label = "neutral" # Default
                                highest_score = 0.0
                                if actual_predictions_list: # Ensure it's not empty
                                    # Find the emotion with the highest score
                                    top_prediction = max(actual_predictions_list, key=lambda x: x['score'])
                                    highest_emotion_label = top_prediction['label']
                                    highest_score = top_prediction['score']

                                result_tuple = (
                                    chunk_start_time,
                                    highest_emotion_label,
                                    highest_score,
                                    actual_predictions_list # Full list of scores
                                )
                                self.emotion_results_queue.put(result_tuple)
                            else:
                                print(f"SER: Unexpected prediction format: {predictions}")

                        except Exception as e:
                            print(f"Error during SER prediction: {e}")
                            # Roll back offset if processing failed for this chunk
                            self.current_audio_offset -= segment_duration


            except queue.Empty:
                continue # Loop again to check self.is_running
            except Exception as e:
                print(f"Error in SER recognition loop: {e}")
                time.sleep(0.1) # Avoid busy-looping

        print("Speech Emotion Recognition loop finished.")

    def start(self):
        if self.is_running:
            print("Speech Emotion Recognition is already running.")
            return
        if not self.classifier:
            print("SER Model not loaded. Cannot start.")
            return

        self.is_running = True
        self.current_audio_offset = 0.0 # Reset for new session

        # Clear queues from previous run
        while not self.audio_input_queue.empty(): # Clear input queue if it's shared and might have stale data
            try: self.audio_input_queue.get_nowait()
            except queue.Empty: break
        while not self.emotion_results_queue.empty():
            try: self.emotion_results_queue.get_nowait()
            except queue.Empty: break

        self.recognition_thread = threading.Thread(target=self._recognition_loop)
        self.recognition_thread.daemon = True
        self.recognition_thread.start()
        print("SpeechEmotionRecognizer started.")

    def stop(self):
        if not self.is_running:
            print("Speech Emotion Recognition is not running.")
            return
        print("Stopping SpeechEmotionRecognizer...")
        self.is_running = False
        if self.recognition_thread and self.recognition_thread.is_alive():
            self.recognition_thread.join(timeout=2)
            if self.recognition_thread.is_alive():
                print("SER recognition thread did not join in time.")
        self.recognition_thread = None
        print("SpeechEmotionRecognizer stopped.")

    def get_emotion_results_queue(self):
        return self.emotion_results_queue

if __name__ == '__main__':
    import sys
    print("SpeechEmotionRecognizer Test Script")
    # This model ("ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition") is usually public.
    # HF_TOKEN might be needed if HuggingFace changes its policies or for other models.
    if not os.environ.get("HF_TOKEN_SENTINEL_FOR_TEST", None): # Using a dummy var to show where token might be checked
        print("Note: HF_TOKEN related environment variables not explicitly checked in this test script's logic,")
        print("but model download might require it if it's gated or if HuggingFace policies change.")

    SAMPLE_RATE = 16000
    CHUNK_DURATION_S = 0.5  # Audio chunks generated every 0.5s
    ACCUMULATION_S = 2.0    # SER processes 2s chunks of audio
    SIMULATION_DURATION_S = 10 # Total simulation time

    audio_q = queue.Queue()

    print("\nInitializing SpeechEmotionRecognizer for testing...")
    try:
        recognizer = SpeechEmotionRecognizer(
            audio_q,
            sample_rate=SAMPLE_RATE,
            accumulation_seconds=ACCUMULATION_S
        )
    except Exception as e:
        print(f"Failed to initialize SpeechEmotionRecognizer: {e}")
        sys.exit(1)

    recognizer.start()

    def audio_producer_thread_ser():
        print(f"Audio producer started: generating {SIMULATION_DURATION_S}s of audio...")
        total_chunks = int(SIMULATION_DURATION_S / CHUNK_DURATION_S)
        chunk_samples = int(SAMPLE_RATE * CHUNK_DURATION_S)

        for i in range(total_chunks):
            if not recognizer.is_running: break
            sim_chunk = np.random.uniform(low=-0.1, high=0.1, size=(chunk_samples,)).astype(np.float32)
            # Add some variation: occasionally make a louder chunk
            if i % 5 == 0:
                sim_chunk *= 3
            audio_q.put(sim_chunk)
            time.sleep(CHUNK_DURATION_S)
        print("Audio producer finished.")

    producer_ser = threading.Thread(target=audio_producer_thread_ser)
    producer_ser.daemon = True
    producer_ser.start()

    print("\nListening for emotion recognition results...")
    results_count = 0
    listen_end_time = time.time() + SIMULATION_DURATION_S + ACCUMULATION_S + 2

    while time.time() < listen_end_time:
        try:
            timestamp, emotion, score, all_scores = recognizer.get_emotion_results_queue().get(timeout=1.0)
            print(f"\nEmotion @ {timestamp:.2f}s: {emotion} (Score: {score:.3f})")
            # print("All scores:")
            # for s in sorted(all_scores, key=lambda x: x['score'], reverse=True)[:3]: # Print top 3
            #     print(f"  - {s['label']}: {s['score']:.3f}")
            results_count += 1
        except queue.Empty:
            if not producer_ser.is_alive() and audio_q.empty():
                print("Producer stopped and input audio queue empty for SER.")
                break
        if not recognizer.is_running and recognizer.get_emotion_results_queue().empty():
            print("SER stopped and output result queue empty.")
            break

    print(f"\nTotal emotion results received: {results_count}")
    if results_count == 0:
        print("No emotion results produced. Check model loading and audio data flow.")

    print("\nStopping SpeechEmotionRecognizer...")
    recognizer.stop()
    if producer_ser.is_alive():
        producer_ser.join(timeout=1)
    print("Test finished.")
    sys.exit(0)
