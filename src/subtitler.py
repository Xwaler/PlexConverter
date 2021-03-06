import os
import shlex
import time
import zipfile
from configparser import ConfigParser
from subprocess import check_call, CalledProcessError

from requests import get

from modules import escape, get_pending_items, get_new_items, scp_option


class Subtitler:
    def __init__(self):
        config = ConfigParser()
        config.read('config.ini')

        self.TEMP_FOLDER = config['FOLDERS']['TEMP']
        self.EXTRACT_FOLDER = config['FOLDERS']['EXTRACT']
        self.INPUT_FOLDER = config['FOLDERS']['INPUT']
        self.SUBBED_FOLDER = config['FOLDERS']['SUBBED']
        self.CONVERTING_FOLDER = config['FOLDERS']['CONVERTING']

        if not os.path.exists(self.TEMP_FOLDER):
            os.mkdir(self.TEMP_FOLDER)
        if not os.path.exists(self.EXTRACT_FOLDER):
            os.mkdir(self.EXTRACT_FOLDER)
        if not os.path.exists(self.INPUT_FOLDER):
            os.mkdir(self.INPUT_FOLDER)
        if not os.path.exists(self.SUBBED_FOLDER):
            os.mkdir(self.SUBBED_FOLDER)
        if not os.path.exists(self.CONVERTING_FOLDER):
            os.mkdir(self.CONVERTING_FOLDER)

        self.library_directory = config["PLEX"]["LIBRARY_DIRECTORY"]

        self.player = config['SUBTITLER']['PLAYER']
        self.player_sub_option = config['SUBTITLER']['PLAYER_SUB_OPTION']
        self.upload_after = config['SUBTITLER'].getboolean('UPLOAD_AFTER')
        self.upload_ssh = f'{config["SUBTITLER"]["USER"]}@{config["SUBTITLER"]["URL"]}'
        self.upload_dir = config['SUBTITLER']['DIRECTORY']

        self.last_path = ''

    def rename(self, item):
        forbidden = ['/', '\\', '(', ')', '-', '_', '.']
        s_file = ""
        name, extension = item.local_file.rsplit('.', 1)
        for char in name:
            if char in forbidden:
                if s_file[-1] != ' ':
                    s_file += ' '
            else:
                s_file += char

        words = s_file.split(' ')
        year = None
        for word in words[::-1]:
            if word.isdigit() and len(word) == 4:
                year = word
                break

        if not year:
            return

        new_name = words[0]
        correct = False
        for word in words[1:]:
            if word == year:
                new_name += f" ({word})"
                correct = True
                break
            else:
                new_name += f" {word}"

        if not correct:
            return
        new_file = f'{new_name}.{extension}'

        if item.local_file != new_file:
            if input(f'Rename {item.local_file}\n    to {new_file} ? (Y/n): ') != 'n':
                os.rename(os.path.join(self.INPUT_FOLDER, item.local_file),
                          os.path.join(self.INPUT_FOLDER, new_file))
                item.local_file = new_file
                item.name = new_name

    def discover_subtitles(self, item):
        for file in os.listdir(self.TEMP_FOLDER):
            if 'eng' not in item.subs_in_file and 'eng' not in item.subs_out_file and file.lower() in [
                f'{item.name}.eng.srt'.lower(),
                f'{item.name}.en.srt'.lower()
            ]:
                self.convert_sub(file, folder=self.TEMP_FOLDER)
                item.subs_out_file['eng'] = file
            elif 'fre' not in item.subs_in_file and 'fre' not in item.subs_out_file and file.lower() in [
                f'{item.name}.fre.srt'.lower(),
                f'{item.name}.fr.srt'.lower()
                    ]:
                self.convert_sub(file, folder=self.TEMP_FOLDER)
                item.subs_out_file['fre'] = file

    def get_subtitles(self, item):
        print(f'--- Getting subtitles ---\n'
              f'Subs in file: {item.subs_in_file}\nSubs out file: {item.subs_out_file}')
        item.missing_subs_language = []
        if 'fre' not in item.subs_in_file and 'fre' not in item.subs_out_file:
            if input(">> French subs ? (Y/n): ") != 'n':
                item.missing_subs_language.append('fre')
        if 'eng' not in item.subs_in_file and 'eng' not in item.subs_out_file:
            if input(">> English subs ? (Y/n): ") != 'n':
                item.missing_subs_language.append('eng')

        if item.missing_subs_language:
            item.get_sub_from_yify()
            item.get_sub_from_podnapisi()

            print(f'-- Syncing subtitles for {item.name} --')
            for language in item.missing_subs_language:
                for link in item.english_links if language == 'eng' else item.french_links:
                    file = self.download_sub(link)
                    if file:
                        new_file = f'{item.name}.{language}.srt'
                        os.rename(os.path.join(self.EXTRACT_FOLDER, file),
                                  os.path.join(self.EXTRACT_FOLDER, new_file))
                        self.convert_sub(new_file, folder=self.EXTRACT_FOLDER)

                        os.system(f'"{self.player}" "{os.path.join(self.INPUT_FOLDER, item.local_file)}" '
                                  f'{self.player_sub_option} "{os.path.join(self.EXTRACT_FOLDER, new_file)}"')

                        if input(f'>> Is {language} sub correct ? (Y/n): ') != 'n':
                            os.rename(os.path.join(self.EXTRACT_FOLDER, new_file),
                                      os.path.join(self.TEMP_FOLDER, new_file))
                            if language == 'fre':
                                item.subs_out_file['fre'] = new_file
                            else:
                                item.subs_out_file['eng'] = new_file
                            break

                        else:
                            os.remove(os.path.join(self.EXTRACT_FOLDER, new_file))

    def download_sub(self, link):
        print(f"Downloading and unzipping {link}")
        with open(os.path.join(self.EXTRACT_FOLDER, 'sub.zip'), "wb") as file:
            response = get(link)
            file.write(response.content)

        with zipfile.ZipFile(os.path.join(self.EXTRACT_FOLDER, 'sub.zip'), "r") as zip_file:
            zip_file.extractall(self.EXTRACT_FOLDER)

        os.remove(os.path.join(self.EXTRACT_FOLDER, 'sub.zip'))
        srts = []
        for thing in os.listdir(self.EXTRACT_FOLDER):
            if os.path.isdir(os.path.join(self.EXTRACT_FOLDER, thing)):
                for in_file in os.listdir(os.path.join(self.EXTRACT_FOLDER, thing)):
                    os.remove(os.path.join(self.EXTRACT_FOLDER, thing, in_file))
                os.removedirs(os.path.join(self.EXTRACT_FOLDER, thing))
            elif not thing.endswith('.srt'):
                os.remove(os.path.join(self.EXTRACT_FOLDER, thing))
            else:
                srts.append(thing)
        if not srts or len(srts) > 1:
            for srt in srts:
                os.remove(os.path.join(self.EXTRACT_FOLDER, srt))
            return None
        else:
            return srts[0]

    @staticmethod
    def convert_sub(file, folder):
        print(f"Converting {file}")

        file_path = os.path.join(folder, file)

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
    def required_sub(item):
        for sub in item.missing_subs_language:
            if sub not in item.subs_out_file:
                return False
        return True

    def mux(self, item):
        print(f'--- Muxing ---')
        input_path = os.path.join(self.INPUT_FOLDER, item.local_file)
        output_file = item.name + '.mkv'
        output_path = os.path.join(self.TEMP_FOLDER, output_file)

        command = f'ffmpeg -v warning -stats -fflags +genpts -i "{input_path}" '

        for sub in item.subs_out_file.values():
            command += f'-i {escape(os.path.join(self.TEMP_FOLDER, sub))} '
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
        command += f'{escape(output_path)}'

        try:
            check_call(shlex.split(command))

            os.rename(output_path,
                      os.path.join(self.SUBBED_FOLDER, output_file))
            for sub in item.subs_out_file.values():
                os.remove(os.path.join(self.TEMP_FOLDER, sub))
            os.remove(input_path)
            item.local_file = output_file

        except CalledProcessError:
            print('Muxing failed !')
            time.sleep(30)
            self.mux(item)

    def ask_path(self):
        if not (self.last_path and input(f'>> Save in same directory ? '
                                         f'({os.path.join(self.library_directory, self.last_path)}) '
                                         f'(Y/n): ') != 'n'):
            self.last_path = input(f'>> Save in : {self.library_directory}')

    def upload(self, item):
        print(f'--- Uploading ---')

        self.ask_path()
        info_file = f'{os.path.join(self.TEMP_FOLDER, item.name)}.info'
        with open(info_file, 'w', encoding='utf-8') as f:
            f.write(os.path.join(self.library_directory, self.last_path, item.local_file))
        local_file = os.path.join(self.SUBBED_FOLDER, item.local_file)

        command_info = f'scp {scp_option} ' \
                       f'"{info_file}" ' \
                       f'{self.upload_ssh}:\'\"{os.path.join(self.upload_dir, self.TEMP_FOLDER)}\"\''

        command_file = f'scp {scp_option} ' \
                       f'"{local_file}" ' \
                       f'{self.upload_ssh}:\'\"{os.path.join(self.upload_dir, self.CONVERTING_FOLDER)}\"\''

        try:
            check_call(shlex.split(command_info))
            check_call(shlex.split(command_file))

            os.remove(local_file)
            os.remove(info_file)

        except CalledProcessError:
            print('Upload failed !')
            time.sleep(30)
            self.upload(item)

    def prepare_for_conversion(self, item):
        os.rename(os.path.join(self.SUBBED_FOLDER, item.local_file),
                  os.path.join(self.CONVERTING_FOLDER, item.local_file))

    def run(self):
        items = []

        while True:
            for item in get_pending_items(self.SUBBED_FOLDER):
                self.upload(item)

            get_new_items(self.INPUT_FOLDER, items)
            if not items:
                print('\nWaiting for new files...')
            while not items:
                time.sleep(1)
                get_new_items(self.INPUT_FOLDER, items)

            print('\nPlease select next file to process:')
            priority = sorted(items, key=lambda x: (x.missing_subs_online, x.need_video_convert(),
                                                    x.need_audio_convert(), x.local_file))
            for i, item in enumerate(priority):
                print(f'{i:3d}: ('
                      f'{"S" if item.missing_subs_online else "-"}'
                      f'{"V" if item.need_video_convert() else "-"}'
                      f'{"A" if item.need_audio_convert() else "-"}'
                      f') {item.local_file}')
            print(f'Options: [0...{len(priority) - 1}] | reload')
            i, selected, reload = None, None, False
            while not (selected or reload):
                try:
                    i = input('>> ')
                    selected = priority[int(i)]
                except ValueError:
                    if i == '':
                        selected = priority[0]
                    elif i == 'reload':
                        reload = True
            if reload:
                continue

            self.rename(selected)
            print(f'--> {selected}')

            self.discover_subtitles(selected)
            self.get_subtitles(selected)

            if self.required_sub(selected):
                self.mux(selected)
                if self.upload_after:
                    self.upload(selected)
                else:
                    self.prepare_for_conversion(selected)
                items.remove(selected)

            else:
                selected.missing_subs_online = True
                print(f'Missing subtitles for {selected.local_file}')


if __name__ == '__main__':
    subtitler = Subtitler()
    subtitler.run()
