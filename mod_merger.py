import io
import os
import re
import shutil
import sys
import traceback
import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Tuple, Set

try:
    import py7zr
    HAS_7Z_SUPPORT = True
except ImportError:
    HAS_7Z_SUPPORT = False
    print("Warning: py7zr not available. 7z archive support disabled.")


class ArchiveType(Enum):
    """Supported archive types"""
    ZIP = "zip"
    SEVEN_Z = "7z"


@dataclass
class ModFile:
    """Represents a mod file with its metadata"""
    source_name: str
    temp_path: Path
    original_path: str


@dataclass
class ParameterChange:
    """Represents a parameter change with source information"""
    key: str
    value: str
    source: str


@dataclass
class ConflictResolution:
    """Represents a conflict resolution choice"""
    parameter_key: str
    chosen_value: str
    chosen_source: str


class GameConfig:
    """Configuration constants for the game mod merger"""
    
    # File and directory names
    BASE_PAK_FILENAME = "data0.pak"
    BASE_FILENAME_IN_PAK = "scripts/player/player_variables.scr"
    FINAL_PLAYER_VARS_PATH = "scripts/player/player_variables.scr"
    FINAL_ARCHIVE_NAME = "data3.pak"
    PLAYER_VARS_MARKER = ".PLAYER_VARS.scr"
    
    # Directory structure
    BASE_FILE_DIR_NAME = "01_Original_Game_File"
    MODS_DIR_NAME = "02_Put_Mods_Here"
    TEMP_DIR_NAME = "_temp_extracted_files"
    ARCHIVE_DIR_NAME = "OUTPUT_Merged_Mod"
    
    # Supported file extensions
    SUPPORTED_ARCHIVE_EXTS = ('.zip', '.pak', '.7z')
    SUPPORTED_MOD_EXTS = SUPPORTED_ARCHIVE_EXTS + ('.scr',)
    
    # Encoding settings
    DEFAULT_ENCODING = 'utf-8'
    FALLBACK_ENCODING = 'latin-1'


class ModMergerError(Exception):
    """Base exception for mod merger operations"""
    pass


class FileNotFoundError(ModMergerError):
    """Raised when required files are not found"""
    pass


class ArchiveError(ModMergerError):
    """Raised when archive operations fail"""
    pass


class PathManager:
    """Manages all file paths for the application"""
    
    def __init__(self):
        self.base_dir = self._get_base_directory()
        self.base_file_dir = self.base_dir / GameConfig.BASE_FILE_DIR_NAME
        self.mods_dir = self.base_dir / GameConfig.MODS_DIR_NAME
        self.temp_dir = self.base_dir / GameConfig.TEMP_DIR_NAME
        self.archive_dir = self.base_dir / GameConfig.ARCHIVE_DIR_NAME
    
    @staticmethod
    def _get_base_directory() -> Path:
        """Get the base directory, handling both script and executable contexts"""
        if getattr(sys, 'frozen', False):
            return Path(sys.executable).parent
        return Path(__file__).parent.absolute()
    
    @property
    def base_pak_path(self) -> Path:
        """Path to the base game pak file"""
        return self.base_file_dir / GameConfig.BASE_PAK_FILENAME
    
    @property
    def final_archive_path(self) -> Path:
        """Path to the final output archive"""
        return self.archive_dir / GameConfig.FINAL_ARCHIVE_NAME


class FileUtils:
    """Utility functions for file operations"""
    
    @staticmethod
    def safe_read_text(file_path: Path, encoding: str = None) -> List[str]:
        """Safely read text file with multiple encoding attempts"""
        encodings = [encoding] if encoding else [GameConfig.DEFAULT_ENCODING, GameConfig.FALLBACK_ENCODING]
        
        for enc in encodings:
            if enc is None:
                continue
            try:
                with open(file_path, 'r', encoding=enc, errors='ignore') as f:
                    return f.readlines()
            except (UnicodeDecodeError, UnicodeError):
                continue
            except Exception as e:
                print(f"Error reading file {file_path}: {e}")
                break
        return []
    
    @staticmethod
    def safe_write_file(file_path: Path, content: Union[str, bytes], mode: str = 'w') -> bool:
        """Safely write file with error handling"""
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            if 'b' in mode:
                with open(file_path, mode) as f:
                    f.write(content)
            else:
                with open(file_path, mode, encoding=GameConfig.DEFAULT_ENCODING) as f:
                    f.write(content)
            return True
        except Exception as e:
            print(f"Error writing file {file_path}: {e}")
            return False
    
    @staticmethod
    def clean_directory(directory: Path) -> bool:
        """Safely clean a directory"""
        try:
            if directory.exists():
                shutil.rmtree(directory)
            directory.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            print(f"Error cleaning directory {directory}: {e}")
            return False


