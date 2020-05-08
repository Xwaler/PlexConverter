import os
import shlex
import sys
import time
from configparser import ConfigParser
from subprocess import check_call, CalledProcessError

from modules import RemoteItem, Library, escape
from requests import get
from requests.exceptions import ConnectionError
from xmltodict import parse


class PlexFetcher:
    def __init__(self):
        config = ConfigParser()
        config.read('config.ini')

        self.TEMP_FOLDER = config['FOLDERS']['TEMP']
        self.CONVERTING_FOLDER = config['FOLDERS']['CONVERTING']

        if not os.path.exists(self.TEMP_FOLDER):
            os.mkdir(self.TEMP_FOLDER)
        if not os.path.exists(self.CONVERTING_FOLDER):
            os.mkdir(self.CONVERTING_FOLDER)

        self.plex_token = config['PLEX']['TOKEN']
        self.plex_url = f'http://{config["PLEX"]["URL"]}:{config["PLEX"]["PORT"]}'
        self.sftp_url = f'{config["SSH"]["USER"]}@{config["PLEX"]["URL"]}'
        self.sftp_base_path = config["SSH"]["BASE_PATH"]

    def get_wrapper(self, url):
        failed = False
        while True:
            try:
                response = get(url, params={'X-Plex-Token': self.plex_token})

                if failed:
                    print(' success !')
                return response

            except ConnectionError:
                if failed:
                    print('.', end='')
                else:
                    print('Failed to get response.', end='')
                sys.stdout.flush()
                failed = True
                time.sleep(3)

    def getLibraries(self):
        print('--- Fetching libraries ---')

        response = self.get_wrapper(
            f'{self.plex_url}/library/sections',
        )
        librairies = parse(response.content)['MediaContainer']['Directory']
        librairies = [Library(library) for library in librairies]
        librairies = sorted(librairies, key=lambda x: x.id)

        return librairies

    def getItems(self, librairy):
        response = self.get_wrapper(
            f'{self.plex_url}/library/sections/{librairy.id}/allLeaves'
        )
        items = parse(response.content)['MediaContainer']['Video']

        parsed_items = []
        for item in items:
            media_infos = item['Media']
            if not isinstance(media_infos, list):
                media_infos = [media_infos]
            previous_path = None
            for media_info in media_infos:
                if previous_path is None:
                    previous_path = media_info['Part']['@file']
                else:
                    if media_info['Part']['@file'] == previous_path:
                        continue
                    else:
                        previous_path = media_info['Part']['@file']

                parsed_items.append(RemoteItem(item['@title'], media_info))

        return parsed_items

    def getPendingItems(self, library):
        return [item for item in self.getItems(library) if item.reasons and item.canBeCorrected()]

    def download(self, item):
        print(f'--- Downloading {item.name} ---')
        path = os.path.join(self.sftp_base_path, item.remote_directory[1:], item.remote_file)
        command = f'scp {escape(self.sftp_url)}:{escape(path), escape(self.TEMP_FOLDER)}'

        try:
            check_call(shlex.split(command))

            with open(os.path.join(self.TEMP_FOLDER, f'{item.local_file}.info'), 'w') as f:
                f.write(item.remote_path)
            os.rename(os.path.join(self.TEMP_FOLDER, item.remote_file),
                      os.path.join(self.CONVERTING_FOLDER, item.local_file))

        except CalledProcessError:
            print('Download failed, retry soon...')
            time.sleep(30)
            self.download(item)

    def folderFull(self):
        return len(os.listdir(self.CONVERTING_FOLDER)) > 5

    def notDownloaded(self, item):
        return not (os.path.exists(os.path.join(self.CONVERTING_FOLDER, item.local_file)) and
                    0.99 <= os.path.getsize(os.path.join(self.CONVERTING_FOLDER, item.local_file)) / item.size <= 1.01)

    def run(self):
        done = []
        while True:
            for library in self.getLibraries():
                print(f'--- Analysing library {library.name} ---')

                items = [item for item in self.getPendingItems(library)
                         if item not in done and self.notDownloaded(item)]
                size = len(items)
                i = 0

                for item in items:
                    print(f'Entry {i + 1}/{size}\n{item}')

                    while self.folderFull():
                        time.sleep(1)

                    while self.notDownloaded(item):
                        self.download(item)

                    done.append(item)
                    i += 1

            time.sleep(120)


if __name__ == '__main__':
    fetcher = PlexFetcher()
    fetcher.run()
