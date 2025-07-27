import os
import re
import logging
import json
from pathlib import Path

# --- Configuration ---
VIDEO_EXTENSIONS = ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm']

# --- New: Patterns to remove from filename before AV code extraction (case-insensitive) ---
# These patterns represent common prefixes/suffixes or delimiters that are NOT part of the AV code itself.
# They will be removed to clean the filename for more accurate AV code matching.
JUNK_PATTERNS = [
    r'hhd\d+\.com@',  # e.g., "hhd800.com@"
    r'\[.*?\]',  # e.g., "[Any text in brackets]"
    r'\(.*?\)',  # e.g., "(Any text in parentheses)"
    r'_uncensored_',  # e.g., "_uncensored_"
    r'_jav_',  # e.g., "_jav_"
    r'^\s*-\s*',  # Leading hyphen with spaces
    r'\s*-\s*$',  # Trailing hyphen with spaces
    r'^\s*@\s*',  # Leading @ with spaces
    r'\s*@\s*$',  # Trailing @ with spaces
    r'^\s*\[.*?\]\s*',  # [Any text in brackets] at start/end
    r'^\s*\(.*?\)\s*',  # (Any text in parentheses) at start/end
    r'^\s*www\..*?\.\w{2,3}\s*@?\s*',  # e.g., "www.example.com@" at the start
    r'\s*@\s*www\..*?\.\w{2,3}\s*$',  # e.g., "@www.example.com" at the end
    r'^\s*\[\s*(\d{2,5}[A-Z]{2,5}[-_]?\d{2,5}|\d{2,5}[A-Z]{2,5}\d{2,5}|[A-Z]{2,5}[-_]?\d{2,5})\s*\]',
    # AV code in brackets at start, e.g., [SSIS-001]
    r'^\s*\(\s*(\d{2,5}[A-Z]{2,5}[-_]?\d{2,5}|\d{2,5}[A-Z]{2,5}\d{2,5}|[A-Z]{2,5}[-_]?\d{2,5})\s*\)',
    # AV code in parentheses at start
]


def clean_filename_for_av_code(filename: str) -> str:
    """
    清理文件名，去除常见无关前缀和后缀，为AV番号提取做准备。

    args:
        filename (str): 原始文件名。

    return:
        str: 清理后的文件名。
    """
    cleaned_filename = filename
    for pattern in JUNK_PATTERNS:
        # Use re.sub with re.IGNORECASE for case-insensitive replacement
        cleaned_filename = re.sub(pattern, '', cleaned_filename, flags=re.IGNORECASE).strip()
    return cleaned_filename


# --- Helper function: Extract AV Code and Segment Identifier ---
def extract_av_code_and_segment(filename: str) -> tuple[str | None, str | None]:
    """
    从文件名中提取AV番号和分段标识符。

    args:
        filename (str): 视频文件名。

    return:
        tuple[str | None, str | None]: 包含(base_av_code, segment_id)的元组。
                                       segment_id将是原始文件名，如果找到base_av_code。
                                      如果没有找到AV番号，则返回(None, None)。
    """
    original_filename = filename  # Keep original filename for segment_id

    # First, clean the filename to remove junk patterns
    filename_for_extraction = clean_filename_for_av_code(original_filename)
    filename_for_extraction_upper = filename_for_extraction.upper()  # Convert to uppercase for consistent matching

    # Prioritize matching common AV code patterns as the base code
    # Patterns include: letters-numbers (ABP-123), numbers-letters-numbers (001ABC-001), letters-numbers-numbers (ABC001-001)
    # Considering possible delimiters (-, _) and quality identifiers (-FHD, -SD)
    base_av_patterns = [
        r'([A-Z]{2,5}[-_]?\d{2,5})',  # PRED-782, SSIS-001, ABP_123
        r'(\d{2,5}[A-Z]{2,5}[-_]?\d{2,5})',  # 001ABC-001 (e.g., 001ABC-001)
        r'([A-Z]{2,5}\d{2,5}[-_]?\d{2,5})',  # ABC001-001 (e.g., ABC001-001)
    ]

    base_av_code = None

    for pattern in base_av_patterns:
        match = re.search(pattern, filename_for_extraction_upper)
        if match:
            base_av_code = match.group(1).replace('_', '-')  # Standardize delimiter to hyphen
            # Remove potential quality identifiers within the code (e.g., -FHD, -SD)
            base_av_code = re.sub(r'-(FHD|SD|HD)\b', '', base_av_code)
            break  # Stop after finding the first match

    if not base_av_code:
        return None, None  # No AV code found after cleaning and pattern matching

    # New logic: If the extracted base_av_code is in the format "LETTERSNumbers" (e.g., DNJR139),
    # insert a hyphen between the letters and numbers.
    # This specifically targets cases like DNJR139 -> DNJR-139
    if base_av_code and re.match(r'^[A-Z]+\d+$', base_av_code):
        # Find the split point between letters and numbers
        match_split = re.match(r'^([A-Z]+)(\d+)$', base_av_code)
        if match_split:
            alpha_part = match_split.group(1)
            num_part = match_split.group(2)
            base_av_code = f"{alpha_part}-{num_part}"
            logging.debug(f"Normalized AV code from {match_split.group(0)} to {base_av_code}")

    # If a base AV code is found, the entire original filename is used as the segment_id.
    # This ensures each video file has a unique identifier based on its original name.
    return base_av_code, original_filename


