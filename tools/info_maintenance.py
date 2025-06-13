import os
import json
from datetime import datetime
import atexit


class InfoMaintenancer:

    def __init__(self, docs_root_dir, knowledge_base_dir, config, logger):

        self.knowledge_base_dir = knowledge_base_dir
        self.docs_root_dir = docs_root_dir
        self.config = config
        self.logger = logger

        self.get_kb_info()
        # 注册退出时的回调函数
        atexit.register(self.save_kb_info)

    
    def new_kb_info(self):
        """
        新建一个 kb_info.json 文件
        """
        doc_root_name = os.path.basename(self.docs_root_dir)
        return {
            'doc_tree': {
                doc_root_name: {
                    'dir_path': self.docs_root_dir,
                    'children': {},
                    'files': {}
                }
            },
            'create_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'name': os.path.basename(self.knowledge_base_dir)
        }

    def get_kb_info(self):

        # 检查 knowledge_base_dir 是否存在
        if not os.path.exists(self.knowledge_base_dir):
            self.logger.warning('知识库目录不存在，将创建一个')
            os.makedirs(self.knowledge_base_dir)
            self.kb_info = self.new_kb_info()
            # 保存 kb_info.json
            with open(os.path.join(self.knowledge_base_dir, 'kb_info.json'), 'w') as f:
                json.dump(self.kb_info, f, indent=4, ensure_ascii=False)


        # 读取 knowledge_base_dir 下的 kb_info.json
        elif not os.path.exists(os.path.join(self.knowledge_base_dir, 'kb_info.json')):
            self.logger.warning('知识库目录下没有 kb_info.json 文件，将创建一个空的')
            self.kb_info = self.new_kb_info()
            # 保存 kb_info.json
            with open(os.path.join(self.knowledge_base_dir, 'kb_info.json'), 'w') as f:
                json.dump(self.kb_info, f, indent=4, ensure_ascii=False)
            
        # 读取 kb_info.json
        else:
            with open(os.path.join(self.knowledge_base_dir, 'kb_info.json'), 'r') as f:
                self.kb_info = json.load(f)



    def save_kb_info(self):
        """
        保存 kb_info.json
        """
        self.kb_info['mod_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        with open(os.path.join(self.knowledge_base_dir, 'kb_info.json'), 'w') as f:
            json.dump(self.kb_info, f, indent=4, ensure_ascii=False)

    

    def is_new(self, file_path):
        """
        判断文件是否为新文件
        """

        # 判断 file_path 是不是 file
        if not os.path.isfile(file_path):
            rasie(ValueError(f'{file_path} 不是一个文件'))

        path_in_root = os.path.relpath(file_path, self.docs_root_dir)
        root_name = os.path.basename(self.docs_root_dir)
        sep = os.path.sep
        path_in_root_list = path_in_root.split(os.path.sep)
        current_doc_tree = self.kb_info['doc_tree'][root_name]
        for key in path_in_root_list[:-1]:
            if key not in current_doc_tree['children']:
                return True
            else:
                current_doc_tree = current_doc_tree['children'][key]
        
        
        
        file_name = path_in_root_list[-1]
        if file_name not in current_doc_tree['files']:
            return True
        else:
            file_mtime = os.path.getmtime(file_path)
            if file_mtime > current_doc_tree['files'][file_name]['mtime']:
                return True
        
        return False

    
    def updated(self, file_path):
        """
        更新 doc_tree
        """
        # 判断 file_path 是不是 file
        if not os.path.isfile(file_path):
            rasie(ValueError(f'{file_path} 不是一个文件'))

        # 判断 file_path 是否在 docs_root_dir 下
        if not file_path.startswith(self.docs_root_dir):
            rasie(ValueError(f'{file_path} 不是在 {self.docs_root_dir} 下'))
        
        # 找到 file_path 在 doc_tree 中的位置
        path_in_root = os.path.relpath(file_path, self.docs_root_dir)
        sep = os.path.sep
        path_in_root_list = path_in_root.split(os.path.sep)
        root_name = os.path.basename(self.docs_root_dir)
        current_doc_tree = self.kb_info['doc_tree'][root_name]
        for key in path_in_root_list[:-1]:
            if key not in current_doc_tree['children']:
                current_doc_tree['children'][key] = {
                    "dir_path": os.path.join(self.docs_root_dir, *path_in_root_list[:path_in_root_list.index(key)+1]),
                    "children": {},
                    "files": {}
                }
            current_doc_tree = current_doc_tree['children'][key]
        
        # 更新 file_path 对应的 doc_tree 中的信息
        file_name = path_in_root_list[-1]
        current_doc_tree['files'][file_name] = {
            "dir_path": os.path.join(self.docs_root_dir, *path_in_root_list),
            "mtime": os.path.getmtime(file_path)
        }
        


    def __gen_doc_tree(self, file_path_with_root_folder):
        """
        生成目录树
        """
        root_name = dir_path.split('/')[-1]
        root_path = dir_path.split(root_name)[0]
        tree = {
            root_name: {
                'dir_path': dir_path, 'children': {}, 'files': {}
            }
        }
        sep = os.path.sep

        for root, dirs, files in os.walk(dir_path):
            # root 去掉 root_path
            root = root.replace(root_path, '')

            cur_node = tree[root_name]
            for p in root.split(sep)[1:]:
                cur_node = cur_node['children'][p]

            # 把 dirs 转为 dict
            for d in dirs:
                cur_node['children'][d] = {
                    'dir_path': os.path.join(dir_path, root, d), 'children': {}, 'files': {}
                }
            
            # 把 files 转为 dict
            for f in files:
                # 获取修改时间
                mtime = os.path.getmtime(os.path.join(dir_path, root, f))
                cur_node['files'][f] = {
                    'dir_path': os.path.join(dir_path, root, f),
                    'mtime': mtime
                }
        
        return tree


    # def __del__(self):

    #     self.save_kb_info()