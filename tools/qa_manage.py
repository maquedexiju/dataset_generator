import pandas as pd
class QA_Manager:

    def __init__(self, cfg):
        self.cfg = cfg
        self.qa = []
        # TODO
        # 可以加载 qa

    def merge_qa(self, qa_to_merge):
        self.qa.extend(qa_to_merge)
    
    def export_csv(self, file_path):
        df = pd.DataFrame(self.qa)
        df.to_csv(file_path, index=False)