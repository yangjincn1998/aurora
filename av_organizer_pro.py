import os
import json
import shutil
import logging
import sys
import re
from pathlib import Path
import glob  # Used to find subtitle files

# Try to import pywin32 library to create .lnk shortcuts
try:
    import win32com.client

    PYWIN32_AVAILABLE = True
    logging.info("pywin32 library is installed, will attempt to create .lnk shortcuts.")
except ImportError:
    PYWIN32_AVAILABLE = False
    logging.warning(
        "pywin32 library is not installed. Will fall back to creating symbolic links (os.symlink) on Windows."
        "Symbolic links may require administrator privileges and appear differently in file explorer.")

# --- Environment and Directory Settings ---
from dotenv import load_dotenv

load_dotenv()

VIDEO_DIRECTORY = Path(os.getenv("VIDEO_DIRECTORY", "./videos")).resolve()
SCH_JP_DIRECTORY = Path(os.getenv("SCH_JP_DIRECTORY", "./subtitles/bilingual")).resolve()  # Bilingual subtitle directory
METADATA_CACHE_DIR = Path("metadata_cache").resolve()  # Assuming metadata_cache directory is in project root

# --- Logging Configuration ---
logging.basicConfig(
    filename='av_organizer_pro.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    encoding='utf-8',
    filemode='w'  # Clear log file on each run
)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
console_handler.setFormatter(formatter)
logging.getLogger().addHandler(console_handler)


