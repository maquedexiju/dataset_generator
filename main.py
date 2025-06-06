import os, sys
from configparser import ConfigParser
from tools import file_manage, qa_manage
import logging

config = ConfigParser(interpolation=None)
config.read('config.ini')
config_dict = {}
for section in config.sections():
    config_dict[section] = dict(config[section])

config_dict['RUNTIME'] = {}
config_dict['RUNTIME']['os'] = os.name

# 日志配置
log_level = config_dict['LOG']['log_level']
log_format = config_dict['LOG']['log_format']
log_to_file = config_dict['LOG']['log_to_file']
log_to_console = config_dict['LOG']['log_to_console']
logger = logging.getLogger()
logger.setLevel(log_level)
log_formatter = logging.Formatter(log_format)
# 日志输出到文件和控制台
if log_to_file == 'True':
    log_file = config_dict['LOG']['log_file']
    log_file_path = os.path.dirname(log_file)
    if log_file_path != '' and not os.path.exists(log_file_path):
        os.makedirs(log_file_path)
        
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(log_formatter)
    logger.addHandler(file_handler)
# 如果 log_to_console 为 True，输出到控制台
if log_to_console == 'True':
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    logger.addHandler(console_handler)

# 处理 系统
if sys.platform.startswith('darwin'):
    # 如果 /Applications/LibreOffice.app/Contents/MacOS/soffice 存在
    if os.path.exists('/Applications/LibreOffice.app/Contents/MacOS/soffice'):
        config_dict['RUNTIME']['libreoffice_path'] = '/Applications/LibreOffice.app/Contents/MacOS/soffice'
    else:
        config_dict['RUNTIME']['libreoffice_path'] = 'libreoffice'


if __name__ == '__main__':

    args = sys.argv
    if len(args) == 1:
        print('请输入要解析的文件路径')
        exit(1)
    elif len(args) >= 2:
        root_dir = ' '.join(args[1:])

    parser_chooser = file_manage.Parser_Chooser(config_dict)
    qa_manager = qa_manage.QA_Manager(config_dict)

    for dir, children, files in os.walk(root_dir):
        for file in files:
            file_path = os.path.join(dir, file)
            parser_class = parser_chooser.choose_parser(file_path)
            if parser_class is not None:
                parser = parser_class(file_path, root_dir, config_dict, title_prefix='%parent', logger=logger)
                result = parser.parse()
                qa_manager.merge_qa(result)
            elif parser_class is 'ignored':
                logger.info('======')
                logger.info(f'file {file_path} ignored')
            else:
                logger.warning('======')
                logger.warning(f'no parser for {file_path}')
    
    qa_manager.export_csv('qa.csv')