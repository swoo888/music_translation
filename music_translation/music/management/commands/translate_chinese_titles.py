import logging
from optparse import make_option
import datetime
import threading
from urllib.request import urlopen
from urllib.parse import urlencode

import shutil
import lockfile
from django.core.management import base
import os
from bs4 import BeautifulSoup
import re
from shutil import copy

logger = logging.getLogger('music_translation.music.translate_chinese_titles')


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
        self.folder_to_translate = self.MUSIC_FOLDER
        self.test_mode = False

    def handle_noargs(self, **options):
        if not options['silentmode']:
            logging.getLogger('music_translation').setLevel(logging.INFO)
        if options['extrasilent']:
            logging.getLogger('music_translation').setLevel(logging.ERROR)
        if options['debugmode']:
            logging.getLogger('music_translation').setLevel(logging.DEBUG)

        self.folder_to_translate = options['folder']
        self.test_mode = options['testmode']

        lock = lockfile.FileLock('/tmp/translate_chinese_titles')
        lock.acquire(3)
        with lock:
            self.translate_chinese_titles()

    def translate_chinese_titles(self):
        destination_music_folder = os.path.join(os.path.dirname(self.folder_to_translate),
                                                'translate-{}'.format(datetime.datetime.now().strftime('%m-%d-%y')))
        if not os.path.exists(destination_music_folder):
            # shutil.rmtree(destination_music_folder, ignore_errors=True)
            os.mkdir(destination_music_folder)

        # exclude_mp3_match = re.compile(r'\(\d+\)$', re.I | re.U)
        for dir_path, dir_names, file_names in os.walk(self.folder_to_translate):
            dir_name = os.path.split(dir_path)[1]
            if dir_name not in self.FOLDERS_IGNORE:
                logger.info('dir_name: %s', dir_name)
                dir_name_translated = dir_name
                try:
                    dir_name.encode('ascii')
                except UnicodeEncodeError:  # translate only non ascii chars
                    dir_name_translated = Command.http_translate_chinese_txt(dir_name)
                    if not dir_name_translated:
                        # raise Exception('Cant translate chinese directory name')
                        dir_name_translated = dir_name
                logger.info(dir_name_translated)
                destination_dir = os.path.join(destination_music_folder,
                                               '<{}>{}'.format(dir_name_translated, dir_name))
                if not os.path.exists(destination_dir):
                    os.mkdir(destination_dir)

                for filename in file_names:
                    if filename.endswith('.mp3'):
                        # if filename.endswith('.mp3') and not exclude_mp3_match.search(os.path.splitext(filename)[0]):
                        # ignore duplicate mp3 files that ends in file_name(1).mp3 etc..
                        file_name_translated = filename
                        logger.info(filename)
                        try:
                            filename.encode('ascii')
                        except UnicodeEncodeError:
                            file_name_translated = Command.http_translate_chinese_txt(filename)
                            if not file_name_translated:
                                # raise Exception('Cant translate chinese file name')
                                file_name_translated = filename
                        logger.info(file_name_translated)
                        file_name_translated = '<{}>{}'.format(file_name_translated, filename)

                        dest_filename = os.path.join(destination_dir, file_name_translated)
                        src_filename = os.path.join(dir_path, filename)
                        logger.info('copy src_filename:{} To dest_filename:{}'.format(src_filename, dest_filename))
                        threading.Thread(None, target=lambda: copy(src_filename, dest_filename)).start()
                        if self.test_mode:
                            return

    @staticmethod
    def http_translate_chinese_txt(zhong_wen_txt):
        data = urlencode({
            'zwzyp_zhongwen': zhong_wen_txt,
            'zwzyp_shengdiao': 0,
            'zwzyp_wenzi': 0,
            'zwzyp_jiange': 1,
            'zwzyp_duozhongduyin': 0,
        }).encode('utf-8')

        response = urlopen(
            url='http://zhongwenzhuanpinyin.51240.com/web_system/51240_com_www/system/file/' +
                'zhongwenzhuanpinyin/data/?ajaxtimestamp=144295876963',
            data=data)

        if response.reason != 'OK':
            raise Exception('Cant obtain translation data from web.')

        resp_data = response.read()
        soup = BeautifulSoup(resp_data, 'html.parser')
        resp_txt = soup.findAll('textarea', attrs={'name': "zhongwen"}, limit=1)
        if not resp_txt:
            strip_txt = re.sub(r'[\x00-\x7f]', r'', zhong_wen_txt)  # strip all ASCII
            if strip_txt != zhong_wen_txt:
                return Command.http_translate_chinese_txt(strip_txt)
            raise Exception('Data from web is empty')

        title = resp_txt[0].get_text().title()
        return re.sub(r'\s+', '', title)
