import os
import sys
import shutil
import zipfile
import py7zr
import re
import io
import traceback
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Tuple

# --- 1. SETUP PATHS AND CONSTANTS (.EXE-PROOF) ---
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent.absolute()

BASE_FILE_DIR = BASE_DIR / "01_Original_Game_File"
MODS_DIR = BASE_DIR / "02_Put_Mods_Here"
TEMP_DIR = BASE_DIR / "_temp_extracted_files"
ARCHIVE_DIR = BASE_DIR / "OUTPUT_Merged_Mod"

BASE_PAK_FILENAME = "data0.pak"
BASE_FILENAME_IN_PAK = "scripts/player/player_variables.scr"
FINAL_PLAYER_VARS_PATH = "scripts/player/player_variables.scr"
FINAL_ARCHIVE_NAME = "data3.pak"
PLAYER_VARS_MARKER = ".PLAYER_VARS.scr"

SUPPORTED_ARCHIVE_EXTS = ('.zip', '.pak', '.7z')
SUPPORTED_MOD_EXTS = SUPPORTED_ARCHIVE_EXTS + ('.scr',)

# Global state
other_files_map: Dict[str, List[Dict[str, Any]]] = {}


# --- 2. UNIVERSAL HELPER FUNCTIONS ---
class ArchiveHandler:
    """Handle different archive formats with a unified interface"""
    
    @staticmethod
    def get_filenames(archive_obj: Any, archive_type: str) -> List[str]:
        """Get list of files in archive"""
        if archive_type == 'zip': 
            return archive_obj.namelist()
        if archive_type == '7z': 
            return archive_obj.getnames()
        return []
    
    @staticmethod
    def read_file(archive_obj: Any, archive_type: str, filename: str) -> bytes:
        """Read file from archive"""
        if archive_type == '7z': 
            return archive_obj.read([filename])[filename].getvalue()
        return archive_obj.read(filename)
    
    @staticmethod
    def is_directory(member: Any, archive_type: str) -> bool:
        """Check if archive member is a directory"""
        if archive_type == '7z': 
            return member.is_directory
        return member.is_dir()


def get_param_key(line: str) -> Optional[str]:
    """Extract parameter key from line"""
    match = re.search(r'^\s*Param\s*\(\s*"([^"]+)"', line)
    return match.group(1) if match else None


def safe_read_file(file_path: Path, encoding: str = 'utf-8') -> List[str]:
    """Safely read file with error handling"""
    try:
        with open(file_path, 'r', encoding=encoding, errors='ignore') as f:
            return f.readlines()
    except Exception as e:
        print(f"Error reading file {file_path}: {e}")
        return []


def safe_write_file(file_path: Path, content: Union[str, bytes], mode: str = 'w') -> bool:
    """Safely write file with error handling"""
    try:
        if 'b' in mode:
            with open(file_path, mode) as f:
                f.write(content)
        else:
            with open(file_path, mode, encoding='utf-8') as f:
                f.write(content)
        return True
    except Exception as e:
        print(f"Error writing file {file_path}: {e}")
        return False


# --- CORE SCRIPT FUNCTIONS ---
def setup_directories() -> None:
    """Create necessary directories"""
    print("--- Checking and creating folder structure ---")
    for path in [BASE_FILE_DIR, MODS_DIR, ARCHIVE_DIR]:
        path.mkdir(parents=True, exist_ok=True)
        print(f"Folder '{path.name}' is ready.")


def cleanup() -> None:
    """Clean up temporary files"""
    if TEMP_DIR.exists():
        print("\n--- Cleaning up temporary files ---")
        shutil.rmtree(TEMP_DIR)
        print("Temporary folder deleted.")


def load_base_file_from_pak() -> Optional[List[str]]:
    """Load the base player_variables.scr file from the original game archive"""
    base_pak_path = BASE_FILE_DIR / BASE_PAK_FILENAME
    if not base_pak_path.exists():
        print(f"\nCRITICAL ERROR: Base file container not found: {base_pak_path}")
        print(f"Please ensure '{BASE_PAK_FILENAME}' is in the '{BASE_FILE_DIR.name}' folder.")
        return None

    try:
        with zipfile.ZipFile(base_pak_path, 'r') as pak:
            with pak.open(BASE_FILENAME_IN_PAK) as scr_file:
                return scr_file.read().decode('utf-8', errors='ignore').splitlines(keepends=True)
    except Exception as e:
        print(f"\nCRITICAL ERROR: Could not read base file from '{BASE_PAK_FILENAME}': {e}")
        print("Please ensure the archive is not corrupt and contains the required file.")
        return None


