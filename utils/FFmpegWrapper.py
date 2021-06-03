from pathlib import Path
from dotenv import find_dotenv, dotenv_values


config = dotenv_values(find_dotenv())


class FFmpegWrapper():
    
    bin = config['ffmpeg']

    def __init__(self, loglevel='quiet'):
        self.loglevel = loglevel
        self.inputs = []
        self.params = []
        self.outputs = []
    
    def _commit(self):
        """Build the final command to run"""
        command = f'{FFmpegWrapper.bin} -y -hide_banner -stats -loglevel {self.loglevel} '
        command += self._commitInputs()
        command += self._commitParams()
        return cmd


    def _commitInputs(self):
        inputs_cmd = ''
        for input in self.inputs:
            inputs_cmd += f'-i \"{input}\" '
    
    
    def _commitParams(self):
        params_cmd = ''
        for param in self.params:
            params_cmd += f'{param} '


    def _addInput(self, input):
        self.inputs.append(input)


    def _addParam(self, param):
        self.params.append(param)

    
    def _addOutput(self, output):
        self.outputs.append(output)


    def getExtract(self, input, start, duration, output=None):
        if not output:
            input = Path(input)
            output = f"{input.stem}.t{start}.d{duration}{input.suffix}"

        self._addInput(input)
        self._addParam(f"-c copy -ss {start} -t {duration} ")
        self._addOutput(output)