class ArchiveHandler:
    """Handle different archive formats with a unified interface"""
    
    @staticmethod
    def get_archive_type(file_path: Path) -> Optional[ArchiveType]:
        """Determine archive type from file extension"""
        suffix = file_path.suffix.lower()
        if suffix in ('.zip', '.pak'):
            return ArchiveType.ZIP
        elif suffix == '.7z' and HAS_7Z_SUPPORT:
            return ArchiveType.SEVEN_Z
        return None
    
    @staticmethod
    def get_filenames(archive_obj: Any, archive_type: ArchiveType) -> List[str]:
        """Get list of files in archive"""
        if archive_type == ArchiveType.ZIP:
            return archive_obj.namelist()
        elif archive_type == ArchiveType.SEVEN_Z:
            return archive_obj.getnames()
        return []
    
    @staticmethod
    def read_file(archive_obj: Any, archive_type: ArchiveType, filename: str) -> bytes:
        """Read file from archive"""
        if archive_type == ArchiveType.SEVEN_Z:
            return archive_obj.read([filename])[filename].getvalue()
        return archive_obj.read(filename)
    
    @staticmethod
    def is_directory(member: Any, archive_type: ArchiveType) -> bool:
        """Check if archive member is a directory"""
        if archive_type == ArchiveType.SEVEN_Z:
            return member.is_directory
        return member.is_dir()
    
    @staticmethod
    def open_archive(file_path: Path, archive_type: ArchiveType):
        """Open archive with appropriate handler"""
        if archive_type == ArchiveType.ZIP:
            return zipfile.ZipFile(file_path, 'r')
        elif archive_type == ArchiveType.SEVEN_Z and HAS_7Z_SUPPORT:
            return py7zr.SevenZipFile(file_path, 'r')
        else:
            raise ArchiveError(f"Unsupported archive type: {archive_type}")


class ParameterParser:
    """Handles parsing of game parameters"""
    
    PARAM_PATTERN = re.compile(r'^\s*Param\s*\(\s*"([^"]+)"')
    
    @classmethod
    def get_param_key(cls, line: str) -> Optional[str]:
        """Extract parameter key from line"""
        match = cls.PARAM_PATTERN.search(line)
        return match.group(1) if match else None
    
    @classmethod
    def parse_parameters(cls, lines: List[str]) -> Dict[str, str]:
        """Parse parameters from lines of a player_variables.scr file"""
        params = {}
        for line in lines:
            key = cls.get_param_key(line)
            if key:
                params[key] = line.strip()
        return params
    
    @classmethod
    def find_closing_brace_position(cls, lines: List[str]) -> int:
        """Find the position of the last closing brace for parameter insertion"""
        for i in range(len(lines) - 1, -1, -1):
            if "}" in lines[i]:
                return i
        return -1


