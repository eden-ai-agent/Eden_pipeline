import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend

# TODO: For production, salt should be unique per user/installation and stored securely.
# Hardcoding salt is not secure for general use but simplifies this example.
SALT = b'_eden_recorder_fixed_salt_v1.0_'

def generate_aes_key(key_size_bytes=32) -> bytes:
    """
    Generates a random AES key for AES-GCM.
    :param key_size_bytes: Desired key size in bytes (e.g., 32 for AES-256).
    :return: AES key as bytes.
    """
    if key_size_bytes not in [16, 24, 32]: # AES-128, AES-192, AES-256
        raise ValueError("Invalid key size. Must be 16, 24, or 32 bytes.")
    return AESGCM.generate_key(bit_length=key_size_bytes * 8)

def encrypt_data(data_bytes: bytes, key: bytes) -> bytes:
    """
    Encrypts data using AES-GCM.
    :param data_bytes: Data to encrypt (as bytes).
    :param key: AES key (as bytes).
    :return: Encrypted data (nonce + ciphertext) as bytes.
    :raises ValueError: If data_bytes is not bytes or key is invalid.
    """
    if not isinstance(data_bytes, bytes):
        raise ValueError("Data to encrypt must be bytes.")
    if not key or len(key) not in [16, 24, 32]:
        raise ValueError("Invalid AES key.")

    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # AES-GCM standard nonce size is 12 bytes (96 bits)
    encrypted_data = aesgcm.encrypt(nonce, data_bytes, None)  # associated_data=None
    return nonce + encrypted_data

def decrypt_data(encrypted_payload: bytes, key: bytes) -> bytes:
    """
    Decrypts data using AES-GCM.
    :param encrypted_payload: Encrypted data (nonce + ciphertext) as bytes.
    :param key: AES key (as bytes).
    :return: Decrypted data as bytes.
    :raises InvalidTag: If decryption fails (e.g., wrong key, tampered data).
    :raises ValueError: If payload is too short or key is invalid.
    """
    if not isinstance(encrypted_payload, bytes):
        raise ValueError("Encrypted payload must be bytes.")
    if not key or len(key) not in [16, 24, 32]:
        raise ValueError("Invalid AES key.")
    if len(encrypted_payload) < 13: # Nonce (12) + at least 1 byte of data/tag
        raise ValueError("Encrypted payload is too short.")

    nonce = encrypted_payload[:12]
    encrypted_data = encrypted_payload[12:]
    aesgcm = AESGCM(key)
    decrypted_data = aesgcm.decrypt(nonce, encrypted_data, None) # associated_data=None
    return decrypted_data

def encrypt_file(input_filepath: str, key: bytes, output_filepath: str):
    """
    Encrypts a file using AES-GCM.
    :param input_filepath: Path to the file to encrypt.
    :param key: AES key (as bytes).
    :param output_filepath: Path to save the encrypted file.
    """
    try:
        with open(input_filepath, 'rb') as f_in:
            file_content_bytes = f_in.read()

        encrypted_payload = encrypt_data(file_content_bytes, key)

        with open(output_filepath, 'wb') as f_out:
            f_out.write(encrypted_payload)
        # print(f"File '{input_filepath}' encrypted successfully to '{output_filepath}'.")
    except FileNotFoundError:
        print(f"Error: Input file not found at '{input_filepath}'.")
        raise
    except Exception as e:
        print(f"Error during file encryption: {e}")
        raise

def decrypt_file(encrypted_filepath: str, key: bytes, output_filepath: str):
    """
    Decrypts a file using AES-GCM.
    :param encrypted_filepath: Path to the encrypted file.
    :param key: AES key (as bytes).
    :param output_filepath: Path to save the decrypted file.
    """
    try:
        with open(encrypted_filepath, 'rb') as f_in:
            encrypted_payload_bytes = f_in.read()

        decrypted_data = decrypt_data(encrypted_payload_bytes, key)

        with open(output_filepath, 'wb') as f_out:
            f_out.write(decrypted_data)
        # print(f"File '{encrypted_filepath}' decrypted successfully to '{output_filepath}'.")
    except FileNotFoundError:
        print(f"Error: Encrypted file not found at '{encrypted_filepath}'.")
        raise
    except InvalidTag:
        print(f"Error: Decryption failed for '{encrypted_filepath}'. Invalid key or tampered data.")
        # Optionally, delete the potentially corrupted output file if created
        if os.path.exists(output_filepath): os.remove(output_filepath)
        raise
    except Exception as e:
        print(f"Error during file decryption: {e}")
        raise

def wrap_session_key(session_key: bytes, master_key: bytes) -> bytes:
    """
    Wraps (encrypts) a session key using a master key.
    :param session_key: The session key to wrap (bytes).
    :param master_key: The master key to use for wrapping (bytes).
    :return: Wrapped (encrypted) session key as bytes.
    """
    return encrypt_data(session_key, master_key)

def unwrap_session_key(wrapped_session_key: bytes, master_key: bytes) -> bytes:
    """
    Unwraps (decrypts) a session key using a master key.
    :param wrapped_session_key: The wrapped (encrypted) session key (bytes).
    :param master_key: The master key to use for unwrapping (bytes).
    :return: Original session key as bytes.
    """
    return decrypt_data(wrapped_session_key, master_key)

