import pandas as pd
import os
import atexit

class QA_Manager:

    def __init__(self, cfg, docs_root_dir, knowledge_base_dir):
        self.cfg = cfg
        self.docs_root_dir = docs_root_dir
        self.knowledge_base_dir = knowledge_base_dir

        # 加载 qa
        qa_file_path = os.path.join(knowledge_base_dir, 'qa.csv')
        if os.path.exists(qa_file_path):
            self.qa = pd.read_csv(qa_file_path).to_dict('records')
        else:
            self.qa = []

        # 注册退出时的清理函数
        atexit.register(self.export_csv, qa_file_path)

    def merge_qa(self, qa_to_merge, file_path=None):

        # 如果 file_path 不为空，将 knowledge_path 设置为相对路径
        if file_path:
            rel_path = os.path.relpath(file_path, self.docs_root_dir)
            for qa in qa_to_merge:
                qa['knowledge_path'] = rel_path
        
        # 删除 qa 中 knowledge_path 为 rel_path 的 qa
        self.qa = [qa for qa in self.qa if qa['knowledge_path'] != rel_path]

        # 合并 qa
        self.qa.extend(qa_to_merge)
    
    def export_csv(self, file_path):
        df = pd.DataFrame(self.qa)
        df.to_csv(file_path, index=False)
    

    # def __del__(self):

    #     self.export_csv(os.path.join(self.knowledge_base_dir, 'qa.csv'))