class ModExtractor:
    """Handles extraction and processing of mod files"""
    
    def __init__(self, paths: PathManager):
        self.paths = paths
        self.other_files_map: Dict[str, List[ModFile]] = {}
    
    def setup_directories(self) -> None:
        """Create necessary directories"""
        print("--- Checking and creating folder structure ---")
        for path in [self.paths.base_file_dir, self.paths.mods_dir, self.paths.archive_dir]:
            path.mkdir(parents=True, exist_ok=True)
            print(f"Folder '{path.name}' is ready.")
    
    def cleanup(self) -> None:
        """Clean up temporary files"""
        if self.paths.temp_dir.exists():
            print("\n--- Cleaning up temporary files ---")
            shutil.rmtree(self.paths.temp_dir)
            print("Temporary folder deleted.")
    
    def load_base_file(self) -> Optional[List[str]]:
        """Load the base player_variables.scr file from the original game archive"""
        if not self.paths.base_pak_path.exists():
            print(f"\nCRITICAL ERROR: Base file container not found: {self.paths.base_pak_path}")
            print(f"Please ensure '{GameConfig.BASE_PAK_FILENAME}' is in the '{self.paths.base_file_dir.name}' folder.")
            return None

        try:
            with zipfile.ZipFile(self.paths.base_pak_path, 'r') as pak:
                with pak.open(GameConfig.BASE_FILENAME_IN_PAK) as scr_file:
                    content = scr_file.read().decode(GameConfig.DEFAULT_ENCODING, errors='ignore')
                    return content.splitlines(keepends=True)
        except Exception as e:
            print(f"\nCRITICAL ERROR: Could not read base file from '{GameConfig.BASE_PAK_FILENAME}': {e}")
            print("Please ensure the archive is not corrupt and contains the required file.")
            return None
    
    def _process_archive_content(self, archive: Any, archive_type: ArchiveType, source_name: str) -> bool:
        """Process files in an archive and extract relevant content"""
        found_player_vars = False
        
        try:
            members = archive.list() if archive_type == ArchiveType.SEVEN_Z else archive.infolist()
        except Exception as e:
            print(f"  -> Error listing archive contents: {e}")
            return False

        for member in members:
            if ArchiveHandler.is_directory(member, archive_type):
                continue

            member_path = member.filename.replace('\\', '/')

            if member_path.lower().endswith('player_variables.scr'):
                temp_filename = source_name + GameConfig.PLAYER_VARS_MARKER
                temp_filepath = self.paths.temp_dir / temp_filename
                
                try:
                    file_data = ArchiveHandler.read_file(archive, archive_type, member.filename)
                    if FileUtils.safe_write_file(temp_filepath, file_data, 'wb'):
                        print(f"  -> Found and extracted '{member_path}'")
                        found_player_vars = True
                except Exception as e:
                    print(f"  -> Error extracting player variables: {e}")
            else:
                # Skip nested archives to prevent infinite recursion
                if not member_path.lower().endswith(GameConfig.SUPPORTED_ARCHIVE_EXTS):
                    if member_path not in self.other_files_map:
                        self.other_files_map[member_path] = []
                    
                    temp_filename = f"{source_name}_{Path(member_path).name}"
                    temp_filepath = self.paths.temp_dir / temp_filename
                    
                    try:
                        file_data = ArchiveHandler.read_file(archive, archive_type, member.filename)
                        if FileUtils.safe_write_file(temp_filepath, file_data, 'wb'):
                            mod_file = ModFile(
                                source_name=source_name,
                                temp_path=temp_filepath,
                                original_path=member_path
                            )
                            self.other_files_map[member_path].append(mod_file)
                            print(f"  -> Found additional file: '{member_path}'")
                    except Exception as e:
                        print(f"  -> Error extracting {member_path}: {e}")

        return found_player_vars
    
    def extract_mods(self) -> bool:
        """Extract mod files from archives and prepare for processing"""
        print("\n--- Step 1: Extracting and Preparing Mods ---")
        
        if not FileUtils.clean_directory(self.paths.temp_dir):
            print("Failed to prepare temporary directory")
            return False

        if not self.paths.mods_dir.exists() or not any(self.paths.mods_dir.iterdir()):
            print(f"Folder '{self.paths.mods_dir.name}' is empty.")
            return False

        found_player_vars = False

        for item_path in self.paths.mods_dir.iterdir():
            if not item_path.is_file():
                continue
                
            print(f"\nProcessing: {item_path.name}")
            
            # Check if file extension is supported
            if item_path.suffix.lower() not in GameConfig.SUPPORTED_MOD_EXTS:
                print(f"  -> File skipped. Only {', '.join(GameConfig.SUPPORTED_MOD_EXTS)} files are supported.")
                continue

            try:
                # Handle SCR files directly
                if item_path.suffix.lower() == '.scr' and 'player_variables' in item_path.name.lower():
                    temp_filename = item_path.name + GameConfig.PLAYER_VARS_MARKER
                    shutil.copy2(item_path, self.paths.temp_dir / temp_filename)
                    found_player_vars = True
                    print(f"  -> Found and copied '{item_path.name}'")
                    continue
                    
                # Handle archive files
                archive_type = ArchiveHandler.get_archive_type(item_path)
                if not archive_type:
                    print(f"  -> Unsupported archive type: {item_path.suffix}")
                    continue
                
                if archive_type == ArchiveType.SEVEN_Z and not HAS_7Z_SUPPORT:
                    print(f"  -> 7z support not available, skipping {item_path.name}")
                    continue
                
                with ArchiveHandler.open_archive(item_path, archive_type) as archive:
                    filenames = ArchiveHandler.get_filenames(archive, archive_type)
                    pak_files = [f for f in filenames if f.lower().endswith('.pak')]
                    found_in_pak = False

                    if pak_files:
                        pak_name = pak_files[0]
                        print(f"  Found .pak file inside: '{pak_name}'. Looking into it...")
                        try:
                            pak_data = ArchiveHandler.read_file(archive, archive_type, pak_name)
                            pak_stream = io.BytesIO(pak_data)
                            with zipfile.ZipFile(pak_stream, 'r') as pak_archive:
                                if self._process_archive_content(pak_archive, ArchiveType.ZIP, item_path.name):
                                    found_in_pak = True
                                    found_player_vars = True
                        except Exception as e:
                            print(f"  -> Error processing nested pak: {e}")

                    if not found_in_pak:
                        print("  .pak not found, searching for files in the archive root...")
                        if self._process_archive_content(archive, archive_type, item_path.name):
                            found_player_vars = True

            except Exception as e:
                print(f"  -> ERROR processing '{item_path.name}': {e}")
                if hasattr(e, '__traceback__'):
                    traceback.print_exc()

        if not found_player_vars:
            print("\nCould not find any 'player_variables.scr' files to process.")
            
        return found_player_vars