def process_archive_content(archive: Any, archive_type: str, source_name: str) -> bool:
    """Process files in an archive and extract relevant content"""
    found_player_vars = False
    members = archive.list() if archive_type == '7z' else archive.infolist()

    for member in members:
        if ArchiveHandler.is_directory(member, archive_type):
            continue

        member_path = member.filename.replace('\\', '/')

        if member_path.lower().endswith('player_variables.scr'):
            temp_filename = source_name + PLAYER_VARS_MARKER
            temp_filepath = TEMP_DIR / temp_filename
            file_data = ArchiveHandler.read_file(archive, archive_type, member.filename)
            if safe_write_file(temp_filepath, file_data, 'wb'):
                print(f"  -> Found and extracted '{member_path}'")
                found_player_vars = True
        else:
            # Skip nested archives to prevent infinite recursion
            if not member_path.lower().endswith(SUPPORTED_ARCHIVE_EXTS):
                if member_path not in other_files_map:
                    other_files_map[member_path] = []
                temp_filename = f"{source_name}_{Path(member_path).name}"
                temp_filepath = TEMP_DIR / temp_filename
                file_data = ArchiveHandler.read_file(archive, archive_type, member.filename)
                if safe_write_file(temp_filepath, file_data, 'wb'):
                    other_files_map[member_path].append({
                        'source': source_name, 
                        'temp_path': temp_filepath
                    })
                    print(f"  -> Found additional file: '{member_path}'")

    return found_player_vars


def extract_mods() -> bool:
    """Extract mod files from archives and prepare for processing"""
    print("\n--- Step 1: Extracting and Preparing Mods ---")
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)
    TEMP_DIR.mkdir(parents=True)

    if not MODS_DIR.exists() or not any(MODS_DIR.iterdir()):
        print(f"Folder '{MODS_DIR.name}' is empty.")
        return False

    found_player_vars = False

    for item_path in MODS_DIR.iterdir():
        if not item_path.is_file():
            continue
            
        print(f"\nProcessing: {item_path.name}")
        
        # Check if file extension is supported
        if item_path.suffix.lower() not in SUPPORTED_MOD_EXTS:
            print(f"  -> File skipped. Only {', '.join(SUPPORTED_MOD_EXTS)} files are supported.")
            continue

        try:
            # Handle SCR files directly
            if item_path.suffix.lower() == '.scr' and 'player_variables' in item_path.name.lower():
                temp_filename = item_path.name + PLAYER_VARS_MARKER
                shutil.copy2(item_path, TEMP_DIR / temp_filename)
                found_player_vars = True
                print(f"  -> Found and copied '{item_path.name}'")
                continue
                
            # Handle archive files
            archive_type = None
            if item_path.suffix.lower() in ('.zip', '.pak'):
                archive_type = 'zip'
                archive = zipfile.ZipFile(item_path, 'r')
            elif item_path.suffix.lower() == '.7z':
                archive_type = '7z'
                archive = py7zr.SevenZipFile(item_path, 'r')
            
            if archive_type and archive:
                with archive:
                    filenames = ArchiveHandler.get_filenames(archive, archive_type)
                    pak_files = [f for f in filenames if f.lower().endswith('.pak')]
                    found_in_pak = False

                    if pak_files:
                        pak_name = pak_files[0]
                        print(f"  Found .pak file inside: '{pak_name}'. Looking into it...")
                        pak_data = ArchiveHandler.read_file(archive, archive_type, pak_name)
                        pak_stream = io.BytesIO(pak_data)
                        with zipfile.ZipFile(pak_stream, 'r') as pak_archive:
                            if process_archive_content(pak_archive, 'zip', item_path.name):
                                found_in_pak = True
                                found_player_vars = True

                    if not found_in_pak:
                        print("  .pak not found, searching for files in the archive root...")
                        if process_archive_content(archive, archive_type, item_path.name):
                            found_player_vars = True

        except Exception as e:
            print(f"  -> ERROR processing '{item_path.name}': {e}")
            traceback.print_exc()

    if not found_player_vars:
        print("\nCould not find any 'player_variables.scr' files to process.")
        
    return found_player_vars


def parse_params(lines: List[str]) -> Dict[str, str]:
    """Parse parameters from lines of a player_variables.scr file"""
    params = {}
    for line in lines:
        key = get_param_key(line)
        if key:
            params[key] = line.strip()
    return params


def analyze_and_resolve_player_vars(base_file_lines: List[str]) -> Dict[str, str]:
    """Analyze player_variables.scr files and resolve conflicts"""
    print("\n--- Step 2: Analyzing player_variables.scr and Resolving Conflicts ---")

    base_params = parse_params(base_file_lines)
    changes_map: Dict[str, List[Dict[str, Any]]] = {}
    mod_files = [f for f in TEMP_DIR.iterdir() if f.name.endswith(PLAYER_VARS_MARKER)]

    if not mod_files:
        print("'player_variables.scr' files not found for analysis.")
        return {}

    for mod_file in mod_files:
        mod_lines = safe_read_file(mod_file)
        if not mod_lines:
            continue
            
        mod_params = parse_params(mod_lines)
        source_display_name = mod_file.name.replace(PLAYER_VARS_MARKER, '')

        for key, mod_value in mod_params.items():
            base_value = base_params.get(key)
            if base_value != mod_value:
                if key not in changes_map:
                    changes_map[key] = []
                # Avoid duplicate values from different sources
                if not any(c['value'] == mod_value for c in changes_map[key]):
                    changes_map[key].append({
                        'source': source_display_name, 
                        'value': mod_value
                    })

    final_changes = {}
    if not changes_map:
        print("No parameter differences found in 'player_variables.scr' files compared to the base file.")
        return final_changes

    for key, changes in sorted(changes_map.items()):
        if len(changes) == 1:
            final_changes[key] = changes[0]['value']
            print(f"[Auto] Applied change for '{key}' from '{changes[0]['source']}'.")
        else:
            print(f"\n[CONFLICT] Multiple changes detected for parameter '{key}':")
            for idx, change in enumerate(changes):
                print(f"  {idx + 1}. '{change['value']}' (from {change['source']})")
            
            while True:
                try:
                    choice = int(input(f"Enter the number of the desired option (1-{len(changes)}): "))
                    if 1 <= choice <= len(changes):
                        final_changes[key] = changes[choice - 1]['value']
                        print(f"Option {choice} selected.")
                        break
                    print("Error: Invalid number.")
                except ValueError:
                    print("Error: Please enter a number.")
                    
    return final_changes


