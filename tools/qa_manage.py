import pandas as pd
import os

from main import knowledge_base_dir
class QA_Manager:

    def __init__(self, cfg, root_dir):
        self.cfg = cfg
        self.qa = []
        self.root_dir = root_dir
        # TODO
        # 可以加载 qa

    def merge_qa(self, qa_to_merge, file_path=None):

        # 如果 file_path 不为空，将 knowledge_path 设置为相对路径
        if file_path:
            rel_path = os.path.relpath(file_path, self.root_dir)
            for qa in qa_to_merge:
                qa['knowledge_path'] = rel_path

        self.qa.extend(qa_to_merge)
    
    def export_csv(self, file_path):
        df = pd.DataFrame(self.qa)
        df.to_csv(file_path, index=False)