class ConflictResolver:
    """Handles conflict resolution for parameters and files"""
    
    def __init__(self, paths: PathManager):
        self.paths = paths
    
    def analyze_player_variables(self, base_file_lines: List[str]) -> Dict[str, str]:
        """Analyze player_variables.scr files and resolve conflicts"""
        print("\n--- Step 2: Analyzing player_variables.scr and Resolving Conflicts ---")

        base_params = ParameterParser.parse_parameters(base_file_lines)
        changes_map: Dict[str, List[ParameterChange]] = {}
        
        mod_files = [f for f in self.paths.temp_dir.iterdir() 
                    if f.name.endswith(GameConfig.PLAYER_VARS_MARKER)]

        if not mod_files:
            print("'player_variables.scr' files not found for analysis.")
            return {}

        for mod_file in mod_files:
            mod_lines = FileUtils.safe_read_text(mod_file)
            if not mod_lines:
                continue
                
            mod_params = ParameterParser.parse_parameters(mod_lines)
            source_display_name = mod_file.name.replace(GameConfig.PLAYER_VARS_MARKER, '')

            for key, mod_value in mod_params.items():
                base_value = base_params.get(key)
                if base_value != mod_value:
                    if key not in changes_map:
                        changes_map[key] = []
                    
                    # Avoid duplicate values from different sources
                    if not any(c.value == mod_value for c in changes_map[key]):
                        change = ParameterChange(
                            key=key,
                            value=mod_value,
                            source=source_display_name
                        )
                        changes_map[key].append(change)

        return self._resolve_parameter_conflicts(changes_map)
    
    def _resolve_parameter_conflicts(self, changes_map: Dict[str, List[ParameterChange]]) -> Dict[str, str]:
        """Resolve conflicts between parameter changes"""
        final_changes = {}
        
        if not changes_map:
            print("No parameter differences found in 'player_variables.scr' files compared to the base file.")
            return final_changes

        for key, changes in sorted(changes_map.items()):
            if len(changes) == 1:
                final_changes[key] = changes[0].value
                print(f"[Auto] Applied change for '{key}' from '{changes[0].source}'.")
            else:
                print(f"\n[CONFLICT] Multiple changes detected for parameter '{key}':")
                for idx, change in enumerate(changes):
                    print(f"  {idx + 1}. '{change.value}' (from {change.source})")
                
                choice = self._get_user_choice(len(changes))
                if choice is not None:
                    final_changes[key] = changes[choice - 1].value
                    print(f"Option {choice} selected.")
                    
        return final_changes
    
    def resolve_file_conflicts(self, other_files_map: Dict[str, List[ModFile]]) -> Dict[str, Path]:
        """Resolve conflicts for other files found in mods"""
        print("\n--- Step 3: Processing Additional Files ---")
        final_other_files = {}
        
        if not other_files_map:
            print("No additional files found for processing.")
            return final_other_files

        for path, mod_files in sorted(other_files_map.items()):
            if len(mod_files) == 1:
                final_other_files[path] = mod_files[0].temp_path
                print(f"[Auto] Added file '{path}' from mod '{mod_files[0].source_name}'.")
            else:
                print(f"\n[CONFLICT] The same file '{path}' was found in multiple mods:")
                for idx, mod_file in enumerate(mod_files):
                    print(f"  {idx + 1}. Use version from mod '{mod_file.source_name}'")
                
                choice = self._get_user_choice(len(mod_files))
                if choice is not None:
                    final_other_files[path] = mod_files[choice - 1].temp_path
                    print(f"Option {choice} selected.")
                    
        return final_other_files
    
    @staticmethod
    def _get_user_choice(max_options: int) -> Optional[int]:
        """Get user choice for conflict resolution"""
        while True:
            try:
                choice = int(input(f"Enter the number of the desired option (1-{max_options}): "))
                if 1 <= choice <= max_options:
                    return choice
                print("Error: Invalid number.")
            except ValueError:
                print("Error: Please enter a number.")
            except KeyboardInterrupt:
                print("\nOperation cancelled by user.")
                return None


