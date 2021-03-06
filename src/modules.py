import os
import platform
from configparser import ConfigParser
from difflib import SequenceMatcher

import psutil
from bs4 import BeautifulSoup
from requests import get, session

from ffprobe_wrapper import FFProbe

config = ConfigParser()
config.read('config.ini')

TEMP_FOLDER = config['FOLDERS']['TEMP']
MAX_VIDEO_WIDTH = config['CONVERTER'].getint('MAX_VIDEO_WIDTH')
MAX_VIDEO_HEIGHT = config['CONVERTER'].getint('MAX_VIDEO_HEIGHT')
MAX_BITRATE = config['CONVERTER'].getint('MAX_BITRATE')

scp_option = '-T' if platform.system() == 'Linux' else ''


def escape(string):
    for char in [' ', ',', ';', ':', '(', ')', '[', ']', '{', '}', '\'', '\"']:
        string = string.replace(char, '\\' + char)
    return string


def has_handle(paths):
    fpaths = {os.path.abspath(path): i for i, path in enumerate(paths)}
    kpaths = fpaths.keys()
    handles = [False] * len(fpaths)
    for proc in psutil.process_iter():
        try:
            of = set(p.path for p in proc.open_files())
        except psutil.AccessDenied:
            pass
        else:
            for inter in kpaths & of:
                handles[fpaths[inter]] = True
    return handles


def get_pending_items(folder):
    files = os.listdir(folder)
    items = []
    if files:
        paths = [os.path.join(folder, f) for f in files]
        handles = has_handle(paths)
        for path in [path for i, path in enumerate(paths) if not handles[i]]:
            items.append(LocalItem(FFProbe(path)))
        return sorted(items, key=lambda x: x.name)
    return items


def get_new_items(folder, items):
    files = [file for file in os.listdir(folder) if file not in [item.local_file for item in items]]
    if files:
        paths = [os.path.join(folder, f) for f in files]
        handles = has_handle(paths)
        for path in [path for i, path in enumerate(paths) if not handles[i]]:
            items.append(LocalItem(FFProbe(path)))
        items.sort(key=lambda x: x.name)


class Item:
    def __init__(self):
        self.name = None
        self.remote_path = None
        self.remote_file = None
        self.local_file = None
        self.bitrate = None
        self.framerate = None
        self.video_codec = None
        self.video_profile = None
        self.video_resolution = None
        self.audio_codec = None
        self.audio_profile = None
        self.audio_channels = None
        self.container = None
        self.reasons = {}

    def get_reasons(self):
        if self.video_codec != 'h264' or self.video_profile != 'high':
            self.reasons['Video codec'] = {'Codec': self.video_codec,
                                           'Profile': self.video_profile}

        if self.audio_codec != 'aac':
            self.reasons['Audio codec'] = self.audio_codec
        elif self.audio_codec == 'aac' and self.audio_profile != 'lc':
            self.reasons['Audio codec'] = {'Codec': self.audio_codec,
                                           'Profile': self.audio_profile}

        if self.audio_channels not in ('1', '2'):
            self.reasons['Audio channels'] = self.audio_channels

        if self.bitrate > MAX_BITRATE:
            self.reasons['High bitrate'] = {'Bitrate': self.bitrate,
                                            'Resolution': self.video_resolution}

        elif self.video_resolution[0] < MAX_VIDEO_HEIGHT and self.video_resolution[1] < MAX_VIDEO_WIDTH:
            self.reasons['Low resolution'] = self.video_resolution

        if self.container != 'mkv':
            self.reasons['Container'] = self.container

        if self.framerate != 'NTSC' and self.framerate != 'PAL' and (
                int(self.framerate[:-1]) > 30):
            self.reasons['Framerate'] = self.framerate

    def need_video_convert(self):
        return 'Video codec' in self.reasons or \
               'High bitrate' in self.reasons or \
               'Framerate' in self.reasons or \
               'Low resolution' in self.reasons

    def need_audio_convert(self):
        return 'Audio codec' in self.reasons or \
               'Audio channels' in self.reasons

    def __repr__(self):
        return f'{self.local_file} | {self.reasons}'

    def __eq__(self, other):
        return self.name == other.name and self.reasons == other.reasons


