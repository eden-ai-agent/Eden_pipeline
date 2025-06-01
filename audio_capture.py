import sounddevice as sd
import soundfile as sf
import numpy as np
import time
import queue # Added for audio chunk queue

class AudioRecorder:
    def __init__(self):
        self.frames = []
        self.stream = None
        self.samplerate = 44100  # Default samplerate
        self.channels = 1        # Default channels
        self.is_recording = False
        self.audio_chunk_queue = queue.Queue() # Queue for live audio data (RMS for VU meter)
        self.transcription_audio_queue = queue.Queue() # Queue for raw audio chunks for transcription

    def _audio_callback(self, indata, frame_count, time_info, status):
        """This is called (from a separate thread) for each audio block."""
        if status:
            print(f"Audio callback status: {status}", flush=True)

        # Make a copy for safety, as indata buffer might be reused by PortAudio
        current_chunk = indata.copy()

        # Append raw data for saving the full audio file
        self.frames.append(current_chunk)

        # Calculate RMS of the current chunk and put it on the VU meter queue
        try:
            rms = np.sqrt(np.mean(current_chunk**2))
            self.audio_chunk_queue.put(rms)
        except Exception as e:
            print(f"Error calculating RMS or putting to VU meter queue: {e}", flush=True)

        # Put the raw audio chunk onto the transcription queue
        try:
            self.transcription_audio_queue.put(current_chunk)
        except Exception as e:
            print(f"Error putting to transcription queue: {e}", flush=True)


    def start_recording(self, channels=1, samplerate=44100):
        if self.is_recording:
            print("Recording is already in progress.")
            return

        self.channels = channels
        self.samplerate = samplerate
        self.frames = []  # Clear previous frames

        try:
            # Query devices and select a default input device if available
            # print(sd.query_devices()) # Useful for debugging device issues
            # Consider blocksize for InputStream for more controlled chunk sizes if needed
            # For example, blocksize=int(samplerate * 0.1) # 100ms chunks
            self.stream = sd.InputStream(
                samplerate=self.samplerate,
                channels=self.channels,
                callback=self._audio_callback
                # device=input_device # Can specify device if needed,
                # blocksize= desired_block_size # can be set to control callback frequency/chunk size
            )
            # Clear the queues before starting a new recording
            while not self.audio_chunk_queue.empty():
                try:
                    self.audio_chunk_queue.get_nowait()
                except queue.Empty:
                    break
            while not self.transcription_audio_queue.empty():
                try:
                    self.transcription_audio_queue.get_nowait()
                except queue.Empty:
                    break
            self.stream.start()
            self.is_recording = True
            print("Recording started...")
        except Exception as e:
            print(f"Error starting recording: {e}")
            self.is_recording = False # Ensure state is correct

    def stop_recording(self, output_filename="temp_full_audio.wav"):
        if not self.is_recording:
            print("Recording is not in progress or already stopped.")
            return

        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        self.is_recording = False
        print("Recording stopped.")

        if not self.frames:
            print("No frames recorded.")
            return

        try:
            # Concatenate all frames into a single numpy array
            audio_data = np.concatenate(self.frames, axis=0)
            # Save the audio data as a WAV file
            sf.write(output_filename, audio_data, self.samplerate)
            print(f"Audio saved to {output_filename}")
        except Exception as e:
            print(f"Error saving audio file: {e}")

    def get_audio_chunk_queue(self):
        """Returns the queue for accessing live audio RMS values (for VU meter)."""
        return self.audio_chunk_queue

    def get_transcription_audio_queue(self):
        """Returns the queue for accessing live raw audio chunks (for transcription)."""
        return self.transcription_audio_queue

if __name__ == '__main__':
    recorder = AudioRecorder()

    # Test Case 1: Basic recording and queue check (conceptual)
    print("\n--- Test Case: Start Recording (3 seconds), check queue conceptually ---")
    try:
        print("Available audio devices:", sd.query_devices())
    except Exception as e:
        print(f"Could not query audio devices: {e}")
        print("Attempting to record anyway...")

    recorder.start_recording(samplerate=44100, channels=1)

    if recorder.is_recording:
        # In a real app, another thread or a QTimer would read from the queue.
        # Here, we'll just simulate a short recording period and then check the queues.
        print("Simulating recording for 3 seconds...")

        live_rms_checks = 0
        live_transcription_checks = 0

        for i in range(15): # Try to read a few initial chunks (e.g., 15 * 0.2s = 3s)
            time.sleep(0.2) # Wait a bit for chunks to arrive
            try:
                rms_val = recorder.get_audio_chunk_queue().get_nowait()
                # print(f"RMS from queue (live): {rms_val:.4f}")
                live_rms_checks +=1
            except queue.Empty:
                pass
            try:
                audio_chunk = recorder.get_transcription_audio_queue().get_nowait()
                # print(f"Audio chunk for transcription (live): shape {audio_chunk.shape}, dtype {audio_chunk.dtype}")
                live_transcription_checks +=1
            except queue.Empty:
                pass

        print(f"Live checks: RMS queue got {live_rms_checks} items, Transcription queue got {live_transcription_checks} items.")
        # time.sleep(1) # Ensure recording runs for roughly 3 seconds. This time.sleep is now part of the loop.

        recorder.stop_recording("test_audio_3s_with_queues.wav")

        print("\nPost-recording queue checks:")
        rms_q = recorder.get_audio_chunk_queue()
        rms_count = 0
        while not rms_q.empty():
            try:
                rms_q.get_nowait()
                rms_count +=1
            except queue.Empty:
                break
        print(f"Number of RMS values remaining in VU meter queue: {rms_count}")
        if live_rms_checks == 0 and rms_count == 0 and recorder.frames:
             print("Warning: Frames were recorded, but RMS (VU meter) queue is empty. Check callback logic.")

        transcription_q = recorder.get_transcription_audio_queue()
        transcription_count = 0
        total_samples = 0
        while not transcription_q.empty():
            try:
                chunk = transcription_q.get_nowait()
                total_samples += len(chunk)
                transcription_count +=1
            except queue.Empty:
                break
        print(f"Number of raw audio chunks remaining in transcription queue: {transcription_count}")
        print(f"Total audio samples in transcription queue (post-recording): {total_samples}")

        if live_transcription_checks == 0 and transcription_count == 0 and recorder.frames:
             print("Warning: Frames were recorded, but transcription queue is empty. Check callback logic.")
        elif recorder.frames:
            expected_total_samples = sum(len(f) for f in recorder.frames)
            print(f"Total samples recorded to self.frames: {expected_total_samples}")
            if total_samples != expected_total_samples:
                 print(f"Warning: Mismatch in samples. Transcription queue had {total_samples}, self.frames had {expected_total_samples}")


    else:
        print("Failed to start recording. Check audio device availability and permissions.")

    print("\nAudio recording test with both queues finished.")
