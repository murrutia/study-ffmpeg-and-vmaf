#!/usr/bin/env python3

import re
import sys
import json
import argparse
from os import rename
import subprocess
from subprocess import run, PIPE, Popen
from collections import deque
from pprint import PrettyPrinter
from os.path import splitext, isdir, join as path_join, basename, abspath
from pathlib import Path
import shutil



# source : https://stackoverflow.com/a/14981125
def eprint(*args, **kwargs):
    """print message(s) to stderr"""
    print(*args, file=sys.stderr, **kwargs)


def pp(dict):
    ppp = PrettyPrinter(2)
    ppp.pprint(dict)


def run_shell(*args, **kwargs):
    r = run(*args, stdout=PIPE, stderr=PIPE, **kwargs)
    return r.stdout.strip()


def scale_params(size):
    if not re.fullmatch(r'[0-9]+x[0-9]+', size):
        eprint(f"La résolution '{size}' n'est pas valide")
        sys.exit(1)

    (w, h) = size.split('x')
    ratio = int(w) / int(h)

    return ['-aspect', str(ratio), '-vf', f"scale={size},setsar=1/1"]


def get_streams_data(file_input):
    command = [
        'ffprobe',
        file_input,
        '-show_streams',
        '-print_format', 'json',
        '-hide_banner'
    ]
    json_str = run_shell(command)
    try:
        streams = json.loads(json_str)['streams']
    except:
        eprint("Une erreur est survenue lors de l'extraction des informations de cette vidéo")
        sys.exit(4)

    return streams


def get_stream_data(file_input, type):

    streams = get_streams_data(file_input)

    streams_of_type = [stream for stream in streams if stream['codec_type'] == type]

    if len(streams_of_type) == 0:
        eprint(f"Ce fichier ne contient pas de piste {type}, il ne sera donc pas traité.")
        sys.exit(2)
    elif len(streams_of_type) > 1:
        eprint(f"Ce fichier contient plusieurs pistes {type}, il ne sera donc pas traité.")
        sys.exit(3)

    return streams_of_type[0]


def get_ffprobe_sar(file_input):
    """Certains fichiers vidéo ont plusieurs inforations de SAR/DAR et il arrive à `ffprobe`
    de ne pas nous renvoyer la bonne si on utilise l'option `-show_streams`.
    J'ai pensé utiliser la commande `mediainfo`, mais il lui arrive aussi de mal interpréter
    ces doublons.
    Après l'avoir testé sur plusieurs fichiers, il semble que dans la sortie sur `stderr`
    peut apparaître 1 ou 2 fois, entre `[]` ou non et que celle entre `[]` est forcément bonne.
    Du coup, ce code cherche d'abord une valeur entre `[]` et se rabat sur l'autre sinon.
    """
    command = [
        'ffprobe',
        file_input
    ]
    proc = Popen(command, stdout=PIPE, stderr=PIPE)
    stdout, stderr = proc.communicate()
    err_str = str(stderr)

    sar_bracket = re.search(r'\[SAR ([0-9]+:[0-9]+) ', err_str)
    if sar_bracket:
        return sar_bracket[1]

    sar = re.search(r'SAR ([0-9]+:[0-9]+) ', err_str)
    if sar:
        return sar[1]

    return None


def guess_resolution(file_input):

    # https://forum.videohelp.com/threads/323530-please-explain-SAR-DAR-PAR
    # Display Aspect Ratio = Frame Aspect Ratio x Sample Aspect Ratio
    # DAR = FARxSAR
    # 16/9 = 1440/1080 x 4/3
    video = get_stream_data(file_input, 'video')

    width = int(video['width']) if 'width' in video else int(video['coded_width'])
    height = int(video['height']) if 'height' in video else int(video['coded_width'])

    # correction de dimensions à valeurs impaires
    width = width - width % 2
    height = height - height % 2

    ratio = width / height

    sar_str = get_ffprobe_sar(file_input)

    print(f"dimensions : {width}x{height}", end='')

    if sar_str:
        # print("sar_str", sar_str)
        sar_a = sar_str.split(':')
        sar = int(sar_a[0]) / int(sar_a[1])
        dar = width / height * sar
    else:
        dar = ratio

    if ratio != dar:
        width = int(height * dar)
        print(f" --> {width}x{height}")
    else:
        print('')

    return f"{width}x{height}"


def guess_frame_rate(file_input):
    video = get_stream_data(file_input, 'video')
    num, den = video['r_frame_rate'].split('/')
    frame_rate = int(num) / int(den)
    return frame_rate


