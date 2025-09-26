import os
import sys
import shutil
import zipfile
import py7zr
import re
import io
import traceback


# ... (весь код до функции apply_changes_and_archive остается без изменений) ...

def apply_changes_and_archive(base_file_lines, final_player_vars_changes, final_other_files):
    print("\n--- Step 4: Building Final File and Archiving ---")

    output_lines = list(base_file_lines)
    base_params_map = {get_param_key(line): i for i, line in enumerate(output_lines) if get_param_key(line)}

    new_params = []

    # 1. Сначала ЗАМЕНЯЕМ существующие параметры
    for key, new_value in final_player_vars_changes.items():
        if key in base_params_map:
            line_index = base_params_map[key]
            output_lines[line_index] = "    " + new_value + '\n'  # Добавим отступ для единообразия
        else:
            # Если ключа нет в базе - это НОВЫЙ параметр. Собираем их.
            new_params.append(new_value)

    # 2. Теперь ДОБАВЛЯЕМ новые параметры в правильное место
    if new_params:
        print(f"Found {len(new_params)} new parameters to add.")
        # Ищем последнюю закрывающую скобку '}' для вставки ПЕРЕД ней
        insertion_point = -1
        for i in range(len(output_lines) - 1, 0, -1):
            if "}" in output_lines[i]:
                insertion_point = i
                break

        if insertion_point != -1:
            print(f"Inserting new parameters before line {insertion_point + 1}.")
            for param in reversed(new_params):  # Вставляем в обратном порядке, чтобы сохранить исходный
                output_lines.insert(insertion_point, "    " + param + '\n')
        else:
            # Аварийный случай, если '}' не найдена - добавляем в конец
            print("Warning: Could not find closing brace '}'. Appending new params to the end of the file.")
            for param in new_params:
                output_lines.append("    " + param + '\n')

    final_scr_content = "".join(output_lines)
    print("\nFinal 'player_variables.scr' successfully built in memory.")

    if os.path.exists(ARCHIVE_DIR): shutil.rmtree(ARCHIVE_DIR)
    os.makedirs(ARCHIVE_DIR)
    print(f"Folder '{os.path.basename(ARCHIVE_DIR)}' has been cleared and is ready.")

    archive_path = os.path.join(ARCHIVE_DIR, FINAL_ARCHIVE_NAME)
    print(f"Creating archive: {archive_path}")
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as pak_archive:
        pak_archive.writestr(FINAL_PLAYER_VARS_PATH.replace('/', os.sep), final_scr_content.encode('utf-8'))
        print(f" -> '{FINAL_PLAYER_VARS_PATH}' added to archive.")

        for archive_dest_path, temp_source_path in final_other_files.items():
            pak_archive.write(temp_source_path, arcname=archive_dest_path.replace('/', os.sep))
            print(f" -> '{archive_dest_path}' added to archive.")

    print("\nArchive created successfully!")


# ... (остальной код остается без изменений) ...
# Я привожу его ниже для полноты

# --- 1. SETUP PATHS AND CONSTANTS (.EXE-PROOF) ---
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BASE_FILE_DIR = os.path.join(BASE_DIR, "01_Original_Game_File")
MODS_DIR = os.path.join(BASE_DIR, "02_Put_Mods_Here")
TEMP_DIR = os.path.join(BASE_DIR, "_temp_extracted_files")
ARCHIVE_DIR = os.path.join(BASE_DIR, "OUTPUT_Merged_Mod")

BASE_PAK_FILENAME = "data0.pak"
BASE_FILENAME_IN_PAK = "scripts/player/player_variables.scr"
FINAL_PLAYER_VARS_PATH = "scripts/player/player_variables.scr"
FINAL_ARCHIVE_NAME = "data3.pak"
PLAYER_VARS_MARKER = ".PLAYER_VARS.scr"

other_files_map = {}


# --- 2. UNIVERSAL HELPER FUNCTIONS ---
def get_archive_filenames(archive_obj, archive_type):
    if archive_type == 'zip': return archive_obj.namelist()
    if archive_type == '7z': return archive_obj.getnames()
    return []


def read_file_from_archive(archive_obj, archive_type, filename):
    if archive_type == '7z': return archive_obj.read([filename])[filename].getvalue()
    return archive_obj.read(filename)


# --- CORE SCRIPT FUNCTIONS ---
def setup_directories():
    print("--- Checking and creating folder structure ---")
    for path in [BASE_FILE_DIR, MODS_DIR, ARCHIVE_DIR]:
        os.makedirs(path, exist_ok=True)
        print(f"Folder '{os.path.basename(path)}' is ready.")


def cleanup():
    if os.path.exists(TEMP_DIR):
        print("\n--- Cleaning up temporary files ---")
        shutil.rmtree(TEMP_DIR)
        print("Temporary folder deleted.")


def load_base_file_from_pak():
    base_pak_path = os.path.join(BASE_FILE_DIR, BASE_PAK_FILENAME)
    if not os.path.exists(base_pak_path):
        print(f"\nCRITICAL ERROR: Base file container not found: {base_pak_path}")
        print(f"Please ensure '{BASE_PAK_FILENAME}' is in the '{os.path.basename(BASE_FILE_DIR)}' folder.")
        return None

    try:
        with zipfile.ZipFile(base_pak_path, 'r') as pak:
            with pak.open(BASE_FILENAME_IN_PAK) as scr_file:
                return scr_file.read().decode('utf-8', errors='ignore').splitlines(keepends=True)
    except Exception as e:
        print(f"\nCRITICAL ERROR: Could not read base file from '{BASE_PAK_FILENAME}': {e}")
        print("Please ensure the archive is not corrupt and contains the required file.")
        return None