class LocalItem(Item):
    def __init__(self, metadata):
        super().__init__()

        video = metadata.video[0]
        audio = metadata.audio[0]

        self.local_file = os.path.basename(metadata.path_to_video)
        self.name = self.local_file.rsplit('.', 1)[0]
        print(f'Found {self.local_file}')

        self.get_remote_path()

        self.video_codec = video.codec_name
        self.video_profile = video.profile.lower()
        self.audio_codec = audio.codec_name
        if self.audio_codec == 'aac':
            self.audio_profile = audio.profile.lower()
        self.audio_channels = audio.channels
        self.video_resolution = (int(video.height), int(video.width))
        self.bitrate = int(metadata.metadata['bitrate'][:-5])
        self.framerate = str(video.framerate)
        self.container = self.local_file[-3:]

        self.subs_in_file = [sub.language() for sub in metadata.subtitle]
        self.subs_out_file = {}
        self.max_id = max([int(stream.index) for stream in metadata.streams])
        self.audio_languages = {audio.index: audio.language() for audio in metadata.audio}
        self.missing_subs_language = []
        self.missing_subs_online = False
        self.french_links = []
        self.english_links = []

        self.get_reasons()

    def get_remote_path(self):
        for file in os.listdir(TEMP_FOLDER):
            if file == self.name + '.info':
                self.remote_path = open(os.path.join(TEMP_FOLDER, file), 'r', encoding='utf-8').readline()
                self.remote_file = os.path.basename(self.remote_path)
                return

    def get_sub_from_yify(self):
        print("Getting missing subtitles from Yify... ", end='')

        site = "http://yifysubtitles.org"
        search_name = self.name.replace('(', '').replace(')', '').lower()

        page = get(site + "/search?q=" + search_name)
        soup = BeautifulSoup(page.text, "html.parser")
        movies = soup.find_all("h3", class_="media-heading")

        url = None
        for movie in movies:
            if SequenceMatcher(None, movie.string.lower(), search_name[:-5]).ratio() > .8:
                url = movie.find_parent("a").find_parent("div").find("a", href=True)['href']
                break

        if url is None:
            page = get(site + "/search?q=" + search_name[:-5])
            soup = BeautifulSoup(page.text, "html.parser")
            movies = soup.find_all("h3", class_="media-heading")

            for movie in movies:
                if SequenceMatcher(None, movie.string.lower(), search_name[:-5]).ratio() > .8:
                    url = movie.find_parent("a").find_parent("div").find("a", href=True)['href']
                    break

        if url is None:
            print('not found')

        else:
            print('found')

            page = get(site + url)
            soup = BeautifulSoup(page.text, "html.parser")

            subtitles = soup.find_all("span", class_="sub-lang")

            for language in self.missing_subs_language:
                for sub in subtitles:
                    if sub.string[:3].lower() == language:
                        link = site + "/subtitle" + sub.find_next("a", href=True)['href'][10:] + '.zip'
                        if language == 'fre':
                            self.french_links.append(link)
                        else:
                            self.english_links.append(link)

    def get_sub_from_podnapisi(self):
        print("Getting missing subtitles from podnapisi... ", end='')

        site = "http://www.podnapisi.net"

        s = session()
        headers = {"Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7"}

        page = s.get(site + "/moviedb/search/?keywords=" + self.name.replace(' ', '+'),
                     headers=headers)
        soup = BeautifulSoup(page.text, "html.parser")
        movies = soup.find_all("a", attrs={'class': "movie_item"})

        def get_url():
            for movie in movies:
                if SequenceMatcher(
                        None,
                        movie.find('div', attrs={'class': 'title'}).find('span').find('span').string.lower(),
                        self.name.lower()
                ).ratio() > .8:
                    return movie['href'].split('/moviedb/entry')[1]

        url = get_url()
        if url is None:
            page = s.get(site + "/moviedb/search/?keywords=" + self.name.split()[0], headers=headers)
            soup = BeautifulSoup(page.text, "html.parser")
            movies = soup.find_all("a", attrs={'class': "movie_item"})
            url = get_url()

        if url is None:
            print('not found')
        else:
            print('found')

            page = get(f"{site}/subtitles/search{url}?language=en&language=fr&sort=stats.downloads&order=desc#list",
                       headers=headers)
            soup = BeautifulSoup(page.text, "html.parser")

            subtitles = soup.find_all("tr", attrs={"class": "subtitle-entry"})

            for language in self.missing_subs_language:
                for sub in subtitles:
                    if f"/subtitles/{language[:2].lower()}" in sub['data-href']:
                        link = site + sub['data-href'] + '/download'
                        if language == 'fre':
                            self.french_links.append(link)
                        else:
                            self.english_links.append(link)


class RemoteItem(Item):
    def __init__(self, name, media_info):
        super().__init__()

        self.name = name

        self.remote_path = media_info['Part']['@file']
        self.remote_file = os.path.basename(self.remote_path)

        self.video_codec = media_info['@videoCodec']
        self.video_profile = media_info['@videoProfile']
        self.audio_codec = media_info['@audioCodec']
        if self.audio_codec == 'aac':
            self.audio_profile = media_info['@audioProfile']
        self.audio_channels = media_info['@audioChannels']
        self.video_resolution = (int(media_info['@height']), int(media_info['@width']))
        self.size = int(media_info['Part']['@size'])
        self.duration = int(media_info['@duration'])
        self.bitrate = int(self.size * 8 / self.duration)
        self.framerate = media_info['@videoFrameRate']
        self.container = media_info['@container']
        self.get_reasons()


class Library:
    def __init__(self, xml):
        self.name = xml["@title"]
        self.id = int(xml['Location']['@id'])
