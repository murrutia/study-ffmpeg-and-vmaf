#!/usr/local/anaconda3/envs/vmaf/bin/python

import sys
import subprocess
from time import time
from pathlib import Path
from datetime import datetime


SCRIPT_DIR = Path(sys.path[0])
input_files = SCRIPT_DIR / "mp4.files"
ORIGINAL_VIDEO_DIR = SCRIPT_DIR / "tmp" / "original"
ENCODED_VIDEO_DIR = SCRIPT_DIR / "tmp" / "encoded"
ORIGINAL_VIDEO_DIR.mkdir(parents=True, exist_ok=True)
ENCODED_VIDEO_DIR.mkdir(parents=True, exist_ok=True)
FFMPEG_BIN = SCRIPT_DIR / "external" / "ffmpeg"

log_path = SCRIPT_DIR / "output" / "encoding.log"


def remove_first_line(input):
    subprocess.run(['sed', '-i', '-e', '1d', input])


def get_first_line(input):
    line = subprocess.check_output(['head', '-n', '1', input], text=True)
    return line.strip()


def unshift_first_line(input):
    line = get_first_line(input)
    if line:
        remove_first_line(input)
        return line
    return None


def convert_bytes(size):
    for x in ['bytes', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return "%3.1f %s" % (size, x)
        size /= 1024.0

    return size


def download_video(video_name):
    video_local_path = ORIGINAL_VIDEO_DIR / video_name
    subprocess.run(['touch', video_local_path])
    subprocess.run(['rsync', '-avrz', f"murrutia@axone.utc.fr:/var/www/resources/videos/{video_name}", video_local_path])
    return video_local_path


def upload_video(video_path):
    video_name = video_path.name
    subprocess.run(['rsync', '-avrz', video_path, f"murrutia@axone.utc.fr:/var/www/resources/videos/{video_name}"])


def encode_video(original_path):
    encoded_path = ENCODED_VIDEO_DIR / original_path.name
    subprocess.run([
        FFMPEG_BIN,
        '-i', original_path,
        '-crf', '27',
        '-movflags', '+faststart',
        '-y', encoded_path])
    return encoded_path


if __name__ == '__main__':

    # check if there is a file in the orignal video folder
    if any(ORIGINAL_VIDEO_DIR.iterdir()):
        first_file = [f for f in ORIGINAL_VIDEO_DIR.iterdir()][0]
        file_stats = first_file.stat()
        download_failed = file_stats.st_size == 0 and file_stats.st_mtime < time() - 3600

        encoding = any(ENCODED_VIDEO_DIR.iterdir())
        encoded_file = [f for f in ENCODED_VIDEO_DIR.iterdir()][0]
        encoding_failed = encoding and encoded_file.stat().st_mtime < time() - 300
        
        if encoding_failed or download_failed: 
            video_name = first_file.name
        else:
            print(f"The directory {ORIGINAL_VIDEO_DIR} is not empty and the file is too recent to be discarded as an error. End of script.")
            sys.exit()
    else:
        # if there is not get first line
        print("No file, beginning of the script")
        video_name = unshift_first_line(input_files)

        # if line download video
        if not video_name:
            print("There is no file to encode")
            sys.exit()
    
    print()

    dl_time = datetime.now()
    original_path = download_video(video_name)

    # after download begin encoding
    enc_time = datetime.now()
    encoded_path = encode_video(original_path)

    # after encoding if video is downsized below 90%, reupload video
    size_original = original_path.stat().st_size
    size_encoded = encoded_path.stat().st_size

    ratio = size_encoded / size_original

    if ratio < 0.9:
        upload_video(encoded_path)

    # erase original and encoded
    original_path.unlink()
    encoded_path.unlink()

    ''' write infos in log file:
        - video name
        - time of beginning of download
        - time of beginning of encoding
        - filesize comparison
        - time of beginning of reupload (if any)
        - time of end of script
    '''
    with open(log_path, 'a') as fd:
        fd.write(f'''
Video : {original_path.name}
    download : {dl_time.strftime("%Y-%m-%d %H-%M-%S")}
    encoding : {enc_time.strftime("%Y-%m-%d %H-%M-%S")}
    end of script : {datetime.now().strftime("%Y-%m-%d %H-%M-%S")}
    original size : {size_original} ({convert_bytes(size_original)})
    encoded size : {size_encoded} ({convert_bytes(size_encoded)})
    ratio : {ratio}
    re-uploaded : {'yes' if ratio < 0.9 else 'no'}

''')