def resolve_other_files() -> Dict[str, Path]:
    """Resolve conflicts for other files found in mods"""
    print("\n--- Step 3: Processing Additional Files ---")
    final_other_files = {}
    
    if not other_files_map:
        print("No additional files found for processing.")
        return final_other_files

    for path, sources in sorted(other_files_map.items()):
        if len(sources) == 1:
            final_other_files[path] = sources[0]['temp_path']
            print(f"[Auto] Added file '{path}' from mod '{sources[0]['source']}'.")
        else:
            print(f"\n[CONFLICT] The same file '{path}' was found in multiple mods:")
            for idx, source in enumerate(sources):
                print(f"  {idx + 1}. Use version from mod '{source['source']}'")
            
            while True:
                try:
                    choice = int(input(f"Enter the number of the desired option (1-{len(sources)}): "))
                    if 1 <= choice <= len(sources):
                        final_other_files[path] = sources[choice - 1]['temp_path']
                        print(f"Option {choice} selected.")
                        break
                    print("Error: Invalid number.")
                except ValueError:
                    print("Error: Please enter a number.")
                    
    return final_other_files


def apply_changes_and_archive(base_file_lines: List[str], 
                             final_player_vars_changes: Dict[str, str], 
                             final_other_files: Dict[str, Path]) -> bool:
    """Apply changes and create the final archive"""
    print("\n--- Step 4: Building Final File and Archiving ---")

    # Create a map of parameter keys to line indices
    base_params_map = {get_param_key(line): i for i, line in enumerate(base_file_lines) if get_param_key(line)}
    output_lines = list(base_file_lines)

    # Apply changes to existing parameters and add new ones
    for key, new_value in final_player_vars_changes.items():
        if key in base_params_map:
            line_index = base_params_map[key]
            output_lines[line_index] = new_value + '\n'
        else:
            # Add new parameter at the end
            output_lines.append(new_value + '\n')

    final_scr_content = "".join(output_lines)
    print("\nFinal 'player_variables.scr' successfully built in memory.")

    # Prepare output directory
    if ARCHIVE_DIR.exists():
        shutil.rmtree(ARCHIVE_DIR)
    ARCHIVE_DIR.mkdir(parents=True)
    print(f"Folder '{ARCHIVE_DIR.name}' has been cleared and is ready.")

    # Create final archive
    archive_path = ARCHIVE_DIR / FINAL_ARCHIVE_NAME
    print(f"Creating archive: {archive_path}")
    
    try:
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as pak_archive:
            pak_archive.writestr(FINAL_PLAYER_VARS_PATH, final_scr_content.encode('utf-8'))
            print(f" -> '{FINAL_PLAYER_VARS_PATH}' added to archive.")

            for archive_dest_path, temp_source_path in final_other_files.items():
                pak_archive.write(temp_source_path, arcname=archive_dest_path)
                print(f" -> '{archive_dest_path}' added to archive.")

        print("\nArchive created successfully!")
        return True
    except Exception as e:
        print(f"Error creating archive: {e}")
        return False


def main() -> None:
    """Main function to orchestrate the mod merging process"""
    try:
        setup_directories()
        base_lines = load_base_file_from_pak()
        if base_lines is None:
            return

        if not extract_mods():
            print("\nProcess finished as no suitable mods were found.")
            return

        final_player_vars = analyze_and_resolve_player_vars(base_lines)
        final_others = resolve_other_files()

        if final_player_vars or final_others:
            if apply_changes_and_archive(base_lines, final_player_vars, final_others):
                print("\n\n=== Utility finished successfully! ===")
                print(f"Your finished mod can be found here: {ARCHIVE_DIR / FINAL_ARCHIVE_NAME}")
            else:
                print("\n\n=== Error creating the final archive ===")
        else:
            print("\n\n=== Process finished. No changes were found to apply. ===")

    except Exception as e:
        print(f"\nA critical error occurred: {e}")
        traceback.print_exc()
    finally:
        cleanup()


if __name__ == "__main__":
    main()
    input("\nPress Enter to exit...")
