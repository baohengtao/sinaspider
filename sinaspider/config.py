import os
from pathlib import Path
from omegaconf import OmegaConf


config_home = os.getenv('XDG_CONFIG_HOME') or os.getenv('HOME')
config_path = Path(config_home)/'sinaspider'/'config.yaml'
conf = OmegaConf.load(config_path)
headers = conf.headers
