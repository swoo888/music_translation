import logging
import multiprocessing
import subprocess
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import lockfile
import os
import re
import shutil
from bs4 import BeautifulSoup
from django.core.management import BaseCommand
from shutil import copy

logger = logging.getLogger('music_translation.music.translate_chinese_songs')


def copy_and_convert_music_file_to_dest(src_file_full_path, dest_file_full_path):
    logger.info('copy and convert music {} to {}'.format(src_file_full_path, dest_file_full_path))
    dest_filename_mp3 = dest_file_full_path
    if src_file_full_path.endswith('.flac'):
        root, ext = os.path.splitext(dest_file_full_path)
        dest_filename_mp3 = root + '.mp3'
        xld = '/usr/local/bin/xld -f mp3 -o "{}" --bit=320kbps --samplerate=44100 "{}"'.format(
            dest_filename_mp3, src_file_full_path)
        try:
            subprocess.call(xld, shell=True)
        except subprocess.CalledProcessError as e:
            logger.error(e)
            return ""
    else:
        copy(src_file_full_path, dest_filename_mp3)
    return dest_filename_mp3


def tag_song(dest_song_full_path_mp3, artist_name_tag, song_name_tag):
    # id3tag --artist=冷漠,王雅洁,WangYaJie,LengMo --album=ChouSheng test_cd.mp3
    tag_cmd = "/usr/local/bin/id3tag --artist='{}' --song='{}' '{}'".format(
        artist_name_tag, song_name_tag, dest_song_full_path_mp3)
    logger.info('tag cmd: {}'.format(tag_cmd))
    try:
        subprocess.call(tag_cmd, shell=True)
    except subprocess.CalledProcessError as e:
        logger.error(e)


def translate_chinese_song(src_song_full_path, dest_dir, artist_name, song_name):
    artist_name_tag = artist_name
    if is_chinese(artist_name):
        artist_name_tag = Command.get_ch_text_translation(artist_name) + ", " + artist_name
    song_name_tag = song_name
    if is_chinese(song_name):
        song_name_tag = Command.get_ch_text_translation(song_name) + ", " + song_name
    src_ext = os.path.splitext(src_song_full_path)[1]
    dest_song_full_path = os.path.join(dest_dir, song_name_tag) + src_ext
    dest_song_full_path_mp3 = copy_and_convert_music_file_to_dest(src_song_full_path, dest_song_full_path)
    if dest_song_full_path_mp3:
        tag_song(dest_song_full_path_mp3, artist_name_tag, song_name_tag)


def is_chinese(text):
    try:
        text.encode('ascii')
    except UnicodeEncodeError:
        return True
    return False


