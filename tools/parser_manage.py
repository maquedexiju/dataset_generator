import os
import importlib
from file_parsers.basic_parser import BasicParser
import re


class Parser_Chooser:

    def __init__(self, config, logger):
        # self.parser = {}
        # for k, v in config['PARSER'].items():
        #     lib_name = 'file_parsers.' + v
        #     self.parser[k] = importlib.import_module(v)
        # 获取 file_parsers 目录下的所有文件
        self.parser = {
            'reg': {},
            'suffix': {},
        }
        for file in os.listdir('file_parsers'):
            if file.endswith('.py') and not file.startswith('__'):
                lib_name = 'file_parsers.' + file.split('.')[0]
                # 获取 lib_name 下所有 BaseParser 的子类
                for name, obj in importlib.import_module(lib_name).__dict__.items():
                    if isinstance(obj, type) and issubclass(obj, BasicParser) and obj is not BasicParser:
                        # 如果 suffix 在 obj 中
                        if hasattr(obj, 'suffix'):
                            # self.parser['suffix'][obj.suffix] = obj
                            if type(obj.suffix) is str:
                                if obj.suffix in self.parser['suffix'].keys():
                                    self.logger.warning(f'后缀 {obj.suffix} 已有处理器 {self.parser['suffix'][obj.suffix].__name__}， {obj.__name__} 会被忽略')
                                else:
                                    self.parser['suffix'][obj.suffix] = obj
                            elif type(obj.suffix) is list:
                                for r in obj.suffix:
                                    if r in self.parser['suffix'].keys():
                                        self.logger.warning(f'后缀 {r} 已有处理器 {self.parser['suffix'][r].__name__}， {obj.__name__} 会被忽略')
                                    else:
                                        self.parser['suffix'][r] = obj
                        if hasattr(obj,'reg'):
                            self.parser['reg'][obj.reg] = obj
        
        self.path_ignore = self.read_path_ignore(config['GENERAL']['path_ignore'])

        
    def choose_parser(self, file_path):

        # 根据 path_ignore 过滤
        for p in self.path_ignore:
            if re.search(p, file_path):
                return 'ignored'

        # 根据 reg 匹配
        for reg, parser in self.parser['reg'].items():
            if re.search(reg, file_path):
                return parser

        # 根据 suffix 匹配
        file_ext = file_path.split('.')[-1].lower()
        if file_ext in self.parser['suffix'].keys():
            return self.parser['suffix'][file_ext]

        # 如果都没有匹配到，返回 None
        return None


    def read_path_ignore(self, path_ignore_file):
        """
        读取 path_ignore_file 文件，返回一个列表
        """
        if not os.path.exists(path_ignore_file):
            return []

        with open(path_ignore_file, 'r') as f:
            lines = f.readlines()
            return [x.strip() for x in lines if not x.strip().startswith(('#', ';', '//'))]