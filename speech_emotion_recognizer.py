import os
import queue
import threading
import time
import numpy as np
import torch
from transformers import pipeline as hf_pipeline
from typing import Optional, Tuple, List, Dict, Any
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SpeechEmotionRecognizer:
    """
    Real-time Speech Emotion Recognition using wav2vec2 model.
    
    Processes audio chunks in a separate thread and outputs emotion predictions
    with timestamps and confidence scores.
    """
    
    def __init__(self, 
                 audio_input_queue: queue.Queue,
                 sample_rate: int = 16000,
                 model_name: str = "ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition",
                 accumulation_seconds: float = 2.0,
                 overlap_seconds: float = 0.5,
                 min_confidence_threshold: float = 0.1):
        """
        Initialize the Speech Emotion Recognizer.
        
        Args:
            audio_input_queue: Queue containing audio chunks as numpy arrays
            sample_rate: Sample rate of input audio
            model_name: HuggingFace model identifier
            accumulation_seconds: Duration of audio chunks to process
            overlap_seconds: Overlap between consecutive chunks for smoother detection
            min_confidence_threshold: Minimum confidence score to report emotions
        """
        self.audio_input_queue = audio_input_queue
        self.sample_rate = sample_rate
        self.model_name = model_name
        self.accumulation_seconds = accumulation_seconds
        self.overlap_seconds = overlap_seconds
        self.min_confidence_threshold = min_confidence_threshold
        
        # Calculate frame counts
        self.frames_to_accumulate = int(self.sample_rate * self.accumulation_seconds)
        self.overlap_frames = int(self.sample_rate * self.overlap_seconds)
        self.step_frames = self.frames_to_accumulate - self.overlap_frames

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Using device: {self.device}")

        # State variables
        self.emotion_results_queue = queue.Queue()
        self.classifier: Optional[Any] = None
        self.is_running = False
        self.recognition_thread: Optional[threading.Thread] = None
        self.current_audio_offset = 0.0
        
        # Audio buffer for overlapping windows
        self.audio_buffer = np.array([], dtype=np.float32)
        
        # Emotion smoothing
        self.emotion_history: List[Tuple[str, float]] = []
        self.history_size = 3

        self._load_model()

    def _load_model(self) -> None:
        """Load the speech emotion recognition model."""
        logger.info(f"Loading model: {self.model_name}")
        try:
            self.classifier = hf_pipeline(
                "audio-classification",
                model=self.model_name,
                device=self.device,
                top_k=None,
                return_tensors="pt"
            )
            
            # Verify sample rate compatibility
            if hasattr(self.classifier.feature_extractor, 'sampling_rate'):
                expected_sr = self.classifier.feature_extractor.sampling_rate
                if expected_sr != self.sample_rate:
                    logger.warning(f"Model expects {expected_sr}Hz, input is {self.sample_rate}Hz. "
                                 f"Pipeline will handle resampling.")
            
            logger.info("Model loaded successfully")
            
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise

    def _smooth_emotions(self, current_emotion: str, current_score: float) -> Tuple[str, float]:
        """
        Apply temporal smoothing to emotion predictions to reduce flickering.
        
        Args:
            current_emotion: Current predicted emotion
            current_score: Current confidence score
            
        Returns:
            Smoothed emotion and confidence score
        """
        self.emotion_history.append((current_emotion, current_score))
        
        # Keep only recent history
        if len(self.emotion_history) > self.history_size:
            self.emotion_history.pop(0)
        
        # If we don't have enough history, return current
        if len(self.emotion_history) < 2:
            return current_emotion, current_score
        
        # Count emotion occurrences in recent history
        emotion_counts = {}
        total_score = 0.0
        
        for emotion, score in self.emotion_history:
            if emotion not in emotion_counts:
                emotion_counts[emotion] = []
            emotion_counts[emotion].append(score)
            total_score += score
        
        # Find most frequent emotion with highest average score
        best_emotion = current_emotion
        best_avg_score = current_score
        
        for emotion, scores in emotion_counts.items():
            avg_score = np.mean(scores)
            if len(scores) >= 2 and avg_score > best_avg_score:
                best_emotion = emotion
                best_avg_score = avg_score
        
        return best_emotion, best_avg_score

    def _process_audio_segment(self, audio_segment: np.ndarray, timestamp: float) -> None:
        """
        Process a single audio segment for emotion recognition.
        
        Args:
            audio_segment: Audio data as numpy array
            timestamp: Timestamp of the segment start
        """
        try:
            # Normalize audio to prevent clipping
            if np.max(np.abs(audio_segment)) > 0:
                audio_segment = audio_segment / np.max(np.abs(audio_segment)) * 0.9
            
            predictions = self.classifier(audio_segment, sampling_rate=self.sample_rate)
            
            if not predictions or not isinstance(predictions, list):
                logger.warning("Invalid prediction format received")
                return
            
            # Handle different prediction formats
            if isinstance(predictions[0], list):
                # Auto-chunked by pipeline
                actual_predictions = predictions[0]
            else:
                actual_predictions = predictions
            
            if not actual_predictions:
                logger.warning("Empty predictions received")
                return
            
            # Find highest confidence emotion
            top_prediction = max(actual_predictions, key=lambda x: x['score'])
            emotion = top_prediction['label']
            confidence = top_prediction['score']
            
            # Apply confidence threshold
            if confidence < self.min_confidence_threshold:
                emotion = "neutral"
                confidence = 0.0
            
            # Apply temporal smoothing
            smoothed_emotion, smoothed_confidence = self._smooth_emotions(emotion, confidence)
            
            # Create result tuple
            result = (
                timestamp,
                smoothed_emotion,
                smoothed_confidence,
                actual_predictions,
                confidence  # Original confidence for debugging
            )
            
            self.emotion_results_queue.put(result)
            
        except Exception as e:
            logger.error(f"Error processing audio segment: {e}")

    def _recognition_loop(self) -> None:
        """Main recognition loop running in separate thread."""
        logger.info("Recognition loop started")
        
        try:
            while self.is_running:
                try:
                    # Get audio chunk with timeout
                    audio_chunk = self.audio_input_queue.get(timeout=0.1)
                    
                    if audio_chunk is None:
                        continue
                    
                    # Add to buffer
                    self.audio_buffer = np.concatenate([self.audio_buffer, audio_chunk])
                    
                    # Process overlapping windows
                    while len(self.audio_buffer) >= self.frames_to_accumulate:
                        # Extract segment
                        segment = self.audio_buffer[:self.frames_to_accumulate].copy()
                        
                        # Process segment
                        self._process_audio_segment(segment, self.current_audio_offset)
                        
                        # Advance buffer and offset
                        if len(self.audio_buffer) > self.step_frames:
                            self.audio_buffer = self.audio_buffer[self.step_frames:]
                        else:
                            self.audio_buffer = np.array([], dtype=np.float32)
                        
                        self.current_audio_offset += self.step_frames / self.sample_rate
                    
                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"Error in recognition loop: {e}")
                    time.sleep(0.1)
                    
        except Exception as e:
            logger.error(f"Fatal error in recognition loop: {e}")
        finally:
            logger.info("Recognition loop finished")

    def start(self) -> None:
        """Start the emotion recognition process."""
        if self.is_running:
            logger.warning("Already running")
            return
            
        if not self.classifier:
            logger.error("Model not loaded")
            return

        logger.info("Starting emotion recognition")
        self.is_running = True
        self.current_audio_offset = 0.0
        self.audio_buffer = np.array([], dtype=np.float32)
        self.emotion_history.clear()

        # Clear queues
        self._clear_queue(self.emotion_results_queue)

        # Start recognition thread
        self.recognition_thread = threading.Thread(target=self._recognition_loop, daemon=True)
        self.recognition_thread.start()
        
        logger.info("Emotion recognition started")

    def stop(self) -> None:
        """Stop the emotion recognition process."""
        if not self.is_running:
            logger.warning("Not running")
            return

        logger.info("Stopping emotion recognition")
        self.is_running = False
        
        if self.recognition_thread and self.recognition_thread.is_alive():
            self.recognition_thread.join(timeout=3.0)
            if self.recognition_thread.is_alive():
                logger.warning("Recognition thread did not stop gracefully")
        
        self.recognition_thread = None
        logger.info("Emotion recognition stopped")

    def get_emotion_results_queue(self) -> queue.Queue:
        """Get the queue containing emotion recognition results."""
        return self.emotion_results_queue

    def get_latest_emotion(self) -> Optional[Tuple[float, str, float]]:
        """
        Get the most recent emotion result without blocking.
        
        Returns:
            Tuple of (timestamp, emotion, confidence) or None if no results
        """
        try:
            result = self.emotion_results_queue.get_nowait()
            return result[:3]  # timestamp, emotion, confidence
        except queue.Empty:
            return None

    def get_stats(self) -> Dict[str, Any]:
        """Get recognition statistics."""
        return {
            'is_running': self.is_running,
            'current_offset': self.current_audio_offset,
            'buffer_size': len(self.audio_buffer),
            'results_pending': self.emotion_results_queue.qsize(),
            'device': self.device,
            'model': self.model_name
        }

    @staticmethod
    def _clear_queue(q: queue.Queue) -> None:
        """Clear all items from a queue."""
        while not q.empty():
            try:
                q.get_nowait()
            except queue.Empty:
                break

