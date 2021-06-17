import re
import sys
import json
import logging
import subprocess
from pathlib import Path
from utils.easyVmaf.Vmaf import vmaf
from utils.easyVmaf.FFmpeg import FFprobe
from statistics import mean, harmonic_mean
from dotenv import find_dotenv, dotenv_values
from scenecut_extractor.__main__ import get_scenecuts

config = dotenv_values(find_dotenv())
logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s %(name)-12s %(levelname)-8s %(message)s'))
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)


class FFProbeWrapper(FFprobe):

    def getStreamsInfo(self):
        self.cmd =  f'{FFprobe.cmd} -hide_banner -loglevel {self.loglevel} -print_format json -i \"{self.videoSrc}\" -show_streams -read_intervals %+5'
        logger.debug(f'getStreamsInfo : {self.cmd}')
        return self._run()['streams']


    def getStreamsOfType(self, type):
        streams = self.getStreamsInfo()
        streams_of_type = [stream for stream in streams if stream['codec_type'] == type]
        return streams_of_type


    def getVideoStreamsInfo(self):
        return self.getStreamsOfType('video')
    

    def getAudioStreamsInfo(self):
        return self.getStreamsOfType('audio')


    def getResolution(self):
        video_stream = self.getVideoStreamsInfo()[0]
        # https://forum.videohelp.com/threads/323530-please-explain-SAR-DAR-PAR
        # Display Aspect Ratio = Frame Aspect Ratio x Sample Aspect Ratio
        # DAR = FARxSAR
        # 16/9 = 1440/1080 x 4/3
        width = int(video_stream['width']) if 'width' in video_stream else int(video_stream['coded_width'])
        height = int(video_stream['height']) if 'height' in video_stream else int(video_stream['coded_width'])

        # correction of odd values
        width = width - width % 2
        height = height - height % 2

        ratio = width / height

        sar_str = self.getSAR()

        if sar_str:
            sar_a = sar_str.split(':')
            sar = int(sar_a[0]) / int(sar_a[1])
            dar = width / height * sar
        else:
            dar = ratio

        if ratio != dar:
            width = int(height * dar)
            # print(f" --> {width}x{height}")
        # else:
            # print('')

        return f"{width}x{height}"


    def getSAR(self):
        """Certains fichiers vidéo ont plusieurs informations de SAR/DAR et il arrive à `ffprobe`
        de ne pas nous renvoyer la bonne si on utilise l'option `-show_streams`.
        J'ai pensé utiliser la commande `mediainfo`, mais il lui arrive aussi de mal interpréter
        ces doublons.
        Après l'avoir testé sur plusieurs fichiers, il semble que dans la sortie sur `stderr`
        peut apparaître 1 ou 2 fois, entre `[]` ou non et que celle entre `[]` est forcément bonne.
        Du coup, ce code cherche d'abord une valeur entre `[]` et se rabat sur l'autre sinon.
        """
        command = [
            config['ffprobe'],
            self.videoSrc
        ]
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate()
        err_str = str(stderr)

        sar_bracket = re.search(r'\[SAR ([0-9]+:[0-9]+) ', err_str)
        if sar_bracket:
            return sar_bracket[1]

        sar = re.search(r'SAR ([0-9]+:[0-9]+) ', err_str)
        if sar:
            return sar[1]

        return None


    def getFrameRate(self):
        video = self.getVideoStreamsInfo()[0]
        frame_rate = video['avg_frame_rate'] if 'avg_frame_rate' in video else video['r_frame_rate']
        # frame_rate = video['r_frame_rate']
        return frame_rate


    def getVideoDuration(self):
        cmd = f"{config['ffprobe']} -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1"
        cmd_a = cmd.split(" ")
        cmd_a.append(self.videoSrc)
        return float(subprocess.check_output(cmd_a))



    def getSampleRate(self):
        audio = self.getAudioStreamsInfo()[0]
        return audio['sample_rate'] if 'sample_rate' in audio else None


    def getChannels(self):
        audio = self.getAudioStreamsInfo()[0]
        return audio['channels'] if 'channels' in audio else None


