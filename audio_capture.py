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
            audio_data = np.concatenate(self.frames, axis=0)
            sf.write(output_filepath, audio_data, self.samplerate) # Changed output_filename to output_filepath
            print(f"Audio saved to {output_filepath}")
        except Exception as e:
            print(f"Error saving audio file: {e}")

    def get_audio_chunk_queue(self):
        """Returns the queue for accessing live audio RMS values (for VU meter)."""
        return self.audio_chunk_queue

    def get_transcription_audio_queue(self):
        """Returns the queue for accessing live raw audio chunks (for transcription)."""
        return self.transcription_audio_queue

    def save_redacted_audio(self, output_filepath, mute_segments_time_list): # Changed output_filename to output_filepath
        """
        Saves a version of the recorded audio with specified segments muted.

        :param output_filepath: Full filepath for the redacted audio.
        :param mute_segments_time_list: A list of (start_time, end_time) tuples in seconds.
        """
        if not self.frames:
            print("No frames recorded to save redacted audio from.")
            return
        if self.is_recording:
            print("Cannot save redacted audio while recording is in progress. Stop recording first.")
            return
        if self.samplerate == 0:
            print("Samplerate is 0, cannot process audio for redaction.")
            return

        print(f"Preparing to save redacted audio to {output_filename} with {len(mute_segments_time_list)} mute segments.")

        try:
            full_audio_data = np.concatenate(self.frames, axis=0)
            redacted_audio_data = full_audio_data.copy()

            for start_time, end_time in mute_segments_time_list:
                start_sample = int(start_time * self.samplerate)
                end_sample = int(end_time * self.samplerate)

                # Boundary checks
                if start_sample < 0: start_sample = 0
                if end_sample > len(redacted_audio_data): end_sample = len(redacted_audio_data)
                if start_sample >= end_sample: # If segment is invalid or outside bounds after clamping
                    # print(f"Skipping invalid or out-of-bounds mute segment: ({start_time:.2f}s, {end_time:.2f}s)")
                    continue

                # print(f"Muting from {start_time:.2f}s ({start_sample}) to {end_time:.2f}s ({end_sample})")
                if self.channels == 1:
                    redacted_audio_data[start_sample:end_sample] = 0
                else: # Stereo or multi-channel
                    redacted_audio_data[start_sample:end_sample, :] = 0

            sf.write(output_filename, redacted_audio_data, self.samplerate)
            print(f"Redacted audio saved to {output_filepath}") # Changed output_filename to output_filepath

        except Exception as e:
            print(f"Error saving redacted audio file: {e}")


if __name__ == '__main__':
    import os # For path joining in test
    # Create a dummy test_outputs directory if it doesn't exist
    test_output_dir = "test_outputs_audio_capture"
    os.makedirs(test_output_dir, exist_ok=True)

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

        original_filepath = os.path.join(test_output_dir, "test_audio_3s_original.wav")
        recorder.stop_recording(output_filepath=original_filepath) # Use full path

        print("\n--- Post-recording checks & Redaction Test ---")
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
             print("Warning: Transcription queue was empty during/after recording. Check callback.")
        elif recorder.frames:
            expected_total_samples = sum(len(f) for f in recorder.frames)
            print(f"Total samples in self.frames: {expected_total_samples}")
            if total_samples != expected_total_samples and transcription_count > 0 : # If queue had items but not all
                 print(f"Warning: Sample mismatch. Transcription queue had {total_samples}, self.frames had {expected_total_samples}")

        # Test saving redacted audio
        if recorder.frames:
            dummy_mute_segments = [(0.5, 1.0), (1.5, 2.0), (2.5, 2.8)]
            redacted_filepath = os.path.join(test_output_dir, "test_audio_3s_redacted.wav") # Use full path
            print(f"\nAttempting to save redacted audio to '{redacted_filepath}' with segments: {dummy_mute_segments}")
            recorder.save_redacted_audio(output_filepath=redacted_filepath, mute_segments_time_list=dummy_mute_segments) # Use full path
        else:
            print("\nSkipping redacted audio test as no frames were recorded.")

    else:
        print("Failed to start recording. Check audio device availability and permissions.")

    print("\nAudio recording and redaction test finished.")