# Test and demo code
if __name__ == '__main__':
    import sys
    
    def run_emotion_recognition_demo():
        """Run a demonstration of the emotion recognition system."""
        print("=== Speech Emotion Recognition Demo ===\n")
        
        # Configuration
        SAMPLE_RATE = 16000
        CHUNK_DURATION = 0.25  # Faster chunks for more responsive demo
        ACCUMULATION_DURATION = 2.0
        OVERLAP_DURATION = 0.5
        SIMULATION_TIME = 15.0
        
        # Create audio queue
        audio_queue = queue.Queue()
        
        # Initialize recognizer
        print("Initializing recognizer...")
        try:
            recognizer = SpeechEmotionRecognizer(
                audio_queue,
                sample_rate=SAMPLE_RATE,
                accumulation_seconds=ACCUMULATION_DURATION,
                overlap_seconds=OVERLAP_DURATION,
                min_confidence_threshold=0.2
            )
        except Exception as e:
            print(f"Failed to initialize: {e}")
            return 1
        
        # Start recognition
        recognizer.start()
        
        # Audio producer thread
        def produce_simulated_audio():
            """Generate simulated audio with varying characteristics."""
            print(f"Generating {SIMULATION_TIME}s of simulated audio...")
            
            chunk_samples = int(SAMPLE_RATE * CHUNK_DURATION)
            total_chunks = int(SIMULATION_TIME / CHUNK_DURATION)
            
            for i in range(total_chunks):
                if not recognizer.is_running:
                    break
                
                # Create different audio patterns
                t = i * CHUNK_DURATION
                
                if t < 3:
                    # Low energy (neutral/calm)
                    amplitude = 0.05
                    freq = 200
                elif t < 6:
                    # Higher energy (excitement/happiness)
                    amplitude = 0.15
                    freq = 400
                elif t < 9:
                    # Very low (sadness)
                    amplitude = 0.02
                    freq = 150
                else:
                    # Mixed energy (anger/frustration)
                    amplitude = 0.25
                    freq = 600
                
                # Generate sinusoidal with noise
                time_vec = np.linspace(0, CHUNK_DURATION, chunk_samples)
                signal = amplitude * np.sin(2 * np.pi * freq * time_vec)
                noise = np.random.normal(0, amplitude * 0.1, chunk_samples)
                
                audio_chunk = (signal + noise).astype(np.float32)
                audio_queue.put(audio_chunk)
                
                time.sleep(CHUNK_DURATION)
            
            print("Audio generation completed")
        
        # Start audio producer
        producer_thread = threading.Thread(target=produce_simulated_audio, daemon=True)
        producer_thread.start()
        
        # Monitor results
        print("\nMonitoring emotion recognition results:")
        print("Time  | Emotion    | Confidence | Smoothed")
        print("-" * 45)
        
        results_received = 0
        start_time = time.time()
        
        while time.time() - start_time < SIMULATION_TIME + 5:
            try:
                result = recognizer.get_emotion_results_queue().get(timeout=1.0)
                timestamp, emotion, confidence, all_preds, orig_conf = result
                
                print(f"{timestamp:5.1f} | {emotion:10} | {confidence:7.3f}    | {orig_conf:7.3f}")
                results_received += 1
                
            except queue.Empty:
                if not producer_thread.is_alive():
                    break
        
        # Print final statistics
        print(f"\nResults Summary:")
        print(f"- Total results: {results_received}")
        print(f"- Recognition stats: {recognizer.get_stats()}")
        
        # Cleanup
        print("\nStopping recognizer...")
        recognizer.stop()
        
        if producer_thread.is_alive():
            producer_thread.join(timeout=2)
        
        print("Demo completed successfully!")
        return 0
    
    # Run the demo
    sys.exit(run_emotion_recognition_demo())