class ArchiveBuilder:
    """Handles building the final archive with merged changes"""
    
    def __init__(self, paths: PathManager):
        self.paths = paths
    
    def apply_changes_and_create_archive(self, 
                                       base_file_lines: List[str],
                                       final_player_vars_changes: Dict[str, str],
                                       final_other_files: Dict[str, Path]) -> bool:
        """Apply changes and create the final archive"""
        print("\n--- Step 4: Building Final File and Archiving ---")

        output_lines = list(base_file_lines)
        base_params_map = {
            ParameterParser.get_param_key(line): i 
            for i, line in enumerate(output_lines) 
            if ParameterParser.get_param_key(line)
        }

        new_params = []

        # 1. Replace existing parameters
        for key, new_value in final_player_vars_changes.items():
            if key in base_params_map:
                line_index = base_params_map[key]
                output_lines[line_index] = "    " + new_value + '\n'  # Add indentation for consistency
            else:
                # If key doesn't exist in base - it's a NEW parameter. Collect them.
                new_params.append(new_value)

        # 2. Add new parameters in the correct location
        if new_params:
            print(f"Found {len(new_params)} new parameters to add.")
            # Find the last closing brace '}' to insert BEFORE it
            insertion_point = ParameterParser.find_closing_brace_position(output_lines)

            if insertion_point != -1:
                print(f"Inserting new parameters before line {insertion_point + 1}.")
                for param in reversed(new_params):  # Insert in reverse order to maintain original order
                    output_lines.insert(insertion_point, "    " + param + '\n')
            else:
                # Emergency case if '}' not found - add to end
                print("Warning: Could not find closing brace '}'. Appending new params to the end of the file.")
                for param in new_params:
                    output_lines.append("    " + param + '\n')

        final_scr_content = "".join(output_lines)
        print("\nFinal 'player_variables.scr' successfully built in memory.")

        return self._create_archive(final_scr_content, final_other_files)
    
    def _create_archive(self, final_scr_content: str, final_other_files: Dict[str, Path]) -> bool:
        """Create the final archive with all changes"""
        # Prepare output directory
        if not FileUtils.clean_directory(self.paths.archive_dir):
            print("Failed to prepare output directory")
            return False
        
        print(f"Folder '{self.paths.archive_dir.name}' has been cleared and is ready.")

        # Create final archive
        print(f"Creating archive: {self.paths.final_archive_path}")
        
        try:
            with zipfile.ZipFile(self.paths.final_archive_path, 'w', zipfile.ZIP_DEFLATED) as pak_archive:
                pak_archive.writestr(
                    GameConfig.FINAL_PLAYER_VARS_PATH, 
                    final_scr_content.encode(GameConfig.DEFAULT_ENCODING)
                )
                print(f" -> '{GameConfig.FINAL_PLAYER_VARS_PATH}' added to archive.")

                for archive_dest_path, temp_source_path in final_other_files.items():
                    pak_archive.write(temp_source_path, arcname=archive_dest_path)
                    print(f" -> '{archive_dest_path}' added to archive.")

            print("\nArchive created successfully!")
            return True
        except Exception as e:
            print(f"Error creating archive: {e}")
            return False


class ModMergerApplication:
    """Main application class that orchestrates the mod merging process"""
    
    def __init__(self):
        self.paths = PathManager()
        self.extractor = ModExtractor(self.paths)
        self.resolver = ConflictResolver(self.paths)
        self.builder = ArchiveBuilder(self.paths)
    
    def run(self) -> None:
        """Main function to orchestrate the mod merging process"""
        try:
            print("=== Game Mod Merger Utility ===")
            print(f"Base directory: {self.paths.base_dir}")
            print()
            
            self.extractor.setup_directories()
            
            base_lines = self.extractor.load_base_file()
            if base_lines is None:
                return

            if not self.extractor.extract_mods():
                print("\nProcess finished as no suitable mods were found.")
                return

            final_player_vars = self.resolver.analyze_player_variables(base_lines)
            final_others = self.resolver.resolve_file_conflicts(self.extractor.other_files_map)

            if final_player_vars or final_others:
                if self.builder.apply_changes_and_create_archive(base_lines, final_player_vars, final_others):
                    print("\n\n=== Utility finished successfully! ===")
                    print(f"Your finished mod can be found here: {self.paths.final_archive_path}")
                else:
                    print("\n\n=== Error creating the final archive ===")
            else:
                print("\n\n=== Process finished. No changes were found to apply. ===")

        except KeyboardInterrupt:
            print("\n\nOperation cancelled by user.")
        except Exception as e:
            print(f"\nA critical error occurred: {e}")
            traceback.print_exc()
        finally:
            self.extractor.cleanup()


def main() -> None:
    """Entry point for the application"""
    app = ModMergerApplication()
    app.run()


