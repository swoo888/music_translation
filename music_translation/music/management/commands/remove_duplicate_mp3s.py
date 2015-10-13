import logging
from optparse import make_option
import threading

import shutil
import lockfile
from django.core.management import base
import os
import re

logger = logging.getLogger('music_translation.music.remove_duplicate_mp3s')


class Command(base.NoArgsCommand):
    MUSIC_FOLDER = '/Users/StevenWoo/Music/favorite'
    FOLDERS_IGNORE = ['favorite', 'Images', 'Lyrics', 'System Volume Information']
    # ignore these folder, they are not music folders

    option_list = base.NoArgsCommand.option_list + (
        make_option('-s', action='store_true', dest='silentmode',
                    default=False, help='Run in silent mode'),
        make_option('--extrasilent', action='store_true', dest='extrasilent',
                    default=False,
                    help='Run in silent mode with warnings ignored'),
        make_option('--debug', action='store_true', dest='debugmode',
                    default=False, help='Debug mode (overrides silent mode)'),
        make_option('--folder', action='store', dest='folder',
                    default=MUSIC_FOLDER, help='The music folder to translate'),
        make_option('-t', action='store_true', dest='testmode',
                    default=False, help='Test mode only translate one file'),
    )

    def __init__(self):
        super(Command, self).__init__()
        self.folder_to_strip_duplicate = self.MUSIC_FOLDER
        self.test_mode = False

    def handle_noargs(self, **options):
        if not options['silentmode']:
            logging.getLogger('music_translation').setLevel(logging.INFO)
        if options['extrasilent']:
            logging.getLogger('music_translation').setLevel(logging.ERROR)
        if options['debugmode']:
            logging.getLogger('music_translation').setLevel(logging.DEBUG)

        self.folder_to_strip_duplicate = options['folder']
        self.test_mode = options['testmode']

        lock = lockfile.FileLock('/tmp/remove_duplicate_mp3s')
        lock.acquire(3)
        with lock:
            self.remove_duplicate_mp3s()

    def remove_duplicate_mp3s(self):
        destination_dir = r'/tmp'
        duplicate_mp3_match = re.compile(r'\(\d+\)$', re.I | re.U)
        for dir_path, dir_names, file_names in os.walk(self.folder_to_strip_duplicate):
            dir_name = os.path.split(dir_path)[1]
            if dir_name not in self.FOLDERS_IGNORE:
                for filename in file_names:
                    if filename.endswith('.mp3') and duplicate_mp3_match.search(os.path.splitext(filename)[0]):
                        src_filename = os.path.join(dir_path, filename)
                        dest_filename = src_filename.replace(self.folder_to_strip_duplicate, destination_dir)
                        dest_dirname = os.path.split(dest_filename)[0]
                        if not os.path.exists(dest_dirname):
                            os.makedirs(dest_dirname)
                        logger.info('Moving file {} To {}'.format(src_filename, dest_filename))
                        threading.Thread(None, target=lambda: shutil.move(src_filename, dest_filename)).start()
                        if self.test_mode:
                            return