def get_param_key(line):
    match = re.search(r'^\s*Param\s*\(\s*"([^"]+)"', line)
    return match.group(1) if match else None


def process_archive_content(archive, archive_type, source_name):
    found_player_vars = False
    members = archive.list() if archive_type == '7z' else archive.infolist()

    for member in members:
        is_directory = member.is_directory if archive_type == '7z' else member.is_dir()
        if is_directory: continue

        member_path = member.filename.replace('\\', '/')

        if member_path.lower().endswith('player_variables.scr'):
            temp_filename = source_name + PLAYER_VARS_MARKER
            with open(os.path.join(TEMP_DIR, temp_filename), 'wb') as f:
                f.write(read_file_from_archive(archive, archive_type, member.filename))
            print(f"  -> Found and extracted '{member_path}'")
            found_player_vars = True
        else:
            if not member_path.lower().endswith(('.zip', '.pak', '.7z')):
                if member_path not in other_files_map:
                    other_files_map[member_path] = []
                temp_filename = f"{source_name}_{os.path.basename(member_path)}"
                temp_filepath = os.path.join(TEMP_DIR, temp_filename)
                with open(temp_filepath, 'wb') as f:
                    f.write(read_file_from_archive(archive, archive_type, member.filename))
                other_files_map[member_path].append({'source': source_name, 'temp_path': temp_filepath})
                print(f"  -> Found additional file: '{member_path}'")

    return found_player_vars


def extract_mods():
    print("\n--- Step 1: Extracting and Preparing Mods ---")
    if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR)
    os.makedirs(TEMP_DIR)

    if not os.path.exists(MODS_DIR) or not os.listdir(MODS_DIR):
        print(f"Folder '{os.path.basename(MODS_DIR)}' is empty.")
        return False

    for item_name in os.listdir(MODS_DIR):
        item_path = os.path.join(MODS_DIR, item_name)
        print(f"\nProcessing: {item_name}")

        try:
            archive_type = None
            if item_name.lower().endswith(('.zip', '.pak')):
                archive_type = 'zip'
            elif item_name.lower().endswith('.7z'):
                archive_type = '7z'

            if archive_type:
                archive_class = {'zip': zipfile.ZipFile, '7z': py7zr.SevenZipFile}[archive_type]
                with archive_class(item_path, 'r') as archive:
                    filenames = get_archive_filenames(archive, archive_type)
                    pak_files = [f for f in filenames if f.lower().endswith('.pak')]
                    found_in_pak = False

                    if pak_files:
                        pak_name = pak_files[0]
                        print(f"  Found .pak file inside: '{pak_name}'. Looking into it...")
                        pak_data = read_file_from_archive(archive, archive_type, pak_name)
                        pak_stream = io.BytesIO(pak_data)
                        with zipfile.ZipFile(pak_stream, 'r') as pak_archive:
                            if process_archive_content(pak_archive, 'zip', item_name):
                                found_in_pak = True

                    if not found_in_pak:
                        print("  .pak not found, searching for files in the archive root...")
                        process_archive_content(archive, archive_type, item_name)

            elif item_name.lower().endswith('.scr'):
                if 'player_variables' in item_name.lower():
                    temp_filename = item_name + PLAYER_VARS_MARKER
                    shutil.copy(item_path, os.path.join(TEMP_DIR, temp_filename))
            else:
                print(f"  -> File skipped. Only .zip, .7z, .pak, and .scr files are supported.")

        except Exception as e:
            print(f"  -> ERROR processing '{item_name}': {e}.")

    if not any(f.endswith(PLAYER_VARS_MARKER) for f in os.listdir(TEMP_DIR)):
        print("\nCould not find any 'player_variables.scr' files to process.")
        return False
    return True


def analyze_and_resolve_player_vars(base_file_lines):
    print("\n--- Step 2: Analyzing player_variables.scr and Resolving Conflicts ---")

    def parse_params(lines):
        params = {}
        for line in lines:
            key = get_param_key(line)
            if key:
                params[key] = line.strip()
        return params

    base_params = parse_params(base_file_lines)
    changes_map = {}
    mod_files = [f for f in os.listdir(TEMP_DIR) if f.endswith(PLAYER_VARS_MARKER)]

    if not mod_files:
        print("'player_variables.scr' files not found for analysis.")
        return {}

    for mod_filename in mod_files:
        mod_filepath = os.path.join(TEMP_DIR, mod_filename)
        with open(mod_filepath, 'r', encoding='utf-8', errors='ignore') as f:
            mod_lines = f.readlines()

        mod_params = parse_params(mod_lines)
        source_display_name = mod_filename.replace(PLAYER_VARS_MARKER, '')

        for key, mod_value in mod_params.items():
            base_value = base_params.get(key)
            if base_value != mod_value:
                if key not in changes_map:
                    changes_map[key] = []
                if not any(c['value'] == mod_value for c in changes_map[key]):
                    changes_map[key].append({'source': source_display_name, 'value': mod_value})

    final_changes = {}
    if not changes_map:
        print("No parameter differences found in 'player_variables.scr' files compared to the base file.")
        return {}

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
                    else:
                        print("Error: Invalid number.")
                except ValueError:
                    print("Error: Please enter a number.")

    return final_changes


def resolve_other_files():
    print("\n--- Step 3: Processing Additional Files ---")
    final_other_files = {}
    if not other_files_map:
        print("No additional files found for processing.")
        return {}

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
                    else:
                        print("Error: Invalid number.")
                except ValueError:
                    print("Error: Please enter a number.")
    return final_other_files


def main():
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
            apply_changes_and_archive(base_lines, final_player_vars, final_others)
            print("\n\n=== Utility finished successfully! ===")
            print(f"Your finished mod can be found here: {os.path.join(ARCHIVE_DIR, FINAL_ARCHIVE_NAME)}")
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
