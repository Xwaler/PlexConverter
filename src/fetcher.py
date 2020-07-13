import os
import shlex
import time
from configparser import ConfigParser
from subprocess import check_call, CalledProcessError

from requests import get
from requests.exceptions import ConnectionError
from xmltodict import parse

from modules import RemoteItem, Library, scp_option


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
        self.ssh = f'{config["SSH"]["USER"]}@{config["PLEX"]["URL"]}'

    def get_wrapper(self, url):
        failed = False
        while True:
            try:
                response = get(url, params={'X-Plex-Token': self.plex_token}, timeout=(2, None))

                if failed:
                    print(' success !', flush=True)
                return response

            except ConnectionError:
                if failed:
                    print('.', end='', flush=True)
                else:
                    print('Failed to get response.', end='', flush=True)
                    failed = True
                time.sleep(3)

    def getLibraries(self):
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
        all_items = self.getItems(library)
        pending_items = [item for item in all_items if item.reasons]
        return pending_items, len(all_items)

    def download(self, item):
        print(f'--- Downloading {item.name} ---')
        command = ['scp', scp_option, f'{self.ssh}:{shlex.quote(item.remote_path)}', self.TEMP_FOLDER]

        try:
            check_call(command)

            with open(os.path.join(self.TEMP_FOLDER, f'{item.remote_file.rsplit(".", 1)[0]}.info'), 'w') as f:
                f.write(item.remote_path)
            os.rename(os.path.join(self.TEMP_FOLDER, item.remote_file),
                      os.path.join(self.CONVERTING_FOLDER, item.remote_file))

        except CalledProcessError:
            print('Download failed, retry soon...')
            time.sleep(30)
            self.download(item)

    def folderFull(self):
        return sum(f.endswith('.info') for f in os.listdir(self.TEMP_FOLDER)) >= 2

    def notDownloaded(self, item):
        return not os.path.exists(os.path.join(self.TEMP_FOLDER, f'{item.remote_file.rsplit(".", 1)[0]}.info'))

    def run(self):
        done = []
        while True:
            print(f'\n--- Fetching libraries --- ({time.strftime("%X", time.localtime())})')

            for library in self.getLibraries():
                print(f'Library {library.name}: ', end='', flush=True)

                pending_items, count_items = self.getPendingItems(library)
                items = [item for item in pending_items
                         if item not in done and self.notDownloaded(item)]
                size = len(items)
                i = 0

                print(f'{len(pending_items)} pending, {count_items} total')
                for item in items:
                    print(f'Entry {i + 1}/{size}\n{item}')

                    while self.folderFull():
                        time.sleep(1)

                    while self.notDownloaded(item):
                        self.download(item)

                    done.append(item)
                    i += 1
                    print('', end='\n')

            time.sleep(150)


if __name__ == '__main__':
    fetcher = PlexFetcher()
    fetcher.run()
