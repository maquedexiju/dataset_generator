import os
import tempfile
class BasicParser:

    # suffix = 'txt'
    # reg = '.*\.txt$'

    def __init__(self, file_path, root_path, cfg, title_prefix='%parent', logger=None, output_dir='./output'):
        '''
        初始化解析器
        :param file_path: 完整的文件路径
        :param root_path: 根目录路径
        :param cfg: 配置内容
        :param title_prefix: 可用替代字符：%parent 所有目录，%parent_n 至多几级目录，%file 文件名
        '''

        # 检查文件路径是否存在
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件路径不存在: {file_path}")
            
        self.file_path = file_path
        knowledge_path = os.path.relpath(file_path, root_path)
        # self.knowledge_path = knowledge_path.replace(os.path.sep, '-')
        self.knowledge_path = knowledge_path
        self.output_dir = os.path.join(output_dir, self.knowledge_path)

        # 获取文件的基本名称（不包含扩展名）
        file_fullname = file_path.split('/')[-1]
        self.file_basename = os.path.splitext(file_fullname)[0]

        # 计算 parent
        dir_name = os.path.dirname(file_path)
        rel_path = os.path.relpath(dir_name, root_path)
        if rel_path == '.': rel_path = ''
        self.parents = rel_path.split(os.path.sep)

        # 处理 title_prefix
        if '%file' in title_prefix:
            title_prefix = title_prefix.replace('%file', self.file_basename)
        
        # TODO
        # 支持 parent_n

        if '%parent' in title_prefix:
            parent = '-'.join(self.parents)
            title_prefix = title_prefix.replace('%parent', parent)
        
        self.title_prefix = title_prefix

        self.cfg = cfg

        if logger is None:
            self.logger = logging.getLogger()
        else:
            self.logger = logger

        self.qa_info =[]

        # 创建 temp_dir
        dir_prefix = os.path.basename(file_path) + '_'
        self.temp_dir = tempfile.TemporaryDirectory(prefix=dir_prefix)

        logger.info('======')
        logger.info(f'Parser {self.__class__.__name__} initialized: {file_path}')

    def parse(self):
        self.qa_info.append({
            'simple_title': '',
            'full_title': '',
            'content': self.add_tag('content', 'section', 'position'), # @resource: 用来标记资源，@section 用来标记一段内容（同一来源）
            # 'other key'
        })

        return self.qa_info

    def add_tag(self, content, tag_name, tag_desc):
        '''
        给 content 添加 tag_name 标签
        :param content: 内容
        :param tag_name: 标签名称
        :param tag_desc: 标签说明
        :return:
        '''

        return f'\n@{tag_name}: {self.knowledge_path}: {tag_desc}\n\n{content}\n@end{tag_name}\n'
    

    def add_resource_tag(self, content, resource_path_in_file):
        '''
        给 content 添加 @resource 标签
        :param content: 内容
        :param resource_path: 资源路径
        '''
        return self.add_tag(content, 'resource', f'{self.knowledge_path}: {resource_path_in_file}')


    def add_section_tag(self, content, section_path_in_file):
        '''
        给 content 添加 @section 标签
        :param content: 内容
        :param section_path: 资源路径
        '''
        return self.add_tag(content,'section', f'{self.knowledge_path}: {section_path_in_file}')
    
    def __del__(self):
        self.temp_dir.cleanup()