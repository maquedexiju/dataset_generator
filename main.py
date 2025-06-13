import os, sys
from configparser import ConfigParser
from tools import parser_manage, qa_manage, info_maintenance
import logging
import argparse

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

    # 对 argv 进行解析
    parser = argparse.ArgumentParser(description='解析文档')
    parser.add_argument('filename', type=str, nargs='?', help='要解析的文档根目录', default=None)
    parser.add_argument('-i', '--input', type=str, help='要解析的文档根目录')
    # parser.add_argument('--input', type=str, help='要解析的文档根目录')
    parser.add_argument('-o', '--output', type=str, help='输出位置', default=os.path.join('.', 'output'))
    # parser.add_argument('-o', type=str, help='输出位置', default=os.path.join('.', 'output'))
    # parser.add_argument('-h', '--help', action='help', help='显示帮助信息')


    args = parser.parse_args(sys.argv[1:])

    if args.input:
        docs_root_dir = args.input
    elif args.filename:
        docs_root_dir = args.filename
    else:
        print('请指定要解析的文档根目录')
        exit(1)

    if not os.path.exists(docs_root_dir):
        print(f'文件路径不存在: {docs_root_dir}')
        exit(1)

    docs_root_name = os.path.basename(docs_root_dir)
    output_dir = args.output
    output_docs_dir = os.path.join(args.output, docs_root_name)
    # parent_path, file_name = os.path.split(docs_root_dir)
    # output_docs_dir = os.path.join(parent_path, f'{file_name}_kb')
    # if not os.path.exists(output_docs_dir):
    #     os.makedirs(output_docs_dir)
    # output_docs_dir = os.path.join('.', 'output', docs_root_dir)
    if not os.path.exists(output_docs_dir):
        os.makedirs(output_docs_dir)


    parser_chooser = parser_manage.Parser_Chooser(config_dict, logger)
    qa_manager = qa_manage.QA_Manager(config_dict, docs_root_dir, output_dir)
    info_maintenance = info_maintenance.InfoMaintenancer(docs_root_dir, output_dir, config_dict, logger)

    for dir, children, files in os.walk(docs_root_dir):
        for file in files:
            file_path = os.path.join(dir, file)
            parser_class = parser_chooser.choose_parser(file_path)
            if parser_class == 'ignored':
                logger.info('======')
                logger.info(f'跳过 {file_path}')
            elif parser_class is not None:

                is_new = info_maintenance.is_new(file_path)
                if is_new:
                    try:
                        parser = parser_class(file_path, docs_root_dir, config_dict, title_prefix='%parent', logger=logger, output_dir=output_docs_dir)
                        result = parser.parse()
                        qa_manager.merge_qa(result, file_path)
                        info_maintenance.updated(file_path)
                    except Exception as e:
                        raise(e)

                else:
                    logger.info('======')
                    logger.info(f'{file_path} 无更新，跳过')
            else:
                logger.warning('======')
                logger.warning(f'{file_path} 无法解析')
    
    # qa_manager.export_csv('qa.csv')