class FFmpegWrapper():
    
    bin = config['ffmpeg']


    def __init__(self, loglevel='quiet'):
        self._loglevel = loglevel
        self._inputs = []
        self._params = []
        self._outputs = []


    def _commit(self):
        """Build the final command to run"""
        self._command = f'{FFmpegWrapper.bin} -hide_banner -stats -loglevel {self._loglevel} '
        self._command += self._commitInputs()
        self._command += self._commitParams()
        self._command += self._commitOutputs()
        return self._command


    def _commitInputs(self):
        inputs_cmd = ''
        for input in self._inputs:
            inputs_cmd += f'-i {input} '
        return inputs_cmd
    
    
    def _commitParams(self):
        params_cmd = ''
        for param in self._params:
            params_cmd += f'{param} '
        return params_cmd


    def _commitOutputs(self):
        outputs_cmd = ''
        for output in self._outputs:
            outputs_cmd += f'-y {output} '
        outputs_cmd = outputs_cmd.strip()
        return outputs_cmd


    def _addInput(self, input):
        self._inputs.append(input)


    def _addParam(self, param):
        if not isinstance(param, list):
            param = [param]
        for p in param:
            self._params.append(p)

    
    def _addOutput(self, output):
        self._outputs.append(output)


    def execute(self):
        self._commit()
        logger.debug(f'execute:  {self._command}')
        print(self._command.split(' '))
        process = subprocess.Popen(self._command.split(' '), stdout=subprocess.PIPE, shell=True)
        self._clearCommand()
        return process.communicate()


    def _clearCommand(self):
        self._command = ""
        self._inputs = []
        self._params = []
        self._outputs = []


    def getExtractAtTime(self, input, start, duration, output=None):
        
        if not output:
            input = Path(input)
            output = f"{input.stem}.t{start}.d{duration}{input.suffix}"

        self._addInput(input)
        self._addParam(f"-ss {start} -c copy -t {duration}")
        self._addOutput(output)

        return self.execute()


    def getExtractAroundTime(self, input, middle_time, duration, output=None):
        ffprobe = FFProbeWrapper(input, loglevel=self._loglevel)
        full_duration = ffprobe.getVideoDuration()
        
        if duration > full_duration:
            sys.exit(f"Error: the video is shorter ({full_duration} s) than the duration of the extract needed for quality check ({extract_d} s).")

        if middle_time < duration / 2:
            start = 0
        elif middle_time + duration / 2 > full_duration:
            start = full_duration - duration
        else:
            start = middle_time - duration / 2

        logger.debug(f'getExtractAroundTime {input}, {start}, {duration}, {output}')
        return self.getExtractAtTime(input, start, duration, output)


    def encode(self, input, output, crf=27, mode='simple', size=None, dry_run=False, sample_rate=None, channels=None, frame_rate=None, threads=0, options={}):

        input = Path(input).resolve()
        ffprobe_input = FFProbeWrapper(input, loglevel=self._loglevel)
        size        = size          if size         else ffprobe_input.getResolution()
        frame_rate  = frame_rate    if frame_rate   else ffprobe_input.getFrameRate()
        sample_rate = sample_rate   if sample_rate  else ffprobe_input.getSampleRate()
        channels    = channels      if channels     else ffprobe_input.getChannels()

        self._addInput(input)
        self._addParam([
            '-c:a', 'aac',
            '-ar', sample_rate,
            '-ac', channels])
        if mode != 'simple':
            self._addParam([
                '-c:v', 'libx264',
                '-sws_flags', 'bicubic',
                '-pix_fmt', 'yuv420p',
                '-threads', str(threads),
                '-movflags', '+faststart',
                # '-b-pyramid', 'none',
                # '-b_strategy', '2',
                '-r', str(frame_rate),
                '-g', '250',
                '-keyint_min', '25',
                '-preset', 'medium',
                # '-refs', '6',
                # '-me_method', 'hex',
                # '-me_range', '32',
                '-qcomp', '0.6',
                # '-qmin', '3',
                # '-subq', '4',
                '-crf', str(crf),
                '-trellis', '2',
            ])
            self._addScaleParam(size)
        self._addOutput(output)

        if dry_run:
            return self._commit()
        else:
            return self.execute()


    def _addScaleParam(self, size):

        if not re.fullmatch(r'[0-9]+x[0-9]+', size):
            return

        (w, h) = size.split('x')
        ratio = int(w) / int(h)

        self._addParam(['-aspect', str(ratio), '-vf', f"scale={size},setsar=1/1"])


    def getScenescores(self, input, output=None):

        input = Path(input)
        output = Path(output) if output else Path(f"/tmp/{input.stem}.json") 

        if not output.exists():
            scenescores = get_scenecuts(input, threshold=0)
            scenescores = sorted(scenescores, key=lambda ss: ss['score'])

            with open(output, 'w') as fd:
                fd.write(json.dumps(scenescores, indent=4))
        else:
            with open(output, 'r') as fd:
                scenescores = json.loads(fd.read())
        
        return scenescores

    def getVmaf(self, original, encoded, log_path=None):
        encoded = Path(encoded)
        log_path = log_path if log_path else Path(f"/tmp/{encoded.stem}.json")
        my_vmaf = vmaf(encoded, original, 'json', log_path=log_path, loglevel='quiet')
        offset1, psnr1 = my_vmaf.syncOffset()  # TODO: étudier les arguments de cette fonction : syncWindow, start, reverse
        offset2, psnr2 = my_vmaf.syncOffset(reverse=True)
        offset, psnr = [offset1, psnr1] if psnr1 >= psnr2 else [-offset2, psnr2]
        

        scores = []
        for offset in [offset1, offset2, -offset1, -offset2]:
            my_vmaf.setOffset(offset)
            my_vmaf.getVmaf()

            vmaf_scores = []
            with open(log_path, 'r') as fd:
                jsonData = json.load(fd)
                for frame in jsonData['frames']:
                    vmaf_scores.append(frame["metrics"]["vmaf"])

            scores.append({'offset': offset, 'psnr': psnr, 'arithmetic mean': mean(vmaf_scores), 'harmonic mean': harmonic_mean})
        return scores