# --- Core Function: Scan Video Files ---
def scan_videos(video_base_dir: str, status_dict: dict) -> dict:
    """
    扫描指定目录及其子目录下的视频文件，并更新状态字典。
    支持多分段视频，将信息组织在base_av_code下的'segments'字典中。

    args:
        video_base_dir (str): 视频文件根目录。
        status_dict (dict): 当前处理状态字典。

    return:
        dict: 更新后的处理状态字典。
    """
    logging.info(f"Starting video scan in directory: {video_base_dir}")
    print(f'[Video Scanner] Starting scan in directory: {video_base_dir}')

    if not os.path.isdir(video_base_dir):
        logging.error(f"Video root directory does not exist or is not a directory: {video_base_dir}")
        print(f'[Video Scanner] Error: Video root directory does not exist or is not a directory: {video_base_dir}')
        return status_dict  # Return original dictionary

    scanned_new_segments_count = 0
    skipped_existing_segments_count = 0

    for root, _, files in os.walk(video_base_dir):
        for file in files:
            file_extension = os.path.splitext(file)[1].lower()
            if file_extension in VIDEO_EXTENSIONS:
                video_path = os.path.join(root, file)
                # segment_id is now the original filename
                base_av_code, segment_id = extract_av_code_and_segment(file)

                if base_av_code:
                    # Get the absolute path of the video file
                    absolute_video_path = os.path.abspath(video_path)

                    # Ensure the base AV code exists in status_dict
                    status_dict.setdefault(base_av_code, {})
                    status_dict[base_av_code].setdefault('segments', {})  # Ensure 'segments' dictionary exists

                    # Check if this segment (using original filename as key) has already been scanned
                    if segment_id in status_dict[base_av_code]['segments'] and \
                            status_dict[base_av_code]['segments'][segment_id].get('scanned'):
                        # If already scanned, update path and skip, but ensure path is up-to-date
                        status_dict[base_av_code]['segments'][segment_id]['full_path'] = absolute_video_path
                        skipped_existing_segments_count += 1
                        continue  # Skip already scanned segment

                    # Update or create segment information
                    status_dict[base_av_code]['segments'][segment_id] = status_dict[base_av_code]['segments'].get(
                        segment_id, {})
                    status_dict[base_av_code]['segments'][segment_id].update({
                        'scanned': True,
                        'full_path': absolute_video_path,  # Add the absolute path of the video
                        'video_file_name': file,
                        # Record the original filename (same as segment_id but kept for clarity)
                        # Initialize other processing states as pending
                        'audio_extractor': 'pending',
                        'transformer': 'pending',
                        'sch_translator': 'pending',
                        'bilingual': 'pending'
                    })
                    scanned_new_segments_count += 1
                    logging.info(f"Scanned video segment: {base_av_code} (File: {file})")
                    print(f'[Video Scanner] Scanned video segment: {base_av_code} (File: {file})')
                else:
                    logging.warning(f"Could not extract AV code from filename: {file} (Path: {video_path})")

    logging.info(
        f"Video scan completed. Added {scanned_new_segments_count} new segments, skipped {skipped_existing_segments_count} already scanned segments.")
    print(
        f'[Video Scanner] Scan completed. Added {scanned_new_segments_count} new segments, skipped {skipped_existing_segments_count} existing segments.')
    return status_dict