def guess_sample_rate(file_input):
    audio = get_stream_data(file_input, 'audio')
    return audio['sample_rate'] if 'sample_rate' in audio else None



def guess_channels(file_input):
    audio = get_stream_data(file_input, 'audio')
    return audio['channels'] if 'channels' in audio else None


def ffshort(file_input, file_output=None, crf=27, size=None, temp_folder=None, dry_run=False, force_encode=False, sample_rate=None, channels=None, frame_rate=None, ffmpeg_path=None, threads=0, remove_options={}):

    # Make the path absolute, resolving any symlinks
    file_input = Path(file_input).resolve()

    print(f"Traitement de {file_input}...")


    size = size if size else guess_resolution(file_input)
    frame_rate = frame_rate if frame_rate else guess_frame_rate(file_input)
    sample_rate = sample_rate if sample_rate else guess_sample_rate(file_input)
    channels = channels if channels else guess_channels(file_input)
    print(f"size : {size}, sample_rate : {sample_rate}, channels : {channels}")

    suffix = f".{size}.mp4"

    if file_output:
        file_output = Path(file_output)
        if file_output.is_dir():
            file_output = Path(file_output) / file_input.name
            file_output = file_input.with_suffix(suffix)
    else:
        file_output = file_input.with_suffix(suffix)

    if temp_folder:
        file_tmp = Path(temp_folder) / file_input.name
        file_tmp = file_tmp.with_suffix(suffix)

    encode_output = file_output if not temp_folder else file_tmp

    if force_encode or not encode_output.exists():
        command = [
            ffmpeg_path, '-hide_banner',
            '-loglevel', 'quiet', '-stats',
            '-i', file_input
        ]

        # audio parameters
        command.extend([ '-c:a', 'aac' ])
        if sample_rate: command.extend([ '-ar', sample_rate ])
        if channels: command.extend(['-ac', str(channels)])

        # video parameters
        command.extend([
            '-c:v', 'libx264',
            '-sws_flags', 'lanczos',
            '-pix_fmt', 'yuv420p',
            '-threads', threads,
            '-movflags', '+faststart',
            '-b-pyramid', 'none',
            '-b_strategy', '2',
            '-r', frame_rate,
            '-g', '300',
            '-keyint_min', '1',
            '-preset', 'veryfast',
            '-refs', '4',
            '-me_method', 'hex',
            '-me_range', '32',
            '-qcomp', '0.6',
            '-qmin', '3',
            '-subq', '4',
            '-crf', crf,
            *scale_params(size)
        ])
        for option in remove_options:
            del command[option]
        
        command.extend([ '-y', encode_output ])

        cmd_str = ' '.join([str(c) for c in command])
        print(cmd_str)
        
        if dry_run:
            return cmd_str
    
        run(command)

    if temp_folder:
        print(f"mv '{file_tmp}' '{file_output}'")
        if not dry_run:
            shutil.move(str(file_tmp), str(file_output))

    print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('file_input', type=str, help="le fichier à convertir")
    parser.add_argument('file_output', nargs='?', type=str, help="le fichier de sortie")
    parser.add_argument('--size', '-s', type=str, help="la résolution du fichier de sortie")
    parser.add_argument('--sample-rate', type=str, help="fréquence d'échantillonage audio")
    parser.add_argument('--frame-rate', '-r', type=int, help="Nombre d'images par seconde")
    parser.add_argument('--channels', type=str, help="nombre de canaux audio")
    parser.add_argument('--temp-folder', type=str, help="utilisation d'un dossier temporaire où sera effectué l'encodage")
    parser.add_argument('--dry-run', '-d', action='store_true', help="affiche juste la commande ffmpeg sans l'exécuter")
    parser.add_argument('--force-encode', '-f', action='store_true', help="force le réencodage de la vidéo même si le fichier de sortie exite déjà")
    parser.add_argument('--crf', '-q', type=int, default=30, help="qualité d'encodage de la vidéo entre 0 et 51 avec 0 signifiant aucune perte (30 par défaut)")
    parser.add_argument('--ffmpeg-path', '-p', type=str, default="/usr/local/bin/ffmpeg", help="Chemin de l'exécutable de ffmpeg")
    parser.add_argument('--threads', type=int, default=0, help="Nombre de coeurs utilisés pour l'encodage")

    args = parser.parse_args()

    ffshort(**vars(args))


if __name__ == "__main__":
    main()
