import datetime
import logging
import multiprocessing
import subprocess
from optparse import make_option
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import lockfile
import os
import re
from bs4 import BeautifulSoup
from django.core.management import base
from shutil import copy

logger = logging.getLogger('music_translation.music.translate_chinese_titles')


def copy_music_file_to_dest(src_filename, dest_filename):
    logger.info('copy_music_file_to_dest, {}, {}'.format(src_filename, dest_filename))
    if dest_filename.endswith('.flac'):
        root, ext = os.path.splitext(dest_filename)
        dest_filename_mp3 = root + '.mp3'
        xld = '/usr/local/bin/xld -f mp3 -o "{}" --bit=320kbps --samplerate=44100 "{}"'.format(dest_filename_mp3,
                                                                                               src_filename)
        subprocess.call(xld, shell=True)
    else:
        copy(src_filename, dest_filename)


def translate_file_to_dest(src_dir, src_filename, dest_dir):
    file_name_translated = src_filename
    logger.info(src_filename)
    try:
        src_filename.encode('ascii')
    except UnicodeEncodeError:
        file_name_translated = Command.http_translate_chinese_txt(src_filename)
        if not file_name_translated:
            # raise Exception('Cant translate chinese file name')
            file_name_translated = src_filename
    logger.info(file_name_translated)
    file_name_translated = '{}{}{}{}'.format(
        Command.LEFT_SEP, file_name_translated, Command.RIGHT_SEP, src_filename)

    dest_filename = os.path.join(dest_dir, file_name_translated)
    src_filename = os.path.join(src_dir, src_filename)
    logger.info('copy src_filename:{} To dest_filename:{}'.format(src_filename, dest_filename))
    copy_music_file_to_dest(src_filename, dest_filename)


