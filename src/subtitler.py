import os
import shlex
import time
import zipfile
from configparser import ConfigParser
from subprocess import check_call, CalledProcessError

from modules import escape, getPendingItems, getNewItems
from requests import get


class Subtitler:
    def __init__(self):
        config = ConfigParser()
        config.read('config.ini')

        self.TEMP_FOLDER = config['FOLDERS']['TEMP']
        self.EXTRACT_FOLDER = config['FOLDERS']['EXTRACT']
        self.INPUT_FOLDER = config['FOLDERS']['INPUT']
        self.CONVERTING_FOLDER = config['FOLDERS']['CONVERTING']

        if not os.path.exists(self.TEMP_FOLDER):
            os.mkdir(self.TEMP_FOLDER)
        if not os.path.exists(self.EXTRACT_FOLDER):
            os.mkdir(self.EXTRACT_FOLDER)
        if not os.path.exists(self.INPUT_FOLDER):
            os.mkdir(self.INPUT_FOLDER)
        if not os.path.exists(self.CONVERTING_FOLDER):
            os.mkdir(self.CONVERTING_FOLDER)

        self.base_path = config['SSH']['BASE_PATH']
        self.shared_directory = config['PLEX']['SHARED_DIRECTORY']

        self.player = config['SUBTITLER']['PLAYER']
        self.upload_after = config['SUBTITLER'].getboolean('UPLOAD_AFTER')
        self.upload_ssh = f'{config["SUBTITLER"]["USER"]}@{config["SUBTITLER"]["URL"]}'
        self.upload_dir = config['SUBTITLER']['DIRECTORY']

    def rename(self, file):
        forbidden = ['/', '\\', '(', ')', '-', '_', '.']
        s_file = ""
        for char in file:
            if char in forbidden:
                if s_file[-1] != ' ':
                    s_file += ' '
            else:
                s_file += char
        new_name = ""

        words = s_file.split(' ')
        year = 'N.A.'
        for word in words[::-1]:
            if word.isdigit() and len(word) == 4:
                year = word
                break

        for word in words:
            if word == year:
                new_name += f"({word})"
                break
            else:
                new_name += f"{word} "
        new_name += '.mkv'

        if file != new_name:
            os.rename(os.path.join(self.INPUT_FOLDER, file),
                      os.path.join(self.INPUT_FOLDER, new_name))

    def discoverSubtitles(self, item):
        for file in os.listdir(self.TEMP_FOLDER):
            if 'eng' not in item.subs_in_file and 'eng' not in item.subs_out_file and file == f'{item.name}.eng.srt':
                self.convertSub(file, FOLDER=self.TEMP_FOLDER)
                item.subs_out_file['eng'] = file
            elif 'fre' not in item.subs_in_file and 'fre' not in item.subs_out_file and file == f'{item.name}.fre.srt':
                self.convertSub(file, FOLDER=self.TEMP_FOLDER)
                item.subs_out_file['fre'] = file

    def getSubtitles(self, item):
        print(f'-- Getting subtitles for {item.name} --\n'
              f'Subs in file: {item.subs_in_file}\nSubs out file: {item.subs_out_file}')
        if 'fre' not in item.subs_in_file and 'fre' not in item.subs_out_file:
            if input(">> French subs? (y/n): ") != 'n':
                item.missing_subs_language.append('fre')
        if 'eng' not in item.subs_in_file and 'eng' not in item.subs_out_file:
            if input(">> English subs? (y/n): ") != 'n':
                item.missing_subs_language.append('eng')

        if item.missing_subs_language:
            item.getSubFromYify()
            item.getSubFromPodnapisi()

            print(f'-- Syncing subtitles for {item.name} --')
            for language in item.missing_subs_language:
                for link in item.english_links if language == 'eng' else item.french_links:
                    file = self.downloadSub(link)
                    if file:
                        new_file = f'{item.name}.{language}.srt'
                        os.rename(os.path.join(self.EXTRACT_FOLDER, file),
                                  os.path.join(self.EXTRACT_FOLDER, new_file))
                        self.convertSub(new_file, FOLDER=self.EXTRACT_FOLDER)

                        os.system(f'""{self.player}" "{os.path.join(self.INPUT_FOLDER, item.local_file)}" '
                                  f'"{os.path.join(self.EXTRACT_FOLDER, new_file)}""')

                        if input(f'>> Is {language} sub correct? (y/n): ') != 'n':
                            os.rename(os.path.join(self.EXTRACT_FOLDER, new_file),
                                      os.path.join(self.TEMP_FOLDER, new_file))
                            if language == 'fre':
                                item.subs_out_file['fre'] = new_file
                            else:
                                item.subs_out_file['eng'] = new_file
                            break

                        else:
                            os.remove(os.path.join(self.EXTRACT_FOLDER, new_file))

    def downloadSub(self, link):
        print(f"Downloading and unzipping {link}")
        with open(os.path.join(self.EXTRACT_FOLDER, 'sub.zip'), "wb") as file:
            response = get(link)
            file.write(response.content)

        with zipfile.ZipFile(os.path.join(self.EXTRACT_FOLDER, 'sub.zip'), "r") as zip_file:
            zip_file.extractall(self.EXTRACT_FOLDER)

        os.remove(os.path.join(self.EXTRACT_FOLDER, 'sub.zip'))
        srts = []
        for file in os.listdir(self.EXTRACT_FOLDER):
            if os.path.isdir(os.path.join(self.EXTRACT_FOLDER, file)):
                os.removedirs(os.path.join(self.EXTRACT_FOLDER, file))
            elif not file.endswith('.srt'):
                os.remove(os.path.join(self.EXTRACT_FOLDER, file))
            else:
                srts.append(file)
        if not srts or len(srts) > 1:
            for srt in srts:
                os.remove(os.path.join(self.EXTRACT_FOLDER, srt))
            return None
        else:
            return srts[0]

    @staticmethod
    def convertSub(file, FOLDER):
        print(f"Converting {file}")

        file_path = os.path.join(FOLDER, file)

        f = open(file_path, mode='r', encoding='utf-8', errors='strict')
        try:
            for _ in f:
                pass
            f.close()

        except Exception as _:
            f.close()
            with open(file_path, encoding='cp1252') as f:
                data = f.read()
            with open(file_path + '.tmp', 'w', encoding='utf8') as f:
                f.write(data)

            os.remove(file_path)
            os.rename(file_path + '.tmp', file_path)

    @staticmethod
    def requiredSub(item):
        for sub in item.missing_subs_language:
            if sub not in item.subs_out_file:
                return False
        return True

    def mux(self, item):
        print(f'--- Muxing {item.name} ---')
        input_path = os.path.join(self.INPUT_FOLDER, item.local_file)
        output_path = os.path.join(self.TEMP_FOLDER, item.local_file)

        command = f'ffmpeg -v warning -stats -i "{input_path}" '

        for sub in item.subs_out_file.values():
            command += f'-i "{os.path.join(self.TEMP_FOLDER, sub)}" '
        command += '-map 0 '
        for i in range(1, len(item.subs_out_file) + 1):
            command += f'-map {i} '
        command += f'-movflags fastart -c:v copy -c:a copy -c:s srt '
        for language in item.subs_out_file.keys():
            item.max_id += 1
            command += f'-metadata:s:{item.max_id} language={language} '

        for audio in item.audio_languages.keys():
            if item.audio_languages[audio] in ['und', None]:
                if len(item.subs_in_file) + len(item.subs_out_file) >= 2:
                    item.audio_languages[audio] = 'eng'
                else:
                    item.audio_languages[audio] = 'fre'

            command += f'-metadata:s:{audio} language={item.audio_languages[audio]} '
        command += f'"{output_path}"'

        try:
            check_call(shlex.split(command))

            os.rename(output_path,
                      os.path.join(self.CONVERTING_FOLDER, item.local_file))
            for sub in item.subs_out_file.values():
                os.remove(os.path.join(self.TEMP_FOLDER, sub))
            os.remove(input_path)

        except CalledProcessError:
            print('Muxing failed !')
            time.sleep(30)
            self.mux(item)

    def upload(self, item):
        print(f'--- Uploading {item.name} ---')

        info_file = f'{os.path.join(self.TEMP_FOLDER, item.local_file)}.info'
        with open(info_file, 'w', encoding='utf-8') as f:
            f.write(os.path.join(self.shared_directory,
                                 input(f'Save in : {os.path.join(self.base_path, self.shared_directory)}'),
                                 item.local_file))
        local_file = os.path.join(self.CONVERTING_FOLDER, item.local_file)

        command_file = 'scp ' \
                       f'{escape(local_file)} ' \
                       f'{escape(self.upload_ssh)}:"{escape(os.path.join(self.upload_dir, self.CONVERTING_FOLDER))}"'

        command_info = 'scp ' \
                       f'{escape(info_file)} ' \
                       f'{escape(self.upload_ssh)}:"{escape(os.path.join(self.upload_dir, self.TEMP_FOLDER))}"'

        try:
            check_call(shlex.split(command_info))
            check_call(shlex.split(command_file))

            os.remove(local_file)
            os.remove(info_file)

        except CalledProcessError:
            print('Upload failed !')
            time.sleep(30)
            self.upload(item)

    def run(self):
        items = getPendingItems(self.INPUT_FOLDER)
        noSubOnline = []

        while True:
            getNewItems(self.INPUT_FOLDER, items)
            if not items:
                print('\nWaiting for new files...')
            while not items:
                time.sleep(1)
                getNewItems(self.INPUT_FOLDER, items)

            for item in items[:]:
                if item not in noSubOnline:
                    print(f'\n{item}')

                self.discoverSubtitles(item)
                if item not in noSubOnline:
                    self.getSubtitles(item)

                if self.requiredSub(item):
                    if item in noSubOnline:
                        print(f'\n{item}')
                        noSubOnline.remove(item)

                    self.mux(item)
                    if self.upload_after:
                        self.upload(item)
                    items.remove(item)

                else:
                    if item not in noSubOnline:
                        noSubOnline.append(item)
                        print(f'Missing subtitles for {item.name}')

            time.sleep(1)


if __name__ == '__main__':
    subtitler = Subtitler()
    subtitler.run()