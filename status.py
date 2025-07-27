import json
import os
import logging

STATUS_FILE = 'status.json'

def load_status(file_path=STATUS_FILE) -> dict:
    """
    Loads the processing status from a JSON file.

    Args:
        file_path (str): The path to the status JSON file.

    Returns:
        dict: The loaded status dictionary, or an empty dictionary if the file
              does not exist or is corrupted.
    """
    if not os.path.exists(file_path):
        logging.info(f"Status file '{file_path}' not found. Starting with empty status.")
        return {}
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            status = json.load(f)
            logging.info(f"Status loaded successfully from '{file_path}'.")
            return status
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON from status file '{file_path}': {e}. Starting with empty status.")
        return {}
    except Exception as e:
        logging.error(f"An unexpected error occurred while loading status file '{file_path}': {e}. Starting with empty status.", exc_info=True)
        return {}

def save_status(status_dict: dict, file_path=STATUS_FILE):
    """
    Saves the current processing status to a JSON file.

    Args:
        status_dict (dict): The dictionary containing the current processing status.
        file_path (str): The path to the status JSON file.
    """
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(status_dict, f, indent=2, ensure_ascii=False)
            logging.info(f"Status saved successfully to '{file_path}'.")
    except Exception as e:
        logging.error(f"An error occurred while saving status file '{file_path}': {e}", exc_info=True)

# Example usage (for testing this module independently)
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

    # Test loading
    print("--- Testing load_status ---")
    current_status = load_status('test_status.json')
    print(f"Loaded status: {current_status}")

    # Test saving
    print("\n--- Testing save_status ---")
    current_status['TEST-001'] = {
        'metadata_crawled': True,
        'segments': {
            'TEST-001-A.mp4': {
                'full_path': '/path/to/TEST-001-A.mp4',
                'audio_extractor': 'done',
                'transformer': 'pending'
            },
            'TEST-001-B.mp4': {
                'full_path': '/path/to/TEST-001-B.mp4',
                'audio_extractor': 'pending'
            }
        }
    }
    save_status(current_status, 'test_status.json')
    print("Status saved.")

    # Verify saved status
    print("\n--- Verifying saved status ---")
    reloaded_status = load_status('test_status.json')
    print(f"Reloaded status: {reloaded_status}")

    # Clean up test file
    if os.path.exists('test_status.json'):
        os.remove('test_status.json')
        print("\nCleaned up 'test_status.json'.")
