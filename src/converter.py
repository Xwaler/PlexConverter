import os
import shlex
import time
from configparser import ConfigParser
from subprocess import check_call, CalledProcessError

from modules import get_pending_items, scp_option


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

        self.ssh = f'{config["SSH"]["USER"]}@{config["PLEX"]["URL"]}'

        self.max_video_width = config['CONVERTER'].getint('MAX_VIDEO_WIDTH')
        self.avg_bitrate = config['CONVERTER'].getint('AVERAGE_BITRATE')
        self.max_bitrate = config['CONVERTER'].getint('MAX_BITRATE')

    def convert(self, item):
        print(f'--- Converting ---')
        input_path = os.path.join(self.CONVERTING_FOLDER, item.local_file)
        output_path = os.path.join(self.TEMP_FOLDER, item.local_file.rsplit('.', 1)[0] + '.mkv')

        nvenc = 'CUDA' in os.environ['PATH']
        video_options = '-c:v h264_nvenc -preset slow -rc:v vbr_hq -cq:v 19' if nvenc \
            else '-c:v libx264 -preset slow'
        try:
            audio_channels = min(int(item.audio_channels), 2)
        except ValueError:
            audio_channels = 2

        if item.need_video_convert():
            command = f'ffmpeg -v warning -stats -fflags +genpts -i "{input_path}" -movflags fastart -map 0 ' \
                      f'-pix_fmt yuv420p -vf scale={self.max_video_width}:-2:flags=lanczos ' \
                      f'{video_options} -profile:v high -level:v 4.1 -qmin 16 ' \
                      f'-b:v {self.avg_bitrate}k -maxrate:v {self.max_bitrate}k -bufsize {2 * self.avg_bitrate}k ' \
                      f'-c:a {f"aac -ac {audio_channels}" if item.need_audio_convert() else "copy"} ' \
                      f'-c:s srt "{output_path}"'

        elif item.need_audio_convert():
            command = f'ffmpeg -v warning -stats -fflags +genpts -i "{input_path}" -movflags fastart -map 0 ' \
                      f'-c:v copy -c:a aac -ac {audio_channels} -c:s srt "{output_path}"'

        else:
            command = f'ffmpeg -v warning -stats -fflags +genpts -i "{input_path}" -movflags fastart -map 0 ' \
                      f'-c:v copy -c:a copy -c:s srt "{output_path}"'

        try:
            check_call(shlex.split(command))
            item.local_file = os.path.basename(output_path)
            os.rename(output_path,
                      os.path.join(self.NORMALIZING_FOLDER, item.local_file))
            os.remove(input_path)

        except CalledProcessError:
            print('Conversion failed !')
            time.sleep(30)
            self.convert(item)

    def normalize(self, item):
        print(f'--- Normalizing ---')
        input_path = os.path.join(self.NORMALIZING_FOLDER, item.local_file)
        output_path = os.path.join(self.OUTPUT_FOLDER, item.local_file)

        command = f'ffmpeg-normalize "{input_path}" -v -pr -c:a aac -b:a 128k -ar 48000 -o "{output_path}"'

        try:
            check_call(shlex.split(command))
            os.remove(input_path)

        except CalledProcessError:
            print('Normalization failed !')
            time.sleep(30)
            self.normalize(item)

    def upload(self, item):
        print(f'--- Uploading ---\nTo {os.path.dirname(item.remote_path)}')
        command_dirs = ['ssh', self.ssh,
                        'mkdir', '-p', shlex.quote(os.path.dirname(item.remote_path))]
        command = ['scp', scp_option,
                   os.path.join(self.OUTPUT_FOLDER, item.local_file),
                   f'{self.ssh}:{shlex.quote(os.path.join(os.path.dirname(item.remote_path), item.local_file))}']
        command_duplicate = ['ssh', self.ssh,
                             'rm', '-f', shlex.quote(item.remote_path)]

        try:
            check_call(command_dirs)
            check_call(command)
            if item.remote_file != item.local_file:
                print(f'Removing old file {item.remote_file}')
                check_call(command_duplicate)

            os.remove(os.path.join(self.OUTPUT_FOLDER, item.local_file))
            info = os.path.join(self.TEMP_FOLDER, item.name + '.info')
            os.remove(info)

        except CalledProcessError:
            print('Upload failed !')
            time.sleep(30)
            self.upload(item)

    def run(self):
        waiting = False
        while True:
            converting = get_pending_items(self.CONVERTING_FOLDER)
            normalizing = get_pending_items(self.NORMALIZING_FOLDER)
            uploading = get_pending_items(self.OUTPUT_FOLDER)

            if converting or normalizing or uploading:
                waiting = False

                for item in uploading:
                    print(f'\n{item}')
                    self.upload(item)

                for item in converting:
                    if not item.need_video_convert():
                        print(f'\n{item}')
                        self.convert(item)
                        self.normalize(item)
                        self.upload(item)

                if normalizing:
                    for item in normalizing:
                        print(f'\n{item}')
                        self.normalize(item)
                        self.upload(item)

                else:
                    for item in converting:
                        if item.need_video_convert():
                            print(f'\n{item}')
                            self.convert(item)
                            break

            else:
                if not waiting:
                    print('\nWaiting for new files...')
                    waiting = True

                else:
                    time.sleep(1)


if __name__ == '__main__':
    converter = PlexConverter()
    converter.run()
