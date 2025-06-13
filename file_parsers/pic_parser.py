import json
import os
import re
import base64
import io
from openai import OpenAI
from PIL import Image

from .basic_parser import BasicParser


img_parse_prompt = '''
你是一个图像识别助手，请详细描述图片中的内容，包括标题、内容、表格、图表等，并对图片中的其他内容进行描述，并返回 markdown 格式结果。
不能缺失任何内容，不能包含错误或编造的内容。
'''


class PictureParser(BasicParser):

    suffix = ['png', 'jpg', 'jpeg', 'tiff', ]

    def __init__(self, file_path, root_path, cfg={}, title_prefix='%parent', logger=None, output_dir=''):

        # 获取图像识别模型的相关算法配置
        self.img_parse_url = cfg['IMG_RECONGNIZE_MODEL']['url']
        self.img_parse_key = cfg['IMG_RECONGNIZE_MODEL']['api_key']
        self.img_parse_model = cfg['IMG_RECONGNIZE_MODEL']['model_name']
        self.openai_client = OpenAI(api_key=self.img_parse_key, base_url=self.img_parse_url)

        super().__init__(file_path, root_path, cfg, title_prefix, logger, output_dir)


    def get_summary(self):
        # 调用 OpenAI 的 API 进行图像识别
       
        img_path = self.file_path

        b64_img = base64.b64encode(open(img_path, 'rb').read()).decode()


        response = self.openai_client.chat.completions.create(
            model=self.img_parse_model,
            messages=[
                {"role": "system", "content": ppt_parse_prompt},
                {"role": "user", "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}
                    },
                ]}
            ]
        )
        
        result = response.choices[0].message.content
        self.md_content = result

    def split_md(self):

        result = {}
        headers = []
        current_header_path = ''
        current_content = []

        is_in_code = False
        for l in self.md_content.splitlines():

            # 处理代码
            if line.startswith('```'):
                is_in_code = not is_in_code
                continue
            if is_in_code:
                current_content.append(line)
                continue

            # 处理标题
            if line.startswith('#') and not is_in_code:
                # 处理当前标题内容
                if current_header_path and current_content and ''.join(current_content) != '':
                    position = "-".join(headers)
                    result[current_header_path] = self.add_section_tag('\n'.join(current_content).strip(), position)
                    current_content = []

                # 解析新标题级别和文本
                level = line.count('#')
                header_text = line.strip('#').strip()

                # 标题级别错误处理
                if level > len(headers) + 1:
                    self.logger.warning(f'标题级别跳跃: 当前标题级别 {level}, 上一级标题级别 {len(headers)}。标题: {header_text}')
                    # 尝试修正标题级别，设置为上一级标题级别加 1
                    level = len(headers) + 1

                # 调整标题层级
                if level > len(headers):
                    headers.append(header_text)
                elif level == len(headers):
                    headers[-1] = header_text
                else:
                    headers = headers[:level - 1]
                    headers.append(header_text)

                # current_header_path = '-'.join([self.title_prefix] + headers)
                if self.title_prefix == '':
                    current_header_path = '-'.join(headers)
                else:
                    current_header_path = '-'.join([self.title_prefix] + headers)
            else:
                current_content.append(line)

        # 处理最后一个标题内容
        if current_header_path and current_content:
            position = "-".join(headers)
            result[current_header_path] = self.add_section_tag('\n'.join(current_content).strip(), position)
        elif current_content:
            position = self.file_basename
            result[self.file_basename] = self.add_section_tag('\n'.join(current_content).strip(), position)

        
        self.content_dict = result
    

    def assemble_qa_info(self):
        qa_info = []

        for title, content in self.content_dict.items():
            qa_info.append({
                'simple_title': title,
                'full_title': title,
                'content': content
            })
        
        self.qa_info = qa_info


    def parse(self):

        self.get_summary()
        self.parse_md()
        self.assemble_qa_info()

        return self.qa_info