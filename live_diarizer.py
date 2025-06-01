import os
import queue
import threading
import time
import numpy as np
import torch
from pyannote.audio import Pipeline
from pyannote.audio.features import Pretrained # For embedding model

# Attempt to set a local cache for HuggingFace to avoid issues in restricted envs,
# though pyannote might have its own model download logic.
# os.environ["HF_HOME"] = os.path.join(os.getcwd(), "models", "huggingface_cache")
# os.makedirs(os.environ["HF_HOME"], exist_ok=True)

# Pyannote database config: often needed if running pyannote scripts,
# but for pipeline usage directly, might not be strictly necessary.
# If errors arise, creating a dummy db.yml and pointing to it can help.
# Example: with open("dummy_db.yml", "w") as f: f.write("Databases:\n  MyDatabase:\n    Annotation: /path/to/your/annotations\n    Speech: /path/to/your/audiofiles")
# os.environ["PYANNOTE_DATABASE_CONFIG"] = os.path.abspath("./dummy_db.yml")


class LiveDiarizer:
    def __init__(self, audio_input_queue, sample_rate=16000,
                 accumulation_seconds=5,
                 diarization_model_name="pyannote/speaker-diarization-3.1",
                 embedding_model_name="speechbrain/speaker-recognition-ecapa-tdnn"):
        self.audio_input_queue = audio_input_queue
        self.sample_rate = sample_rate
        self.accumulation_seconds = accumulation_seconds
        self.frames_to_accumulate = self.sample_rate * self.accumulation_seconds
        self.diarization_model_name = diarization_model_name
        self.embedding_model_name = embedding_model_name

        self.diarization_result_queue = queue.Queue()
        self.pipeline = None
        self.embedding_model = None
        self.is_running = False
        self.diarization_thread = None
        self.hf_token = os.environ.get("HF_TOKEN")

        if not self.hf_token:
            print("Warning: HF_TOKEN environment variable not set. Model downloads might fail if authentication is required.")
            print("Please ensure you have accepted model terms of use on Hugging Face Hub.")

        self._load_models()

    def _load_models(self):
        print(f"Loading pyannote.audio pipeline: {self.diarization_model_name}")
        try:
            self.pipeline = Pipeline.from_pretrained(
                self.diarization_model_name,
                use_auth_token=self.hf_token if self.hf_token else True)
            print("Diarization pipeline loaded successfully.")
        except Exception as e:
            print(f"Error loading diarization pipeline: {e}")
            raise

        print(f"Loading embedding model: {self.embedding_model_name}")
        try:
            self.embedding_model = Pretrained(
                ssl_model=self.embedding_model_name, # speechbrain models are common
                use_auth_token=self.hf_token if self.hf_token else True)
            # Some embedding models might need to be moved to a device if using GPU
            # self.embedding_model.to(torch.device("cuda" if torch.cuda.is_available() else "cpu"))
            print("Embedding model loaded successfully.")
        except Exception as e:
            print(f"Error loading embedding model: {e}")
            raise

    def _diarization_loop(self):
        accumulated_frames_list = []
        current_accumulated_samples = 0
        print("Diarization loop started.")

        while self.is_running:
            try:
                audio_chunk_np = self.audio_input_queue.get(timeout=0.2)

                if audio_chunk_np is not None:
                    accumulated_frames_list.append(audio_chunk_np)
                    current_accumulated_samples += len(audio_chunk_np)

                    if current_accumulated_samples >= self.frames_to_accumulate:
                        # Prepare the full accumulated audio segment for diarization
                        full_segment_np = np.concatenate(accumulated_frames_list).astype(np.float32)
                        accumulated_frames_list = [] # Reset for next accumulation
                        current_accumulated_samples = 0

                        if full_segment_np.ndim == 2 and full_segment_np.shape[1] == 1: # (samples, 1)
                            full_segment_np = full_segment_np.flatten() # -> (samples,)

                        # Diarization pipeline expects [batch_size, num_samples] or [batch_size, num_channels, num_samples]
                        # For mono, it's often [batch_size, num_samples]
                        full_segment_tensor = torch.from_numpy(full_segment_np).unsqueeze(0) # -> (1, num_samples)

                        diarization_input_dict = {"waveform": full_segment_tensor, "sample_rate": self.sample_rate}

                        try:
                            diarization_annotation = self.pipeline(diarization_input_dict)

                            for turn, _, speaker_label in diarization_annotation.itertracks(yield_label=True):
                                # Extract audio for this specific turn to get embedding
                                # pipeline.crop() returns a new dict {'waveform': cropped_tensor, 'sample_rate': ...}
                                # The cropped_tensor is what the embedding model needs.
                                try:
                                    segment_audio_dict = self.pipeline.crop(diarization_input_dict, turn)
                                except Exception as crop_err:
                                     print(f"Error cropping segment for speaker {speaker_label} at {turn.start}-{turn.end}: {crop_err}")
                                     continue # Skip this turn if cropping fails

                                # Check if segment_audio_dict['waveform'] is not empty or too short
                                if segment_audio_dict['waveform'].shape[1] < self.sample_rate * 0.1: # e.g. < 100ms
                                    # print(f"Segment for {speaker_label} too short to embed, skipping.")
                                    embedding_vector = np.array([]) # Empty or placeholder embedding
                                else:
                                    # Get embedding for the cropped segment
                                    # The Pretrained model expects a batch, so (1, num_channels, num_samples)
                                    # If segment_audio_dict['waveform'] is (1, samples), it's fine.
                                    # If it's (samples), unsqueeze again.
                                    # Most embedding models from pyannote handle (1, samples) for mono.
                                    embedding_vector = self.embedding_model(segment_audio_dict) # Returns np.ndarray
                                    if embedding_vector.ndim > 1: # e.g. (1, D)
                                        embedding_vector = embedding_vector.squeeze() # -> (D,)

                                result = (speaker_label, turn.start, turn.end, embedding_vector)
                                self.diarization_result_queue.put(result)
                        except Exception as e:
                            print(f"Error during diarization or embedding processing: {e}")
                            # Clear frames to avoid reprocessing bad data if a major error occurs
                            accumulated_frames_list = []
                            current_accumulated_samples = 0


            except queue.Empty:
                continue # Loop again to check self.is_running
            except Exception as e:
                print(f"Error in diarization loop: {e}")
                time.sleep(0.1)

        print("Diarization loop finished.")

    def start(self):
        if self.is_running:
            print("Diarization is already running.")
            return
        if not self.pipeline or not self.embedding_model:
            print("Models not loaded. Cannot start diarization.")
            return

        self.is_running = True
        while not self.diarization_result_queue.empty(): # Clear queue
            try: self.diarization_result_queue.get_nowait()
            except queue.Empty: break

        self.diarization_thread = threading.Thread(target=self._diarization_loop)
        self.diarization_thread.daemon = True
        self.diarization_thread.start()
        print("LiveDiarizer started.")

    def stop(self):
        if not self.is_running:
            print("Diarization is not running.")
            return
        print("Stopping LiveDiarizer...")
        self.is_running = False
        if self.diarization_thread and self.diarization_thread.is_alive():
            self.diarization_thread.join(timeout=2) # Wait for up to 2 seconds
            if self.diarization_thread.is_alive():
                 print("Diarization thread did not join in time.")
        self.diarization_thread = None
        print("LiveDiarizer stopped.")

    def get_diarization_result_queue(self):
        return self.diarization_result_queue