if __name__ == "__main__":
    main()
    input("\nPress Enter to exit...")
    
    def _process_archive_content(self, archive: Any, archive_type: ArchiveType, source_name: str) -> bool:
        """Process files in an archive and extract relevant content"""
        found_player_vars = False
        
        try:
            members = archive.list() if archive_type == ArchiveType.SEVEN_Z else archive.infolist()
        except Exception as e:
            print(f"  -> Error listing archive contents: {e}")
            return False

        for member in members:
            if ArchiveHandler.is_directory(member, archive_type):
                continue

            member_path = member.filename.replace('\\', '/')

            if member_path.lower().endswith('player_variables.scr'):
                temp_filename = source_name + GameConfig.PLAYER_VARS_MARKER
                temp_filepath = self.paths.temp_dir / temp_filename
                
                try:
                    file_data = ArchiveHandler.read_file(archive, archive_type, member.filename)
                    if FileUtils.safe_write_file(temp_filepath, file_data, 'wb'):
                        print(f"  -> Found and extracted '{member_path}'")
                        found_player_vars = True
                except Exception as e:
                    print(f"  -> Error extracting player variables: {e}")
            else:
                # Skip nested archives to prevent infinite recursion
                if not member_path.lower().endswith(GameConfig.SUPPORTED_ARCHIVE_EXTS):
                    if member_path not in self.other_files_map:
                        self.other_files_map[member_path] = []
                    
                    temp_filename = f"{source_name}_{Path(member_path).name}"
                    temp_filepath = self.paths.temp_dir / temp_filename
                    
                    try:
                        file_data = ArchiveHandler.read_file(archive, archive_type, member.filename)
                        if FileUtils.safe_write_file(temp_filepath, file_data, 'wb'):
                            mod_file = ModFile(
                                source_name=source_name,
                                temp_path=temp_filepath,
                                original_path=member_path
                            )
                            self.other_files_map[member_path].append(mod_file)
                            print(f"  -> Found additional file: '{member_path}'")
                    except Exception as e:
                        print(f"  -> Error extracting {member_path}: {e}")

        return found_player_vars
    
    def extract_mods(self) -> bool:
        """Extract mod files from archives and prepare for processing"""
        print("\n--- Step 1: Extracting and Preparing Mods ---")
        
        if not FileUtils.clean_directory(self.paths.temp_dir):
            print("Failed to prepare temporary directory")
            return False

        if not self.paths.mods_dir.exists() or not any(self.paths.mods_dir.iterdir()):
            print(f"Folder '{self.paths.mods_dir.name}' is empty.")
            return False

        found_player_vars = False

        for item_path in self.paths.mods_dir.iterdir():
            if not item_path.is_file():
                continue
                
            print(f"\nProcessing: {item_path.name}")
            
            # Check if file extension is supported
            if item_path.suffix.lower() not in GameConfig.SUPPORTED_MOD_EXTS:
                print(f"  -> File skipped. Only {', '.join(GameConfig.SUPPORTED_MOD_EXTS)} files are supported.")
                continue

            try:
                # Handle SCR files directly
                if item_path.suffix.lower() == '.scr' and 'player_variables' in item_path.name.lower():
                    temp_filename = item_path.name + GameConfig.PLAYER_VARS_MARKER
                    shutil.copy2(item_path, self.paths.temp_dir / temp_filename)
                    found_player_vars = True
                    print(f"  -> Found and copied '{item_path.name}'")
                    continue
                    
                # Handle archive files
                archive_type = ArchiveHandler.get_archive_type(item_path)
                if not archive_type:
                    print(f"  -> Unsupported archive type: {item_path.suffix}")
                    continue
                
                if archive_type == ArchiveType.SEVEN_Z and not HAS_7Z_SUPPORT:
                    print(f"  -> 7z support not available, skipping {item_path.name}")
                    continue
                
                with ArchiveHandler.open_archive(item_path, archive_type) as archive:
                    filenames = ArchiveHandler.get_filenames(archive, archive_type)
                    pak_files = [f for f in filenames if f.lower().endswith('.pak')]
                    found_in_pak = False

                    if pak_files:
                        pak_name = pak_files[0]
                        print(f"  Found .pak file inside: '{pak_name}'. Looking into it...")
                        try:
                            pak_data = ArchiveHandler.read_file(archive, archive_type, pak_name)
                            pak_stream = io.BytesIO(pak_data)
                            with zipfile.ZipFile(pak_stream, 'r') as pak_archive:
                                if self._process_archive_content(pak_archive, ArchiveType.ZIP, item_path.name):
                                    found_in_pak = True
                                    found_player_vars = True
                        except Exception as e:
                            print(f"  -> Error processing nested pak: {e}")

                    if not found_in_pak:
                        print("  .pak not found, searching for files in the archive root...")
                        if self._process_archive_content(archive, archive_type, item_path.name):
                            found_player_vars = True

            except Exception as e:
                print(f"  -> ERROR processing '{item_path.name}': {e}")
                if hasattr(e, '__traceback__'):
                    traceback.print_exc()

        if not found_player_vars:
            print("\nCould not find any 'player_variables.scr' files to process.")
            
        return found_player_vars