# --- Example Usage (for testing this module independently) ---
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(module)s %(levelname)s: %(message)s',
                        encoding='utf-8')
    import shutil  # Import shutil for test cleanup

    # Create a virtual video directory structure for testing
    test_base_dir = "test_videos_for_scanner_flexible"
    os.makedirs(os.path.join(test_base_dir, "AUKS-083"), exist_ok=True)
    os.makedirs(os.path.join(test_base_dir, "PRED-782"), exist_ok=True)
    os.makedirs(os.path.join(test_base_dir, "Single"), exist_ok=True)
    os.makedirs(os.path.join(test_base_dir, "MultiPart"), exist_ok=True)
    os.makedirs(os.path.join(test_base_dir, "TestCases"), exist_ok=True)  # Ensure directory exists for test cases

    # Create dummy video files (multi-segment, various naming styles)
    with open(os.path.join(test_base_dir, "AUKS-083", "AUKS-083-1 女女同志 早川.mp4"), "w") as f:
        f.write("dummy video 1")
    with open(os.path.join(test_base_dir, "AUKS-083", "AUKS-083-2 女女同志 早川.mp4"), "w") as f:
        f.write("dummy video 2")
    with open(os.path.join(test_base_dir, "AUKS-083", "AUKS-083-3.mkv"), "w") as f:
        f.write("dummy video 3")  # Simplified filename
    with open(os.path.join(test_base_dir, "MultiPart", "ABCD-001 Part 2.mp4"), "w") as f:
        f.write("dummy video part 2")
    with open(os.path.join(test_base_dir, "MultiPart", "XYZ-005 (C).mp4"), "w") as f:
        f.write("dummy video segment C")
    with open(os.path.join(test_base_dir, "MultiPart", "MDR-007 [A].mp4"), "w") as f:
        f.write("dummy video segment A")

    # Test case for the reported issue: hhd800.com@RKI-715
    with open(os.path.join(test_base_dir, "TestCases", "hhd800.com@RKI-715.mp4"), "w") as f:
        f.write("dummy video RKI-715")

    # New test case for DNJR139 -> DNJR-139
    with open(os.path.join(test_base_dir, "TestCases", "DNJR139.mp4"), "w") as f:
        f.write("dummy video DNJR139")

    # Create dummy video files (single segment)
    with open(os.path.join(test_base_dir, "PRED-782", "PRED-782-FHD.mp4"), "w") as f:
        f.write("dummy video PRED")
    with open(os.path.join(test_base_dir, "Single", "SSIS-456.avi"), "w") as f:
        f.write("dummy video SSIS")

    # Create an unrecognizable video
    with open(os.path.join(test_base_dir, "Unmatched.mp4"), "w") as f:
        f.write("dummy video unmatched")

    # Simulate loading existing status (or empty status)
    status_json_path = "test_status_scanner_flexible.json"
    if os.path.exists(status_json_path):
        with open(status_json_path, 'r', encoding='utf-8') as f:
            initial_status = json.load(f)
    else:
        initial_status = {}

    print("\n--- First Scan ---")
    updated_status = scan_videos(test_base_dir, initial_status)
    print("\n--- First Scan Result ---")
    print(json.dumps(updated_status, indent=2, ensure_ascii=False))
    with open(status_json_path, 'w', encoding='utf-8') as f:
        json.dump(updated_status, f, indent=2, ensure_ascii=False)

    # Verify the specific test cases
    if "RKI-715" in updated_status and "hhd800.com@RKI-715.mp4" in updated_status["RKI-715"]["segments"]:
        print(f"\n{os.path.basename(__file__)}: Successfully extracted RKI-715 from hhd800.com@RKI-715.mp4!")
    else:
        print(f"\n{os.path.basename(__file__)}: Failed to extract RKI-715 from hhd800.com@RKI-715.mp4.")

    if "DNJR-139" in updated_status and "DNJR139.mp4" in updated_status["DNJR-139"]["segments"]:
        print(f"\n{os.path.basename(__file__)}: Successfully extracted DNJR-139 from DNJR139.mp4!")
    else:
        print(f"\n{os.path.basename(__file__)}: Failed to extract DNJR-139 from DNJR139.mp4.")

    print("\n--- Second Scan (Testing skipping already scanned files) ---")
    # Simulate one segment being processed, check if it's skipped
    # Note: The key here is now the full original filename
    if "AUKS-083" in updated_status and "AUKS-083-1 女女同志 早川.mp4" in updated_status["AUKS-083"]["segments"]:
        updated_status["AUKS-083"]["segments"]["AUKS-083-1 女女同志 早川.mp4"]["audio_extractor"] = "done"
        updated_status["AUKS-083"]["segments"]["AUKS-083-1 女女同志 早川.mp4"]["transformer"] = "done"
        updated_status["AUKS-083"]["segments"]["AUKS-083-1 女女同志 早川.mp4"]["sch_translator"] = "done"
        updated_status["AUKS-083"]["segments"]["AUKS-083-1 女女同志 早川.mp4"]["bilingual"] = "done"
        print("\nSimulated AUKS-083-1 女女同志 早川.mp4 as processed.")

    updated_status_again = scan_videos(test_base_dir, updated_status)
    print("\n--- Second Scan Result ---")
    print(json.dumps(updated_status_again, indent=2, ensure_ascii=False))

    # Clean up test files and directory
    print("\n--- Cleaning up test files ---")
    if os.path.exists(test_base_dir):
        shutil.rmtree(test_base_dir)
        print(f"Deleted test directory: {test_base_dir}")
    if os.path.exists(status_json_path):
        os.remove(status_json_path)
        print(f"Deleted test status file: {status_json_path}")
    print("Test cleanup completed.")
