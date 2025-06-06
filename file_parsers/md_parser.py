import os
import re
from .basic_parser import BasicParser
from PIL import Image
import io
import base64
import requests
from openai import OpenAI

img_parse_prompt = '''
你是一个图像识别助手，识别图片中的内容，并返回详细描述，格式如下：
图片概述：图片概述（不超过 30 字）
图片内容：
* 描述 1
* 描述 2
'''

class MDParser(BasicParser):
    reg = '(?:.*\.md$|.*\.markdown$)'

    def __init__(self, file_path, root_path, cfg={}, title_prefix='%parent', logger=None):
        # 检查文件类型
        if not file_path.lower().endswith('.md') and not file_path.lower().endswith('.markdown'):
            raise ValueError("file type error, not a markdown file")

        # 获取图像识别模型的相关算法配置
        self.img_parse_url = cfg['IMG_RECONGNIZE_MODEL']['url']
        self.img_parse_key = cfg['IMG_RECONGNIZE_MODEL']['api_key']
        self.img_parse_model = cfg['IMG_RECONGNIZE_MODEL']['model_name']
        self.openai_client = OpenAI(api_key=self.img_parse_key, base_url=self.img_parse_url)

        super().__init__(file_path, root_path, cfg, title_prefix, logger)


    def get_image_description(self, img_path):
        # 调用 OpenAI 的 API 进行图像识别
        b64_img = base64.b64encode(open(img_path, 'rb').read()).decode()
        response = self.openai_client.chat.completions.create(
            model=self.img_parse_model,
            messages=[
                {"role": "system", "content": img_parse_prompt},
                {"role": "user", "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}
                    },
                ]}
            ]
        )
        try:
            result = response.choices[0].message.content
            return result
        except Exception as e:
            self.logger.error(f'image path: {img_path} parse error')
            self.logger.error(f'error: {e}')
            self.logger.error(f'response: {result}')


    def save_img(self, img_path):

        # 检查 img_path 是否是 base64 编码
        if re.search(r'^data:image\/(.*);base64,', img_path):
            # 如果是 base64 编码，将其转换为图片
            img_data = re.sub(r'^data:image\/(.*);base64,', '', img_path)
            img = Image.open(io.BytesIO(base64.b64decode(img_data)))
        # 检查 img_path 是否是网址
        elif re.search(r'^http[s]?://', img_path):
            # 如果是网址，下载图片
            try:
                img = Image.open(requests.get(img_path, stream=True).raw)
            except:
                self.logger.warning(f'图片下载失败: {img_path}')
                return None

        # 本地文件
        else:
            # 检查 img_path 是否是相对路径
            if not os.path.isabs(img_path):
                img_path = os.path.join(os.path.dirname(self.file_path), img_path)

            # 检查 img_path 是否存在
            if not os.path.exists(img_path):
                self.logger.warning(f'图片路径不存在: {img_path}')
                return None

            # 打开图片
            img = Image.open(img_path)

        # 保存图片
        img_fullname = os.path.basename(img_path)
        img_basename, _ = os.path.splitext(img_fullname)
        new_img_name = f'{img_basename}.jpg'
        img_saved = os.path.join(self.image_output_dir, os.path.basename(new_img_name))
        
        # img 转成 jpg
        if img.mode in ('RGBA', 'LA'):
            background = Image.new('RGB', img.size, (240,240,240))
            background.paste(img, mask=img.split()[-1])
            img = background

        img.save(img_saved, 'JPEG', quality=95)

        return img_saved

    def handle_img_reg(self, reg, link_reg, line):
        # 通过 reg 处理图片
        # reg 需要有一个 group
        for comp in re.findall(reg, line):
            try:
                img_path = re.search(link_reg, comp).group(1)
            except:
                self.logger.error('reg format error, no group included')

            # 保存图片
            img_saved = self.save_img(img_path)

            # 获取图片描述
            description = self.get_image_description(img_saved)
            position = f'{self.knowledge_path}: {os.path.basename(img_saved)}'
            description = self.add_tag(description, 'resource', position)
            # description = f'\n@resource: {position}\n\n' + description + '\n@endresource\n'

            # 替换
            # line = re.sub(comp, description, line)
            line = line.replace(comp, description)

        return line



    def split_md(self):

        # 读取 Markdown 文件内容
        with open(self.file_path, 'r', encoding='utf-8') as file:
            self.md_content = file.read()
        
        # 若 md 开头不是一级标题，添加一级标题为文件名
        if not self.md_content.startswith('#'):
            self.md_content = f'# {self.file_basename}\n\n' + self.md_content
        
        # 如果 md 中含有多个一级标题，那么 self.title_prefix 保留文件名
        if self.md_content.count('\n# ') > 1:
            if self.file_basename not in self.title_prefix:
                self.title_prefix += '-' + self.file_basename


        result = {}
        headers = []
        current_header_path = ''
        current_content = []

        # 创建图片输出目录
        self.image_output_dir = os.path.join(self.output_path, 'images')
        if not os.path.exists(self.image_output_dir):
            os.makedirs(self.image_output_dir)

        # 按行遍历 Markdown 内容
        for line in self.md_content.splitlines():
            if line.startswith('#'):
                # 处理当前标题内容
                if current_header_path and current_content and ''.join(current_content) != '':
                    position = f'{self.knowledge_path}: {"-".join(headers)}'
                    result[current_header_path] = self.add_tag('\n'.join(current_content).strip(), 'section', position)
                    # result[current_header_path] = f'\n@section: {position}\n\n' + '\n'.join(current_content).strip() + '\n@endsection\n'
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

                current_header_path = '-'.join([self.title_prefix] + headers)
            else:
                # 处理 md 语法的图片
                line = self.handle_img_reg(r'!\[.*\]\(.*\)', r'!\[.*\]\((.*)\)', line)
                # 处理 html 语法的图片
                line = self.handle_img_reg(r'<img.*src=".*"[^>]*>', r'<img.*src="(.*)"[^>]*>', line)

                current_content.append(line)

        # 处理最后一个标题内容
        if current_header_path and current_content:
            position = f'{self.knowledge_path}: {"-".join(headers)}'
            result[current_header_path] = self.add_tag('\n'.join(current_content).strip(), 'section', position)

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
        
        self.split_md()
        self.assemble_qa_info()

        return self.qa_info