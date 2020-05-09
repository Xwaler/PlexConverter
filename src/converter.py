import os
import shlex
import time
from configparser import ConfigParser
from subprocess import check_call, CalledProcessError

from modules import escape, getPendingItems, getNewItems


class PlexConverter:
    def __init__(self):
        config = ConfigParser()
        config.read('config.ini')

        self.TEMP_FOLDER = config['FOLDERS']['TEMP']
        self.CONVERTING_FOLDER = config['FOLDERS']['CONVERTING']
        self.NORMALIZING_FOLDER = config['FOLDERS']['NORMALIZING']
        self.OUTPUT_FOLDER = config['FOLDERS']['DONE']

        if not os.path.exists(self.TEMP_FOLDER):
            os.mkdir(self.TEMP_FOLDER)
        if not os.path.exists(self.CONVERTING_FOLDER):
            os.mkdir(self.CONVERTING_FOLDER)
        if not os.path.exists(self.NORMALIZING_FOLDER):
            os.mkdir(self.NORMALIZING_FOLDER)
        if not os.path.exists(self.OUTPUT_FOLDER):
            os.mkdir(self.OUTPUT_FOLDER)

        self.base_path = config['SSH']['BASE_PATH']
        self.ssh = f'{config["SSH"]["USER"]}@{config["PLEX"]["URL"]}'

        self.max_video_width = config['CONVERTER'].getint('MAX_VIDEO_WIDTH')
        self.avg_bitrate = config['CONVERTER'].getint('AVERAGE_BITRATE')
        self.max_bitrate = config['CONVERTER'].getint('MAX_BITRATE')

    def notConverted(self, item):
        return not os.path.exists(os.path.join(self.NORMALIZING_FOLDER, item.local_file))

    def convert(self, item):
        print(f'--- Converting {item.name} ---')
        input_path = os.path.join(self.CONVERTING_FOLDER, item.local_file)
        output_path = os.path.join(self.TEMP_FOLDER, item.local_file)

        nvenc = 'CUDA' in os.environ['PATH']
        video_options = '-c:v h264_nvenc -preset slow -rc:v vbr_hq -cq:v 19' if nvenc \
            else '-c:v libx264 -preset slow'

        if item.needVideoConvert():
            command = f'ffmpeg -v warning -stats -i "{input_path}" -movflags fastart -map 0 ' \
                      f'-pix_fmt yuv420p -filter:v scale={min(item.video_resolution[1], self.max_video_width)}:-2 ' \
                      f'-sws_flags lanczos {video_options} -profile:v high -level:v 4.1 -qmin 16 ' \
                      f'-b:v {self.avg_bitrate}k -maxrate:v {self.max_bitrate}k -bufsize {2 * self.avg_bitrate}k ' \
                      f'-c:a aac -ac 2 -c:s srt "{output_path}"'

        elif item.needAudioConvert():
            command = f'ffmpeg -v warning -stats -i "{input_path}" -movflags fastart -map 0 ' \
                      f'-c:v copy -c:a aac -ac 2 -c:s srt "{output_path}"'

        else:
            command = f'ffmpeg -v warning -stats -i "{input_path}" -movflags fastart -map 0 ' \
                      f'-c:v copy -c:a copy -c:s srt "{output_path}"'

        try:
            check_call(shlex.split(command))
            os.rename(output_path,
                      os.path.join(self.NORMALIZING_FOLDER, item.local_file))

        except CalledProcessError:
            print('Convertion failed !')
            time.sleep(30)
            self.convert(item)

    def notNormalized(self, item):
        return not os.path.exists(os.path.join(self.OUTPUT_FOLDER, item.local_file))

    def normalize(self, item):
        print(f'--- Normalizing {item.name} ---')
        input_path = os.path.join(self.NORMALIZING_FOLDER, item.local_file)
        output_path = os.path.join(self.OUTPUT_FOLDER, item.local_file)

        command = f'ffmpeg-normalize "{input_path}" -v -pr -c:a aac -b:a 128k -ar 48000 -o "{output_path}"'

        try:
            check_call(shlex.split(command))

        except CalledProcessError:
            print('Normalization failed !')
            time.sleep(30)
            self.normalize(item)

    def ready(self, item):
        return os.path.exists(os.path.join(self.OUTPUT_FOLDER, item.local_file)) and \
               os.path.getsize(os.path.join(self.OUTPUT_FOLDER, item.local_file)) > 1_000

    def upload(self, item):
        print(f'--- Uploading {item.name} ---')
        command = 'scp ' \
                  f'{escape(os.path.join(self.OUTPUT_FOLDER, item.local_file))} ' \
                  f'{escape(self.ssh)}:{escape(os.path.join(self.base_path, item.remote_directory))}'

        try:
            check_call(shlex.split(command))

        except CalledProcessError:
            print('Upload failed !')
            time.sleep(30)
            self.upload(item)

    def cleanup(self, item):
        os.remove(os.path.join(self.CONVERTING_FOLDER, item.local_file))
        os.remove(os.path.join(self.NORMALIZING_FOLDER, item.local_file))
        os.remove(os.path.join(self.OUTPUT_FOLDER, item.local_file))

        info = os.path.join(self.TEMP_FOLDER, item.local_file + '.info')
        if os.path.exists(info):
            os.remove(info)

    def run(self):
        items = getPendingItems(self.CONVERTING_FOLDER)

        while True:
            while items:
                item = items[0]
                for i in items:
                    if not i.needVideoConvert():
                        item = i
                        break

                print(f'\n{item}')

                while self.notConverted(item):
                    self.convert(item)

                while self.notNormalized(item):
                    self.normalize(item)

                if self.ready(item):
                    self.upload(item)
                    self.cleanup(item)
                    items.remove(item)

                else:
                    print('Failed !')

            getNewItems(self.CONVERTING_FOLDER, items)
            if not items:
                print('\nWaiting for new files...')

            while not items:
                time.sleep(1)
                getNewItems(self.CONVERTING_FOLDER, items)


if __name__ == '__main__':
    converter = PlexConverter()
    converter.run()