class Command(BaseCommand):
    MUSIC_FOLDER = '/Users/StevenWoo/Music/网易云音乐'
    # ignore these folder, they are not music folders
    FOLDERS_IGNORE = ['favorite', 'Images', 'Lyrics', 'System Volume Information']

    def add_arguments(self, parser):
        parser.add_argument('-s', action='store_true', dest='silentmode',
                            default=False, help='Run in silent mode'),
        parser.add_argument('--extrasilent', action='store_true', dest='extrasilent',
                            default=False,
                            help='Run in silent mode with warnings ignored'),
        parser.add_argument('--debug', action='store_true', dest='debugmode',
                            default=False, help='Debug mode (overrides silent mode)'),
        parser.add_argument('-t', action='store_true', dest='testmode',
                            default=False, help='Test mode only translate one file'),
        parser.add_argument('--folder', action='store', dest='folder',
                            default=self.MUSIC_FOLDER,
                            help='The music folder to translate; '
                                 'music files are assumed to be organized by artists sub folders'),
        parser.add_argument('--destination', action='store', dest='destination',
                            default='/tmp/translate-music-out',
                            help='Destination folder to store your translated music')

    def __init__(self):
        super(Command, self).__init__()
        self.folder_to_translate = self.MUSIC_FOLDER
        self.test_mode = False
        self.destination = ''

    def handle(self, *args, **options):
        if not options['silentmode']:
            logging.getLogger('music_translation').setLevel(logging.INFO)
        if options['extrasilent']:
            logging.getLogger('music_translation').setLevel(logging.ERROR)
        if options['debugmode']:
            logging.getLogger('music_translation').setLevel(logging.DEBUG)

        self.folder_to_translate = options['folder']
        self.test_mode = options['testmode']
        self.destination = options['destination']

        lock = lockfile.FileLock('/tmp/translate_chinese_titles')
        lock.acquire(3)
        with lock:
            self.translate_chinese_titles()

    @staticmethod
    def has_music_file(file_names):
        for file_name in file_names:
            if file_name.endswith('.mp3') or file_name.endswith('.flac'):
                return True
        return False

    def translate_chinese_titles(self):
        if os.path.exists(self.destination):
            shutil.rmtree(self.destination, ignore_errors=True)
        if not os.path.exists(self.destination):
            os.mkdir(self.destination)

        folders_translated = {}
        pool = multiprocessing.Pool()
        for root, dir_names, file_names in os.walk(self.folder_to_translate):
            if not file_names or not self.has_music_file(file_names):
                continue
            dir_name = os.path.split(root)[1]
            if dir_name in self.FOLDERS_IGNORE:
                continue
            logger.info('Processing dir_name: %s', dir_name)
            dir_name_translated = folders_translated.get(dir_name)
            if not dir_name_translated:
                if is_chinese(dir_name):
                    dir_name_translated = Command.get_ch_text_translation(dir_name)
                else:
                    dir_name_translated = dir_name
                folders_translated[dir_name] = dir_name_translated
            destination_dir = os.path.join(self.destination, dir_name_translated)
            if not os.path.exists(destination_dir):
                os.mkdir(destination_dir)

            for filename in file_names:
                if filename.endswith('.mp3') or filename.endswith('.flac'):
                    # 刘珂矣 - 半壶纱.flac
                    song_name_noext = os.path.splitext(filename)[0]
                    logger.info('Processing song name: {}'.format(song_name_noext))
                    [artist_name, song_name] = song_name_noext.split(' - ', 1)
                    pool.apply_async(translate_chinese_song,
                                     args=(os.path.join(root, filename),
                                           destination_dir, artist_name, song_name))
                    if self.test_mode:
                        break
        pool.close()
        pool.join()

    @staticmethod
    def get_ch_text_translation(ch_text):
        txt_translated = Command._http_get_chinese_translation(ch_text)
        if not txt_translated:
            return ch_text
        return txt_translated

    @staticmethod
    # http_get_chinese_translation translates chinese text to english letter pronounciations
    def _http_get_chinese_translation(zhong_wen_txt):
        data = urlencode({
            'zwzyp_zhongwen': zhong_wen_txt,
            'zwzyp_shengdiao': 0,
            'zwzyp_wenzi': 0,
            'zwzyp_jiange': 1,
            'zwzyp_duozhongduyin': 0,
        }).encode('utf-8')

        cnt = 0
        resp_data = ''
        while cnt < 3:
            try:
                response = urlopen(
                    url='http://zhongwenzhuanpinyin.51240.com/web_system/51240_com_www/system/file/' +
                        'zhongwenzhuanpinyin/data/?ajaxtimestamp=144295876963',
                    data=data)
            except URLError:
                logger.info('web connection failed')
            else:
                if response.reason != 'OK':
                    logger.info('Cant obtain translation data from web.')
                else:
                    resp_data = response.read()
                    break
            cnt += 1

        soup = BeautifulSoup(resp_data, 'html.parser')
        resp_txt = soup.findAll('textarea', attrs={'name': "zhongwen"}, limit=1)
        if not resp_txt:
            strip_txt = re.sub(r'[\x00-\x7f]', r'', zhong_wen_txt)  # strip all ASCII
            if strip_txt != zhong_wen_txt:
                return Command._http_get_chinese_translation(strip_txt)
            else:
                logger.info('Data from web is empty')
                return zhong_wen_txt
        else:
            title = resp_txt[0].get_text().title()
            return re.sub(r'\s+', '', title)