class ConflictResolver:
    """Handles conflict resolution for parameters and files"""
    
    def __init__(self, paths: PathManager):
        self.paths = paths
    
    def analyze_player_variables(self, base_file_lines: List[str]) -> Dict[str, str]:
        """Analyze player_variables.scr files and resolve conflicts"""
        print("\n--- Step 2: Analyzing player_variables.scr and Resolving Conflicts ---")

        base_params = ParameterParser.parse_parameters(base_file_lines)
        changes_map: Dict[str, List[ParameterChange]] = {}
        
        mod_files = [f for f in self.paths.temp_dir.iterdir() 
                    if f.name.endswith(GameConfig.PLAYER_VARS_MARKER)]

        if not mod_files:
            print("'player_variables.scr' files not found for analysis.")
            return {}

        for mod_file in mod_files:
            mod_lines = FileUtils.safe_read_text(mod_file)
            if not mod_lines:
                continue
                
            mod_params = ParameterParser.parse_parameters(mod_lines)
            source_display_name = mod_file.name.replace(GameConfig.PLAYER_VARS_MARKER, '')

            for key, mod_value in mod_params.items():
                base_value = base_params.get(key)
                if base_value != mod_value:
                    if key not in changes_map:
                        changes_map[key] = []
                    
                    # Avoid duplicate values from different sources
                    if not any(c.value == mod_value for c in changes_map[key]):
                        change = ParameterChange(
                            key=key,
                            value=mod_value,
                            source=source_display_name
                        )
                        changes_map[key].append(change)

        return self._resolve_parameter_conflicts(changes_map)
    
    def _resolve_parameter_conflicts(self, changes_map: Dict[str, List[ParameterChange]]) -> Dict[str, str]:
        """Resolve conflicts between parameter changes"""
        final_changes = {}
        
        if not changes_map:
            print("No parameter differences found in 'player_variables.scr' files compared to the base file.")
            return final_changes

        for key, changes in sorted(changes_map.items()):
            if len(changes) == 1:
                final_changes[key] = changes[0].value
                print(f"[Auto] Applied change for '{key}' from '{changes[0].source}'.")
            else:
                print(f"\n[CONFLICT] Multiple changes detected for parameter '{key}':")
                for idx, change in enumerate(changes):
                    print(f"  {idx + 1}. '{change.value}' (from {change.source})")
                
                choice = self._get_user_choice(len(changes))
                if choice is not None:
                    final_changes[key] = changes[choice - 1].value
                    print(f"Option {choice} selected.")
                    
        return final_changes
    
    def resolve_file_conflicts(self, other_files_map: Dict[str, List[ModFile]]) -> Dict[str, Path]:
        """Resolve conflicts for other files found in mods"""
        print("\n--- Step 3: Processing Additional Files ---")
        final_other_files = {}
        
        if not other_files_map:
            print("No additional files found for processing.")
            return final_other_files

        for path, mod_files in sorted(other_files_map.items()):
            if len(mod_files) == 1:
                final_other_files[path] = mod_files[0].temp_path
                print(f"[Auto] Added file '{path}' from mod '{mod_files[0].source_name}'.")
            else:
                print(f"\n[CONFLICT] The same file '{path}' was found in multiple mods:")
                for idx, mod_file in enumerate(mod_files):
                    print(f"  {idx + 1}. Use version from mod '{mod_file.source_name}'")
                
                choice = self._get_user_choice(len(mod_files))
                if choice is not None:
                    final_other_files[path] = mod_files[choice - 1].temp_path
                    print(f"Option {choice} selected.")
                    
        return final_other_files
    
    @staticmethod
    def _get_user_choice(max_options: int) -> Optional[int]:
        """Get user choice for conflict resolution"""
        while True:
            try:
                choice = int(input(f"Enter the number of the desired option (1-{max_options}): "))
                if 1 <= choice <= max_options:
                    return choice
                print("Error: Invalid number.")
            except ValueError:
                print("Error: Please enter a number.")
            except KeyboardInterrupt:
                print("\nOperation cancelled by user.")
                return None


