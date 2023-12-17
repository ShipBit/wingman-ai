from os import path, makedirs


class FileCreator:
    def __init__(self, app_root_dir: str, subdir: str):
        """Creates the given subdirectory in the app root path if it doesn't exist yet.
        Use the get_full_file_path to create files within the subdirectory safely afterwards.
        """

        self.file_dir: str = path.join(app_root_dir, subdir)
        if not path.exists(self.file_dir):
            makedirs(self.file_dir)

    def get_full_file_path(self, file_name: str) -> str:
        return path.join(self.file_dir, file_name)