class Command(base.NoArgsCommand):
    MUSIC_FOLDER = '/Users/StevenWoo/Music/favorite'
    FOLDERS_IGNORE = ['favorite', 'Images', 'Lyrics', 'System Volume Information']
    # ignore these folder, they are not music folders
    MAX_FILES = 255
    RIGHT_SEP = '>'
    LEFT_SEP = '<'
    FIRST_CHR_IDX = 1  # after <
    FOLDER_PER_ARTIST = True  # organize songs into their own artist folder

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
        make_option('--destination', action='store', dest='destination',
                    default='', help='Destination folder to store your translated music'),
    )

    def __init__(self):
        super(Command, self).__init__()
        self.folder_to_translate = self.MUSIC_FOLDER
        self.test_mode = False
        self.destination = ''

    def handle_noargs(self, **options):
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

    def translate_chinese_titles(self):
        if not self.destination:
            self.destination = os.path.join(os.path.dirname(self.folder_to_translate),
                                            'translate-{}'.format(datetime.datetime.now().strftime('%m-%d-%y')))
        if not os.path.exists(self.destination):
            # shutil.rmtree(self.destination, ignore_errors=True)
            os.mkdir(self.destination)

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
                destination_dir = os.path.join(self.destination, '{}{}{}{}'.format(
                    Command.LEFT_SEP, dir_name_translated, Command.RIGHT_SEP, dir_name))
                if not os.path.exists(destination_dir):
                    os.mkdir(destination_dir)

                pool = multiprocessing.Pool()
                for filename in file_names:
                    if filename.endswith('.mp3') or filename.endswith('.flac'):
                        # if filename.endswith('.mp3') and not exclude_mp3_match.search(os.path.splitext(filename)[0]):
                        # ignore duplicate mp3 files that ends in file_name(1).mp3 etc..

                        pool.apply_async(translate_file_to_dest, args=(dir_path, filename, destination_dir))
                        if self.test_mode:
                            return
                pool.close()
                pool.join()
                Command.organize_songs(destination_dir)

    @staticmethod
    def organize_songs(mp3_folder):
        # organize songs into max 255 each per folder
        for dir_path, dir_names, file_names in os.walk(mp3_folder):
            if dir_path == mp3_folder:
                if not Command.FOLDER_PER_ARTIST:
                    if len(file_names) > Command.MAX_FILES:
                        next_song_list = sorted(file_names)
                        songs_cnt = len(next_song_list)
                        while songs_cnt >= 1:
                            first_char = next_song_list[0][Command.FIRST_CHR_IDX]
                            # organize songs into each starting Letter folder for easy find
                            last_char = first_char
                            sub_name = first_char
                            sub_name = sub_name.upper()
                            dest_mp3_folder = Command.get_folder_name_with_sub_name(mp3_folder, sub_name)
                            next_song_list = Command.move_songs_by_first_char(
                                    dir_path, next_song_list, first_char, last_char, dest_mp3_folder)
                            if songs_cnt == len(next_song_list):
                                raise Exception('Organize songs failed; song list not changing')
                            songs_cnt = len(next_song_list)
                        return
                else:
                    next_song_list = sorted(file_names)
                    songs_cnt = len(next_song_list)
                    while songs_cnt >= 1:
                        # <ChenYiWen-TaoHuaZhanXiaoRong.MP3>陈忆文 - 桃花展笑容.mp3
                        first_artist_name = Command.get_artist_name(next_song_list[0])
                        last_artist_name = first_artist_name
                        sub_name = first_artist_name
                        dest_mp3_folder = Command.get_folder_name_with_sub_name(mp3_folder, sub_name)
                        next_song_list = Command.move_songs_by_artist_name(
                                dir_path, next_song_list, first_artist_name, last_artist_name, dest_mp3_folder)
                        if songs_cnt == len(next_song_list):
                            raise Exception('Organize songs failed; song list not changing')
                        songs_cnt = len(next_song_list)
                    return

    @staticmethod
    def get_artist_name(song_name):
        # <ChenYiWen-TaoHuaZhanXiaoRong.MP3>陈忆文 - 桃花展笑容.mp3
        return song_name.split('-')[0][Command.FIRST_CHR_IDX:]

    @staticmethod
    def rm_artist_name(song_name):
        # <ChenYiWen-TaoHuaZhanXiaoRong.MP3>陈忆文 - 桃花展笑容.mp3
        artist_name = Command.get_artist_name(song_name)
        return song_name.replace(artist_name+'-', '', 1)

    @staticmethod
    def move_songs_by_first_char(dir_path, sorted_file_names, first_char, last_char, dest_mp3_folder):
        cnt = 1
        songs_renamed = []
        for song in sorted_file_names:
            if first_char <= song[Command.FIRST_CHR_IDX] <= last_char:
                dir, name = os.path.split(song)
                dest_mp3_filename = os.path.join(dest_mp3_folder, name)
                src_mp3_filename = os.path.join(dir_path, song)
                os.rename(src_mp3_filename, dest_mp3_filename)
                songs_renamed.append(song)
                cnt += 1
                if cnt >= Command.MAX_FILES:
                    break
        next_song_list = [x for x in sorted_file_names if x not in songs_renamed]
        return next_song_list

    @staticmethod
    def move_songs_by_artist_name(dir_path, sorted_file_names, first_artist_name, last_artist_name, dest_mp3_folder):
        cnt = 1
        songs_renamed = []
        for song in sorted_file_names:
            if first_artist_name <= Command.get_artist_name(song) <= last_artist_name:
                _dir, name = os.path.split(song)
                if Command.FOLDER_PER_ARTIST:
                    name = Command.rm_artist_name(name)
                dest_mp3_filename = os.path.join(dest_mp3_folder, name)
                src_mp3_filename = os.path.join(dir_path, song)
                os.rename(src_mp3_filename, dest_mp3_filename)
                songs_renamed.append(song)
                cnt += 1
                if cnt >= Command.MAX_FILES:
                    break
        next_song_list = [x for x in sorted_file_names if x not in songs_renamed]
        return next_song_list

    @staticmethod
    def get_folder_name_with_sub_name(dir_path, sub_name):
        if not dir_path.index(Command.RIGHT_SEP):
            dir_path = '{}{}{}'.format(Command.LEFT_SEP, dir_path, Command.RIGHT_SEP)
        cnt = 1
        while cnt < 20:
            if cnt >= 2:
                sub_name_rep = sub_name + str(cnt)
            else:
                sub_name_rep = sub_name
            if not Command.FOLDER_PER_ARTIST:
                path_with_sub_name = dir_path.replace(Command.RIGHT_SEP, Command.RIGHT_SEP + sub_name_rep, 1)
            else:
                path_with_sub_name = os.path.join(dir_path, sub_name_rep)
            if not os.path.exists(path_with_sub_name):
                os.mkdir(path_with_sub_name)
                return path_with_sub_name
            cnt += 1

    @staticmethod
    def http_translate_chinese_txt(zhong_wen_txt):
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
                return Command.http_translate_chinese_txt(strip_txt)
            else:
                logger.info('Data from web is empty')
                return zhong_wen_txt
        else:
            title = resp_txt[0].get_text().title()
            return re.sub(r'\s+', '', title)