# --- Helper Functions: Load and Save status.json ---
def load_status(status_file_path='status.json') -> dict:
    if os.path.exists(status_file_path):
        try:
            with open(status_file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            logging.error(f"Error decoding JSON from {status_file_path}. File might be corrupted.")
            return {}
        except Exception as e:
            logging.error(f"Error loading status file {status_file_path}: {e}")
            return {}
    return {}


def save_status(status_dict: dict, status_file_path='status.json'):
    try:
        with open(status_file_path, 'w', encoding='utf-8') as f:
            json.dump(status_dict, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Error saving status file {status_file_path}: {e}")


# --- Helper Functions: File and Directory Operations (Consistent with main.py and transformer.py) ---
def sanitize_filename(name: str) -> str:
    """
    Cleans a string to make it suitable for use as a filename or directory name.
    Removes characters disallowed in Windows and replaces some special characters.
    """
    cleaned_name = re.sub(r'[<>:"/\\|?*]', '_', name)
    cleaned_name = cleaned_name.rstrip('.')
    cleaned_name = cleaned_name.replace('...', '…')
    cleaned_name = cleaned_name.replace('?', '')
    cleaned_name = cleaned_name.strip()
    return cleaned_name


def get_sanitized_segment_stem(original_filename: str) -> str:
    """
    Extracts a clean, filename-safe "segment stem" from the original filename.
    E.g., "AUKS-083-1 女女同志 早川.mp4" -> "AUKS-083-1 女女同志 早川"
    Then applies filename sanitization.
    """
    stem = Path(original_filename).stem  # Get filename without extension
    return sanitize_filename(stem)


def create_shortcut(target_path: str, shortcut_path: str) -> bool:
    """
    Creates a .lnk shortcut on Windows, or a symbolic link on other systems.
    """
    if not os.path.exists(target_path):
        logging.error(f"Target file does not exist, cannot create shortcut: {target_path}")
        return False

    shortcut_dir = os.path.dirname(shortcut_path)
    if not os.path.exists(shortcut_dir):
        os.makedirs(shortcut_dir)

    if sys.platform == "win32" and PYWIN32_AVAILABLE:
        try:
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortcut(shortcut_path)
            shortcut.TargetPath = target_path
            shortcut.Save()
            logging.debug(f"Created .lnk shortcut: {shortcut_path} -> {target_path}")
            return True
        except Exception as e:
            logging.error(f"Failed to create .lnk shortcut ({shortcut_path} -> {target_path}): {e}", exc_info=True)
            logging.warning("Attempting to create symbolic link as alternative.")
            # If .lnk fails, try creating a symbolic link
            return _create_symlink(target_path, shortcut_path)
    else:
        # Non-Windows systems or pywin32 not available, create symbolic link
        return _create_symlink(target_path, shortcut_path)


def _create_symlink(target_path: str, shortcut_path: str) -> bool:
    """
    Creates a symbolic link.
    """
    # Ensure shortcut_path does not have .lnk suffix, as symlink won't add it
    if sys.platform == "win32" and shortcut_path.lower().endswith(".lnk"):
        symlink_path = shortcut_path[:-4]  # Remove .lnk
    else:
        symlink_path = shortcut_path

    if os.path.exists(symlink_path):
        try:
            # Check if it's a broken symlink
            if os.path.islink(symlink_path) and not os.path.exists(os.readlink(symlink_path)):
                os.remove(symlink_path)
                logging.warning(f"Deleted broken symbolic link: {symlink_path}")
            # If it's a regular file or directory, delete it first to prevent creation failure
            elif not os.path.islink(symlink_path):
                os.remove(symlink_path)
                logging.warning(f"Deleted existing non-symlink file/directory: {symlink_path}")
            else:  # It's a valid symbolic link
                logging.debug(f"Symbolic link already exists and is valid: {symlink_path}")
                return True  # Already exists, no need to recreate
        except OSError as e:
            logging.error(f"Could not delete existing symbolic link/file {symlink_path}: {e}")
            return False

    try:
        os.symlink(target_path, symlink_path)
        logging.debug(f"Created symbolic link: {symlink_path} -> {target_path}")
        return True
    except OSError as e:
        logging.error(f"Failed to create symbolic link ({symlink_path} -> {target_path}): {e}. "
                      f"On Windows, creating symbolic links may require administrator privileges or Developer Mode enabled.",
                      exc_info=True)
        return False


# --- Feature 1: Standardize Directory Structure and Move Files ---
def standardize_video_directory(status_dict: dict, video_dir: str, sch_jp_dir: str):
    """
    Moves video files into standard directories named after their AV code, and copies bilingual subtitles.
    Supports multi-segment videos, moving each segment file into the BASE_AV_CODE directory.
    """
    logging.info(f"Starting to standardize video directory: {video_dir}")
    print(f"\n--- Starting to standardize video directory: {video_dir} ---")

    processed_files_count = 0
    for base_av_code, base_info in list(status_dict.items()):  # Use list() to avoid modifying dict during iteration
        segments = base_info.get('segments', {})
        if not segments:
            logging.warning(f"Skipping base AV code {base_av_code}: No segment information found.")
            continue

        # Create directory for the base AV code
        standard_base_av_dir = os.path.join(video_dir, base_av_code)
        if not os.path.exists(standard_base_av_dir):
            os.makedirs(standard_base_av_dir)
            logging.info(f"Created base AV code directory: {standard_base_av_dir}")

        for segment_id, segment_info in segments.items():  # segment_id is now the original filename
            original_video_path = segment_info.get('full_path')

            # Check if video file exists
            if not original_video_path or not os.path.exists(original_video_path):
                logging.warning(
                    f"Skipping {base_av_code} (Segment: {segment_id}): Original video file '{original_video_path}' does not exist or path is invalid.")
                continue

            # Get original video extension
            original_video_ext = Path(original_video_path).suffix

            # Build new video file path (in base AV code directory, named using sanitized_segment_stem)
            sanitized_segment_stem = get_sanitized_segment_stem(segment_id)
            new_video_filename = f"{sanitized_segment_stem}{original_video_ext}"
            new_video_path = os.path.join(standard_base_av_dir, new_video_filename)

            # If the original video file is already in the standard directory and named correctly, skip moving
            if Path(original_video_path).parent == Path(standard_base_av_dir) and \
                    Path(original_video_path).name == new_video_filename:
                logging.info(
                    f"Video {base_av_code} (Segment: {segment_id}) is already in standard directory {standard_base_av_dir} and correctly named, no move needed.")
                # Still check and copy subtitles to ensure completeness
                copy_bilingual_subtitles(base_av_code, segment_id, standard_base_av_dir, sch_jp_dir)
                processed_files_count += 1
                continue

            logging.info(f"Processing movie {base_av_code} (Segment: {segment_id})...")

            # Move video file
            try:
                # If target path already has a file with the same name, delete it first (to prevent move failure)
                if os.path.exists(new_video_path) and os.path.samefile(original_video_path, new_video_path):
                    logging.info(f"Target file {new_video_path} is the same as source, skipping move.")
                elif os.path.exists(new_video_path):
                    os.remove(new_video_path)
                    logging.warning(f"Deleted old duplicate target video file: {new_video_path}")

                shutil.move(original_video_path, new_video_path)
                logging.info(f"Moved video file: {original_video_path} -> {new_video_path}")
                print(f"  Moved video: {Path(original_video_path).name} -> {new_video_filename}")

                # Update full_path for this segment in status_dict
                segment_info['full_path'] = new_video_path
                status_dict[base_av_code]['segments'][segment_id] = segment_info  # Ensure status_dict is updated
                save_status(status_dict)  # Save status promptly to prevent data loss on interruption
            except shutil.Error as e:
                logging.error(f"Failed to move video file {original_video_path}: {e}", exc_info=True)
                print(f"  Error: Failed to move video file {Path(original_video_path).name}: {e}")
                continue
            except Exception as e:
                logging.error(f"An unknown error occurred while moving video file {original_video_path}: {e}",
                              exc_info=True)
                print(
                    f"  Error: An unknown error occurred while moving video file {Path(original_video_path).name}: {e}")
                continue

            # Copy bilingual subtitle files to the new directory
            copy_bilingual_subtitles(base_av_code, segment_id, standard_base_av_dir, sch_jp_dir)
            processed_files_count += 1

    print(f"\n--- Video directory standardization completed. Processed {processed_files_count} video files. ---")


def copy_bilingual_subtitles(base_av_code: str, segment_id: str, target_dir: str, sch_jp_dir: str):
    """
    Copies bilingual subtitle files (.ass and .srt) to the new video directory, and renames them.
    For multi-segment videos, subtitle files are named as sanitized_segment_stem.ext.
    """
    # Use sanitized_segment_stem to build subtitle filenames
    sanitized_segment_stem = get_sanitized_segment_stem(segment_id)

    # Subtitle files should be named as sanitized_segment_stem-sch-jap.srt/ass (from main.py output)
    # Target filenames will be sanitized_segment_stem.srt/ass
    potential_sub_files = [
        os.path.join(sch_jp_dir, f"{sanitized_segment_stem}-sch-jap.ass"),  # ASS filename generated by main program
        os.path.join(sch_jp_dir, f"{sanitized_segment_stem}-sch-jap.srt")  # SRT filename generated by main program
    ]

    for sub_path in potential_sub_files:
        if os.path.exists(sub_path):
            sub_ext = Path(sub_path).suffix
            # Target subtitle filename matches video file base name
            # If original subtitle is -sch-jap.ass, target is .ass
            if sub_ext == '.ass' and sub_path.endswith('-sch-jap.ass'):
                target_sub_filename = f"{sanitized_segment_stem}.ass"
            elif sub_ext == '.srt' and sub_path.endswith('-sch-jap.srt'):
                target_sub_filename = f"{sanitized_segment_stem}.srt"
            else:  # Fallback or if already clean
                target_sub_filename = f"{sanitized_segment_stem}{sub_ext}"

            target_sub_path = os.path.join(target_dir, target_sub_filename)

            if not os.path.exists(target_sub_path) or not os.path.samefile(sub_path,
                                                                           target_sub_path):  # Avoid copying to self
                try:
                    shutil.copy2(sub_path, target_sub_path)
                    logging.info(f"Copied bilingual subtitle: {sub_path} -> {target_sub_path}")
                    print(f"  Copied subtitle: {Path(sub_path).name} -> {Path(target_sub_path).name}")
                except Exception as e:
                    logging.error(f"Failed to copy subtitle file {sub_path} to {target_sub_path}: {e}", exc_info=True)
                    print(f"  Error: Failed to copy subtitle file {Path(sub_path).name}: {e}")
            else:
                logging.info(f"Subtitle file {target_sub_path} already exists and content is same, skipping copy.")
        else:
            logging.warning(f"Bilingual subtitle file {sub_path} does not exist, cannot copy.")


# --- Feature 2: Update Chinese Translations in status.json ---
def update_translation_from_cache(status_dict: dict, metadata_cache_dir: str):
    """
    Reads JSON files from metadata_cache and updates Chinese translations in status.json.
    This function targets metadata at the base AV code level.
    """
    logging.info(
        f"Starting to update Chinese translations in status.json from metadata cache directory '{metadata_cache_dir}'.")
    print(f"\n--- Starting to update status.json from metadata cache ---")

    if not os.path.exists(metadata_cache_dir):
        logging.warning(f"Metadata cache directory '{metadata_cache_dir}' does not exist, skipping translation update.")
        print(f"Warning: Metadata cache directory '{metadata_cache_dir}' does not exist, skipping.")
        return

    updated_count = 0
    for base_av_code, base_info in status_dict.items():
        if not base_info.get('metadata_crawled'):
            continue  # Only process movies with crawled metadata

        cache_file_path = os.path.join(metadata_cache_dir, f"{base_av_code}.json")
        if not os.path.exists(cache_file_path):
            continue  # Cache file does not exist, skip

        try:
            with open(cache_file_path, 'r', encoding='utf-8') as f:
                cached_metadata = json.load(f)

            if 'metadata' in base_info and isinstance(base_info['metadata'], dict):
                current_metadata = base_info['metadata']
                changed = False

                # Check and update Chinese translations for each field
                # Title
                if cached_metadata.get('title_zh') and cached_metadata['title_zh'] != current_metadata.get('title_zh'):
                    current_metadata['title_zh'] = cached_metadata['title_zh']
                    changed = True

                # Director
                if cached_metadata.get('director_zh') and cached_metadata['director_zh'] != current_metadata.get(
                        'director_zh'):
                    current_metadata['director_zh'] = cached_metadata['director_zh']
                    changed = True

                # Actors list (actors_zh)
                if isinstance(cached_metadata.get('actors_zh'), list) and \
                        cached_metadata['actors_zh'] != current_metadata.get('actors_zh'):
                    current_metadata['actors_zh'] = cached_metadata['actors_zh']
                    # Also update compatibility field actor_zh (single actor name)
                    current_metadata['actor_zh'] = cached_metadata['actors_zh'][0] if cached_metadata[
                        'actors_zh'] else 'N/A'
                    changed = True

                # Categories list (categories_zh)
                if isinstance(cached_metadata.get('categories_zh'), list) and \
                        cached_metadata['categories_zh'] != current_metadata.get('categories_zh'):
                    current_metadata['categories_zh'] = cached_metadata['categories_zh']
                    changed = True

                if changed:
                    base_info['metadata'] = current_metadata  # Update reference to ensure dictionary is modified
                    updated_count += 1
                    logging.info(f"Updated Chinese translations for {base_av_code} from cache.")
                    print(f"  Updated Chinese translations for {base_av_code} from cache.")

        except json.JSONDecodeError:
            logging.error(f"Cache file {cache_file_path} has incorrect format, skipping.")
        except Exception as e:
            logging.error(f"An error occurred while processing cache file {cache_file_path}: {e}", exc_info=True)

    if updated_count > 0:
        save_status(status_dict)
        logging.info(f"Updated Chinese translations for {updated_count} movies in status.json.")
        print(f"\nUpdated Chinese translations for {updated_count} movies in status.json.")
    else:
        print("\nNo Chinese translations found to update.")
    print("\n--- Metadata cache update completed. ---")


# --- Feature 3: Create Blank Info Documents in Movie Directory ---
def create_info_docs(status_dict: dict):
    """
    Creates blank .txt info documents in the base AV code directory of the movie.
    These documents are for the entire movie (all segments).
    """
    logging.info("Starting to create info documents in movie directories.")
    print("\n--- Starting to create info documents in movie directories ---")

    doc_count = 0
    for base_av_code, base_info in status_dict.items():
        # Only need to check if the base AV code directory exists, not each segment's video file
        # because these documents are for the entire AV code

        # Get the full_path of any valid video segment to determine the base AV code directory
        first_segment_path = None
        segments = base_info.get('segments', {})
        if segments:
            for segment_id, segment_info in segments.items():
                if segment_info.get('full_path') and os.path.exists(segment_info['full_path']):
                    first_segment_path = segment_info['full_path']
                    break

        if not first_segment_path:
            logging.warning(f"Skipping creating info documents for {base_av_code}: No valid video file path found.")
            continue

        movie_dir = Path(first_segment_path).parent  # The directory containing the video file is the AV code directory
        metadata = base_info.get('metadata', {})

        # Get translated information, fall back to original or N/A if not present
        title = metadata.get('title_zh') or metadata.get('title', 'Unknown Title')
        actor = metadata.get('actor_zh') or metadata.get('actor', 'Unknown Actor')
        director = metadata.get('director_zh') or metadata.get('director', 'Unknown Director')
        categories = ", ".join(metadata.get('categories_zh', [])) if metadata.get('categories_zh') else \
            (", ".join(metadata.get('categories', [])) if metadata.get('categories') else 'Unknown Type')

        info_items = {
            "片名": title,
            "导演": director,
            "类型": categories,
            "演员": actor,
        }

        for label, value in info_items.items():
            doc_filename = sanitize_filename(f"{label}：{value}.txt")
            doc_path = os.path.join(movie_dir, doc_filename)

            if not os.path.exists(doc_path):
                try:
                    with open(doc_path, 'w', encoding='utf-8') as f:
                        pass  # Create empty file
                    logging.info(f"Created info document: {doc_path}")
                    doc_count += 1
                except Exception as e:
                    logging.error(f"Failed to create info document {doc_filename} for {base_av_code}: {e}",
                                  exc_info=True)

    print(f"\n--- Info documents created or updated in {doc_count} locations. ---")


# --- Feature 4: Build Shortcut Index ---
def build_shortcut_index(status_dict: dict, organized_base_dir: str):
    """
    Organizes video files based on metadata and creates categorized folders and shortcuts.
    Supports multi-segment videos, creating a shortcut for each segment.
    """
    logging.info(f"Starting to build shortcut index to: {organized_base_dir}")
    print(f"\n--- Starting to build shortcut index: {organized_base_dir} ---")

    # Clean up old index directory
    if os.path.exists(organized_base_dir):
        logging.info(f"Cleaning existing index directory: {organized_base_dir}")
        try:
            shutil.rmtree(organized_base_dir)
            logging.info("Cleanup completed.")
        except OSError as e:
            logging.error(f"Failed to clean directory: {e}", exc_info=True)
            print(
                f"Error: Could not clean directory {organized_base_dir}. Please delete manually or check permissions.")
            return

    # Define main categorization directories
    director_dir = os.path.join(organized_base_dir, '导演 (Directors)')
    actor_dir = os.path.join(organized_base_dir, '演员 (Actors)')
    category_dir = os.path.join(organized_base_dir, '类别 (Categories)')

    for d in [director_dir, actor_dir, category_dir]:
        if not os.path.exists(d):
            os.makedirs(d)
            logging.info(f"Created categorization directory: {d}")

    processed_count = 0
    for base_av_code, base_info in status_dict.items():
        metadata = base_info.get('metadata', {})
        segments = base_info.get('segments', {})

        if not metadata or not segments:
            logging.warning(f"Skipping indexing {base_av_code}: Metadata or segment information is missing.")
            continue

        # Get translated information
        title_zh = metadata.get('title_zh') or metadata.get('title', base_av_code)
        actors_zh = metadata.get('actors_zh') or metadata.get('actors', [])
        director_zh = metadata.get('director_zh') or metadata.get('director', 'Unknown Director')
        categories_zh = metadata.get('categories_zh') or metadata.get('categories', [])

        for segment_id, segment_info in segments.items():  # segment_id is now the original filename
            original_video_path = segment_info.get('full_path')  # This should now be the standardized path

            if not original_video_path or not os.path.exists(original_video_path):
                logging.warning(
                    f"Skipping indexing {base_av_code} (Segment: {segment_id}): Video file does not exist or path is invalid.")
                continue

            # Construct shortcut name: includes sanitized_segment_stem and movie title
            sanitized_segment_stem = get_sanitized_segment_stem(segment_id)
            shortcut_name_base = f"{sanitized_segment_stem} - {title_zh}"
            if sys.platform == "win32":
                shortcut_name = sanitize_filename(shortcut_name_base) + ".lnk"
            else:
                shortcut_name = sanitize_filename(shortcut_name_base)  # Symlink doesn't need .lnk suffix

            # --- Organize into Director folder ---
            if director_zh and director_zh != 'Unknown Director':
                safe_director_name = sanitize_filename(director_zh)
                target_director_folder = os.path.join(director_dir, safe_director_name)
                create_shortcut(original_video_path, os.path.join(target_director_folder, shortcut_name))

            # --- Organize into Actor folder ---
            if actors_zh:
                for actor_name in actors_zh:
                    safe_actor_name = sanitize_filename(actor_name)
                    target_actor_folder = os.path.join(actor_dir, safe_actor_name)
                    create_shortcut(original_video_path, os.path.join(target_actor_folder, shortcut_name))

            # --- Organize into Category folder ---
            if categories_zh:
                for category_name in categories_zh:
                    safe_category_name = sanitize_filename(category_name)
                    target_category_folder = os.path.join(category_dir, safe_category_name)
                    create_shortcut(original_video_path, os.path.join(target_category_folder, shortcut_name))

            processed_count += 1
            if processed_count % 50 == 0:
                print(f"  Indexed {processed_count} video segments...")

    logging.info(f"Video index building completed. Indexed {processed_count} video segments.")
    print(f"\n--- Video index building completed. Indexed {processed_count} video segments. ---")


# --- Main Program Entry Point ---
if __name__ == '__main__':
    current_dir = os.path.dirname(os.path.abspath(__file__))
    status_file_path = os.path.join(current_dir, 'status.json')
    metadata_cache_full_path = os.path.join(current_dir, METADATA_CACHE_DIR)

    # MODIFICATION HERE: Ensure index is generated under VIDEO_DIRECTORY
    organized_index_base_dir = os.path.join(VIDEO_DIRECTORY, 'Organized_AV_Index')  # Changed this line

    if not VIDEO_DIRECTORY.exists():
        logging.error(f"Video directory '{VIDEO_DIRECTORY}' does not exist. Please create it.")
        print(f"Error: Video directory '{VIDEO_DIRECTORY}' does not exist. Please create it.")
        sys.exit(1)
    if not SCH_JP_DIRECTORY.exists():
        logging.error(f"Bilingual subtitle directory '{SCH_JP_DIRECTORY}' does not exist. Please create it.")
        print(f"Error: Bilingual subtitle directory '{SCH_JP_DIRECTORY}' does not exist. Please create it.")
        sys.exit(1)

    print("Starting movie management program...")

    # 1. Load initial status
    status_data = load_status(status_file_path)

    # 2. Update Chinese translations in status.json from metadata_cache
    update_translation_from_cache(status_data, metadata_cache_full_path)

    # Reload status_data after update to ensure the latest data
    status_data = load_status(status_file_path)

    # 3. Standardize directory structure, move video files, copy bilingual subtitles
    standardize_video_directory(status_data, VIDEO_DIRECTORY, SCH_JP_DIRECTORY)

    # Reload status_data because standardize_video_directory modifies full_path
    status_data = load_status(status_file_path)

    # 4. Create blank info documents in movie directory (for base AV code)
    create_info_docs(status_data)

    # 5. Build shortcut index (for each segment)
    build_shortcut_index(status_data, organized_index_base_dir)

    print("\nAll movie management tasks completed.")
    logging.info("All movie management tasks completed.")