if __name__ == '__main__':
    import sys # For sys.exit()
    print("LiveDiarizer Test Script with Embeddings")
    print("Requires HF_TOKEN and model terms acceptance for:")
    print("  - pyannote/speaker-diarization-3.1")
    print("  - speechbrain/speaker-recognition-ecapa-tdnn")

    hf_token_present = bool(os.environ.get("HF_TOKEN"))
    if not hf_token_present:
        print("\nWARNING: HF_TOKEN environment variable is not set.")
        print("The test may fail if models require authentication for download.")
    else:
        print("\nHF_TOKEN found. Proceeding with test.")

    SAMPLE_RATE = 16000
    CHUNK_DURATION_S = 0.5
    ACCUMULATION_S = 5
    SIMULATION_DURATION_S = 15 # Shorter for quicker test with embeddings

    audio_q = queue.Queue()

    print("\nInitializing LiveDiarizer for testing...")
    try:
        diarizer = LiveDiarizer(
            audio_q,
            sample_rate=SAMPLE_RATE,
            accumulation_seconds=ACCUMULATION_S
            # Default model names are used
        )
    except Exception as e:
        print(f"Failed to initialize LiveDiarizer: {e}")
        print("Ensure internet, HF_TOKEN is correct, and model terms accepted for all models.")
        sys.exit(1)

    diarizer.start()

    def audio_producer_thread():
        print(f"Audio producer started: generating {SIMULATION_DURATION_S}s of audio in {CHUNK_DURATION_S}s chunks.")
        total_chunks = int(SIMULATION_DURATION_S / CHUNK_DURATION_S)
        chunk_samples = int(SAMPLE_RATE * CHUNK_DURATION_S)

        for i in range(total_chunks):
            if not diarizer.is_running: # Stop if diarizer stops
                break
            # Simulate a mono audio chunk
            sim_chunk = np.random.uniform(low=-0.2, high=0.2, size=(chunk_samples,)).astype(np.float32)
            audio_q.put(sim_chunk)
            # print(f"Produced chunk {i+1}/{total_chunks}, queue size: {audio_q.qsize()}")
            time.sleep(CHUNK_DURATION_S)
        print("Audio producer finished.")

    producer = threading.Thread(target=audio_producer_thread)
    producer.daemon = True
    producer.start()

    print("\nListening for diarization results...")
    results_received = 0
    start_time = time.time()
    # Listen for results
    while time.time() - start_time < SIMULATION_DURATION_S + ACCUMULATION_S + 3: # Listen a bit longer
        try:
            speaker_label, start_s, end_s, embedding = diarizer.get_diarization_result_queue().get(timeout=1.0)
            print(f"Diarization: Speaker {speaker_label} ({start_s:.2f}s - {end_s:.2f}s), Embedding shape: {embedding.shape}, Embedding preview: {embedding[:4]}...")
            results_received += 1
        except queue.Empty:
            if not producer.is_alive() and audio_q.empty():
                print("Producer stopped and input audio queue empty, stopping result listening.")
                break
        if not diarizer.is_running and diarizer.get_diarization_result_queue().empty():
            print("Diarizer stopped and output result queue empty.")
            break

    print(f"\nTotal diarization results with embeddings received: {results_received}")
    if results_received == 0:
        print("No diarization results produced. Check pipeline/model loading, HF token, and audio data flow.")
        print("If this was the first run, model downloads might have been in progress or failed.")

    print("\nStopping LiveDiarizer...")
    diarizer.stop()
    if producer.is_alive():
        producer.join(timeout=1)
    print("Test finished.")
    sys.exit(0)