if __name__ == '__main__':
    print("--- Testing Encryption Utilities ---")

    # Key Generation
    master_k = generate_aes_key()
    session_k = generate_aes_key()
    print(f"Master Key (hex): {master_k.hex()}")
    print(f"Session Key (hex): {session_k.hex()}")

    # Data Encryption/Decryption
    print("\n--- Data Encryption/Decryption Test ---")
    original_data = b"This is some secret data for testing AES-GCM."
    print(f"Original data: {original_data.decode()}")
    try:
        encrypted_payload_data = encrypt_data(original_data, session_k)
        print(f"Encrypted payload (data) length: {len(encrypted_payload_data)}")
        decrypted_data = decrypt_data(encrypted_payload_data, session_k)
        print(f"Decrypted data: {decrypted_data.decode()}")
        assert original_data == decrypted_data, "Data decryption mismatch!"
        print("Data encryption/decryption: SUCCESS")
    except Exception as e:
        print(f"Data encryption/decryption test FAILED: {e}")

    # File Encryption/Decryption
    print("\n--- File Encryption/Decryption Test ---")
    dummy_input_file = "test_plain.txt"
    dummy_enc_file = "test_encrypted.enc"
    dummy_dec_file = "test_decrypted.txt"
    file_test_content = b"This is content for file encryption and decryption testing. \nIt includes multiple lines."

    try:
        with open(dummy_input_file, "wb") as f: f.write(file_test_content)

        encrypt_file(dummy_input_file, session_k, dummy_enc_file)
        print(f"'{dummy_input_file}' encrypted to '{dummy_enc_file}'.")

        decrypt_file(dummy_enc_file, session_k, dummy_dec_file)
        print(f"'{dummy_enc_file}' decrypted to '{dummy_dec_file}'.")

        with open(dummy_dec_file, "rb") as f: recovered_content = f.read()
        assert file_test_content == recovered_content, "File content mismatch after decryption!"
        print("File encryption/decryption: SUCCESS")

    except Exception as e:
        print(f"File encryption/decryption test FAILED: {e}")
    finally:
        # Cleanup dummy files
        for f_path in [dummy_input_file, dummy_enc_file, dummy_dec_file]:
            if os.path.exists(f_path): os.remove(f_path)
        print("Dummy files cleaned up.")

    # Session Key Wrapping/Unwrapping
    print("\n--- Session Key Wrapping/Unwrapping Test ---")
    try:
        wrapped_sk = wrap_session_key(session_k, master_k)
        print(f"Session key wrapped (length: {len(wrapped_sk)} bytes).")
        unwrapped_sk = unwrap_session_key(wrapped_sk, master_k)
        assert session_k == unwrapped_sk, "Session key unwrap mismatch!"
        print(f"Session key unwrapped successfully: {unwrapped_sk.hex()}")
        print("Session key wrapping/unwrapping: SUCCESS")
    except Exception as e:
        print(f"Session key wrapping/unwrapping test FAILED: {e}")

    print("\n--- Testing Error Cases (Intentional) ---")
    # Test decryption with wrong key
    try:
        wrong_key = generate_aes_key()
        decrypt_data(encrypted_payload_data, wrong_key)
    except InvalidTag:
        print("Caught InvalidTag with wrong key as expected: SUCCESS")
    except Exception as e:
        print(f"Wrong key test FAILED unexpectedly: {e}")

    # Test with too short payload
    try:
        decrypt_data(b"short", session_k)
    except ValueError as e:
        if "too short" in str(e):
            print(f"Caught ValueError for short payload as expected ('{e}'): SUCCESS")
        else:
            print(f"Short payload test FAILED with unexpected ValueError: {e}")
    except Exception as e:
        print(f"Short payload test FAILED unexpectedly: {e}")

    print("\n--- All Tests Finished ---")


def derive_key_from_password(password: str, salt: bytes = SALT, iterations: int = 100000, key_length: int = 32) -> bytes:
    """
    Derives a key from a password using PBKDF2-HMAC-SHA256.
    :param password: The user's password.
    :param salt: Salt for KDF. Should be unique and stored securely if not fixed.
    :param iterations: Number of iterations for PBKDF2 (e.g., 100,000 to 600,000).
    :param key_length: Desired key length in bytes (e.g., 32 for AES-256).
    :return: Derived key as bytes.
    """
    if not password:
        raise ValueError("Password cannot be empty.")
    password_bytes = password.encode('utf-8')

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=key_length,
        salt=salt,
        iterations=iterations,
        backend=default_backend() # Explicitly specify backend
    )
    derived_key = kdf.derive(password_bytes)
    return derived_key

if __name__ == '__main__':
    # ... (previous tests remain)
    print("\n--- Testing Key Derivation ---")
    test_password = "MyStrongPassword123!"
    try:
        derived_k = derive_key_from_password(test_password)
        print(f"Derived key from password (hex): {derived_k.hex()}")
        assert len(derived_k) == 32, "Derived key length is incorrect."

        # Test with same password and salt yields same key
        derived_k2 = derive_key_from_password(test_password)
        assert derived_k == derived_k2, "Key derivation not deterministic with same salt."

        # Test with different salt yields different key
        different_salt = os.urandom(16)
        derived_k3 = derive_key_from_password(test_password, salt=different_salt)
        assert derived_k != derived_k3, "Key derivation with different salt produced same key."
        print("Key derivation tests: SUCCESS")

    except Exception as e:
        print(f"Key derivation test FAILED: {e}")

    print("\n--- All Tests (including new ones) Finished ---")