class ArchiveBuilder:
    """Handles building the final archive with merged changes"""
    
    def __init__(self, paths: PathManager):
        self.paths = paths
    
    def apply_changes_and_create_archive(self, 
                                       base_file_lines: List[str],
                                       final_player_vars_changes: Dict[str, str],
                                       final_other_files: Dict[str, Path]) -> bool:
        """Apply changes and create the final archive"""
        print("\n--- Step 4: Building Final File and Archiving ---")

        output_lines = list(base_file_lines)
        base_params_map = {
            ParameterParser.get_param_key(line): i 
            for i, line in enumerate(output_lines) 
            if ParameterParser.get_param_key(line)
        }

        new_params = []

        # 1. Replace existing parameters
        for key, new_value in final_player_vars_changes.items():
            if key in base_params_map:
                line_index = base_params_map[key]
                output_lines[line_index] = "    " + new_value + '\n'  # Add indentation for consistency
            else:
                # If key doesn't exist in base - it's a NEW parameter. Collect them.
                new_params.append(new_value)

        # 2. Add new parameters in the correct location
        if new_params:
            print(f"Found {len(new_params)} new parameters to add.")
            # Find the last closing brace '}' to insert BEFORE it
            insertion_point = ParameterParser.find_closing_brace_position(output_lines)

            if insertion_point != -1:
                print(f"Inserting new parameters before line {insertion_point + 1}.")
                for param in reversed(new_params):  # Insert in reverse order to maintain original order
                    output_lines.insert(insertion_point, "    " + param + '\n')
            else:
                # Emergency case if '}' not found - add to end
                print("Warning: Could not find closing brace '}'. Appending new params to the end of the file.")
                for param in new_params:
                    output_lines.append("    " + param + '\n')

        final_scr_content = "".join(output_lines)
        print("\nFinal 'player_variables.scr' successfully built in memory.")

        return self._create_archive(final_scr_content, final_other_files)
    
    def _create_archive(self, final_scr_content: str, final_other_files: Dict[str, Path]) -> bool:
        """Create the final archive with all changes"""
        # Prepare output directory
        if not FileUtils.clean_directory(self.paths.archive_dir):
            print("Failed to prepare output directory")
            return False
        
        print(f"Folder '{self.paths.archive_dir.name}' has been cleared and is ready.")

        # Create final archive
        print(f"Creating archive: {self.paths.final_archive_path}")
        
        try:
            with zipfile.ZipFile(self.paths.final_archive_path, 'w', zipfile.ZIP_DEFLATED) as pak_archive:
                pak_archive.writestr(
                    GameConfig.FINAL_PLAYER_VARS_PATH, 
                    final_scr_content.encode(GameConfig.DEFAULT_ENCODING)
                )
                print(f" -> '{GameConfig.FINAL_PLAYER_VARS_PATH}' added to archive.")

                for archive_dest_path, temp_source_path in final_other_files.items():
                    pak_archive.write(temp_source_path, arcname=archive_dest_path)
                    print(f" -> '{archive_dest_path}' added to archive.")

            print("\nArchive created successfully!")
            return True
        except Exception as e:
            print(f"Error creating archive: {e}")
            return False


class ModMergerApplication:
    """Main application class that orchestrates the mod merging process"""
    
    def __init__(self):
        self.paths = PathManager()
        self.extractor = ModExtractor(self.paths)
        self.resolver = ConflictResolver(self.paths)
        self.builder = ArchiveBuilder(self.paths)
    
    def run(self) -> None:
        """Main function to orchestrate the mod merging process"""
        try:
            print("=== Game Mod Merger Utility ===")
            print(f"Base directory: {self.paths.base_dir}")
            print()
            
            self.extractor.setup_directories()
            
            base_lines = self.extractor.load_base_file()
            if base_lines is None:
                return

            if not self.extractor.extract_mods():
                print("\nProcess finished as no suitable mods were found.")
                return

            final_player_vars = self.resolver.analyze_player_variables(base_lines)
            final_others = self.resolver.resolve_file_conflicts(self.extractor.other_files_map)

            if final_player_vars or final_others:
                if self.builder.apply_changes_and_create_archive(base_lines, final_player_vars, final_others):
                    print("\n\n=== Utility finished successfully! ===")
                    print(f"Your finished mod can be found here: {self.paths.final_archive_path}")
                else:
                    print("\n\n=== Error creating the final archive ===")
            else:
                print("\n\n=== Process finished. No changes were found to apply. ===")

        except KeyboardInterrupt:
            print("\n\nOperation cancelled by user.")
        except Exception as e:
            print(f"\nA critical error occurred: {e}")
            traceback.print_exc()
        finally:
            self.extractor.cleanup()


def main() -> None:
    """Entry point for the application"""
    app = ModMergerApplication()
    app.run()


if __name__ == "__main__":
    main()
    input("\nPress Enter to exit...")
